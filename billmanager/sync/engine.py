"""Оркестратор синхронизации BillManager → NetBox.

Поток основного направления:
  1. Клиент BillManager  →  Tenant NetBox.
  2. Услуга BillManager  →  VM NetBox (привязана к tenant), статус по карте.
  3. IP услуги           →  ip_addresses NetBox (привязаны к tenant/услуге).
  4. VLAN услуги         →  vlans NetBox.

Двусторонняя ветка (NetBox → BillManager) добавляется отдельным модулем —
здесь оставлены точки расширения, но запись в BillManager пока не делается.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..clients.billmanager import BillManagerClient
from ..clients.netbox import NetBoxClient
from ..logging import get_logger
from ..models import Client, Service, netbox_status_for
from .adapters import client_from_bm, service_from_bm

log = get_logger(__name__)


@dataclass
class SyncResult:
    tenants: int = 0
    services: int = 0
    ips: int = 0
    vlans: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "SyncResult") -> None:
        self.tenants += other.tenants
        self.services += other.services
        self.ips += other.ips
        self.vlans += other.vlans
        self.errors.extend(other.errors)


class SyncEngine:
    def __init__(
        self,
        bm: BillManagerClient,
        nb: NetBoxClient,
        *,
        vm_cluster_id: int | None = None,
        dry_run: bool = False,
        only_client: str | None = None,
        ip_pool_prefix: str = "",
        billmgr_readonly: bool = False,
        set_ip_func: str = "service.edit",
        ip_field: str = "ip",
    ) -> None:
        self.bm = bm
        self.nb = nb
        self.vm_cluster_id = vm_cluster_id
        self.dry_run = dry_run
        # Если задан — обрабатывать только этого клиента и его услуги (для тестов).
        self.only_client = str(only_client) if only_client else None
        # Провижининг IP: пул-префикс NetBox + запись адреса обратно в BillManager.
        self.ip_pool_prefix = ip_pool_prefix or ""
        self.billmgr_readonly = billmgr_readonly
        self.set_ip_func = set_ip_func
        self.ip_field = ip_field

    # --- публичные операции --------------------------------------------

    def sync_all(self) -> SyncResult:
        """Полная сверка: все клиенты и все услуги BillManager."""
        result = SyncResult()
        clients = {c.bm_id: c for c in map(client_from_bm, self.bm.list_clients())}
        if self.only_client:
            clients = {k: v for k, v in clients.items() if k == self.only_client}
            log.info("sync.scope.only_client", client=self.only_client)
        log.info("sync.clients.fetched", count=len(clients))
        for client in clients.values():
            result.merge(self._sync_tenant(client))

        for raw in self.bm.list_services():
            service = service_from_bm(raw)
            if self.only_client and service.client_bm_id != self.only_client:
                continue
            client = clients.get(service.client_bm_id)
            result.merge(self._sync_service(service, client))
        log.info("sync.all.done", **_counts(result))
        return result

    def sync_service_by_id(self, bm_service_id: str | int) -> SyncResult:
        """Синхронизировать одну услугу (используется webhook'ом)."""
        result = SyncResult()
        raw = self.bm.get_service(bm_service_id)
        service = service_from_bm(raw)
        client = None
        if service.client_bm_id:
            raw_client = self.bm.get_client(service.client_bm_id)
            client = client_from_bm(raw_client) if raw_client else None
        result.merge(self._sync_service(service, client))
        return result

    # --- внутренняя логика ---------------------------------------------

    def _sync_tenant(self, client: Client) -> SyncResult:
        result = SyncResult()
        try:
            if self.dry_run:
                log.info("sync.tenant.dry_run", name=client.name, bm_id=client.bm_id)
            else:
                self.nb.upsert_tenant(
                    name=client.name,
                    slug=client.slug,
                    bm_id=client.bm_id,
                    description=client.email or "",
                )
            result.tenants += 1
        except Exception as exc:  # noqa: BLE001 — собираем ошибки, не падаем целиком
            msg = f"tenant {client.bm_id}: {exc}"
            log.error("sync.tenant.error", error=msg)
            result.errors.append(msg)
        return result

    def _sync_service(self, service: Service, client: Client | None) -> SyncResult:
        result = SyncResult()
        nb_status = netbox_status_for(service.status)
        try:
            tenant = None
            if client and not self.dry_run:
                tenant = self.nb.upsert_tenant(
                    name=client.name, slug=client.slug, bm_id=client.bm_id
                )
            tenant_id = getattr(tenant, "id", None)

            will_provision = not service.ip_addresses and bool(self.ip_pool_prefix)
            if self.dry_run:
                log.info(
                    "sync.service.dry_run",
                    name=service.name,
                    bm_id=service.bm_id,
                    status=nb_status,
                    existing_ips=service.ip_addresses,
                    provision_from=self.ip_pool_prefix if will_provision else None,
                    bm_writeback=not self.billmgr_readonly if will_provision else False,
                    vlan=service.vlan_id,
                )
                result.services += 1
                result.ips += len(service.ip_addresses) or (1 if will_provision else 0)
                result.vlans += 1 if service.vlan_id else 0
                return result

            if self.vm_cluster_id is not None:
                self.nb.upsert_vm(
                    name=service.name,
                    bm_id=service.bm_id,
                    cluster_id=self.vm_cluster_id,
                    tenant_id=tenant_id,
                    status=nb_status,
                    vcpus=service.vcpus,
                    memory=service.memory_mb,
                    disk=service.disk_gb,
                )
            result.services += 1

            if service.vlan_id:
                self.nb.upsert_vlan(
                    vid=service.vlan_id,
                    name=f"{service.name}-vlan",
                    tenant_id=tenant_id,
                )
                result.vlans += 1

            if service.ip_addresses:
                # IP уже есть в биллинге → отражаем их в NetBox (read-side).
                for ip in service.ip_addresses:
                    self.nb.upsert_ip(
                        address=_with_mask(ip),
                        tenant_id=tenant_id,
                        bm_service_id=service.bm_id,
                        status="active" if nb_status == "active" else "deprecated",
                        description=f"BillManager service {service.bm_id}",
                    )
                    result.ips += 1
            elif self.ip_pool_prefix:
                # IP нет → выдаём из NetBox и фиксируем в биллинге (provision-side).
                self._provision_ip(service, tenant_id, nb_status, result)
        except Exception as exc:  # noqa: BLE001
            msg = f"service {service.bm_id}: {exc}"
            log.error("sync.service.error", error=msg)
            result.errors.append(msg)
        return result

    def _provision_ip(
        self, service: Service, tenant_id: int | None, nb_status: str, result: SyncResult
    ) -> None:
        """Выдать IP из пула NetBox и записать его обратно на услугу в BillManager.

        Идемпотентно: если услуге уже выдан адрес (по billmanager_id), переиспользуем
        его и не выдаём новый.
        """
        existing = self.nb.find_ip_by_bm_service(service.bm_id)
        if existing:
            address = existing.address
            log.info("provision.ip.reuse", bm_id=service.bm_id, address=address)
        else:
            obj = self.nb.allocate_ip_from_prefix(
                self.ip_pool_prefix,
                tenant_id=tenant_id,
                bm_service_id=service.bm_id,
                status="active" if nb_status == "active" else "deprecated",
                description=f"BillManager service {service.bm_id}",
            )
            address = obj.address
            result.ips += 1

        bare = str(address).split("/")[0]  # биллингу обычно нужен адрес без маски
        if self.billmgr_readonly:
            log.info("provision.bm_writeback.skipped_readonly", bm_id=service.bm_id, ip=bare)
            return
        self.bm.set_service_ip(
            service.bm_id, bare, func=self.set_ip_func, field=self.ip_field
        )
        log.info("provision.bm_writeback.ok", bm_id=service.bm_id, ip=bare)


def _with_mask(ip: str) -> str:
    """NetBox требует ip_address с маской; одиночный адрес → /32 (или /128)."""
    if "/" in ip:
        return ip
    return f"{ip}/128" if ":" in ip else f"{ip}/32"


def _counts(result: SyncResult) -> dict[str, Any]:
    return {
        "tenants": result.tenants,
        "services": result.services,
        "ips": result.ips,
        "vlans": result.vlans,
        "errors": len(result.errors),
    }
