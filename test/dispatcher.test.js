import test from "node:test";
import assert from "node:assert/strict";
import { DedupeCache, formatTimestampForNotify, resolveChannels } from "../src/dispatcher.js";

test("dedupe cache drops duplicate key in window", () => {
  const cache = new DedupeCache(45000);
  const now = Date.now();

  assert.equal(cache.shouldDrop("k1", now), false);
  assert.equal(cache.shouldDrop("k1", now + 1000), true);
  assert.equal(cache.shouldDrop("k1", now + 46000), false);
});

test("resolve channels follows severity route", () => {
  const config = {
    enabledChannels: ["tg", "wecom", "serverchan"],
    routeBySeverity: {
      critical: ["tg", "wecom"],
      warning: ["wecom"],
      info: ["tg"],
    },
  };

  const channels = resolveChannels(
    {
      labels: {
        severity: "critical",
      },
      annotations: {},
    },
    config
  );

  assert.deepEqual(channels, ["tg", "wecom"]);
});

test("resolve channels supports explicit overrides and mute", () => {
  const config = {
    enabledChannels: ["tg", "wecom", "serverchan"],
    routeBySeverity: {
      critical: ["tg", "wecom"],
      warning: ["wecom"],
      info: ["tg"],
    },
  };

  const overridden = resolveChannels(
    {
      labels: {
        severity: "warning",
        notify_channels: "tg,serverchan",
      },
      annotations: {},
    },
    config
  );
  assert.deepEqual(overridden, ["tg", "serverchan"]);

  const muted = resolveChannels(
    {
      labels: {
        severity: "critical",
        notify_mute: "true",
      },
      annotations: {},
    },
    config
  );
  assert.deepEqual(muted, []);
});

test("format timestamp with configured timezone", () => {
  const formatted = formatTimestampForNotify("2026-01-01T00:00:00Z", "Asia/Shanghai");
  assert.equal(formatted, "2026-01-01 08:00:00 (Asia/Shanghai)");
});
