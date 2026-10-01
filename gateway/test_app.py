import asyncio
import logging
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("NOTIFY_GATEWAY_TOKEN", "test-token")
os.environ.setdefault("ALERTMANAGER_WEBHOOK_TOKEN", "test-am-token")

from gateway import app as app_module


def test_retry_schedule_default_is_minutes_level():
    assert app_module.parse_retry_schedule(None) == [180000, 300000, 300000]


def test_retry_schedule_env_override_wins():
    assert app_module.parse_retry_schedule("5000,10000") == [5000, 10000]


def test_retry_schedule_ignores_invalid_items():
    assert app_module.parse_retry_schedule("junk,-3,2000") == [2000]


def test_send_with_retry_follows_schedule_then_gives_up():
    sleeps = []

    class FailingNotifier:
        def __init__(self):
            self.calls = 0

        def notify_tag(self, tag, title, body, severity):
            self.calls += 1
            raise RuntimeError("simulated 429")

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    notifier = FailingNotifier()
    message = {"title": "t", "body": "b", "severity": "info"}

    async def run():
        with patch.object(app_module.asyncio, "sleep", fake_sleep):
            await app_module.send_with_retry(
                "tg.test",
                message,
                notifier,
                [180000, 300000],
                logging.getLogger("test"),
            )

    try:
        asyncio.run(run())
        raised = False
    except RuntimeError:
        raised = True

    assert raised
    assert notifier.calls == 3
    assert sleeps == [180.0, 300.0]


def test_send_with_retry_returns_on_first_success():
    sleeps = []

    class RecoveringNotifier:
        def __init__(self):
            self.calls = 0

        def notify_tag(self, tag, title, body, severity):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("simulated 429")
            return "sent"

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    notifier = RecoveringNotifier()
    message = {"title": "t", "body": "b", "severity": "info"}

    async def run():
        with patch.object(app_module.asyncio, "sleep", fake_sleep):
            return await app_module.send_with_retry(
                "tg.test",
                message,
                notifier,
                [180000, 300000],
                logging.getLogger("test"),
            )

    result = asyncio.run(run())

    assert result == "sent"
    assert notifier.calls == 2
    assert sleeps == [180.0]
