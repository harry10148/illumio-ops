"""The dispatcher: one message per channel per run, retries with backoff, a channel cooling down after
repeated failures, and every outcome visible on the alert."""
from datetime import timedelta

import pytest

from illumio_ops.domain.alerting import Confidence, Trigger
from illumio_ops.domain.values import AlertRuleType, ChannelKind, Severity
from illumio_ops.services.alerts import dispatch
from illumio_ops.services.alerts.channels import SendResult
from illumio_ops.services.alerts.dispatch import run_dispatch, send_test
from illumio_ops.store import alerts as store
from tests_v6.services.collect.conftest import NOW, PCE, configured_ctx, minutes


class FakeSend:
    def __init__(self):
        self.calls: list[tuple[ChannelKind, str]] = []
        self.result = SendResult(ok=True, error=None)

    def __call__(self, kind, cfg, rendered, *, timeout=10.0):
        self.calls.append((kind, rendered.text))
        return self.result


@pytest.fixture
def fake(monkeypatch):
    f = FakeSend()
    monkeypatch.setattr(dispatch, "send", f)
    return f


def enable(ctx, *names):
    def mutate(d):
        ch = d["alerts"]["channels"]
        if "line" in names:
            ch["line"].update(enabled=True, access_token="t", target_id="U1")
        if "webhook" in names:
            ch["webhook"].update(enabled=True, url="https://hook.example/x")
    ctx.settings.update(ctx.settings.current().revision, mutate)


def alert(ctx, i=1, channels=("line",)):
    t = Trigger(rule_id="a" * 32, rule_type=AlertRuleType.SYSTEM, subject_key=f"s{i}", severity=Severity.HIGH,
                first_seen=NOW, last_seen=NOW, late=False, message_key="alert_system_disk_low",
                params={"free": "1 GB", "warn": "10 GB"}, facts={}, evidence=None, confidence=Confidence())
    with ctx.db() as conn:
        return store.insert_alert(conn, pce_url=PCE["url"], org_id=PCE["org_id"], rule_name="disk", pack_key=None,
                                  trigger=t, at=NOW, channels=list(channels), hold=None)


def statuses(ctx, alert_id):
    with ctx.db() as conn:
        return [(d["channel"], d["status"], d["attempts"]) for d in store.deliveries(conn, [alert_id])]


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


def test_batches_per_channel(ctx, fake):
    enable(ctx, "line", "webhook")
    ids = [alert(ctx, i, channels=("line", "webhook")) for i in range(3)]
    run_dispatch(ctx, now=NOW)
    assert sorted(k for k, _ in fake.calls) == [ChannelKind.LINE, ChannelKind.WEBHOOK]  # one message each
    assert all(s == ("line", "sent", 1) or s == ("webhook", "sent", 1) for i in ids for s in statuses(ctx, i))


def test_failed_delivery_retried_then_final(ctx, fake):
    enable(ctx, "line")
    a = alert(ctx)
    fake.result = SendResult(ok=False, error="status=500")
    run_dispatch(ctx, now=NOW)
    assert statuses(ctx, a) == [("line", "pending", 1)]
    run_dispatch(ctx, now=NOW + timedelta(seconds=30))  # not due yet (1 min backoff)
    assert len(fake.calls) == 1
    run_dispatch(ctx, now=NOW + minutes(1))
    assert statuses(ctx, a) == [("line", "pending", 2)]
    run_dispatch(ctx, now=NOW + minutes(6))
    assert statuses(ctx, a) == [("line", "failed", 3)]
    with ctx.db() as conn:
        assert store.deliveries(conn, [a])[0]["last_error"] == "status=500"


def test_channel_cooldown_does_not_consume_attempts(ctx, fake):
    enable(ctx, "line")
    ids = [alert(ctx, i) for i in range(3)]
    fake.result = SendResult(ok=False, error="down")
    for step in (0, 1, 6):  # three failed sends in a row: the channel cools down for 5 minutes
        run_dispatch(ctx, now=NOW + minutes(step))
    later = alert(ctx, 9)
    run_dispatch(ctx, now=NOW + minutes(7))
    assert statuses(ctx, later) == [("line", "pending", 0)] and len(fake.calls) == 3
    with ctx.db() as conn:
        assert store.channel_state(conn)["line"]["cooldown_until"] is not None
    fake.result = SendResult(ok=True, error=None)
    run_dispatch(ctx, now=NOW + minutes(12))
    assert statuses(ctx, later) == [("line", "sent", 1)] and ids


def test_no_enabled_channel_marks_undelivered(ctx, fake):
    a = alert(ctx, channels=())
    run_dispatch(ctx, now=NOW)
    assert statuses(ctx, a) == [("-", "no_channel", 0)] and fake.calls == []


def test_disabled_channel_pending_failed(ctx, fake):
    a = alert(ctx, channels=("line",))  # line was enabled when the alert fired, is off now
    run_dispatch(ctx, now=NOW)
    assert statuses(ctx, a) == [("line", "failed", 0)] and fake.calls == []
    with ctx.db() as conn:
        assert store.deliveries(conn, [a])[0]["last_error"] == "channel_disabled"


def test_send_test_writes_nothing(ctx, fake):
    enable(ctx, "line")
    r = send_test(ctx, ChannelKind.LINE)
    assert r.ok and len(fake.calls) == 1
    with ctx.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 0
        assert store.channel_state(conn) == {}
