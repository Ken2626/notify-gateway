# Cloud Run Deployment (us-west1)

Deployment path:

GitHub Actions build -> Artifact Registry -> Cloud Run `--image` deploy

If starting from zero, run one-time setup first:
`docs/one-time-bootstrap.md`.

## Required Cloud Run settings

- `region=us-west1`
- `min-instances=0`
- `max-instances=1`
- `cpu=1`
- `memory=512Mi`
- `concurrency=20`
- `timeout=30s`

## One-time environment setup

```bash
gcloud run services update notify-gateway \
  --region us-west1 \
  --update-env-vars "^@^ENABLED_CHANNELS=tg,wecom,serverchan@ROUTE_CRITICAL=tg,wecom@ROUTE_WARNING=tg,wecom@ROUTE_INFO=tg,wecom@DEDUPE_WINDOW_MS=45000"
```

This route update command does not modify `NOTIFY_TIMEZONE`.

## Required runtime env vars

- `NOTIFY_GATEWAY_TOKEN`
- `ALERTMANAGER_WEBHOOK_TOKEN`
- `NOTIFY_TIMEZONE` (optional, default `UTC`, e.g. `Asia/Shanghai`)

And at least one delivery config method:

1. `APPRISE_CONFIG_YAML_B64` (recommended)
2. `APPRISE_URLS_JSON`
3. Legacy single credentials:
- `TG_BOT_TOKEN`
- `TG_CHAT_ID`
- `WECOM_WEBHOOK_URL`
- `SERVERCHAN_SENDKEY` (optional)

Optional advanced routing vars:

- `SOURCE_ROUTE_JSON`
- `CHANNEL_TAG_MAP_JSON`

## Set/update timezone example

```bash
gcloud run services update notify-gateway \
  --region us-west1 \
  --update-env-vars "NOTIFY_TIMEZONE=Asia/Shanghai"
```

## Domain via Cloudflare

Use Cloud Run domain mapping + Cloudflare DNS CNAME.

Detailed steps:

- `docs/cloudflare-cname.md`
