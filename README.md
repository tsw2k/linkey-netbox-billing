# linkey-netbox-billing

Интеграция между **NetBox** (IPAM/DCIM) и **BillManager** (ISPsystem).
Отдельный Python-сервис: ходит в оба API, поддерживает запуск по webhook и из CLI.

Основной сценарий — **dedicated servers**: при подключении услуги в BillManager
**NetBox выдаёт свободный IP** из пула, адрес **записывается обратно в BillManager**
(фиксируется на услуге), а в NetBox остаётся учёт IP с привязкой к клиенту.

## Поток провижининга IP (главное)

```
Услуга подключена в BillManager ──webhook──> интеграция
   1. NetBox: взять следующий свободный IP из NETBOX_IP_POOL_PREFIX (IPAM available-ips)
   2. NetBox: привязать IP к тенанту клиента + CF billmanager_id (= id услуги)
   3. BillManager: записать выданный адрес на услугу (зафиксировать в биллинге)
```

Идемпотентно: если услуге уже выдан адрес (по `billmanager_id`) — он
переиспользуется, второй не выдаётся. Если у услуги **уже есть** IP в биллинге —
он просто отражается в NetBox (без выдачи нового).

## Что синхронизируется

| BillManager            | NetBox                          | Где хранится связь            |
|------------------------|---------------------------------|-------------------------------|
| Клиент                 | Tenant                          | CF `billmanager_id` у tenant  |
| Услуга (выданный IP)   | IPAM → ip-addresses (из пула)   | CF `billmanager_id` у IP      |
| Состояние услуги       | status объекта                  | CF `billmanager_status`       |
| VLAN услуги            | IPAM → vlans                    | —                             |
| Услуга (опц., позже)   | Virtual Machine                 | CF `billmanager_id` у VM      |

> **VM сейчас вне фокуса** — код есть (`--vm-cluster-id`), но по умолчанию не
> используется. Понадобится позже; для dedicated servers не нужен.

Карта состояний услуги BillManager → status NetBox задана в
[`models.py`](billmanager/models.py) (`BM_STATUS_TO_NETBOX`).

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
git config core.hooksPath .githooks   # включить защиту от коммита секретов
```

> **Секреты.** Реальные креды хранятся только в `.env`, который в `.gitignore` и
> в репозиторий не попадает (коммитится лишь `.env.example` с заглушками).
> Pre-commit hook в `.githooks/` дополнительно блокирует случайный коммит `.env`,
> ключей и строк, похожих на реальные пароли/токены.

## Подготовка NetBox

Один раз создайте custom fields (Admin → Customization → Custom Fields):

| Name                 | Type | Объекты                                              |
|----------------------|------|------------------------------------------------------|
| `billmanager_id`     | Text | tenant, virtual machine, ip-address                  |
| `billmanager_status` | Text | virtual machine, ip-address                          |

Заведите API-токен NetBox с правами на запись по нужным объектам и впишите его
в `.env` (`NETBOX_TOKEN`).

Для провижининга создайте в NetBox **префикс-пул**, из которого будут выдаваться
адреса, и укажите его в `NETBOX_IP_POOL_PREFIX` (CIDR, напр. `203.0.113.0/24`,
либо числовой id префикса).

## Использование

### CLI

```bash
# Полная сверка всех клиентов и услуг
billmanager sync-all --vm-cluster-id 1

# Синхронизировать одну услугу по ID
billmanager sync-service 12345 --vm-cluster-id 1

# Отладка маппинга — посмотреть сырой ответ BillManager
billmanager bm-services --client-id 42
billmanager bm-clients

# Запустить webhook-приёмник
billmanager serve
```

Режим `DRY_RUN=true` в `.env` логирует действия, ничего не записывая в NetBox —
удобно для первого прогона и проверки маппинга.

### Webhook

Запустите приёмник (`billmanager serve`, по умолчанию `:8080`) и настройте:

* **BillManager** → `POST http://<host>:8080/webhook/billmanager` на события
  изменения услуги. Ожидается `id`/`elid` услуги в теле (JSON или form-data).
* **NetBox** → `POST http://<host>:8080/webhook/netbox`. Подпись проверяется
  по `X-Hook-Signature` (HMAC-SHA512, секрет в `NETBOX_WEBHOOK_SECRET`).
  Обработчик пока только валидирует и логирует — точка расширения под обратное
  направление.

## Безопасное тестирование (без прод-NetBox)

