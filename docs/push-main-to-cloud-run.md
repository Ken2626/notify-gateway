# 从 push main 到 Cloud Run 完成部署（完整操作指南）

当前流程：

`GitHub Actions -> Artifact Registry -> Cloud Run(us-west1)`

## 0. 一次性前置

先执行：

- `docs/one-time-bootstrap.md`
- 或直接运行 `bash ./scripts/one-time-bootstrap.sh`

最小检查点：

1. GitHub 变量：`GCP_PROJECT_ID`
2. GitHub secrets：`GCP_WORKLOAD_IDENTITY_PROVIDER`、`GCP_SERVICE_ACCOUNT_EMAIL`
3. Artifact Registry：`us-west1/notify-gateway`
4. Cloud Run 服务：`notify-gateway`
5. Cloud Run 环境变量：`NOTIFY_GATEWAY_TOKEN`、`ALERTMANAGER_WEBHOOK_TOKEN`

## 1. 推送代码到 main

```bash
git add .
git commit -m "your change"
git push origin main
```

## 2. GitHub Actions 自动执行

`.github/workflows/deploy-cloud-run.yml` 会执行：

1. Checkout
2. OIDC 登录 GCP
3. 配置 gcloud
4. Docker 构建并推送镜像（`GITHUB_SHA` + `latest`）
5. `gcloud run deploy --image ... --region us-west1`
6. 更新路由环境变量：
- `ENABLED_CHANNELS=tg,wecom,serverchan`
- `ROUTE_CRITICAL=tg,wecom`
- `ROUTE_WARNING=tg,wecom`
- `ROUTE_INFO=tg,wecom`
- `DEDUPE_WINDOW_MS=45000`

## 3. 验证部署成功

```bash
gcloud run services describe notify-gateway \
  --region us-west1 \
  --format='value(status.url,status.latestReadyRevisionName)'
```

### 健康检查

```bash
curl -sS https://<your-cloud-run-url>/healthz
```

### 鉴权检查

```bash
curl -i -X POST https://<your-cloud-run-url>/ingest/v1/event \
  -H 'Content-Type: application/json' \
  -d '{"source":"manual","severity":"info","summary":"no token"}'
```

期望：`401`。

### 发送检查

```bash
curl -i -X POST https://<your-cloud-run-url>/ingest/v1/event \
  -H "Authorization: Bearer ${NOTIFY_GATEWAY_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"source":"manual","severity":"critical","summary":"deploy check"}'
```

期望：`202` 且消息收到。

## 4. 路由/时区手工更新

```bash
gcloud run services update notify-gateway \
  --region us-west1 \
  --update-env-vars "^@^ENABLED_CHANNELS=tg,wecom,serverchan@ROUTE_CRITICAL=tg,wecom@ROUTE_WARNING=tg,wecom@ROUTE_INFO=tg,wecom@DEDUPE_WINDOW_MS=45000"
```

```bash
gcloud run services update notify-gateway \
  --region us-west1 \
  --update-env-vars "NOTIFY_TIMEZONE=Asia/Shanghai"
```

## 5. 固定域名（推荐）

建议 bot 统一使用：

- `NOTIFY_GATEWAY_URL=https://<your-notify-domain>`

Cloudflare CNAME 操作见：

- `docs/cloudflare-cname.md`

## 6. 回滚

```bash
gcloud run revisions list --region us-west1 --service notify-gateway
```

```bash
gcloud run services update-traffic notify-gateway \
  --region us-west1 \
  --to-revisions <old-revision>=100
```
