from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import apprise
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse

VALID_CHANNELS = {"tg", "wecom", "serverchan"}
VALID_SEVERITIES = {"critical", "warning", "info"}


class ConfigError(RuntimeError):
    pass


def parse_csv_list(raw: Any, fallback: list[str] | None = None) -> list[str]:
    if not isinstance(raw, str):
        return list(fallback or [])
    return [item.strip().lower() for item in raw.split(",") if item and item.strip()]


def uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def normalize_channels(items: list[str]) -> list[str]:
    return uniq([item for item in items if item in VALID_CHANNELS])


def parse_positive_int(raw: Any, fallback: int) -> int:
    try:
        value = int(str(raw).strip())
    except Exception:
        return fallback
    if value <= 0:
        return fallback
    return value


def parse_retry_schedule(raw: Any) -> list[int]:
    default = [1000, 2000, 4000]
    parsed: list[int] = []
    for item in parse_csv_list(raw):
        try:
            value = int(item)
        except Exception:
            continue
        if value > 0:
            parsed.append(value)
    return parsed or default


def parse_timezone(raw: Any) -> str:
    value = str(raw or "UTC").strip() or "UTC"
    try:
        ZoneInfo(value)
    except Exception as exc:
        raise ConfigError(f"NOTIFY_TIMEZONE is invalid: {value}") from exc
    return value


def parse_json_obj(raw: Any, field: str) -> dict[str, Any]:
    if not raw:
        return {}
    if not isinstance(raw, str):
        raise ConfigError(f"{field} must be a JSON object string")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{field} is invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"{field} must decode to an object")
    return value


def normalize_tags(raw: Any) -> list[str]:
    values: list[str] = []
    if raw is None:
        return []
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = [str(v) for v in raw]
    else:
        values = [str(raw)]

    merged: list[str] = []
    for value in values:
        for token in value.split(","):
            normalized = token.strip()
            if normalized:
                merged.append(normalized)
    return uniq(merged)


def parse_source_route(raw: Any) -> dict[str, dict[str, list[str]]]:
    data = parse_json_obj(raw, "SOURCE_ROUTE_JSON") if raw else {}
    route: dict[str, dict[str, list[str]]] = {}

    for source, per_severity in data.items():
        if not isinstance(per_severity, dict):
            continue
        source_key = str(source).strip().lower()
        if not source_key:
            continue

        mapped: dict[str, list[str]] = {}
        for severity in VALID_SEVERITIES:
            tags = normalize_tags(per_severity.get(severity))
            if tags:
                mapped[severity] = tags

        if mapped:
            route[source_key] = mapped

    return route


def parse_channel_tag_map(raw: Any) -> dict[str, list[str]]:
    default = {
        "tg": ["tg"],
        "wecom": ["wecom"],
        "serverchan": ["serverchan"],
    }
    if not raw:
        return default

    data = parse_json_obj(raw, "CHANNEL_TAG_MAP_JSON")
    out: dict[str, list[str]] = {}

    for channel in VALID_CHANNELS:
        tags = normalize_tags(data.get(channel))
        out[channel] = tags or default[channel]

    return out


def parse_apprise_urls(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []

    if not isinstance(raw, str):
        raise ConfigError("APPRISE_URLS_JSON must be a JSON string")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"APPRISE_URLS_JSON is invalid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise ConfigError("APPRISE_URLS_JSON must decode to an array")

    results: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or "").strip()
        if not url:
            continue
        tags = normalize_tags(entry.get("tags"))
        results.append({"url": url, "tags": tags})

    return results


