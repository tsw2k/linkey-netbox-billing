"""Конфигурация сервиса. Загружается из переменных окружения / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # BillManager
    billmgr_url: str = Field(..., description="https://host:1500/billmgr")
    billmgr_user: str
    billmgr_password: str
    billmgr_verify_tls: bool = True
    # Запись в BillManager (back-write выданного IP). true = не писать, только логировать.
    billmgr_readonly: bool = False
    # Функция и поле, через которые выданный IP фиксируется на услуге.
    # ВНИМАНИЕ: зависит от версии панели и processing-модуля — сверьте на реальной BillManager.
    billmgr_set_ip_func: str = "service.edit"
    billmgr_ip_field: str = "ip"

    # NetBox
    netbox_url: str
    netbox_token: str
    netbox_verify_tls: bool = True
    # Тег, которым помечаются все созданные/изменённые объекты (для песочницы).
    # Пусто = не тегировать. Удобно вычистить тест: фильтр по этому тегу.
    netbox_sandbox_tag: str = ""
    # Префикс-пул, из которого NetBox выдаёт IP при подключении услуги.
    # CIDR ("203.0.113.0/24") или числовой id префикса. Пусто = провижининг выключен.
    netbox_ip_pool_prefix: str = ""

    # --- предохранитель от записи в прод ---
    # Подстроки, идентифицирующие прод-NetBox (через запятую), напр. "netbox.prod.local".
    # Если NETBOX_URL содержит любую из них — запись блокируется, пока не задан allow_prod.
    netbox_prod_markers: str = ""
    # Явное разрешение писать в прод (env ALLOW_PROD=true или флаг --allow-prod).
    allow_prod: bool = False

    # Webhook
    netbox_webhook_secret: str = ""
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8080

    # Общее
    log_level: str = "INFO"
    dry_run: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
