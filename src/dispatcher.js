import crypto from "node:crypto";
import { isTruthy, normalizeSeverity, normalizeStatus, parseChannels } from "./config.js";
import { sendByChannel } from "./channels.js";

export class DedupeCache {
  constructor(windowMs, maxEntries = 10000) {
    this.windowMs = windowMs;
    this.maxEntries = maxEntries;
    this.map = new Map();
  }

  shouldDrop(key, now = Date.now()) {
    const existing = this.map.get(key);
    if (existing && now - existing < this.windowMs) {
      return true;
    }

    this.map.set(key, now);
    if (this.map.size > this.maxEntries) {
      for (const [entryKey, ts] of this.map) {
        if (now - ts >= this.windowMs) {
          this.map.delete(entryKey);
        }
      }
      if (this.map.size > this.maxEntries) {
        const oldestKey = this.map.keys().next().value;
        if (oldestKey) this.map.delete(oldestKey);
      }
    }

    return false;
  }
}

function sha256(text) {
  return crypto.createHash("sha256").update(text).digest("hex");
}

function normalizeIso(raw, fallbackIso) {
  if (!raw) return fallbackIso;
  const value = new Date(raw);
  if (Number.isNaN(value.getTime())) {
    return fallbackIso;
  }
  return value.toISOString();
}

export function buildAlertFromEvent(event, config) {
  const nowIso = new Date().toISOString();
  const status = normalizeStatus(event.status);
  const severity = normalizeSeverity(event.severity);

  const labels = {
    ...(event.labels || {}),
    source: String(event.source || config.defaultSource || "unknown"),
    severity,
    alertname: String(event.alertname || event.labels?.alertname || "GatewayEvent"),
  };

  if (event.fingerprint) {
    labels.notify_fingerprint = String(event.fingerprint);
  }

  const overrideChannels = parseChannels(event.channels);
  if (overrideChannels.length > 0) {
    labels.notify_channels = overrideChannels.join(",");
  }

  const annotations = {
    ...(event.annotations || {}),
    summary: String(event.summary || "(no summary)"),
    description: String(event.description || event.summary || ""),
  };

  const startsAt = normalizeIso(event.startsAt, nowIso);
  const alert = {
    labels,
    annotations,
    startsAt,
  };

  if (status === "resolved") {
    alert.endsAt = normalizeIso(event.endsAt, nowIso);
  }

  return alert;
}

export async function pushAlertsToAlertmanager(alerts, config) {
  const endpoint = `http://127.0.0.1:${config.alertmanagerPort}/api/v2/alerts`;
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: JSON.stringify(alerts),
  });

  if (!response.ok) {
    const bodyText = await response.text();
    throw new Error(`alertmanager rejected alerts (${response.status}): ${bodyText}`);
  }
}

function fallbackFingerprint(alert) {
  const base = JSON.stringify({
    labels: alert.labels || {},
    annotations: alert.annotations || {},
    startsAt: alert.startsAt || "",
  });
  return sha256(base);
}

function truncate(raw, maxLen) {
  const text = String(raw || "");
  if (text.length <= maxLen) return text;
  return `${text.slice(0, maxLen - 3)}...`;
}

function formatLabels(labels) {
  const ignoredKeys = new Set(["notify_channels", "notify_mute"]);
  const entries = Object.entries(labels || {}).filter(([key]) => !ignoredKeys.has(key));
  if (entries.length === 0) return "-";
  return entries.map(([k, v]) => `${k}=${v}`).join(", ");
}

export function resolveChannels(alert, config) {
  const labels = alert.labels || {};
  const annotations = alert.annotations || {};

  if (isTruthy(labels.notify_mute) || isTruthy(annotations.notify_mute)) {
    return [];
  }

  const overridden = parseChannels(labels.notify_channels || annotations.notify_channels);
  if (overridden.length > 0) {
    return overridden.filter((channel) => config.enabledChannels.includes(channel));
  }

  const severity = normalizeSeverity(labels.severity);
  return [...(config.routeBySeverity[severity] || [])];
}

function buildMessage(alert, payloadStatus) {
  const labels = alert.labels || {};
  const annotations = alert.annotations || {};

  const status = normalizeStatus(alert.status || payloadStatus);
  const severity = normalizeSeverity(labels.severity);
  const source = String(labels.source || "unknown");
  const alertname = String(labels.alertname || "GatewayEvent");
  const summary = String(annotations.summary || annotations.description || "(no summary)");
  const description = String(annotations.description || "");

  const title = `[${severity.toUpperCase()}][${status.toUpperCase()}][${source}] ${alertname}`;
  const lines = [
    `summary: ${summary}`,
    description ? `description: ${description}` : null,
    `startsAt: ${alert.startsAt || "-"}`,
    `labels: ${formatLabels(labels)}`,
  ].filter(Boolean);

  return {
    title: truncate(title, 180),
    body: truncate(lines.join("\n"), 3500),
    severity,
    status,
  };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function sendWithRetry(channel, message, config, logger) {
  const delays = config.retryScheduleMs;
  let lastError = null;

  for (let attempt = 0; attempt <= delays.length; attempt += 1) {
    try {
      const result = await sendByChannel(channel, message, config);
      if (result?.skipped) {
        logger.info({ channel, reason: result.reason }, "channel skipped");
      }
      return result;
    } catch (error) {
      lastError = error;
      const delay = delays[attempt];
      logger.warn(
        {
          channel,
          attempt: attempt + 1,
          maxAttempt: delays.length + 1,
          error: error instanceof Error ? error.message : String(error),
        },
        "send attempt failed"
      );

      if (delay) {
        await sleep(delay);
      }
    }
  }

  throw lastError || new Error("send failed without explicit error");
}

export async function dispatchAlertmanagerPayload(payload, config, dedupeCache, logger) {
  if (!payload || !Array.isArray(payload.alerts)) {
    throw new Error("invalid alertmanager payload: alerts must be an array");
  }

  const counters = {
    sent: 0,
    skipped: 0,
    failed: 0,
  };

  for (const alert of payload.alerts) {
    const channels = resolveChannels(alert, config);
    if (channels.length === 0) {
      counters.skipped += 1;
      continue;
    }

    const message = buildMessage(alert, payload.status);
    const fingerprint = String(alert.fingerprint || alert.labels?.notify_fingerprint || fallbackFingerprint(alert));

    for (const channel of channels) {
      const dedupeKey = `${fingerprint}:${message.status}:${channel}`;
      if (dedupeCache.shouldDrop(dedupeKey)) {
        counters.skipped += 1;
        logger.info({ channel, fingerprint }, "dedupe suppressed duplicate notification");
        continue;
      }

      try {
        const result = await sendWithRetry(channel, message, config, logger);
        if (result?.skipped) {
          counters.skipped += 1;
        } else {
          counters.sent += 1;
        }
      } catch (error) {
        counters.failed += 1;
        logger.error(
          {
            channel,
            fingerprint,
            error: error instanceof Error ? error.message : String(error),
          },
          "channel delivery failed after retries"
        );
      }
    }
  }

  return counters;
}