Запись идёт **только в NetBox** — BillManager в этом направлении лишь читается.
Поэтому безопасная схема: **читаем реальный BillManager** (read-only пользователь),
а **пишем в одноразовый NetBox** в Docker. Прод NetBox не затрагивается.

Три встроенных предохранителя:

1. **Песочница NetBox** в Docker — [`deploy/sandbox/`](deploy/sandbox/):
   ```bash
   cd deploy/sandbox
   docker compose up -d        # поднять NetBox+Postgres+Redis (UI :8000, admin/admin)
   ./bootstrap.sh              # создать custom fields + тег billmanager-sandbox
   cd ../.. && cp deploy/sandbox/env.sandbox.example .env   # вписать read-only креды BillManager
   billmanager sync-all
   # после тестов:
   cd deploy/sandbox && docker compose down -v   # снести вместе с данными
   ```
2. **Авто-тег** `NETBOX_SANDBOX_TAG=billmanager-sandbox` — все созданные/изменённые
   объекты помечаются тегом, потом легко найти и вычистить фильтром по нему.
3. **Prod-guard** — `NETBOX_PROD_MARKERS` со списком подстрок прод-хостов. Если
   `NETBOX_URL` совпал с маркером, запись **блокируется**, пока не задан
   `ALLOW_PROD=true` (или флаг `--allow-prod`). `DRY_RUN=true` guard не трогает.

Дополнительно — `--only-client <bm_id>` ограничивает сверку одним клиентом, чтобы
не гонять весь биллинг при отладке.

> В **проде** (запись в боевой NetBox — это норма) поставьте `ALLOW_PROD=true`
> или оставьте `NETBOX_PROD_MARKERS` пустым.

## Деплой

Продакшен-вариант — webhook-демон под **systemd** за **nginx с TLS**. Готовые
файлы и пошаговая инструкция: [`deploy/DEPLOY.md`](deploy/DEPLOY.md).

* [`deploy/billmanager-webhook.service`](deploy/billmanager-webhook.service) — systemd-юнит.
* [`deploy/nginx-billmanager.conf`](deploy/nginx-billmanager.conf) — reverse-proxy + TLS, allow-лист источников.

## Тесты

```bash
pytest -q          # юнит-тесты нормализации и адаптеров (без сети)
ruff check .
```

## ⚠️ Что сверить с вашей панелью BillManager

API ISPsystem отличается между версиями и набором модулей. До прода проверьте на
реальной панели и при необходимости поправьте:

1. **Имена функций** управления услугами в [`clients/billmanager.py`](billmanager/clients/billmanager.py)
   (`service`, `service.suspend`, `service.resume`, `service.close`, `client`).
   Сверьте через swagger вашей версии или `func=desktop`.
2. **Имена полей** в ответах — в [`sync/adapters.py`](billmanager/sync/adapters.py)
   (`name`/`realname`, `cpu`/`vcpu`, `ip`/`ipaddr`, `vlan` и т.д.).
   Сначала посмотрите фактический ответ командой `billmanager bm-services`.
3. **Запись IP обратно в биллинг** — `BILLMGR_SET_IP_FUNC` / `BILLMGR_IP_FIELD`
   ([`clients/billmanager.py`](billmanager/clients/billmanager.py), `set_service_ip`).
   Как именно адрес фиксируется на услуге, зависит от processing-модуля dedic в
   вашей панели. Сначала проверяйте с `BILLMGR_READONLY=true` (запись логируется,
   но не выполняется), затем сверьте func/поле и снимите readonly.
4. **Коды состояний услуги** в `BM_STATUS_TO_NETBOX` ([`models.py`](billmanager/models.py)).
5. **Формат session id** в ответе `func=auth` (`auth.id` / `auth.$id`).

## Дорожная карта

- [x] Каркас сервиса, клиенты обоих API, CLI, webhook-приёмник
- [x] Провижининг dedicated servers: NetBox выдаёт IP → запись обратно в BillManager
- [x] Тенанты (клиенты), отражение существующих IP, VLAN
- [x] Деплой webhook-демона: systemd + nginx (TLS) — см. `deploy/`
- [x] Безопасное тестирование: песочница NetBox, авто-тег, prod-guard, readonly, `--only-client`
- [ ] Проверка на реальной панели: func/поле записи IP, имена полей услуг
- [ ] Идемпотентная сверка (reconcile) с отчётом по «осиротевшим» объектам
- [ ] Поддержка VM (отложено) и обратные события NetBox → BillManager
- [ ] Контейнеризация (Dockerfile/compose)
```
