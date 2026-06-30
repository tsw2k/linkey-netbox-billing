"""Сборка клиентов и движка синхронизации из настроек."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from .clients.billmanager import BillManagerClient
from .clients.netbox import NetBoxClient
from .config import Settings, get_settings
from .sync.engine import SyncEngine


def build_netbox(settings: Settings | None = None) -> NetBoxClient:
    s = settings or get_settings()
    return NetBoxClient(s.netbox_url, s.netbox_token, verify_tls=s.netbox_verify_tls)


def build_billmanager(settings: Settings | None = None) -> BillManagerClient:
    s = settings or get_settings()
    return BillManagerClient(
        s.billmgr_url, s.billmgr_user, s.billmgr_password, verify_tls=s.billmgr_verify_tls
    )


@contextmanager
def build_engine(
    settings: Settings | None = None, *, vm_cluster_id: int | None = None
) -> Iterator[SyncEngine]:
    s = settings or get_settings()
    bm = build_billmanager(s)
    nb = build_netbox(s)
    try:
        bm.login()
        yield SyncEngine(bm, nb, vm_cluster_id=vm_cluster_id, dry_run=s.dry_run)
    finally:
        bm.close()
