# notify-gateway

Unified notification gateway with a **Python compatibility API** and **Apprise-based delivery**.

## Features

- API compatible ingest endpoints for bots:
  - `POST /ingest/v1/event`
  - `POST /ingest/v1/alerts`
  - `POST /dispatch/v1/alertmanager` (internal compatibility endpoint)
- Bearer auth on public ingest endpoints (`NOTIFY_GATEWAY_TOKEN`)
- Configurable severity routing (`ROUTE_CRITICAL|ROUTE_WARNING|ROUTE_INFO`)
- Optional source-specific routing (`SOURCE_ROUTE_JSON`)
- Channel fanout via Apprise tags (supports multi TG bot / multi WeCom webhook)
- In-memory dedupe and retry backoff
- Timezone-aware timestamp formatting (`NOTIFY_TIMEZONE`)

## Default routing

- `critical -> tg,wecom`
- `warning -> tg,wecom`
- `info -> tg,wecom`

## Local run

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash ./scripts/entrypoint.sh
```

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
    "source": "my-bot",
    "severity": "critical",
    "summary": "high-priority event detected",
    "description": "event exceeds configured threshold"
  }'
```

## Deployment docs

- `docs/one-time-bootstrap.md`
- `docs/push-main-to-cloud-run.md`
- `docs/deploy-cloud-run.md`
- `docs/github-actions-oidc.md`
- `docs/cloudflare-cname.md`
