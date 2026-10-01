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


def make_queue(**overrides):
    sent = []
    deliveries = []

    class FakeNotifier:
        def __init__(self):
            self.fail_first = 0

        def notify_tag(self, tag, title, body, severity):
            deliveries.append({"tag": tag, "title": title})
            if self.fail_first > 0:
                self.fail_first -= 1
                raise RuntimeError("simulated 429")
            sent.append({"tag": tag, "title": title})
            return "sent"

    notifier = FakeNotifier()
    defaults = dict(
        logger=logging.getLogger("test"),
        sender=None,
        spacing_s=0.0,
        backoff_schedule_s=(0.01, 0.02),
        give_up_after_s=1.0,
    )
    defaults.update(overrides)
    if defaults["sender"] is None:
        async def sender(tag, message):
            return await app_module.send_with_retry(
                tag, message, notifier, [0, 0], defaults["logger"]
            )
        defaults["sender"] = sender
    queue = app_module.DispatchQueue(**defaults)
    return queue, notifier, sent, deliveries


def test_dispatch_queue_serializes_and_delivers_in_order():
    queue, notifier, sent, deliveries = make_queue()

    async def run():
        await queue.enqueue("tg.a", {"title": "first", "body": "b", "severity": "info"})
        await queue.enqueue("tg.a", {"title": "second", "body": "b", "severity": "info"})
        await queue.flush()

    asyncio.run(run())

    assert [d["title"] for d in deliveries] == ["first", "second"]
    assert len(sent) == 2


def test_dispatch_queue_backoff_retries_then_delivers():
    queue, notifier, sent, _ = make_queue()
    notifier.fail_first = 3

    async def run():
        await queue.enqueue("tg.a", {"title": "retry-me", "body": "b", "severity": "info"})
        await queue.flush()

    asyncio.run(run())

    assert [s["title"] for s in sent] == ["retry-me"]


def test_dispatch_queue_gives_up_after_deadline_and_keeps_processing():
    queue, notifier, sent, _ = make_queue(give_up_after_s=0.01, backoff_schedule_s=(5.0,))
    notifier.fail_first = 10**9

    async def run():
        await queue.enqueue("tg.a", {"title": "doomed", "body": "b", "severity": "info"})
        await queue.enqueue("tg.a", {"title": "next", "body": "b", "severity": "info"})
        await queue.flush()

    asyncio.run(run())

    assert sent == []


def test_dispatch_queue_spacing_between_sends():
    import time
    timestamps = []

    async def sender(tag, message):
        timestamps.append(time.monotonic())
        return "sent"

    queue, notifier, sent, _ = make_queue(sender=sender, spacing_s=0.05)

    async def run():
        await queue.enqueue("tg.a", {"title": "1", "body": "b", "severity": "info"})
        await queue.enqueue("tg.a", {"title": "2", "body": "b", "severity": "info"})
        await queue.flush()

    asyncio.run(run())

    assert len(timestamps) == 2
    assert timestamps[1] - timestamps[0] >= 0.05


def test_dispatch_payload_enqueues_and_returns_accepted():
    sent = []

    async def sender(tag, message):
        sent.append((tag, message["title"]))
        return "sent"

    config = app_module.load_config_from_env({
        "NOTIFY_GATEWAY_TOKEN": "tok",
        "ALERTMANAGER_WEBHOOK_TOKEN": "am",
        "SOURCE_ROUTE_JSON": '{"gnosis-frontrun-v2":{"critical":["tg.frontrun"],"warning":["tg.frontrun"],"info":["tg.frontrun"]}}',
        "APPRISE_URLS_JSON": '[{"url":"tgram://tok@1/chat","tags":["tg.frontrun"]}]',
    })
    dedupe = app_module.DedupeCache(45000)
    queue = app_module.DispatchQueue(
        logger=logging.getLogger("test"),
        sender=sender,
        spacing_s=0.0,
        backoff_schedule_s=(0.01,),
        give_up_after_s=1.0,
    )

    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"source": "gnosis-frontrun-v2", "severity": "critical", "summary": "s1"},
            },
            {
                "status": "firing",
                "labels": {"source": "gnosis-frontrun-v2", "severity": "critical", "summary": "s2"},
            },
        ],
    }

    counters = asyncio.run(
        app_module.dispatch_payload(payload, config, dedupe, queue, logging.getLogger("test"))
    )
    asyncio.run(queue.flush())

    assert counters["accepted"] == 2
    assert len(sent) == 2
    assert sent[0][0] == "tg.frontrun"


def test_ingest_endpoint_smoke_with_queue():
    from fastapi.testclient import TestClient

    app = app_module.create_app()
    client = TestClient(app)
    resp = client.post(
        "/ingest/v1/event",
        headers={"Authorization": "Bearer test-token"},
        json={"source": "smoke-bot", "severity": "info", "summary": "smoke"},
    )

    assert resp.status_code == 202
    assert resp.json() == {"accepted": 1, "forwardedTo": "alertmanager"}
