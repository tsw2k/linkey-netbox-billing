# Деплой webhook-приёмника через systemd + nginx (TLS)

Схема: `NetBox / BillManager` → (HTTPS) → `nginx` → (127.0.0.1:8080) → `billmanager serve`.

Приёмник — stateless-демон под systemd. nginx терминирует TLS и ограничивает доступ
по источнику. Своего состояния/БД у сервиса нет.

## Предусловия

- Linux с **Python 3.11+**, `git`, `nginx`, `certbot` (для Let's Encrypt).
- Сетевая связность:
  - **исходящая** с VM: до BillManager (TCP 1500) и NetBox (TCP 443);
  - **входящая** на VM: TCP 443 от NetBox и BillManager (для webhook'ов).
- Подготовлены креды: API-пользователь BillManager, токен NetBox с правом записи,
  созданные в NetBox custom fields `billmanager_id` / `billmanager_status`.

## 1. Системный пользователь и код

```bash
sudo useradd --system --home /opt/linkey-netbox-billing --shell /usr/sbin/nologin billmanager
sudo git clone ssh://git@ssh.github.com:443/tsw2k/linkey-netbox-billing.git /opt/linkey-netbox-billing
cd /opt/linkey-netbox-billing
sudo python3 -m venv .venv
sudo .venv/bin/pip install -e .
sudo chown -R billmanager:billmanager /opt/linkey-netbox-billing
```

## 2. Конфигурация (.env)

```bash
sudo -u billmanager cp .env.example .env
sudo -u billmanager nano .env      # заполнить креды
sudo chmod 600 .env                # секреты только для владельца
```

В `.env` для работы за nginx обязательно:

```ini
WEBHOOK_HOST=127.0.0.1     # наружу слушает только nginx, не сам сервис
WEBHOOK_PORT=8080
NETBOX_WEBHOOK_SECRET=<длинный случайный секрет>   # для HMAC-проверки подписи NetBox
```

Проверка связности до запуска демона:

```bash
sudo -u billmanager .venv/bin/billmanager bm-clients          # BillManager отвечает?
sudo -u billmanager DRY_RUN=true .venv/bin/billmanager sync-all  # оба API опрошены, NetBox не пишется
```

## 3. systemd-юнит

```bash
sudo cp deploy/billmanager-webhook.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now billmanager-webhook
sudo systemctl status billmanager-webhook
journalctl -u billmanager-webhook -f      # логи
```

Проверка локально:

```bash
curl -s http://127.0.0.1:8080/healthz      # {"status":"ok"}
```

## 4. nginx + TLS

```bash
sudo cp deploy/nginx-billmanager.conf /etc/nginx/sites-available/billmanager-webhook
sudo ln -s /etc/nginx/sites-available/billmanager-webhook /etc/nginx/sites-enabled/
# Заменить webhook.example.com на реальный домен и раскомментировать allow-список IP
sudo nano /etc/nginx/sites-available/billmanager-webhook

sudo certbot --nginx -d webhook.example.com   # выпустит сертификат и пропишет пути
sudo nginx -t && sudo systemctl reload nginx
```

Проверка снаружи:

```bash
curl -s https://webhook.example.com/healthz   # {"status":"ok"}
```

## 5. Настройка источников webhook

- **BillManager** → `POST https://webhook.example.com/webhook/billmanager` на событие
  изменения услуги. В теле должен быть `id`/`elid` услуги.
- **NetBox** (Operations → Webhooks) → `POST https://webhook.example.com/webhook/netbox`,
  Secret = тот же `NETBOX_WEBHOOK_SECRET`. Подпись проверяется по `X-Hook-Signature`.

## Обновление версии

```bash
cd /opt/linkey-netbox-billing
sudo -u billmanager git pull
sudo .venv/bin/pip install -e .
sudo systemctl restart billmanager-webhook
```

## Подстраховка (опционально)

Webhook покрывает события в реальном времени, но может пропустить сбойную доставку.
Полезно держать ночную полную сверку как «страховку» — cron от имени пользователя:

```cron
# /etc/cron.d/billmanager-sync
0 3 * * * billmanager cd /opt/linkey-netbox-billing && .venv/bin/billmanager sync-all >> /var/log/billmanager-sync.log 2>&1
```
