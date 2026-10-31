"""What each source sends, the status page's states, the test send, the backlog check (P7 Task 5)."""
import json
from datetime import timedelta

from illumio_ops.domain.alerting import SiemFact, SystemFacts, evaluate_system
from illumio_ops.domain.alertpack import system_rule
from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.services.siem.dispatch import run_siem
from illumio_ops.services.siem.status import siem_status
from illumio_ops.services.siem.tester import send_test
from illumio_ops.settings.schema import SiemDestination
from illumio_ops.store import siem as store
from illumio_ops.store.flowdb import analysis
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.store.test_alert_store import insert as insert_alert
from tests_v6.store.test_analysis_store import DEDUP, _det
from tests_v6.store.test_siem_sources import FIXTURE

from .conftest import DEST, NOW, REFUSED, FakeTransport, configure, destination


def run(ctx, transport):
    return run_siem(ctx, now=NOW, transport_factory=lambda d: transport)


def test_only_alerts_that_notify_of_this_pce_are_sent(ctx):
    from illumio_ops.domain.values import DeliveryStatus
    configure(ctx, destination(sources=["findings"]))
    run(ctx, FakeTransport())
    pce = ("https://pce.test:8443", "1")
    with ctx.db() as conn:
        sent = insert_alert(conn, pce)
        insert_alert(conn, pce, hold=DeliveryStatus.NOT_NOTIFIED)  # an upgraded install's new default rule
        insert_alert(conn, ("https://other.test:8443", "1"))
    t = FakeTransport()
    run(ctx, t)
    lines = [json.loads(x) for x in t.lines]
    assert [x["id"] for x in lines] == [sent] and lines[0]["kind"] == "alert"
    assert lines[0]["signature"] == "alert.system" and lines[0]["severity"] == "high" and lines[0]["summary"]


def test_a_detection_is_sent_once_with_its_text_and_host(ctx):
    configure(ctx, destination(sources=["findings"], format="cef"))
    run(ctx, FakeTransport())
    with ctx.flows().connect() as conn:
        analysis.upsert_detections(conn, [_det("fanout|w1", seen=NOW)], dedup=DEDUP, late=False, at=NOW)
        conn.commit()
    t = FakeTransport()
    run(ctx, t)
    [line] = t.lines
    assert "|detection.fanout|" in line and "cat=illumio_ops_detection" in line and "externalId=detection:" in line
    with ctx.flows().connect() as conn:  # the same detection seen again updates its row: not sent again
        analysis.upsert_detections(conn, [_det("fanout|w1", seen=NOW + timedelta(minutes=5), severity="high")],
                                   dedup=DEDUP, late=False, at=NOW + timedelta(minutes=5))
        conn.commit()
    run(ctx, t)
    assert len(t.lines) == 1


def _log_flows(ctx):
    recs = [normalize_flow(r) for r in json.loads(FIXTURE.read_text())]
    with ctx.flows().connect() as conn:
        upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW, increments="cycle", log_new_connections=True)
        conn.commit()
        return [dict(r) for r in conn.execute("SELECT * FROM new_connection_log ORDER BY id")]


def test_new_connections_follow_the_decision_filter_and_carry_no_counts(ctx):
    configure(ctx, destination(sources=["new_connections"], new_connection_decisions=["blocked"]))
    run(ctx, FakeTransport())
    log = _log_flows(ctx)
    t = FakeTransport()
    run(ctx, t)
    lines = [json.loads(x) for x in t.lines]
    assert len(lines) == sum(1 for r in log if r["decision"] == "blocked")
    assert all(x["decision"] == "blocked" and x["kind"] == "new_connection" for x in lines)
    assert all("count" not in json.dumps(x) and "bytes" not in json.dumps(x) for x in lines)


def test_lightweight_says_the_traffic_sources_need_alert_mode(ctx):
    configure(ctx, destination(sources=["audit", "findings", "new_connections"]))
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"].update({"mode": "lightweight"}))
    run(ctx, FakeTransport())
    view = siem_status(ctx)
    states = {s.source: s.state for s in view.destinations[0].sources}
    assert view.lightweight
    assert states == {"audit": "ok", "alerts": "ok", "detections": "needs_alert_mode",
                      "new_connections": "needs_alert_mode"}


def test_new_connections_wait_for_a_full_baseline(ctx):
    configure(ctx, destination(sources=["new_connections"]))
    assert siem_status(ctx).destinations[0].sources[0].state == "baseline_building"


def test_status_says_failing_and_dlq_full(ctx):
    from tests_v6.services.siem.conftest import add_events
    configure(ctx, destination(), dlq_max_per_dest=100)
    run(ctx, FakeTransport())
    add_events(ctx, [1])
    run(ctx, FakeTransport(lambda n, line: REFUSED))
    [src] = siem_status(ctx).destinations[0].sources
    assert src.state == "failing" and src.pending == 1 and src.last_error
    with ctx.db() as conn:
        for i in range(100):
            store.quarantine(conn, destination_id=DEST, source="audit", record_id=-i, external_id=f"x:{i}",
                             event_time=None, payload="p", error="e", attempts=1, at=NOW)
        store.note_error(conn, DEST, "audit", "dlq_full", NOW + timedelta(seconds=1))
    view = siem_status(ctx)
    assert view.destinations[0].dlq == 100 and view.destinations[0].sources[0].state == "dlq_full"


def test_a_test_send_moves_no_cursor(ctx):
    run(ctx, FakeTransport())
    with ctx.db() as conn:
        before = store.cursors(conn)
    t = FakeTransport()
    r = send_test(ctx, SiemDestination.model_validate(destination()), now=NOW, transport_factory=lambda d: t)
    assert r.ok and t.lines == [r.line] and json.loads(r.line)["kind"] == "test"
    with ctx.db() as conn:
        assert store.cursors(conn) == before
    bad = send_test(ctx, SiemDestination.model_validate(destination()), now=NOW,
                    transport_factory=lambda d: FakeTransport(lambda n, line: REFUSED))
    assert not bad.ok and "refused" in bad.error.lower()


def test_the_backlog_check_fires_when_far_behind_or_the_dlq_is_full():
    rule = system_rule("rule_system_siem_backlog")
    facts = SystemFacts(probe=None, siem=(
        SiemFact("a" * 32, "graylog", pending=60_000, warn=50_000, dlq_full=False, failing=False, error=None),
        SiemFact("b" * 32, "splunk", pending=10, warn=50_000, dlq_full=True, failing=True, error="x"),
        SiemFact("c" * 32, "ok", pending=10, warn=50_000, dlq_full=False, failing=False, error=None)))
    fired = evaluate_system(rule, facts, now=NOW)
    assert sorted(t.subject_key for t in fired) == ["siem_backlog:" + "a" * 32, "siem_backlog:" + "b" * 32]


def test_an_upgraded_file_gets_the_backlog_check(tmp_path):
    from illumio_ops.settings.schema import default_settings
    from illumio_ops.settings.upgrade import upgrade
    from tests_v6.settings.conftest import HASH, KEY
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 8
    del d["siem"]
    d["alerts"]["rules"] = [r for r in d["alerts"]["rules"] if r.get("pack_key") != "rule_system_siem_backlog"]
    out = upgrade(d)
    assert [r for r in out["alerts"]["rules"] if r.get("pack_key") == "rule_system_siem_backlog"]
    again = upgrade({**out, "schema_version": 8})  # already there: not added twice
    assert sum(r.get("pack_key") == "rule_system_siem_backlog" for r in again["alerts"]["rules"]) == 1
