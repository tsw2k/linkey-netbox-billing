"""Тонкая обёртка над pynetbox с хелперами для интеграции.

Связь объектов NetBox с BillManager хранится в custom fields:
  * ``billmanager_id``      — id сущности в BillManager (услуга/клиент);
  * ``billmanager_status``  — последнее известное состояние из биллинга.

Эти custom fields нужно один раз создать в NetBox (см. README, раздел
"Подготовка NetBox"). Хелперы тут на них опираются.
"""

from __future__ import annotations

from typing import Any

import pynetbox

from ..logging import get_logger

log = get_logger(__name__)

CF_BM_ID = "billmanager_id"
CF_BM_STATUS = "billmanager_status"


class NetBoxClient:
    def __init__(self, url: str, token: str, *, verify_tls: bool = True) -> None:
        self.api = pynetbox.api(url, token=token)
        if not verify_tls:
            import requests

            session = requests.Session()
            session.verify = False
            self.api.http_session = session

    # --- tenants --------------------------------------------------------

    def get_tenant_by_bm_id(self, bm_id: str | int) -> Any | None:
        return self.api.tenancy.tenants.get(cf_billmanager_id=str(bm_id))

    def upsert_tenant(
        self, *, name: str, slug: str, bm_id: str | int, description: str = ""
    ) -> Any:
        existing = self.get_tenant_by_bm_id(bm_id) or self.api.tenancy.tenants.get(slug=slug)
        payload: dict[str, Any] = {
            "name": name,
            "slug": slug,
            "description": description,
            "custom_fields": {CF_BM_ID: str(bm_id)},
        }
        if existing:
            existing.update(payload)
            log.info("netbox.tenant.updated", tenant=name, bm_id=bm_id)
            return existing
        created = self.api.tenancy.tenants.create(**payload)
        log.info("netbox.tenant.created", tenant=name, bm_id=bm_id)
        return created

    # --- IPAM -----------------------------------------------------------

    def get_ip(self, address: str) -> Any | None:
        return self.api.ipam.ip_addresses.get(address=address)

    def upsert_ip(
        self,
        *,
        address: str,
        tenant_id: int | None = None,
        bm_service_id: str | int | None = None,
        status: str = "active",
        description: str = "",
    ) -> Any:
        existing = self.get_ip(address)
        payload: dict[str, Any] = {
            "address": address,
            "status": status,
            "description": description,
            "custom_fields": {},
        }
        if tenant_id is not None:
            payload["tenant"] = tenant_id
        if bm_service_id is not None:
            payload["custom_fields"][CF_BM_ID] = str(bm_service_id)
        if existing:
            existing.update(payload)
            return existing
        return self.api.ipam.ip_addresses.create(**payload)

    # --- VLAN -----------------------------------------------------------

    def upsert_vlan(self, *, vid: int, name: str, tenant_id: int | None = None) -> Any:
        existing = self.api.ipam.vlans.get(vid=vid)
        payload: dict[str, Any] = {"vid": vid, "name": name}
        if tenant_id is not None:
            payload["tenant"] = tenant_id
        if existing:
            existing.update(payload)
            return existing
        return self.api.ipam.vlans.create(**payload)

    # --- services as VMs/devices ---------------------------------------

    def get_vm_by_bm_id(self, bm_id: str | int) -> Any | None:
        return self.api.virtualization.virtual_machines.get(cf_billmanager_id=str(bm_id))

    def upsert_vm(
        self,
        *,
        name: str,
        bm_id: str | int,
        cluster_id: int,
        tenant_id: int | None = None,
        status: str = "active",
        vcpus: int | None = None,
        memory: int | None = None,
        disk: int | None = None,
    ) -> Any:
        existing = self.get_vm_by_bm_id(bm_id)
        payload: dict[str, Any] = {
            "name": name,
            "cluster": cluster_id,
            "status": status,
            "vcpus": vcpus,
            "memory": memory,
            "disk": disk,
            "custom_fields": {CF_BM_ID: str(bm_id)},
        }
        if tenant_id is not None:
            payload["tenant"] = tenant_id
        payload = {k: v for k, v in payload.items() if v is not None}
        if existing:
            existing.update(payload)
            return existing
        return self.api.virtualization.virtual_machines.create(**payload)
