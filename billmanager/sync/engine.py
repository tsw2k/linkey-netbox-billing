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
    ) -> None:
        self.bm = bm
        self.nb = nb
        self.vm_cluster_id = vm_cluster_id
        self.dry_run = dry_run

    # --- публичные операции --------------------------------------------

    def sync_all(self) -> SyncResult:
        """Полная сверка: все клиенты и все услуги BillManager."""
        result = SyncResult()
        clients = {c.bm_id: c for c in map(client_from_bm, self.bm.list_clients())}
        log.info("sync.clients.fetched", count=len(clients))
        for client in clients.values():
            result.merge(self._sync_tenant(client))

        for raw in self.bm.list_services():
            service = service_from_bm(raw)
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

            if self.dry_run:
                log.info(
                    "sync.service.dry_run",
                    name=service.name,
                    bm_id=service.bm_id,
                    status=nb_status,
                    ips=service.ip_addresses,
                    vlan=service.vlan_id,
                )
                result.services += 1
                result.ips += len(service.ip_addresses)
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

            for ip in service.ip_addresses:
                self.nb.upsert_ip(
                    address=_with_mask(ip),
                    tenant_id=tenant_id,
                    bm_service_id=service.bm_id,
                    status="active" if nb_status == "active" else "deprecated",
                    description=f"BillManager service {service.bm_id}",
                )
                result.ips += 1
        except Exception as exc:  # noqa: BLE001
            msg = f"service {service.bm_id}: {exc}"
            log.error("sync.service.error", error=msg)
            result.errors.append(msg)
        return result


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
