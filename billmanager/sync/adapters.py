"""Адаптеры: сырой ответ BillManager → канонические модели.

Имена полей в ответе BillManager зависят от версии и набора модулей.
Функции терпимы к отсутствию полей и собирают значения из нескольких
возможных ключей. При подключении к реальной панели проверьте фактические
имена через `func=service` / `func=client` и при необходимости поправьте
карты ниже.
"""

from __future__ import annotations

from typing import Any

from ..models import Client, Service


def _first(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def client_from_bm(raw: dict[str, Any]) -> Client:
    return Client(
        bm_id=str(_first(raw, "id", "elid")),
        name=str(_first(raw, "name", "realname", "fullname", default="unknown")),
        email=_first(raw, "email"),
    )


def service_from_bm(raw: dict[str, Any]) -> Service:
    ips = _first(raw, "ip", "ipaddr", default="")
    ip_list = [p.strip() for p in str(ips).replace(",", " ").split() if p.strip()]
    vlan = _first(raw, "vlan", "vlan_id")
    return Service(
        bm_id=str(_first(raw, "id", "elid")),
        name=str(_first(raw, "name", "domain", "account", default="service")),
        client_bm_id=str(_first(raw, "client", "account", "userid", default="")),
        status=str(_first(raw, "status", default="2")),
        vcpus=_int(_first(raw, "cpu", "vcpu", "ncpu")),
        memory_mb=_int(_first(raw, "mem", "memory", "ram")),
        disk_gb=_int(_first(raw, "disk", "hdd")),
        ip_addresses=ip_list,
        vlan_id=_int(vlan),
    )


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
