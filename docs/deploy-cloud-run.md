# Cloud Run Deployment (us-west1)

This project is designed for image-based deployment:

GitHub Actions build -> Artifact Registry -> Cloud Run `--image` deploy

If you are starting from zero, run the one-time setup first:
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

Set secrets on Cloud Run service (recommended via Secret Manager), then set non-secret route config:

```bash
gcloud run services update notify-gateway \
  --region us-west1 \
  --update-env-vars "^@^ENABLED_CHANNELS=tg,wecom,serverchan@ROUTE_CRITICAL=tg,wecom@ROUTE_WARNING=wecom@ROUTE_INFO=tg@DEDUPE_WINDOW_MS=45000"
```

## Required runtime env vars

- `NOTIFY_GATEWAY_TOKEN`
- `ALERTMANAGER_WEBHOOK_TOKEN`
- `TG_BOT_TOKEN`
- `TG_CHAT_ID`
- `WECOM_WEBHOOK_URL`
- `SERVERCHAN_SENDKEY` (optional)

## Domain with Cloudflare

Use Cloud Run domain mapping and add Cloudflare DNS records based on GCP mapping output.
