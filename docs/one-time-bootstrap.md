# 一次性前置配置（从零开始）

这份文档解决一个目标：  
让你在完成一次性配置后，后续只要 `git push origin main` 就能自动部署到 Cloud Run。

## 推荐方式：交互式脚本

优先直接运行脚本：

```bash
cd notify-gateway
bash ./scripts/one-time-bootstrap.sh
```

脚本会交互式完成：

1. GCP API 启用
2. Artifact Registry 创建
3. Service Account 与 IAM 绑定
4. Workload Identity Pool/Provider 创建
5. GitHub Actions secrets/variable 写入（可选，依赖 `gh`）
6. Cloud Run 初始服务创建或更新（含必需 token、默认路由、通知时区）

依赖处理说明：

1. 缺少 `gcloud` 时，脚本会提示自动安装（当前支持 Debian/Ubuntu 的 `apt`，需要 `sudo` 或 root）
2. 缺少 `gh` 时，只有在你选择“自动写入 GitHub secrets/variables”才会提示安装
3. 如果 `apt` 被系统里其他半安装软件包阻塞，脚本会自动尝试 `dpkg --configure -a` 与 `apt-get -f install` 后重试
4. 脚本会交互询问 `NOTIFY_TIMEZONE`（默认 `UTC`），有 `node` 时会校验时区格式

## 手工方式（逐条命令）

## 1. 准备本地工具

必须安装并可用：

1. `gcloud`
2. `git`
3. `gh`（可选，用于命令行写入 GitHub secrets/variables）

检查版本：

```bash
gcloud --version
git --version
gh --version
```

## 2. 先设置变量（复制后改成你的值）

```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="us-west1"
export GAR_REPO="notify-gateway"
export SERVICE_NAME="notify-gateway"
export NOTIFY_TIMEZONE="UTC"

export GITHUB_OWNER="your-github-owner"
export GITHUB_REPO="notify-gateway"

export SA_ID="notify-gateway-gha"
export WIF_POOL_ID="github-pool"
export WIF_PROVIDER_ID="github-oidc"
```

读取项目号并设置 gcloud 默认项目：

```bash
gcloud auth login
gcloud config set project "${PROJECT_ID}"
gcloud config set run/region "${REGION}"
export PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
```

## 3. 启用 GCP API（一次）

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  serviceusage.googleapis.com \
  cloudresourcemanager.googleapis.com
```

## 4. 创建 Artifact Registry 仓库（一次）

```bash
gcloud artifacts repositories describe "${GAR_REPO}" \
  --location "${REGION}" >/dev/null 2>&1 || \
gcloud artifacts repositories create "${GAR_REPO}" \
  --repository-format docker \
  --location "${REGION}" \
  --description "notify-gateway images"
```

## 5. 创建 GitHub Actions 用 Service Account（一次）

```bash
gcloud iam service-accounts describe "${SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1 || \
gcloud iam service-accounts create "${SA_ID}" \
  --display-name "notify-gateway github deployer"

export SA_EMAIL="${SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
```

授予最小必要角色：

```bash
for ROLE in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member "serviceAccount:${SA_EMAIL}" \
    --role "${ROLE}"
done
```

## 6. 配置 Workload Identity Federation（OIDC，一次）

创建 Workload Identity Pool：

```bash
gcloud iam workload-identity-pools describe "${WIF_POOL_ID}" \
  --project "${PROJECT_ID}" \
  --location global >/dev/null 2>&1 || \
gcloud iam workload-identity-pools create "${WIF_POOL_ID}" \
  --project "${PROJECT_ID}" \
  --location global \
  --display-name "GitHub Actions Pool"
```

创建 OIDC Provider（限定到你的 GitHub 仓库）：

```bash
gcloud iam workload-identity-pools providers describe "${WIF_PROVIDER_ID}" \
  --project "${PROJECT_ID}" \
  --location global \
  --workload-identity-pool "${WIF_POOL_ID}" >/dev/null 2>&1 || \
gcloud iam workload-identity-pools providers create-oidc "${WIF_PROVIDER_ID}" \
  --project "${PROJECT_ID}" \
  --location global \
  --workload-identity-pool "${WIF_POOL_ID}" \
  --display-name "GitHub OIDC Provider" \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner,attribute.ref=assertion.ref" \
  --attribute-condition "assertion.repository=='${GITHUB_OWNER}/${GITHUB_REPO}'"
