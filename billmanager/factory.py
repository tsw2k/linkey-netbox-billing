"""Сборка клиентов и движка синхронизации из настроек."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from .clients.billmanager import BillManagerClient
from .clients.netbox import NetBoxClient
from .config import Settings, get_settings
from .logging import get_logger
from .sync.engine import SyncEngine

log = get_logger(__name__)


class ProdWriteGuardError(RuntimeError):
    """NETBOX_URL опознан как прод, а запись не разрешена явно."""


def build_netbox(settings: Settings | None = None) -> NetBoxClient:
    s = settings or get_settings()
    return NetBoxClient(
        s.netbox_url,
        s.netbox_token,
        verify_tls=s.netbox_verify_tls,
        sandbox_tag=s.netbox_sandbox_tag,
    )


def build_billmanager(settings: Settings | None = None) -> BillManagerClient:
    s = settings or get_settings()
    return BillManagerClient(
        s.billmgr_url, s.billmgr_user, s.billmgr_password, verify_tls=s.billmgr_verify_tls
    )


def assert_write_target_allowed(s: Settings, *, allow_prod: bool) -> None:
    """Блокирует запись в прод-NetBox, пока она не разрешена явно.

    Срабатывает только при реальной записи (не dry_run). Если NETBOX_URL содержит
    любую из подстрок NETBOX_PROD_MARKERS и allow_prod не задан — поднимает ошибку.
    """
    if s.dry_run or allow_prod or s.allow_prod:
        return
    markers = [m.strip() for m in s.netbox_prod_markers.split(",") if m.strip()]
    hit = next((m for m in markers if m in s.netbox_url), None)
    if hit:
        raise ProdWriteGuardError(
            f"NETBOX_URL ({s.netbox_url}) опознан как прод по маркеру '{hit}'. "
            "Запись заблокирована. Используйте DRY_RUN=true, песочницу, "
            "или явно разрешите запись: --allow-prod / ALLOW_PROD=true."
        )


@contextmanager
def build_engine(
    settings: Settings | None = None,
    *,
    vm_cluster_id: int | None = None,
    only_client: str | None = None,
    allow_prod: bool = False,
) -> Iterator[SyncEngine]:
    s = settings or get_settings()
    assert_write_target_allowed(s, allow_prod=allow_prod)
    bm = build_billmanager(s)
    nb = build_netbox(s)
    try:
        bm.login()
        yield SyncEngine(
            bm,
            nb,
            vm_cluster_id=vm_cluster_id,
            dry_run=s.dry_run,
            only_client=only_client,
        )
    finally:
        bm.close()
