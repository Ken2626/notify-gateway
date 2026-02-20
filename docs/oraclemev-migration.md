# OracleMEV Migration

## Goal

Replace direct Telegram push with notify-gateway HTTP ingest.

## Required OracleMEV env vars

- `NOTIFY_GATEWAY_URL`
- `NOTIFY_GATEWAY_TOKEN`
- `NOTIFY_SOURCE=oraclemev`
- `NOTIFY_ERROR_FORWARD=true`
- `NOTIFY_ERROR_COOLDOWN_MS=60000`
- `NOTIFY_TIMEOUT_MS=3000`

## Behavior

- `sendAlert(...)` -> sends `severity=critical`
- `logger.error(...)` -> auto sends `severity=warning` with local cooldown

