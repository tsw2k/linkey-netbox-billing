"""Канонические модели интеграции (нейтральные к источнику).

BillManager и NetBox отдают разные структуры; адаптеры приводят их к этим
моделям, а слой синхронизации работает только с ними. Это упрощает переход
к двусторонней синхронизации в будущем.
"""

from __future__ import annotations

import re

from pydantic import BaseModel


def slugify(value: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", value.lower()).strip()
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:100] or "n-a"


class Client(BaseModel):
    """Клиент BillManager → tenant NetBox."""

    bm_id: str
    name: str
    email: str | None = None

    @property
    def slug(self) -> str:
        return slugify(f"{self.name}-{self.bm_id}")


class Service(BaseModel):
    """Услуга BillManager → VM/устройство NetBox."""

    bm_id: str
    name: str
    client_bm_id: str
    status: str  # сырое состояние из BillManager
    # опциональные параметры тарифа
    vcpus: int | None = None
    memory_mb: int | None = None
    disk_gb: int | None = None
    ip_addresses: list[str] = []
    vlan_id: int | None = None


# Маппинг состояний BillManager → status NetBox.
# Коды состояний услуги BillManager: 1=заказана, 2=активна, 3=остановлена,
# 4=удалена/закрыта, 5=обработка. Сверьте с вашей версией панели.
BM_STATUS_TO_NETBOX: dict[str, str] = {
    "1": "staged",
    "2": "active",
    "3": "offline",
    "4": "decommissioning",
    "5": "staged",
}


def netbox_status_for(bm_status: str) -> str:
    return BM_STATUS_TO_NETBOX.get(str(bm_status), "active")
