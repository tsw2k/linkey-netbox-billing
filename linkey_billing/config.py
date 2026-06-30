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

    # NetBox
    netbox_url: str
    netbox_token: str
    netbox_verify_tls: bool = True

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
