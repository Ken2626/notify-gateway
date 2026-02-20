# 从 push main 到 Cloud Run 完成部署（完整操作指南）

本文按你当前仓库的真实流程编写：  
`GitHub Actions -> Artifact Registry -> Cloud Run(us-west1)`。

## 0. 一次性前置（先做）

你说“不会配置一次性前置”对应的完整手册在：

- `docs/one-time-bootstrap.md`

推荐直接运行交互脚本：

```bash
cd notify-gateway
bash ./scripts/one-time-bootstrap.sh
```

这里仅保留最小检查点，便于你确认是否可以进入 `push main`：

1. GitHub 变量已配置：`GCP_PROJECT_ID`
2. GitHub secrets 已配置：`GCP_WORKLOAD_IDENTITY_PROVIDER`、`GCP_SERVICE_ACCOUNT_EMAIL`
3. Artifact Registry 已创建：`us-west1/notify-gateway`
4. Cloud Run 服务 `notify-gateway` 已存在
5. Cloud Run 已有必需环境变量：`NOTIFY_GATEWAY_TOKEN`、`ALERTMANAGER_WEBHOOK_TOKEN`

## 1. 开发并推送到 main

在本地仓库执行：

```bash
git add .
git commit -m "your change"
git push origin main
```

这会触发 `.github/workflows/deploy-cloud-run.yml`。

## 2. GitHub Actions 自动执行内容

工作流触发后，`deploy` job 会按以下顺序执行：

1. `actions/checkout@v4` 拉取代码。
2. `google-github-actions/auth@v2` 用 OIDC 登录 GCP。
3. `google-github-actions/setup-gcloud@v2` 安装 `gcloud`。
4. `gcloud auth configure-docker us-west1-docker.pkg.dev` 配置推送认证。
5. 构建镜像并推送两个 tag：
- `${GITHUB_SHA}`
- `latest`
6. 用 `gcloud run deploy --image ...` 部署到 Cloud Run（`us-west1`）。
7. 用 `gcloud run services update` 写入路由配置：
- `ENABLED_CHANNELS=tg,wecom,serverchan`
- `ROUTE_CRITICAL=tg,wecom`
- `ROUTE_WARNING=wecom`
- `ROUTE_INFO=tg`
- `DEDUPE_WINDOW_MS=45000`

## 3. 在 GitHub 页面确认流水线成功

路径：`GitHub -> Actions -> Build And Deploy Cloud Run`。

需要确认：
1. 本次 `push` 对应 workflow run 状态为绿色 `Success`。
2. `Build and push image` 步骤成功。
3. `Deploy to Cloud Run (image)` 步骤成功。
4. `Update route config env vars` 步骤成功。

若任一步骤失败，部署未完成。

## 4. 在 Cloud Run 确认新版本已上线

### 4.1 查看服务状态

```bash
gcloud run services describe notify-gateway \
  --region us-west1 \
  --format='value(status.url,status.latestReadyRevisionName)'
```

确认有 `latestReadyRevisionName`，并记录服务 URL。

### 4.2 验证 revision 是否更新

```bash
gcloud run revisions list \
  --region us-west1 \
  --service notify-gateway \
  --sort-by='~createTime' \
  --limit=3 \
  --format='table(name,createTime,status.conditions[0].status)'
```

最近 revision 应为刚刚部署时间。

### 4.3 健康检查

```bash
curl -sS https://<your-cloud-run-url>/healthz
```

期望返回 `ok`。

### 4.4 鉴权检查（必须）

```bash
curl -i -X POST https://<your-cloud-run-url>/ingest/v1/event \
  -H 'Content-Type: application/json' \
  -d '{"source":"manual","severity":"info","summary":"no token"}'
```

期望 `401`。

### 4.5 正常上报检查

```bash
curl -i -X POST https://<your-cloud-run-url>/ingest/v1/event \
  -H "Authorization: Bearer ${NOTIFY_GATEWAY_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"source":"manual","severity":"critical","summary":"deploy check"}'
```

期望 `2xx`，并按路由分发（默认 `critical -> tg,wecom`）。

## 5. 路由策略变更（可选）

如果要修改路由，直接更新 Cloud Run 环境变量并重新触发一次部署，或立即生效：

```bash
gcloud run services update notify-gateway \
  --region us-west1 \
  --update-env-vars "^@^ENABLED_CHANNELS=tg,wecom,serverchan@ROUTE_CRITICAL=tg,wecom@ROUTE_WARNING=wecom@ROUTE_INFO=tg@DEDUPE_WINDOW_MS=45000"
```

说明：当前 workflow 每次部署都会执行一次上述路由写入，所以若你手工改了路由但 workflow 里没改，下一次 `push main` 会被 workflow 值覆盖。

## 6. 常见失败与定位

1. `Authenticate to Google Cloud` 失败
- 检查 `GCP_WORKLOAD_IDENTITY_PROVIDER` 与 `GCP_SERVICE_ACCOUNT_EMAIL` 是否正确。
- 检查 `id-token: write` 权限是否存在（当前 workflow 已配置）。

2. `docker push` 失败
- 检查 `GCP_PROJECT_ID` 是否存在。
- 检查 Artifact Registry 仓库 `notify-gateway` 是否已创建在 `us-west1`。
- 检查 SA 是否有 `roles/artifactregistry.writer`。

3. `gcloud run deploy` 失败
- 检查 SA 是否有 `roles/run.admin` + `roles/iam.serviceAccountUser`。
- 检查 Cloud Run API 是否已启用。

4. 服务可访问但不发通知
- 检查 Cloud Run secrets/env 是否完整（TG/WeCom 凭据）。
- 查看 Cloud Run logs，确认渠道是否因缺失凭据被跳过。

## 7. 回滚（需要时）

查看可用 revision：

```bash
gcloud run revisions list \
  --region us-west1 \
  --service notify-gateway
```

将流量切回旧 revision（示例）：

```bash
gcloud run services update-traffic notify-gateway \
  --region us-west1 \
  --to-revisions notify-gateway-00012-abc=100
```

## 8. 完成定义（Done）

满足以下条件即可判定“部署完成”：

1. GitHub Actions 本次 run 全部绿色成功。
2. Cloud Run 出现新的 `latestReadyRevisionName`。
3. `GET /healthz` 返回 `ok`。
4. `/ingest/v1/event` 无 token 返回 `401`。
5. 携带 token 的测试事件返回 `2xx` 且渠道收到消息。
