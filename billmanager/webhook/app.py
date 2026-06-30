"""FastAPI-приёмник webhook'ов.

Эндпоинты:
  * POST /webhook/billmanager — событие из BillManager (создание/изменение
    услуги). Запускает sync одной услуги в NetBox.
  * POST /webhook/netbox      — событие из NetBox (задел под обратное
    направление). Сейчас только валидирует подпись и логирует.
  * GET  /healthz             — проверка живости.

Подпись NetBox: заголовок ``X-Hook-Signature`` = HMAC-SHA512(secret, body).
BillManager не подписывает webhooks — ограничьте доступ по сети/токену в URL.
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import FastAPI, Header, HTTPException, Request

from ..config import get_settings
from ..factory import ProdWriteGuardError, build_engine
from ..logging import configure_logging, get_logger

log = get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="linkey-netbox-billing", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhook/billmanager")
    async def billmanager_hook(request: Request) -> dict[str, object]:
        payload = await _json(request)
        service_id = (
            payload.get("id")
            or payload.get("elid")
            or payload.get("service_id")
            or payload.get("params", {}).get("elid")
        )
        if not service_id:
            raise HTTPException(422, "не найден id услуги в payload")
        log.info("webhook.billmanager.received", service_id=service_id)
        try:
            with build_engine(settings) as engine:
                result = engine.sync_service_by_id(service_id)
        except ProdWriteGuardError as exc:
            raise HTTPException(403, str(exc)) from None
        return {
            "synced_service": service_id,
            "services": result.services,
            "ips": result.ips,
            "errors": result.errors,
        }

    @app.post("/webhook/netbox")
    async def netbox_hook(
        request: Request, x_hook_signature: str = Header(default="")
    ) -> dict[str, str]:
        body = await request.body()
        _verify_netbox_signature(body, x_hook_signature, settings.netbox_webhook_secret)
        # TODO(двусторонняя): по событию NetBox обновлять услугу в BillManager.
        log.info("webhook.netbox.received", bytes=len(body))
        return {"status": "accepted"}

    return app


async def _json(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        # BillManager может слать form-data
        form = await request.form()
        data = dict(form)
    return data if isinstance(data, dict) else {}


def _verify_netbox_signature(body: bytes, signature: str, secret: str) -> None:
    if not secret:
        return  # подпись не настроена — пропускаем (не для прода)
    expected = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "неверная подпись webhook")


app = create_app()
