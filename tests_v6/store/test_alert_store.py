"""Alert records in the app database: per PCE, always with a delivery row, cascading on retention."""
from datetime import UTC, datetime, timedelta

from illumio_ops.domain.alerting import Confidence, RuleState, Trigger
from illumio_ops.domain.values import AlertRuleType, DeliveryStatus, Severity
from illumio_ops.store import alerts as store
from tests_v6.web.conftest import make_ctx

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
A = ("https://a.example:8443", "1")
B = ("https://b.example:8443", "1")


def trig(subject="s"):
    return Trigger(rule_id="r" * 32, rule_type=AlertRuleType.SYSTEM, subject_key=subject, severity=Severity.HIGH,
                   first_seen=NOW, last_seen=NOW, late=False, message_key="alert_system_disk_low",
                   params={"free_bytes": 1}, facts={}, evidence=None, confidence=Confidence())


def insert(conn, pce=A, *, channels=("line",), hold=None, at=NOW):
    return store.insert_alert(conn, pce_url=pce[0], org_id=pce[1], rule_name="r", pack_key=None, trigger=trig(),
                              at=at, channels=list(channels), hold=hold)


def test_previous_pce_alerts_hidden(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        a = insert(conn, A)
        insert(conn, B)
        rows, total = store.list_alerts(conn, pce_url=A[0], org_id=A[1], since=NOW - timedelta(days=1), limit=50, offset=0)
        assert [r["id"] for r in rows] == [a] and total == 1
        assert store.get_alert(conn, a, pce_url=B[0], org_id=B[1]) is None


def test_not_notified_and_grouped_recorded(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        a = insert(conn, hold=DeliveryStatus.NOT_NOTIFIED)
        b = insert(conn, hold=DeliveryStatus.GROUPED)
        rows = store.deliveries(conn, [a, b])
        assert [(r["channel"], r["status"]) for r in rows] == [("-", "not_notified"), ("-", "grouped")]
        assert store.get_alert(conn, a, pce_url=A[0], org_id=A[1])["notify"] == 0


def test_no_channel_delivery_row(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        a = insert(conn, channels=())
        assert [(r["channel"], r["status"]) for r in store.deliveries(conn, [a])] == [("-", "no_channel")]
        b = insert(conn, channels=("line", "smtp"))
        assert {r["status"] for r in store.deliveries(conn, [b])} == {"pending"}
        assert len(store.due_deliveries(conn, NOW, limit=10)) == 2


def test_retention_cascades(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        old = insert(conn, at=NOW - timedelta(days=100))
        store.add_note(conn, old, body="seen", created_by="illumio", at=NOW)
        keep = insert(conn)
        assert store.delete_alerts_before(conn, NOW - timedelta(days=90)) == 1
        assert store.deliveries(conn, [old]) == [] and store.notes(conn, old) == []
        assert len(store.deliveries(conn, [keep])) == 1


def test_watermark_ignored_for_other_pce(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        store.set_eval_watermark(conn, "events", "42", pce_url=A[0], org_id=A[1])
        assert store.eval_watermark(conn, "events", pce_url=A[0], org_id=A[1]) == "42"
        assert store.eval_watermark(conn, "events", pce_url=B[0], org_id=B[1]) is None


def test_rule_state_round_trip_and_suppressed_counts(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        store.save_rule_state(conn, "r", "s", RuleState(NOW, (NOW,)), suppressed=None)
        store.save_rule_state(conn, "r", "s", RuleState(NOW, (NOW,)), suppressed="cooldown")
        store.save_rule_state(conn, "r", "t", RuleState(None, ()), suppressed="throttle")
        assert store.rule_state(conn, "r", "s") == RuleState(NOW, (NOW,))
        store.set_rule_status(conn, "r", "no_data", NOW)
        insert(conn)
        summary = store.rule_summaries(conn, pce_url=A[0], org_id=A[1], now=NOW)["r"]
        assert (summary.suppressed_cooldown, summary.suppressed_throttle, summary.last_status) == (1, 1, "no_data")
        assert store.rule_summaries(conn, pce_url=A[0], org_id=A[1], now=NOW)["r" * 32].fired_7d == 1
