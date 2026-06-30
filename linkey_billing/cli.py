"""CLI интеграции. Запуск: ``linkey-billing <команда>`` или ``python -m linkey_billing``."""

from __future__ import annotations

import json

import typer

from .config import get_settings
from .factory import build_billmanager, build_engine
from .logging import configure_logging, get_logger

app = typer.Typer(help="Интеграция NetBox ↔ BillManager", no_args_is_help=True)
log = get_logger(__name__)


@app.callback()
def _main() -> None:
    configure_logging(get_settings().log_level)


@app.command()
def sync_all(
    vm_cluster_id: int = typer.Option(
        None, help="ID кластера NetBox для создания VM из услуг (без него VM не создаются)"
    ),
) -> None:
    """Полная сверка всех клиентов и услуг BillManager → NetBox."""
    with build_engine(vm_cluster_id=vm_cluster_id) as engine:
        result = engine.sync_all()
    typer.echo(
        f"tenants={result.tenants} services={result.services} "
        f"ips={result.ips} vlans={result.vlans} errors={len(result.errors)}"
    )
    for err in result.errors:
        typer.echo(f"  ! {err}", err=True)


@app.command()
def sync_service(
    service_id: str = typer.Argument(..., help="ID услуги в BillManager"),
    vm_cluster_id: int = typer.Option(None),
) -> None:
    """Синхронизировать одну услугу по её ID."""
    with build_engine(vm_cluster_id=vm_cluster_id) as engine:
        result = engine.sync_service_by_id(service_id)
    typer.echo(f"services={result.services} ips={result.ips} errors={len(result.errors)}")


@app.command()
def bm_services(
    client_id: str = typer.Option(None, help="Фильтр по ID клиента"),
    limit: int = typer.Option(20),
) -> None:
    """Показать сырой список услуг из BillManager (для отладки маппинга)."""
    bm = build_billmanager()
    try:
        bm.login()
        filters = {"client": client_id} if client_id else {}
        services = bm.list_services(**filters)[:limit]
        typer.echo(json.dumps(services, ensure_ascii=False, indent=2))
    finally:
        bm.close()


@app.command()
def bm_clients(limit: int = typer.Option(20)) -> None:
    """Показать сырой список клиентов из BillManager."""
    bm = build_billmanager()
    try:
        bm.login()
        typer.echo(json.dumps(bm.list_clients()[:limit], ensure_ascii=False, indent=2))
    finally:
        bm.close()


@app.command()
def serve() -> None:
    """Запустить webhook-приёмник (uvicorn)."""
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "linkey_billing.webhook.app:app", host=s.webhook_host, port=s.webhook_port, reload=False
    )


if __name__ == "__main__":
    app()
