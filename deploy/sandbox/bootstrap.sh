#!/usr/bin/env bash
# Готовит песочницу NetBox: ждёт запуск и создаёт нужные custom fields + тег.
# Запуск: ./bootstrap.sh   (после docker compose up -d)
set -euo pipefail

NB_URL="${NB_URL:-http://localhost:8000}"
NB_TOKEN="${NB_TOKEN:-0123456789abcdef0123456789abcdef01234567}"
H_AUTH="Authorization: Token ${NB_TOKEN}"
H_JSON="Content-Type: application/json"

echo "Жду готовности NetBox на ${NB_URL} ..."
for i in $(seq 1 60); do
    if curl -fsS -H "$H_AUTH" "${NB_URL}/api/status/" >/dev/null 2>&1; then
        echo "  NetBox готов."
        break
    fi
    sleep 5
    [ "$i" = 60 ] && { echo "NetBox не поднялся за 5 минут" >&2; exit 1; }
done

# Создать custom field, если его ещё нет.
create_cf() {
    local name="$1" objects="$2"
    if curl -fsS -H "$H_AUTH" "${NB_URL}/api/extras/custom-fields/?name=${name}" | grep -q "\"name\":\"${name}\""; then
        echo "  CF ${name}: уже есть"
        return
    fi
    curl -fsS -X POST -H "$H_AUTH" -H "$H_JSON" "${NB_URL}/api/extras/custom-fields/" \
        -d "{\"name\":\"${name}\",\"type\":\"text\",\"object_types\":${objects},\"label\":\"${name}\"}" \
        >/dev/null
    echo "  CF ${name}: создан"
}

# object_types в формате API v4: "<app>.<model>"
TENANT_IP_VM='["tenancy.tenant","ipam.ipaddress","virtualization.virtualmachine"]'
VM_IP='["virtualization.virtualmachine","ipam.ipaddress"]'

create_cf "billmanager_id" "$TENANT_IP_VM"
create_cf "billmanager_status" "$VM_IP"

# Тег песочницы.
if curl -fsS -H "$H_AUTH" "${NB_URL}/api/extras/tags/?slug=billmanager-sandbox" | grep -q '"slug":"billmanager-sandbox"'; then
    echo "  tag billmanager-sandbox: уже есть"
else
    curl -fsS -X POST -H "$H_AUTH" -H "$H_JSON" "${NB_URL}/api/extras/tags/" \
        -d '{"name":"billmanager-sandbox","slug":"billmanager-sandbox","color":"ff9800"}' >/dev/null
    echo "  tag billmanager-sandbox: создан"
fi

# Тестовый префикс-пул, из которого выдаются адреса (NETBOX_IP_POOL_PREFIX).
POOL="${POOL_PREFIX:-203.0.113.0/24}"
if curl -fsS -H "$H_AUTH" "${NB_URL}/api/ipam/prefixes/?prefix=${POOL}" | grep -q "\"prefix\":\"${POOL}\""; then
    echo "  prefix ${POOL}: уже есть"
else
    curl -fsS -X POST -H "$H_AUTH" -H "$H_JSON" "${NB_URL}/api/ipam/prefixes/" \
        -d "{\"prefix\":\"${POOL}\",\"status\":\"active\",\"description\":\"sandbox pool\"}" >/dev/null
    echo "  prefix ${POOL}: создан"
fi

echo "Готово. Скопируйте deploy/sandbox/env.sandbox.example в .env для тестов."
