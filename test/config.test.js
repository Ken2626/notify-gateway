import test from "node:test";
import assert from "node:assert/strict";
import { loadConfig } from "../src/config.js";

function withEnv(pairs, fn) {
  const snapshot = {};
  for (const [key, value] of Object.entries(pairs)) {
    snapshot[key] = process.env[key];
    if (value === null) {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }

  try {
    fn();
  } finally {
    for (const [key, value] of Object.entries(snapshot)) {
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  }
}

test("route config defaults and overrides", () => {
  withEnv(
    {
      NOTIFY_GATEWAY_TOKEN: "token-a",
      ALERTMANAGER_WEBHOOK_TOKEN: "token-b",
      ENABLED_CHANNELS: "tg,wecom,serverchan",
      ROUTE_CRITICAL: "tg,wecom",
      ROUTE_WARNING: "wecom",
      ROUTE_INFO: "tg",
    },
    () => {
      const config = loadConfig();
      assert.deepEqual(config.routeBySeverity.critical, ["tg", "wecom"]);
      assert.deepEqual(config.routeBySeverity.warning, ["wecom"]);
      assert.deepEqual(config.routeBySeverity.info, ["tg"]);
    }
  );
});

test("route channels are filtered by enabled channels", () => {
  withEnv(
    {
      NOTIFY_GATEWAY_TOKEN: "token-a",
      ALERTMANAGER_WEBHOOK_TOKEN: "token-b",
      ENABLED_CHANNELS: "tg",
      ROUTE_CRITICAL: "tg,wecom,serverchan",
      ROUTE_WARNING: "wecom",
      ROUTE_INFO: "tg",
    },
    () => {
      const config = loadConfig();
      assert.deepEqual(config.routeBySeverity.critical, ["tg"]);
      assert.deepEqual(config.routeBySeverity.warning, []);
      assert.deepEqual(config.routeBySeverity.info, ["tg"]);
    }
  );
});

test("notify timezone defaults to UTC and supports override", () => {
  withEnv(
    {
      NOTIFY_GATEWAY_TOKEN: "token-a",
      ALERTMANAGER_WEBHOOK_TOKEN: "token-b",
      NOTIFY_TIMEZONE: null,
    },
    () => {
      const config = loadConfig();
      assert.equal(config.notifyTimezone, "UTC");
    }
  );

  withEnv(
    {
      NOTIFY_GATEWAY_TOKEN: "token-a",
      ALERTMANAGER_WEBHOOK_TOKEN: "token-b",
      NOTIFY_TIMEZONE: "Asia/Shanghai",
    },
    () => {
      const config = loadConfig();
      assert.equal(config.notifyTimezone, "Asia/Shanghai");
    }
  );
});

test("invalid notify timezone throws", () => {
  withEnv(
    {
      NOTIFY_GATEWAY_TOKEN: "token-a",
      ALERTMANAGER_WEBHOOK_TOKEN: "token-b",
      NOTIFY_TIMEZONE: "Mars/Olympus",
    },
    () => {
      assert.throws(() => loadConfig(), /NOTIFY_TIMEZONE is invalid/);
    }
  );
});
