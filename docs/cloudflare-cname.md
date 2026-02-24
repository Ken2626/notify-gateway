# Cloudflare CNAME 到 Cloud Run（自定义域名）

本仓库是公共仓库，示例统一使用占位符：`<your-notify-domain>`。

目标：以后所有 bot 固定使用

- `NOTIFY_GATEWAY_URL=https://<your-notify-domain>`

## 推荐方式（交互脚本）

运行：

```bash
bash ./scripts/one-time-bootstrap.sh
```

脚本会交互询问：

- `Custom notify domain (optional, e.g. ng.example.com; empty to skip)`

若输入域名，脚本会可选执行：

1. `gcloud beta run domain-mappings create ...`
2. `gcloud beta run domain-mappings describe ... --format='yaml(status.resourceRecords,status.conditions)'`

你按脚本输出把 DNS 记录填到 Cloudflare 即可。

## 手工方式

## 1. 先确认 Cloud Run 服务正常

```bash
gcloud run services describe notify-gateway \
  --project cloudrun-488003 \
  --region us-west1 \
  --format='value(status.url,status.latestReadyRevisionName)'
```

记录 `status.url`（例如 `https://notify-gateway-xxxx-uw.a.run.app`）。

## 2. 在 Cloud Run 创建自定义域名映射

```bash
gcloud beta run domain-mappings create \
  --project cloudrun-488003 \
  --region us-west1 \
  --service notify-gateway \
  --domain <your-notify-domain>
```

如果提示域名所有权验证，先在 Google Search Console 完成验证后重试。

## 3. 读取 Cloud Run 要求的 DNS 记录

```bash
gcloud beta run domain-mappings describe \
  --project cloudrun-488003 \
  --region us-west1 \
  --domain <your-notify-domain> \
  --format='yaml(status.resourceRecords,status.conditions)'
```

重点看 `status.resourceRecords`，子域名场景通常会给出 `CNAME` 目标（常见是 `ghs.googlehosted.com`）。

## 4. 在 Cloudflare 配置 CNAME

在 Cloudflare DNS 中新增记录：

1. `Type`: `CNAME`
2. `Name`: 你的子域前缀（例如 `ng`）
3. `Target`: 使用第 3 步输出的 `rrdata`（不要手填猜测值）
4. `Proxy status`: 先用 `DNS only`（灰色云）直到 Cloud Run 证书 `Ready`

## 5. 等待证书与映射就绪

```bash
gcloud beta run domain-mappings describe \
  --project cloudrun-488003 \
  --region us-west1 \
  --domain <your-notify-domain> \
  --format='value(status.conditions)'
```

当映射和证书都就绪后，访问：

```bash
curl -sS https://<your-notify-domain>/healthz
```

应返回 `ok=true`。

## 6. 切换 bot 统一网关地址

```bash
NOTIFY_GATEWAY_URL=https://<your-notify-domain>
```

`NOTIFY_GATEWAY_TOKEN` 保持原值即可。

## 注意

1. 不要直接把 `<your-notify-domain>` CNAME 到 `*.run.app` 再跳过 Cloud Run 域名映射。
   Cloud Run 需要该自定义域名被正式映射，才能正确处理对应 `Host`。
2. 如果后续开启 Cloudflare 代理（橙色云），建议先确认 `DNS only` 时全链路稳定。
