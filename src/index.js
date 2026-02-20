import Fastify from "fastify";
import { loadConfig } from "./config.js";
import {
  DedupeCache,
  buildAlertFromEvent,
  dispatchAlertmanagerPayload,
  pushAlertsToAlertmanager,
} from "./dispatcher.js";

function extractBearerToken(headerValue) {
  if (!headerValue || typeof headerValue !== "string") return "";
  const [scheme, token] = headerValue.split(" ");
  if (!scheme || !token) return "";
  if (scheme.toLowerCase() !== "bearer") return "";
  return token.trim();
}

function validateIngestEvent(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return "body must be an object";
  }

  if (!raw.source || typeof raw.source !== "string") {
    return "source is required and must be a string";
  }

  if (!raw.summary || typeof raw.summary !== "string") {
    return "summary is required and must be a string";
  }

  const severity = String(raw.severity || "").toLowerCase().trim();
  if (!["critical", "warning", "info"].includes(severity)) {
    return "severity must be one of critical|warning|info";
  }

  if (raw.status !== undefined) {
    const status = String(raw.status).toLowerCase().trim();
    if (!["firing", "resolved"].includes(status)) {
      return "status must be firing|resolved";
    }
    if (status === "resolved" && !raw.endsAt) {
      return "endsAt is required when status=resolved";
    }
  }

  if (raw.labels !== undefined && (typeof raw.labels !== "object" || Array.isArray(raw.labels))) {
    return "labels must be an object when provided";
  }

  if (raw.channels !== undefined && !Array.isArray(raw.channels) && typeof raw.channels !== "string") {
    return "channels must be string[] or comma-separated string when provided";
  }

  if (raw.startsAt !== undefined && Number.isNaN(new Date(raw.startsAt).getTime())) {
    return "startsAt must be a valid ISO datetime when provided";
  }

  if (raw.endsAt !== undefined && Number.isNaN(new Date(raw.endsAt).getTime())) {
    return "endsAt must be a valid ISO datetime when provided";
  }

  return null;
}

function ensureAlertArray(body) {
  if (Array.isArray(body)) return body;
  if (body && Array.isArray(body.alerts)) return body.alerts;
  return null;
}

const config = loadConfig();
const dedupeCache = new DedupeCache(config.dedupeWindowMs);

const app = Fastify({
  logger: {
    level: process.env.LOG_LEVEL || "info",
  },
});

app.get("/healthz", async (request, reply) => {
  const endpoint = `http://127.0.0.1:${config.alertmanagerPort}/-/ready`;

  try {
    const response = await fetch(endpoint);
    if (!response.ok) {
      reply.code(503);
      return {
        ok: false,
        service: "notify-gateway",
        alertmanager: "not-ready",
      };
    }

    return {
      ok: true,
      service: "notify-gateway",
      alertmanager: "ready",
    };
  } catch (error) {
    request.log.error({ error: error instanceof Error ? error.message : String(error) }, "health check failed");
    reply.code(503);
    return {
      ok: false,
      service: "notify-gateway",
      alertmanager: "unreachable",
    };
  }
});

app.post("/ingest/v1/event", async (request, reply) => {
  const token = extractBearerToken(request.headers.authorization);
  if (token !== config.notifyGatewayToken) {
    reply.code(401);
    return { error: "unauthorized" };
  }

  const validationError = validateIngestEvent(request.body);
  if (validationError) {
    reply.code(400);
    return { error: validationError };
  }

  const alert = buildAlertFromEvent(request.body, config);
  await pushAlertsToAlertmanager([alert], config);

  reply.code(202);
  return {
    accepted: 1,
    forwardedTo: "alertmanager",
  };
});

app.post("/ingest/v1/alerts", async (request, reply) => {
  const token = extractBearerToken(request.headers.authorization);
  if (token !== config.notifyGatewayToken) {
    reply.code(401);
    return { error: "unauthorized" };
  }

  const alerts = ensureAlertArray(request.body);
  if (!alerts) {
    reply.code(400);
    return { error: "body must be an alerts array or an object with alerts[]" };
  }

  await pushAlertsToAlertmanager(alerts, config);

  reply.code(202);
  return {
    accepted: alerts.length,
    forwardedTo: "alertmanager",
  };
});

app.post("/dispatch/v1/alertmanager", async (request, reply) => {
  const token = extractBearerToken(request.headers.authorization);
  if (token !== config.alertmanagerWebhookToken) {
    reply.code(401);
    return { error: "unauthorized" };
  }

  const counters = await dispatchAlertmanagerPayload(request.body, config, dedupeCache, request.log);

  return {
    ok: true,
    ...counters,
  };
});

app.setErrorHandler((error, request, reply) => {
  request.log.error({ error: error.message, stack: error.stack }, "request failed");
  const statusCode = error.statusCode && error.statusCode >= 400 ? error.statusCode : 500;
  reply.code(statusCode).send({
    error: error.message,
  });
});

app
  .listen({
    port: config.port,
    host: "0.0.0.0",
  })
  .then(() => {
    app.log.info(
      {
        port: config.port,
        alertmanagerPort: config.alertmanagerPort,
        routeBySeverity: config.routeBySeverity,
      },
      "notify-gateway started"
    );
  })
  .catch((error) => {
    app.log.error({ error: error.message, stack: error.stack }, "failed to start notify-gateway");
    process.exit(1);
  });
