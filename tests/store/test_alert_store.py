"""Alert records in the app database: per PCE, always with a delivery row, cascading on retention."""
from datetime import UTC, datetime, timedelta

from illumio_ops.domain.alerting import Confidence, RuleState, Trigger
from illumio_ops.domain.values import AlertRuleType, DeliveryStatus, Severity
from illumio_ops.store import alerts as store
from tests.web.conftest import make_ctx

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


# ── the hosts an alert is about (purpose-led UI spec §8) ──

W = "/orgs/1/workloads/"


def _with_devices(conn, devices, *, more=0, rule_type=AlertRuleType.LATERAL, subject="xenv|a|b", at=NOW):
    from dataclasses import replace
    t = replace(trig(subject), rule_type=rule_type, devices=tuple(devices), devices_more=more)
    return store.insert_alert(conn, pce_url=A[0], org_id=A[1], rule_name="r", pack_key=None, trigger=t, at=at,
                              channels=["line"], hold=None)


def test_an_alert_is_stored_with_its_hosts_and_found_by_one(tmp_path):
    from illumio_ops.domain.alert_devices import Device
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        a = _with_devices(conn, [Device(W + "a", "source"), Device("ip:10.0.0.9", "destination")], more=2)
        b = insert(conn)
        conn.commit()
        assert store.devices(conn, [a, b]) == {a: [Device(W + "a", "source"), Device("ip:10.0.0.9", "destination")]}
        assert store.get_alert(conn, a, pce_url=A[0], org_id=A[1])["devices_more"] == 2
        since = NOW - timedelta(days=1)
        rows, total = store.list_alerts(conn, pce_url=A[0], org_id=A[1], since=since, device="ip:10.0.0.9", limit=50, offset=0)
        assert [r["id"] for r in rows] == [a] and total == 1
        rows, total = store.list_alerts(conn, pce_url=A[0], org_id=A[1], since=since, device=W + "zz", limit=50, offset=0)
        assert rows == [] and total == 0


def test_deleting_an_alert_removes_its_hosts(tmp_path):
    from illumio_ops.domain.alert_devices import Device
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        a = _with_devices(conn, [Device(W + "a", "source")], at=NOW - timedelta(days=40))
        conn.commit()
        assert store.delete_alerts_before(conn, NOW - timedelta(days=30)) == 1
        assert conn.execute("SELECT COUNT(*) FROM alert_devices WHERE alert_id = ?", (a,)).fetchone()[0] == 0


def test_alerts_from_before_are_given_their_hosts_once(tmp_path):
    """An upgrade: alerts stored before hosts were recorded. A detection's are read from its fingerprint (the
    alert's subject), an event rule's host is its subject; what names no host stays without."""
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        lateral = _with_devices(conn, [], subject=f"xenv|{W}a|{W}b|22|6")
        event = _with_devices(conn, [], rule_type=AlertRuleType.EVENT, subject=W + "c")
        system = insert(conn)
        counted = _with_devices(conn, [], rule_type=AlertRuleType.EVENT, subject="r" * 32)
        conn.commit()
        assert store.backfill_devices(conn) == 2
        got = store.devices(conn, [lateral, event, system, counted])
        assert [(d.key, d.role) for d in got[lateral]] == [(W + "a", "source"), (W + "b", "destination")]
        assert [(d.key, d.role) for d in got[event]] == [(W + "c", "subject")]
        assert system not in got and counted not in got
        assert store.backfill_devices(conn) == 0


# ── a period with an end (the weekly overview, UI redesign spec §9.2) ──

def test_until_bounds_the_period_and_its_end_is_not_included(tmp_path):
    from illumio_ops.domain.alert_devices import Device
    ctx = make_ctx(tmp_path)
    start, end = NOW - timedelta(days=7), NOW
    with ctx.db() as conn:
        for at in (start - timedelta(microseconds=1), start, end - timedelta(microseconds=1), end):
            insert(conn, at=at)
        _with_devices(conn, [Device(f"{W}a", "source")], at=end - timedelta(hours=1))
        _with_devices(conn, [Device(f"{W}a", "source")], at=end)
        same = {"pce_url": A[0], "org_id": A[1], "since": start}
        assert store.count_alerts(conn, **same) == 5 and store.count_alerts(conn, **same, until=end) == 3
        counts = store.period_counts(conn, **same, until=end)
        assert counts == {"high": 3, "grouped": 0} and store.period_counts(conn, **same)["high"] == 5
        assert [(r["key"], r["n"]) for r in store.alerted_devices(conn, **same)] == [(f"{W}a", 2)]
        assert [(r["key"], r["n"]) for r in store.alerted_devices(conn, **same, until=end)] == [(f"{W}a", 1)]
        assert store.first_fired_at(conn, pce_url=A[0], org_id=A[1]) == start - timedelta(microseconds=1)
        assert store.first_fired_at(conn, pce_url=B[0], org_id=B[1]) is None


def test_the_categories_of_a_period_add_up_to_its_alerts(tmp_path):
    """Every rule type falls in exactly one category of the alerts page, a lateral rule's by its detector."""
    from dataclasses import replace
    ctx = make_ctx(tmp_path)
    start, end = NOW - timedelta(days=7), NOW
    with ctx.db() as conn:
        for i, (rule_type, detector) in enumerate([(t, None) for t in AlertRuleType] + [
                (AlertRuleType.LATERAL, "fanout"), (AlertRuleType.LATERAL, "volume_surge")]):
            t = replace(trig(f"s{i}"), rule_type=rule_type, params={"detector": detector} if detector else {})
            store.insert_alert(conn, pce_url=A[0], org_id=A[1], rule_name="r", pack_key=None, trigger=t,
                               at=start + timedelta(hours=i), channels=["line"], hold=None)
        insert(conn, at=end)  # after the period: in no category of it
        got = store.counts_by_category(conn, pce_url=A[0], org_id=A[1], since=start, until=end)
        total = store.count_alerts(conn, pce_url=A[0], org_id=A[1], since=start, until=end)
    assert got == {"lateral": 2, "anomaly": 1, "traffic": 3, "event": 1, "system": 1}
    assert sum(got.values()) == total == len(AlertRuleType) + 2
