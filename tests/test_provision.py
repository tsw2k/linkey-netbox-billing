"""Логика провижининга IP: выдать из NetBox + записать обратно в BillManager."""

from __future__ import annotations

from billmanager.models import Service
from billmanager.sync.engine import SyncEngine, SyncResult


class FakeIP:
    def __init__(self, address: str) -> None:
        self.address = address


class FakeNB:
    def __init__(self, existing: FakeIP | None = None) -> None:
        self._existing = existing
        self.allocated: list[dict] = []

    def find_ip_by_bm_service(self, bm_id):
        return self._existing

    def allocate_ip_from_prefix(self, prefix, **kw):
        self.allocated.append({"prefix": prefix, **kw})
        return FakeIP("203.0.113.7/24")


class FakeBM:
    def __init__(self) -> None:
        self.writes: list[dict] = []

    def set_service_ip(self, elid, ip, **kw):
        self.writes.append({"elid": elid, "ip": ip, **kw})
        return {}


def _svc() -> Service:
    return Service(bm_id="55", name="dedic-1", client_bm_id="42", status="2")


def _engine(nb, bm, **kw) -> SyncEngine:
    return SyncEngine(bm, nb, ip_pool_prefix="203.0.113.0/24", **kw)


def test_allocate_and_writeback():
    nb, bm = FakeNB(existing=None), FakeBM()
    eng = _engine(nb, bm)
    result = SyncResult()
    eng._provision_ip(_svc(), tenant_id=1, nb_status="active", result=result)

    assert len(nb.allocated) == 1            # выдан новый адрес
    assert result.ips == 1
    assert bm.writes == [{"elid": "55", "ip": "203.0.113.7", "func": "service.edit", "field": "ip"}]


def test_readonly_skips_billmanager_write():
    nb, bm = FakeNB(existing=None), FakeBM()
    eng = _engine(nb, bm, billmgr_readonly=True)
    eng._provision_ip(_svc(), tenant_id=1, nb_status="active", result=SyncResult())

    assert len(nb.allocated) == 1            # адрес всё равно выдан в NetBox
    assert bm.writes == []                    # но в биллинг не писали


def test_reuse_existing_ip_no_double_allocation():
    nb, bm = FakeNB(existing=FakeIP("203.0.113.5/24")), FakeBM()
    eng = _engine(nb, bm)
    result = SyncResult()
    eng._provision_ip(_svc(), tenant_id=1, nb_status="active", result=result)

    assert nb.allocated == []                 # новый не выдавали
    assert result.ips == 0
    assert bm.writes[0]["ip"] == "203.0.113.5"  # записали переиспользованный