```

允许该仓库 impersonate 这个 Service Account：

```bash
gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --project "${PROJECT_ID}" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL_ID}/attribute.repository/${GITHUB_OWNER}/${GITHUB_REPO}"
```

读取 Provider 完整资源名（给 GitHub secret 用）：

```bash
export WIF_PROVIDER_RESOURCE="$(gcloud iam workload-identity-pools providers describe "${WIF_PROVIDER_ID}" \
  --project "${PROJECT_ID}" \
  --location global \
  --workload-identity-pool "${WIF_POOL_ID}" \
  --format='value(name)')"

echo "${WIF_PROVIDER_RESOURCE}"
echo "${SA_EMAIL}"
echo "${PROJECT_ID}"
```

## 7. 写入 GitHub Actions 变量和密钥（一次）

必需项：

1. Repository variable: `GCP_PROJECT_ID=${PROJECT_ID}`
2. Repository secret: `GCP_WORKLOAD_IDENTITY_PROVIDER=${WIF_PROVIDER_RESOURCE}`
3. Repository secret: `GCP_SERVICE_ACCOUNT_EMAIL=${SA_EMAIL}`

网页路径：  
`GitHub -> Settings -> Secrets and variables -> Actions`

如果你用 `gh` CLI，可直接执行：

```bash
gh auth login
gh variable set GCP_PROJECT_ID --repo "${GITHUB_OWNER}/${GITHUB_REPO}" --body "${PROJECT_ID}"
gh secret set GCP_WORKLOAD_IDENTITY_PROVIDER --repo "${GITHUB_OWNER}/${GITHUB_REPO}" --body "${WIF_PROVIDER_RESOURCE}"
gh secret set GCP_SERVICE_ACCOUNT_EMAIL --repo "${GITHUB_OWNER}/${GITHUB_REPO}" --body "${SA_EMAIL}"
```

## 8. 初始化 Cloud Run 服务（一次，关键）

你的网关代码启动时强制要求：

1. `NOTIFY_GATEWAY_TOKEN`
2. `ALERTMANAGER_WEBHOOK_TOKEN`

当前 workflow 不在 `deploy` 步骤里写这两个变量，所以必须先做一次初始化，让后续自动部署沿用已有环境变量。

先生成 token：

```bash
export NOTIFY_GATEWAY_TOKEN="$(openssl rand -hex 32)"
export ALERTMANAGER_WEBHOOK_TOKEN="$(openssl rand -hex 32)"
```

用一个临时镜像创建 Cloud Run 服务（后续会被 GitHub Actions 镜像替换）：

```bash
gcloud run deploy "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --image "us-docker.pkg.dev/cloudrun/container/hello" \
  --platform managed \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 1 \
  --cpu 1 \
  --memory 512Mi \
  --concurrency 20 \
  --timeout 30 \
  --set-env-vars "^@^NOTIFY_GATEWAY_TOKEN=${NOTIFY_GATEWAY_TOKEN}@ALERTMANAGER_WEBHOOK_TOKEN=${ALERTMANAGER_WEBHOOK_TOKEN}@ENABLED_CHANNELS=tg,wecom,serverchan@ROUTE_CRITICAL=tg,wecom@ROUTE_WARNING=wecom@ROUTE_INFO=tg@DEDUPE_WINDOW_MS=45000@NOTIFY_TIMEZONE=${NOTIFY_TIMEZONE}"
```

可选：补上渠道密钥（也可以在 Cloud Run 控制台里填）：

```bash
gcloud run services update "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --update-env-vars "^@^TG_BOT_TOKEN=your_tg_bot_token@TG_CHAT_ID=your_tg_chat_id@WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your_key@SERVERCHAN_SENDKEY=your_serverchan_key"
```

## 9. 一次性配置完成的判定

下面 5 条都满足，就可以开始常规 `push main` 自动部署：

1. GitHub `Variables` 里有 `GCP_PROJECT_ID`
2. GitHub `Secrets` 里有 `GCP_WORKLOAD_IDENTITY_PROVIDER` 和 `GCP_SERVICE_ACCOUNT_EMAIL`
3. GCP 有 `us-west1` 的 Artifact Registry 仓库 `notify-gateway`
4. Cloud Run 服务 `notify-gateway` 已存在
5. Cloud Run 服务里已有 `NOTIFY_GATEWAY_TOKEN` 和 `ALERTMANAGER_WEBHOOK_TOKEN`
6. Cloud Run 服务里已有 `NOTIFY_TIMEZONE`（或默认按 `UTC`）

## 10. 首次验证自动部署

在代码仓库执行：

```bash
git add .
git commit -m "test ci deploy"
git push origin main
```

然后看：

1. `GitHub -> Actions -> Build And Deploy Cloud Run` 为 `Success`
2. `gcloud run services describe notify-gateway --region us-west1 --format='value(status.latestReadyRevisionName)'` 有新 revision
