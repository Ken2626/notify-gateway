#!/bin/sh
set -eu

export PORT="${PORT:-8080}"
export ALERTMANAGER_PORT="${ALERTMANAGER_PORT:-9093}"

AM_CONFIG_PATH="/tmp/alertmanager.yml"
AM_STORAGE_PATH="/tmp/alertmanager-data"

mkdir -p "${AM_STORAGE_PATH}"

cat > "${AM_CONFIG_PATH}" <<EOCFG
global:
  resolve_timeout: 5m

route:
  group_by: ['source', 'alertname', 'severity']
  group_wait: 10s
  group_interval: 60s
  repeat_interval: 30m
  receiver: dispatcher-webhook

receivers:
  - name: dispatcher-webhook
    webhook_configs:
      - url: "http://127.0.0.1:${PORT}/dispatch/v1/alertmanager"
        send_resolved: true
        max_alerts: 0
        http_config:
          authorization:
            type: Bearer
            credentials: "${ALERTMANAGER_WEBHOOK_TOKEN}"
EOCFG

/usr/local/bin/alertmanager \
  --config.file="${AM_CONFIG_PATH}" \
  --storage.path="${AM_STORAGE_PATH}" \
  --web.listen-address="127.0.0.1:${ALERTMANAGER_PORT}" \
  --log.level="info" &
AM_PID=$!

READY=0
for _ in $(seq 1 30); do
  if wget -q -O- "http://127.0.0.1:${ALERTMANAGER_PORT}/-/ready" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done

if [ "${READY}" -ne 1 ]; then
  echo "alertmanager failed to become ready"
  kill "${AM_PID}" 2>/dev/null || true
  wait "${AM_PID}" 2>/dev/null || true
  exit 1
fi

node src/index.js &
APP_PID=$!

cleanup() {
  kill "${APP_PID}" 2>/dev/null || true
  kill "${AM_PID}" 2>/dev/null || true
}

trap cleanup INT TERM

while true; do
  if ! kill -0 "${AM_PID}" 2>/dev/null; then
    echo "alertmanager exited unexpectedly"
    kill "${APP_PID}" 2>/dev/null || true
    wait "${APP_PID}" 2>/dev/null || true
    exit 1
  fi

  if ! kill -0 "${APP_PID}" 2>/dev/null; then
    wait "${APP_PID}"
    APP_EXIT=$?
    kill "${AM_PID}" 2>/dev/null || true
    wait "${AM_PID}" 2>/dev/null || true
    exit "${APP_EXIT}"
  fi

  sleep 1
done
