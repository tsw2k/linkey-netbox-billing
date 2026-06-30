# linkey-netbox-billing

Интеграция между **NetBox** (IPAM/DCIM) и **BillManager** (ISPsystem).
Отдельный Python-сервис: ходит в оба API, поддерживает запуск по webhook и из CLI.

Основное направление — **BillManager → NetBox**: продажа/изменение услуги в
биллинге проявляет ресурсы в NetBox (тенант клиента, VM/устройство, IP-адреса,
VLAN). Заложен задел под обратное направление (NetBox → BillManager).

## Что синхронизируется

| BillManager            | NetBox                          | Где хранится связь            |
|------------------------|---------------------------------|-------------------------------|
| Клиент                 | Tenant                          | CF `billmanager_id` у tenant  |
| Услуга                 | Virtual Machine (опц.)          | CF `billmanager_id` у VM      |
| Состояние услуги       | status объекта                  | CF `billmanager_status`       |
| IP услуги              | IPAM → ip-addresses             | CF `billmanager_id` у IP      |
| VLAN услуги            | IPAM → vlans                    | —                             |

Карта состояний услуги BillManager → status NetBox задана в
[`models.py`](linkey_billing/models.py) (`BM_STATUS_TO_NETBOX`).

## Архитектура

```
BillManager ──┐                         ┌── REST ──> NetBox
              │  clients/billmanager.py │   clients/netbox.py (pynetbox)
              v                         v
     adapters.py  ──>  models.py  ──>  sync/engine.py (SyncEngine)
                                          ^        ^
                              cli.py ─────┘        └───── webhook/app.py (FastAPI)
```

* `clients/billmanager.py` — клиент BillManager: сессионная авторизация,
  нормализация JSON-формата ISPsystem (`{"$": value}` → `value`), обёртки над
  функциями управления услугами.
* `clients/netbox.py` — обёртка над pynetbox с upsert-хелперами.
* `sync/adapters.py` — сырой ответ BillManager → канонические модели.
* `sync/engine.py` — оркестратор синхронизации (`SyncEngine`).
* `webhook/app.py` — приёмник webhook'ов (BillManager + NetBox).
* `cli.py` — команды для ручного запуска и отладки.

## Установка

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # заполните реальными значениями
```

## Подготовка NetBox

Один раз создайте custom fields (Admin → Customization → Custom Fields):

| Name                 | Type | Объекты                                              |
|----------------------|------|------------------------------------------------------|
| `billmanager_id`     | Text | tenant, virtual machine, ip-address                  |
| `billmanager_status` | Text | virtual machine, ip-address                          |

Заведите API-токен NetBox с правами на запись по нужным объектам и впишите его
в `.env` (`NETBOX_TOKEN`). Для создания VM из услуг нужен существующий кластер —
его ID передаётся параметром `--vm-cluster-id`.

## Использование

### CLI

```bash
# Полная сверка всех клиентов и услуг
linkey-billing sync-all --vm-cluster-id 1

# Синхронизировать одну услугу по ID
linkey-billing sync-service 12345 --vm-cluster-id 1

# Отладка маппинга — посмотреть сырой ответ BillManager
linkey-billing bm-services --client-id 42
linkey-billing bm-clients

# Запустить webhook-приёмник
linkey-billing serve
```

Режим `DRY_RUN=true` в `.env` логирует действия, ничего не записывая в NetBox —
удобно для первого прогона и проверки маппинга.

### Webhook

Запустите приёмник (`linkey-billing serve`, по умолчанию `:8080`) и настройте:

* **BillManager** → `POST http://<host>:8080/webhook/billmanager` на события
  изменения услуги. Ожидается `id`/`elid` услуги в теле (JSON или form-data).
* **NetBox** → `POST http://<host>:8080/webhook/netbox`. Подпись проверяется
  по `X-Hook-Signature` (HMAC-SHA512, секрет в `NETBOX_WEBHOOK_SECRET`).
  Обработчик пока только валидирует и логирует — точка расширения под обратное
  направление.

## Тесты

```bash
pytest -q          # юнит-тесты нормализации и адаптеров (без сети)
ruff check .
```

## ⚠️ Что сверить с вашей панелью BillManager

API ISPsystem отличается между версиями и набором модулей. До прода проверьте на
реальной панели и при необходимости поправьте:

1. **Имена функций** управления услугами в [`clients/billmanager.py`](linkey_billing/clients/billmanager.py)
   (`service`, `service.suspend`, `service.resume`, `service.close`, `client`).
   Сверьте через swagger вашей версии или `func=desktop`.
2. **Имена полей** в ответах — в [`sync/adapters.py`](linkey_billing/sync/adapters.py)
   (`name`/`realname`, `cpu`/`vcpu`, `ip`/`ipaddr`, `vlan` и т.д.).
   Сначала посмотрите фактический ответ командой `linkey-billing bm-services`.
3. **Коды состояний услуги** в `BM_STATUS_TO_NETBOX` ([`models.py`](linkey_billing/models.py)).
4. **Формат session id** в ответе `func=auth` (`auth.id` / `auth.$id`).

## Дорожная карта

- [x] Каркас сервиса, клиенты обоих API, CLI, webhook-приёмник
- [x] BillManager → NetBox: тенанты, услуги→VM, IP, VLAN
- [ ] Проверка маппинга на реальной панели и фикс имён func/полей
- [ ] Обратное направление NetBox → BillManager (обработчик `/webhook/netbox`)
- [ ] Идемпотентная сверка с удалением «осиротевших» объектов
- [ ] Контейнеризация (Dockerfile/compose) и деплой
```
