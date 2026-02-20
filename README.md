# notify-gateway

Unified notification gateway using **Alertmanager + Dispatcher** in a single container.

## Features

- Public ingest API for bots:
  - `POST /ingest/v1/event`
  - `POST /ingest/v1/alerts`
- Internal dispatch endpoint:
  - `POST /dispatch/v1/alertmanager`
- Bearer auth on both public and internal webhook paths
- Configurable severity routing:
  - `ROUTE_CRITICAL`
  - `ROUTE_WARNING`
  - `ROUTE_INFO`
- Channels:
  - Telegram (`tg`)
  - WeCom (`wecom`)
  - ServerChan (`serverchan`)
- Reliability:
  - In-memory dedupe (`45s` default)
  - Retry backoff (`1000,2000,4000` default)

## Default routing

- `critical -> tg,wecom`
- `warning -> wecom`
- `info -> tg`

## Local run

```bash
cp .env.example .env
npm install
npm run start
```

## One-time bootstrap

```bash
bash ./scripts/one-time-bootstrap.sh
```

On Debian/Ubuntu, the script can prompt to auto-install missing `gcloud` (and `gh` if needed).

## Docker

```bash
docker build -t notify-gateway:local .
docker run --rm -p 8080:8080 --env-file .env notify-gateway:local
```

## API example

```bash
curl -X POST http://127.0.0.1:8080/ingest/v1/event \
  -H "Authorization: Bearer $NOTIFY_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "oraclemev",
    "severity": "critical",
    "summary": "oracle deviation detected",
    "description": "price deviates over threshold"
  }'
```

See `docs/one-time-bootstrap.md`, `docs/push-main-to-cloud-run.md`, `docs/deploy-cloud-run.md`, `docs/github-actions-oidc.md`, and `docs/oraclemev-migration.md` for deployment and integration.
