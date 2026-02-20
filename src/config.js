const VALID_CHANNELS = new Set(["tg", "wecom", "serverchan"]);
const VALID_SEVERITIES = new Set(["critical", "warning", "info"]);

function parseCsvList(raw, fallback = []) {
  if (!raw || typeof raw !== "string") return [...fallback];
  return raw
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

function parsePositiveInt(raw, fallback) {
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return Math.floor(parsed);
}

function uniq(items) {
  return [...new Set(items)];
}

function normalizeChannels(items) {
  return uniq(items.filter((item) => VALID_CHANNELS.has(item)));
}

function parseRetrySchedule(raw) {
  const defaults = [1000, 2000, 4000];
  const parsed = parseCsvList(raw)
    .map((v) => Number(v))
    .filter((v) => Number.isFinite(v) && v > 0)
    .map((v) => Math.floor(v));

  if (parsed.length === 0) return defaults;
  return parsed;
}

export function loadConfig() {
  const enabledChannels = normalizeChannels(
    parseCsvList(process.env.ENABLED_CHANNELS, ["tg", "wecom", "serverchan"])
  );

  const routeCritical = normalizeChannels(
    parseCsvList(process.env.ROUTE_CRITICAL, ["tg", "wecom"])
  ).filter((channel) => enabledChannels.includes(channel));

  const routeWarning = normalizeChannels(
    parseCsvList(process.env.ROUTE_WARNING, ["wecom"])
  ).filter((channel) => enabledChannels.includes(channel));

  const routeInfo = normalizeChannels(
    parseCsvList(process.env.ROUTE_INFO, ["tg"])
  ).filter((channel) => enabledChannels.includes(channel));

  const routeBySeverity = {
    critical: routeCritical,
    warning: routeWarning,
    info: routeInfo,
  };

  const config = {
    port: parsePositiveInt(process.env.PORT, 8080),
    alertmanagerPort: parsePositiveInt(process.env.ALERTMANAGER_PORT, 9093),
    notifyGatewayToken: process.env.NOTIFY_GATEWAY_TOKEN || "",
    alertmanagerWebhookToken: process.env.ALERTMANAGER_WEBHOOK_TOKEN || "",
    dedupeWindowMs: parsePositiveInt(process.env.DEDUPE_WINDOW_MS, 45000),
    retryScheduleMs: parseRetrySchedule(process.env.RETRY_SCHEDULE_MS),
    enabledChannels,
    routeBySeverity,
    defaultSource: (process.env.DEFAULT_SOURCE || "notify-gateway").trim(),
    channelCreds: {
      tgBotToken: process.env.TG_BOT_TOKEN || "",
      tgChatId: process.env.TG_CHAT_ID || "",
      wecomWebhookUrl: process.env.WECOM_WEBHOOK_URL || "",
      serverchanSendKey: process.env.SERVERCHAN_SENDKEY || "",
    },
  };

  if (!config.notifyGatewayToken) {
    throw new Error("NOTIFY_GATEWAY_TOKEN is required");
  }

  if (!config.alertmanagerWebhookToken) {
    throw new Error("ALERTMANAGER_WEBHOOK_TOKEN is required");
  }

  for (const severity of Object.keys(config.routeBySeverity)) {
    if (!VALID_SEVERITIES.has(severity)) {
      throw new Error(`invalid severity in route map: ${severity}`);
    }
  }

  return config;
}

export function parseChannels(raw) {
  if (Array.isArray(raw)) {
    return normalizeChannels(
      raw
        .map((item) => (typeof item === "string" ? item.toLowerCase().trim() : ""))
        .filter(Boolean)
    );
  }

  if (typeof raw === "string") {
    return normalizeChannels(parseCsvList(raw));
  }

  return [];
}

export function isTruthy(raw) {
  if (typeof raw === "boolean") return raw;
  if (typeof raw !== "string") return false;
  const normalized = raw.trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

export function normalizeSeverity(raw) {
  const normalized = String(raw || "info").toLowerCase().trim();
  if (normalized === "critical" || normalized === "warning" || normalized === "info") {
    return normalized;
  }
  return "info";
}

export function normalizeStatus(raw) {
  const normalized = String(raw || "firing").toLowerCase().trim();
  if (normalized === "resolved") return "resolved";
  return "firing";
}