def parse_datetime(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(text)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def normalize_iso(raw: Any, fallback_iso: str) -> str:
    parsed = parse_datetime(raw)
    if parsed is None:
        return fallback_iso
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_status(raw: Any) -> str:
    normalized = str(raw or "firing").strip().lower()
    if normalized == "resolved":
        return "resolved"
    return "firing"


def normalize_severity(raw: Any) -> str:
    normalized = str(raw or "info").strip().lower()
    if normalized in VALID_SEVERITIES:
        return normalized
    return "info"


def is_truthy(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if not isinstance(raw, str):
        return False
    value = raw.strip().lower()
    return value in {"1", "true", "yes", "on"}


def parse_channels(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return normalize_channels([
            str(item).strip().lower() for item in raw if isinstance(item, (str, int, float))
        ])
    if isinstance(raw, str):
        return normalize_channels(parse_csv_list(raw))
    return []


def extract_bearer_token(header_value: Any) -> str:
    if not isinstance(header_value, str):
        return ""
    parts = header_value.split(" ", 1)
    if len(parts) != 2:
        return ""
    scheme, token = parts[0].strip().lower(), parts[1].strip()
    if scheme != "bearer" or not token:
        return ""
    return token


@dataclass(frozen=True)
class AppConfig:
    port: int
    notify_timezone: str
    notify_gateway_token: str
    alertmanager_webhook_token: str
    dedupe_window_ms: int
    retry_schedule_ms: list[int]
    enabled_channels: list[str]
    route_by_severity: dict[str, list[str]]
    default_source: str
    channel_tag_map: dict[str, list[str]]
    source_route_by_severity: dict[str, dict[str, list[str]]]
    apprise_config_yaml_b64: str
    apprise_urls: list[dict[str, Any]]
    tg_bot_token: str
    tg_chat_id: str
    wecom_webhook_url: str
    serverchan_sendkey: str


class DedupeCache:
    def __init__(self, window_ms: int, max_entries: int = 10000) -> None:
        self.window_ms = window_ms
        self.max_entries = max_entries
        self._items: OrderedDict[str, int] = OrderedDict()
        self._lock = threading.Lock()

    def should_drop(self, key: str, now_ms: int | None = None) -> bool:
        now = now_ms if now_ms is not None else int(time.time() * 1000)

        with self._lock:
            existing = self._items.get(key)
            if existing is not None and now - existing < self.window_ms:
                return True

            self._items[key] = now
            self._items.move_to_end(key)

            if len(self._items) > self.max_entries:
                expired_keys = [k for k, ts in self._items.items() if now - ts >= self.window_ms]
                for expired in expired_keys:
                    self._items.pop(expired, None)

                while len(self._items) > self.max_entries:
                    self._items.popitem(last=False)

        return False


class AppriseNotifier:
    def __init__(self, config: AppConfig) -> None:
        self.logger = logging.getLogger("notify-gateway.apprise")
        self.apobj = apprise.Apprise()
        self.has_targets = False

        self._load_from_b64_config(config.apprise_config_yaml_b64)
        self._load_from_urls_json(config.apprise_urls)
        self._load_from_legacy_credentials(config)

    def _load_from_b64_config(self, encoded: str) -> None:
        raw = (encoded or "").strip()
        if not raw:
            return

        try:
            decoded = base64.b64decode(raw).decode("utf-8")
        except Exception as exc:
            raise ConfigError("APPRISE_CONFIG_YAML_B64 is not valid base64 utf-8") from exc

        config = apprise.AppriseConfig()
        if not config.add_config(decoded, format="yaml"):
            raise ConfigError("APPRISE_CONFIG_YAML_B64 failed to load as Apprise YAML")

        self.apobj.add(config)
        self.has_targets = True

    def _load_from_urls_json(self, urls: list[dict[str, Any]]) -> None:
        for item in urls:
            url = str(item.get("url") or "").strip()
            tags = normalize_tags(item.get("tags"))
            if not url:
                continue
            if self.apobj.add(url, tag=tags):
                self.has_targets = True
            else:
                self.logger.warning("failed to load apprise url from APPRISE_URLS_JSON")

    def _load_from_legacy_credentials(self, config: AppConfig) -> None:
        if config.tg_bot_token and config.tg_chat_id:
            tg_url = f"tgram://{config.tg_bot_token}/{config.tg_chat_id}"
            if self.apobj.add(tg_url, tag=config.channel_tag_map.get("tg", ["tg"])):
                self.has_targets = True
            else:
                self.logger.warning("failed to load telegram target from TG_BOT_TOKEN/TG_CHAT_ID")

        if config.wecom_webhook_url:
            if self.apobj.add(
                config.wecom_webhook_url,
                tag=config.channel_tag_map.get("wecom", ["wecom"]),
            ):
                self.has_targets = True
            else:
                self.logger.warning("failed to load wecom target from WECOM_WEBHOOK_URL")

        if config.serverchan_sendkey:
            schan_url = f"schan://{config.serverchan_sendkey}"
            if self.apobj.add(schan_url, tag=config.channel_tag_map.get("serverchan", ["serverchan"])):
                self.has_targets = True
            else:
                self.logger.warning("failed to load serverchan target from SERVERCHAN_SENDKEY")

    def notify_tag(self, tag: str, title: str, body: str, severity: str) -> str:
        notify_type = {
            "critical": apprise.NotifyType.FAILURE,
            "warning": apprise.NotifyType.WARNING,
            "info": apprise.NotifyType.INFO,
        }.get(severity, apprise.NotifyType.INFO)

        result = self.apobj.notify(
            title=title,
            body=body,
            notify_type=notify_type,
            body_format=apprise.NotifyFormat.TEXT,
            tag=tag,
        )

        if result is None:
            return "skipped"
        if result is False:
            raise RuntimeError(f"apprise notify failed for tag={tag}")
        return "sent"


def load_config_from_env(env: dict[str, str]) -> AppConfig:
    enabled_channels = normalize_channels(parse_csv_list(env.get("ENABLED_CHANNELS"), ["tg", "wecom", "serverchan"]))

    route_critical = [
        channel
        for channel in normalize_channels(parse_csv_list(env.get("ROUTE_CRITICAL"), ["tg", "wecom"]))
        if channel in enabled_channels
    ]
    route_warning = [
        channel
        for channel in normalize_channels(parse_csv_list(env.get("ROUTE_WARNING"), ["tg", "wecom"]))
        if channel in enabled_channels
    ]
    route_info = [
        channel
        for channel in normalize_channels(parse_csv_list(env.get("ROUTE_INFO"), ["tg", "wecom"]))
        if channel in enabled_channels
    ]

    config = AppConfig(
        port=parse_positive_int(env.get("PORT"), 8080),
        notify_timezone=parse_timezone(env.get("NOTIFY_TIMEZONE")),
        notify_gateway_token=(env.get("NOTIFY_GATEWAY_TOKEN") or "").strip(),
        alertmanager_webhook_token=(env.get("ALERTMANAGER_WEBHOOK_TOKEN") or "").strip(),
        dedupe_window_ms=parse_positive_int(env.get("DEDUPE_WINDOW_MS"), 45000),
        retry_schedule_ms=parse_retry_schedule(env.get("RETRY_SCHEDULE_MS")),
        enabled_channels=enabled_channels,
        route_by_severity={
            "critical": route_critical,
            "warning": route_warning,
            "info": route_info,
        },
        default_source=(env.get("DEFAULT_SOURCE") or "notify-gateway").strip() or "notify-gateway",
        channel_tag_map=parse_channel_tag_map(env.get("CHANNEL_TAG_MAP_JSON")),
        source_route_by_severity=parse_source_route(env.get("SOURCE_ROUTE_JSON")),
        apprise_config_yaml_b64=(env.get("APPRISE_CONFIG_YAML_B64") or "").strip(),
        apprise_urls=parse_apprise_urls(env.get("APPRISE_URLS_JSON")),
        tg_bot_token=(env.get("TG_BOT_TOKEN") or "").strip(),
        tg_chat_id=(env.get("TG_CHAT_ID") or "").strip(),
        wecom_webhook_url=(env.get("WECOM_WEBHOOK_URL") or "").strip(),
        serverchan_sendkey=(env.get("SERVERCHAN_SENDKEY") or "").strip(),
    )

    if not config.notify_gateway_token:
        raise ConfigError("NOTIFY_GATEWAY_TOKEN is required")

    if not config.alertmanager_webhook_token:
        raise ConfigError("ALERTMANAGER_WEBHOOK_TOKEN is required")

    return config


def fallback_fingerprint(alert: dict[str, Any]) -> str:
    base = json.dumps(
        {
            "labels": alert.get("labels") or {},
            "annotations": alert.get("annotations") or {},
            "startsAt": alert.get("startsAt") or "",
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def truncate(raw: Any, max_len: int) -> str:
    text = str(raw or "")
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3]}..."


def format_labels(labels: dict[str, Any]) -> str:
    ignored_keys = {"notify_channels", "notify_mute"}
    entries = [f"{k}={v}" for k, v in labels.items() if k not in ignored_keys]
    if not entries:
        return "-"
    return ", ".join(entries)


def format_timestamp_for_notify(raw: Any, tz_name: str) -> str:
    if raw is None or raw == "":
        return "-"

    parsed = parse_datetime(raw)
    if parsed is None:
        return str(raw)

    try:
        tz = ZoneInfo(tz_name)
        localized = parsed.astimezone(tz)
        return f"{localized:%Y-%m-%d %H:%M:%S} ({tz_name})"
    except Exception:
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def map_channels_to_tags(channels: list[str], config: AppConfig) -> list[str]:
    tags: list[str] = []
    for channel in channels:
        tags.extend(config.channel_tag_map.get(channel, [channel]))
    return uniq(tags)


def resolve_target_tags(alert: dict[str, Any], config: AppConfig) -> list[str]:
    labels = alert.get("labels") if isinstance(alert.get("labels"), dict) else {}
    annotations = alert.get("annotations") if isinstance(alert.get("annotations"), dict) else {}

    if is_truthy(labels.get("notify_mute")) or is_truthy(annotations.get("notify_mute")):
        return []

    overridden = parse_channels(labels.get("notify_channels") or annotations.get("notify_channels"))
    if overridden:
        return map_channels_to_tags(overridden, config)

    source = str(labels.get("source") or config.default_source).strip().lower()
    severity = normalize_severity(labels.get("severity"))

    source_route = config.source_route_by_severity.get(source, {})
    if severity in source_route and source_route[severity]:
        return uniq(source_route[severity])

    channels = config.route_by_severity.get(severity, [])
    return map_channels_to_tags(channels, config)


def build_alert_from_event(event: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    status = normalize_status(event.get("status"))
    severity = normalize_severity(event.get("severity"))

    incoming_labels = event.get("labels") if isinstance(event.get("labels"), dict) else {}
    labels = {
        **incoming_labels,
        "source": str(event.get("source") or config.default_source or "unknown"),
        "severity": severity,
        "alertname": str(event.get("alertname") or incoming_labels.get("alertname") or "GatewayEvent"),
    }

    if event.get("fingerprint"):
        labels["notify_fingerprint"] = str(event.get("fingerprint"))

    override_channels = parse_channels(event.get("channels"))
    if override_channels:
        labels["notify_channels"] = ",".join(override_channels)

    incoming_annotations = event.get("annotations") if isinstance(event.get("annotations"), dict) else {}
    annotations = {
        **incoming_annotations,
        "summary": str(event.get("summary") or "(no summary)"),
        "description": str(event.get("description") or event.get("summary") or ""),
    }

    alert: dict[str, Any] = {
        "labels": labels,
        "annotations": annotations,
        "startsAt": normalize_iso(event.get("startsAt"), now_iso),
    }

    if status == "resolved":
        alert["endsAt"] = normalize_iso(event.get("endsAt"), now_iso)

    return alert


def build_message(alert: dict[str, Any], payload_status: Any, config: AppConfig) -> dict[str, str]:
    labels = alert.get("labels") if isinstance(alert.get("labels"), dict) else {}
    annotations = alert.get("annotations") if isinstance(alert.get("annotations"), dict) else {}

    status = normalize_status(alert.get("status") or payload_status)
    severity = normalize_severity(labels.get("severity"))
    source = str(labels.get("source") or "unknown")
    alertname = str(labels.get("alertname") or "GatewayEvent")
    summary = str(annotations.get("summary") or annotations.get("description") or "(no summary)")
    description = str(annotations.get("description") or "")

    title = f"[{severity.upper()}][{status.upper()}][{source}] {alertname}"

    lines = [f"summary: {summary}"]
    if description:
        lines.append(f"description: {description}")
    lines.append(f"startsAt: {format_timestamp_for_notify(alert.get('startsAt'), config.notify_timezone)}")
    if alert.get("endsAt"):
        lines.append(f"endsAt: {format_timestamp_for_notify(alert.get('endsAt'), config.notify_timezone)}")
    lines.append(f"labels: {format_labels(labels)}")

    return {
        "title": truncate(title, 180),
        "body": truncate("\n".join(lines), 3500),
        "severity": severity,
        "status": status,
    }


async def send_with_retry(
    tag: str,
    message: dict[str, str],
    notifier: AppriseNotifier,
    retry_schedule_ms: list[int],
    logger: logging.Logger,
) -> str:
    last_error: Exception | None = None

    for attempt in range(len(retry_schedule_ms) + 1):
        try:
            result = await asyncio.to_thread(
                notifier.notify_tag,
                tag,
                message["title"],
                message["body"],
                message["severity"],
            )
            if result == "skipped":
                logger.info("channel skipped", extra={"tag": tag})
            return result
        except Exception as exc:  # pragma: no cover - exercised in integration
            last_error = exc
            logger.warning(
                "send attempt failed",
                extra={
                    "tag": tag,
                    "attempt": attempt + 1,
                    "maxAttempt": len(retry_schedule_ms) + 1,
                    "error": str(exc),
                },
            )
            if attempt < len(retry_schedule_ms):
                await asyncio.sleep(retry_schedule_ms[attempt] / 1000)

    raise RuntimeError(str(last_error or "send failed without explicit error"))


async def dispatch_payload(
    payload: dict[str, Any],
    config: AppConfig,
    dedupe_cache: DedupeCache,
    notifier: AppriseNotifier,
    logger: logging.Logger,
) -> dict[str, int]:
    alerts = payload.get("alerts")
    if not isinstance(alerts, list):
        raise ValueError("invalid alertmanager payload: alerts must be an array")

    counters = {"sent": 0, "skipped": 0, "failed": 0}
    payload_status = payload.get("status")

    for alert in alerts:
        if not isinstance(alert, dict):
            counters["failed"] += 1
            continue

        tags = resolve_target_tags(alert, config)
        if not tags:
            counters["skipped"] += 1
            continue

        message = build_message(alert, payload_status, config)
        fingerprint = str(
            alert.get("fingerprint")
            or (alert.get("labels") or {}).get("notify_fingerprint")
            or fallback_fingerprint(alert)
        )

        for tag in tags:
            dedupe_key = f"{fingerprint}:{message['status']}:{tag}"
            if dedupe_cache.should_drop(dedupe_key):
                counters["skipped"] += 1
                logger.info("dedupe suppressed duplicate notification", extra={"tag": tag, "fingerprint": fingerprint})
                continue

            try:
                result = await send_with_retry(tag, message, notifier, config.retry_schedule_ms, logger)
                if result == "sent":
                    counters["sent"] += 1
                else:
                    counters["skipped"] += 1
            except Exception as exc:  # pragma: no cover - exercised in integration
                counters["failed"] += 1
                logger.error(
                    "channel delivery failed after retries",
                    extra={"tag": tag, "fingerprint": fingerprint, "error": str(exc)},
                )

    return counters


def ensure_alert_array(body: Any) -> list[dict[str, Any]] | None:
    if isinstance(body, list):
        return body
    if isinstance(body, dict) and isinstance(body.get("alerts"), list):
        return body.get("alerts")
    return None


def validate_ingest_event(raw: Any) -> str | None:
    if not isinstance(raw, dict):
        return "body must be an object"

    if not raw.get("source") or not isinstance(raw.get("source"), str):
        return "source is required and must be a string"

    if not raw.get("summary") or not isinstance(raw.get("summary"), str):
        return "summary is required and must be a string"

    severity = str(raw.get("severity") or "").strip().lower()
    if severity not in VALID_SEVERITIES:
        return "severity must be one of critical|warning|info"

    if raw.get("status") is not None:
        status = str(raw.get("status")).strip().lower()
        if status not in {"firing", "resolved"}:
            return "status must be firing|resolved"
        if status == "resolved" and not raw.get("endsAt"):
            return "endsAt is required when status=resolved"

    if raw.get("labels") is not None and not isinstance(raw.get("labels"), dict):
        return "labels must be an object when provided"

    channels = raw.get("channels")
    if channels is not None and not isinstance(channels, (list, str)):
        return "channels must be string[] or comma-separated string when provided"

    if raw.get("startsAt") is not None and parse_datetime(raw.get("startsAt")) is None:
        return "startsAt must be a valid ISO datetime when provided"

    if raw.get("endsAt") is not None and parse_datetime(raw.get("endsAt")) is None:
        return "endsAt must be a valid ISO datetime when provided"

    return None


class AppState:
    def __init__(self, config: AppConfig, notifier: AppriseNotifier) -> None:
        self.config = config
        self.notifier = notifier
        self.dedupe = DedupeCache(config.dedupe_window_ms)


def create_app() -> FastAPI:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("notify-gateway")

    config = load_config_from_env(os.environ)
    notifier = AppriseNotifier(config)
    state = AppState(config, notifier)

    app = FastAPI(title="notify-gateway", version="2.0.0")
    app.state.gateway = state

    async def dispatch_payload_safe(payload: dict[str, Any]) -> None:
        try:
            counters = await dispatch_payload(payload, config, state.dedupe, notifier, logger)
            logger.info("payload dispatched", extra=counters)
        except Exception as exc:
            logger.exception("background dispatch failed: %s", exc)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "service": "notify-gateway",
                "alertmanager": "ready",
            },
        )

    @app.post("/")
    @app.post("/ingest/v1/event")
    async def ingest_event(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
        token = extract_bearer_token(request.headers.get("authorization"))
        if token != config.notify_gateway_token:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        body = await request.json()
        error = validate_ingest_event(body)
        if error:
            return JSONResponse(status_code=400, content={"error": error})

        alert = build_alert_from_event(body, config)
        payload = {
            "status": normalize_status(body.get("status")),
            "alerts": [alert],
        }
        background_tasks.add_task(dispatch_payload_safe, payload)

        return JSONResponse(status_code=202, content={"accepted": 1, "forwardedTo": "alertmanager"})

    @app.post("/ingest/v1/alerts")
    async def ingest_alerts(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
        token = extract_bearer_token(request.headers.get("authorization"))
        if token != config.notify_gateway_token:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        body = await request.json()
        alerts = ensure_alert_array(body)
        if alerts is None:
            return JSONResponse(status_code=400, content={"error": "body must be an alerts array or an object with alerts[]"})

        payload_status = body.get("status") if isinstance(body, dict) else "firing"
        payload = {
            "status": normalize_status(payload_status),
            "alerts": alerts,
        }
        background_tasks.add_task(dispatch_payload_safe, payload)

        return JSONResponse(status_code=202, content={"accepted": len(alerts), "forwardedTo": "alertmanager"})

    @app.post("/dispatch/v1/alertmanager")
    async def dispatch_alertmanager(request: Request) -> JSONResponse:
        token = extract_bearer_token(request.headers.get("authorization"))
        if token != config.alertmanager_webhook_token:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse(status_code=400, content={"error": "invalid alertmanager payload"})

        try:
            counters = await dispatch_payload(body, config, state.dedupe, notifier, logger)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})

        return JSONResponse(status_code=200, content={"ok": True, **counters})

    @app.exception_handler(Exception)
    async def on_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("request failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})

    logger.info(
        "notify-gateway started",
        extra={
            "port": config.port,
            "routeBySeverity": config.route_by_severity,
            "sourceRouteCount": len(config.source_route_by_severity),
        },
    )

    return app


app = create_app()
