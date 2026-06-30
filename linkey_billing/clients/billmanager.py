"""Клиент BillManager (ISPsystem) API.

Документация: https://docs.ispsystem.ru/billmanager/razrabotchiku/vzaimodejstvie-cherez-api

Особенности API:
  * Базовый URL вида ``https://host:1500/billmgr``.
  * Функция вызывается через параметр ``func``; параметры — обычными query/form полями.
  * Авторизация двумя способами:
      - прямая:   ``authinfo=user:pass``
      - сессией:  ``auth=<session_id>`` (сессия создаётся через ``func=auth``).
    Здесь используется сессия: один логин, далее переиспользуем session id.
  * Формат ответа задаётся ``out=json``. JSON ISPsystem оборачивает скалярные
    значения в объект ``{"$": "value"}``, а коллекции — в ``elem: [...]``.
    Метод :meth:`_normalize` разворачивает это в обычные dict/list.
  * Ошибка приходит в ключе ``error`` — мы поднимаем :class:`BillManagerError`.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..logging import get_logger

log = get_logger(__name__)


class BillManagerError(RuntimeError):
    """Ошибка, возвращённая BillManager в поле ``error``."""

    def __init__(self, code: str | None, message: str, func: str, payload: Any = None):
        self.code = code
        self.message = message
        self.func = func
        self.payload = payload
        super().__init__(f"BillManager func={func} error[{code}]: {message}")


class BillManagerClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        verify_tls: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._session_id: str | None = None
        self._http = httpx.Client(verify=verify_tls, timeout=timeout)

    # --- жизненный цикл -------------------------------------------------

    def __enter__(self) -> "BillManagerClient":
        self.login()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # --- авторизация ----------------------------------------------------

    def login(self) -> str:
        """Создаёт сессию и запоминает её id."""
        data = self._raw_call(
            "auth",
            {"username": self._username, "password": self._password},
            authenticated=False,
        )
        # func=auth возвращает doc.auth.$id (или auth.id) в зависимости от версии
        auth = data.get("doc", data).get("auth", {})
        session = auth.get("id") or auth.get("$id") or auth.get("$")
        if not session:
            raise BillManagerError(None, "не удалось получить session id", "auth", data)
        self._session_id = session
        log.info("billmanager.login.ok")
        return session

    def logout(self) -> None:
        if self._session_id:
            try:
                self.call("session.delete")
            finally:
                self._session_id = None

    # --- низкоуровневый вызов ------------------------------------------

    def call(self, func: str, **params: Any) -> dict[str, Any]:
        """Вызов функции с авто-логином и нормализацией ответа."""
        if self._session_id is None:
            self.login()
        data = self._raw_call(func, params, authenticated=True)
        return self._normalize(self._unwrap_doc(data))

    def _raw_call(
        self, func: str, params: dict[str, Any], *, authenticated: bool
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"func": func, "out": "json", **_clean(params)}
        if authenticated:
            body["auth"] = self._session_id
        resp = self._http.post(self._base_url, data=body)
        resp.raise_for_status()
        data = resp.json()
        self._raise_on_error(data, func)
        return data

    @staticmethod
    def _raise_on_error(data: dict[str, Any], func: str) -> None:
        err = data.get("doc", {}).get("error") or data.get("error")
        if not err:
            return
        if isinstance(err, dict):
            code = err.get("$type") or err.get("code")
            msg = err.get("msg", {})
            message = msg.get("$") if isinstance(msg, dict) else str(msg or err)
        else:
            code, message = None, str(err)
        raise BillManagerError(code, message, func, data)

    # --- нормализация формата ISPsystem --------------------------------

    @staticmethod
    def _unwrap_doc(data: dict[str, Any]) -> dict[str, Any]:
        return data.get("doc", data)

    @classmethod
    def _normalize(cls, value: Any) -> Any:
        """Разворачивает {"$": v} в v и приводит elem к спискам."""
        if isinstance(value, dict):
            if set(value.keys()) == {"$"}:
                return value["$"]
            return {k: cls._normalize(v) for k, v in value.items() if not k.startswith("$")
                    or k == "$id"}
        if isinstance(value, list):
            return [cls._normalize(v) for v in value]
        return value

    # --- удобные обёртки над функциями управления услугами -------------
    # Имена func могут отличаться между версиями BillManager — при подключении
    # к реальной панели сверьтесь с `func=desktop` / swagger конкретной версии.

    def list_services(self, **filters: Any) -> list[dict[str, Any]]:
        """Список услуг (func=service). filters, напр. client=<id>."""
        data = self.call("service", **filters)
        return _as_list(data.get("elem"))

    def get_service(self, elid: str | int) -> dict[str, Any]:
        data = self.call("service.edit", elid=elid)
        return data

    def list_clients(self, **filters: Any) -> list[dict[str, Any]]:
        """Список клиентов (func=client)."""
        data = self.call("client", **filters)
        return _as_list(data.get("elem"))

    def get_client(self, elid: str | int) -> dict[str, Any]:
        return self.call("client.edit", elid=elid)

    def suspend_service(self, elid: str | int) -> dict[str, Any]:
        return self.call("service.suspend", elid=elid)

    def resume_service(self, elid: str | int) -> dict[str, Any]:
        return self.call("service.resume", elid=elid)

    def close_service(self, elid: str | int) -> dict[str, Any]:
        return self.call("service.close", elid=elid)


def _clean(params: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in params.items() if v is not None}


def _as_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
