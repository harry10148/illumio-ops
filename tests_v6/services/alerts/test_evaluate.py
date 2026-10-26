"""Alert evaluation over what each collection cycle brought: events, flow growth, detections, system state."""
import json
from datetime import timedelta
from pathlib import Path

import pytest

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin, IngestSource
from illumio_ops.pce.events import EventsPage
from illumio_ops.services.alerts import evaluate
from illumio_ops.services.alerts.evaluate import (
    evaluate_events,
    evaluate_lateral,
    evaluate_system,
    evaluate_traffic,
)
from illumio_ops.services.collect import events as ev
from illumio_ops.services.collect.events import run_events_cycle
from illumio_ops.store import alerts as store
from illumio_ops.store.flowdb import analysis, ingest_state, workloads
from illumio_ops.store.flowdb.analysis import DetectionWrite
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.services.collect.conftest import (
    NOW,
    PCE,
    configured_ctx,
    minutes,
    raw_flow,
)

TAMPER = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "pce" / "events_tamper.json").read_text())


def _ts(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class Pce:
    """Feeds run_events_cycle; each collect() call returns what was queued since the last."""

    def __init__(self, monkeypatch):
        self.items: list[dict] = []
        monkeypatch.setattr(ev, "fetch_events", lambda client, **kw: EventsPage(items=list(self.items), capped=False))

    def event(self, i, event_type, at, **extra):
        self.items.append({"href": f"/orgs/1/events/{i}", "event_type": event_type, "timestamp": _ts(at),
                           "status": extra.pop("status", "success"), "severity": extra.pop("severity", "info"),
                           "created_by": extra.pop("created_by", {"user": {"username": "admin"}}), **extra})


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


@pytest.fixture
def pce(monkeypatch):
    return Pce(monkeypatch)


def _alerts(ctx):
    with ctx.db() as conn:
        rows, _ = store.list_alerts(conn, pce_url=PCE["url"], org_id=PCE["org_id"], since=NOW - timedelta(days=30),
                                    limit=100, offset=0)
        return rows


def _collect_and_evaluate(ctx, pce, at):
    run_events_cycle(ctx, now=at)
    return evaluate_events(ctx, now=at)


# ── events ──

def test_first_run_does_not_alert_history(ctx, pce):
    pce.event(1, "rule_set.create", NOW - minutes(2))
    r = _collect_and_evaluate(ctx, pce, NOW)
    assert r.evaluated == 0 and _alerts(ctx) == []
    with ctx.db() as conn:
        assert store.eval_watermark(conn, "events", pce_url=PCE["url"], org_id=PCE["org_id"]) == "1"


def test_backfill_events_not_evaluated(ctx, pce):
    from illumio_ops.domain.events import normalize_event
    from illumio_ops.store.flowdb.events import upsert_events
    _collect_and_evaluate(ctx, pce, NOW)
    with ctx.flows().connect() as conn:
        upsert_events(conn, [normalize_event({"href": "/orgs/1/events/b", "event_type": "rule_set.create",
                                              "timestamp": _ts(NOW - timedelta(days=3))})],
                      origin=DataOrigin.BACKFILL, now=NOW)
    assert evaluate_events(ctx, now=NOW + minutes(5)).evaluated == 0 and _alerts(ctx) == []


def test_immediate_event_alert_recorded_with_evidence(ctx, pce):
    _collect_and_evaluate(ctx, pce, NOW)
    pce.event(2, "rule_set.create", NOW + minutes(3))
    r = _collect_and_evaluate(ctx, pce, NOW + minutes(5))
    [a] = _alerts(ctx)
    assert r.fired == 1 and a["pack_key"] == "rule_ruleset_change" and a["subject_key"] == "rule_set.create"
    evidence = json.loads(a["evidence_json"])
    assert evidence["kind"] == "event" and evidence["segment"]["filter"]["event_types"] == ["rule_set.create"]
    with ctx.db() as conn:
        assert [d["status"] for d in store.deliveries(conn, [a["id"]])] == ["no_channel"]


def test_count_rule_window(ctx, pce):
    _collect_and_evaluate(ctx, pce, NOW)
    for i in range(4):
        pce.event(10 + i, "user.sign_in", NOW + minutes(1 + i), status="failure")
    _collect_and_evaluate(ctx, pce, NOW + minutes(5))
    assert _alerts(ctx) == []
    pce.event(20, "user.sign_in", NOW + minutes(6), status="failure")
    _collect_and_evaluate(ctx, pce, NOW + minutes(7))
    [a] = _alerts(ctx)
    assert a["pack_key"] == "rule_login_failed" and json.loads(a["facts_json"])["matches"] == 5


def test_cooldown_suppresses_and_counts(ctx, pce):
    _collect_and_evaluate(ctx, pce, NOW)
    pce.event(2, "rule_set.create", NOW + minutes(1))
    _collect_and_evaluate(ctx, pce, NOW + minutes(2))
    pce.event(3, "rule_set.update", NOW + minutes(3))  # same rule, no host: per event type
    pce.event(4, "rule_set.create", NOW + minutes(3))
    r = _collect_and_evaluate(ctx, pce, NOW + minutes(4))
    assert (r.fired, r.suppressed) == (1, 1) and len(_alerts(ctx)) == 2


def _with_host(ctx, ven_href, href="/orgs/1/workloads/w-9"):
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=href, hostname="h9", name=None, managed=1, enforcement_mode=None, visibility_level=None, os_id=None,
            ven_version=None, ven_href=ven_href, label_set=None, online=1, risk_exposure=None, risk_percent=None,
            risk_updated_at=None, fetched_at="x")])


def test_tamper_with_known_cause_grouped_not_sent(ctx, pce):
    from illumio_ops.services.analysis.tamper import add_annotation
    _collect_and_evaluate(ctx, pce, NOW)
    raw = json.loads(json.dumps(TAMPER[0]))
    raw["timestamp"] = _ts(NOW + minutes(1))
    _with_host(ctx, raw["created_by"]["ven"]["href"])
    add_annotation(ctx, host_href="/orgs/1/workloads/w-9", pattern=None, process=None, reason="NetBird", by="t")
    pce.items.append(raw)
    _collect_and_evaluate(ctx, pce, NOW + minutes(2))
    [a] = _alerts(ctx)
    params = json.loads(a["params_json"])
    assert a["grouped_annotation"] is not None and a["subject_key"] == "/orgs/1/workloads/w-9"
    assert params["pattern"] == "too_few" and "classification" in params
    with ctx.db() as conn:
        assert [d["status"] for d in store.deliveries(conn, [a["id"]])] == ["grouped"]


def test_late_event_marked_late(ctx, pce):
    _collect_and_evaluate(ctx, pce, NOW)
    pce.event(2, "rule_set.create", NOW - timedelta(hours=5))
    _collect_and_evaluate(ctx, pce, NOW + minutes(5))
    assert [a["late"] for a in _alerts(ctx)] == [1]


def test_event_batches_capped(ctx, pce, monkeypatch):
    _collect_and_evaluate(ctx, pce, NOW)
    for i in range(5):
        pce.event(30 + i, "rule_set.create", NOW + minutes(1))
    monkeypatch.setattr(evaluate, "EVENT_BATCH", 2)
    monkeypatch.setattr(evaluate, "EVENT_BATCHES", 1)
    assert _collect_and_evaluate(ctx, pce, NOW + minutes(2)).evaluated == 2
    assert evaluate_events(ctx, now=NOW + minutes(3)).evaluated == 2


def test_first_run_after_switch_starts_now(ctx, pce):
    from illumio_ops.services.collect.reset import reset_for_new_pce
    for i in range(3):
        pce.event(i, "user.login", NOW - minutes(1))
    _collect_and_evaluate(ctx, pce, NOW)  # PCE A: watermark at id 3
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update({"url": "https://b.example:8443"}))
    reset_for_new_pce(ctx, now=NOW)
    pce.items = []
    pce.event(50, "rule_set.create", NOW + minutes(1))  # PCE B's store starts at id 1
    r = _collect_and_evaluate(ctx, pce, NOW + minutes(2))
    assert r.evaluated == 0  # a first run for B, though id 1 is below A's watermark 3
    pce.event(51, "rule_set.create", NOW + minutes(3))
    assert _collect_and_evaluate(ctx, pce, NOW + minutes(4)).fired == 1


# ── flow growth ──

def _blocked(ctx, at, conns, *, src=1):
    raw = raw_flow(src, at - minutes(5), at)
    raw["policy_decision"] = "blocked"
    raw["num_connections"] = conns
    with ctx.flows().connect() as conn:
        upsert_flows(conn, [normalize_flow(raw)], origin=DataOrigin.INGEST, now=at, increments="cycle")
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, NOW - timedelta(days=1), at)
        ingest_state.mark_ok(conn, IngestSource.TRAFFIC, at, watermark=at, rows=1)


def test_traffic_rule_fires_on_growth(ctx):
    evaluate_traffic(ctx, now=NOW)  # first run
    _blocked(ctx, NOW + minutes(5), 30)
    r = evaluate_traffic(ctx, now=NOW + minutes(5))
    [a] = _alerts(ctx)
    assert r.fired == 1 and a["pack_key"] == "rule_high_blocked" and json.loads(a["facts_json"])["connections"] == 30
    assert json.loads(a["evidence_json"])["kind"] == "flow"
    _blocked(ctx, NOW + minutes(15), 40)  # grew by 10 only
    assert evaluate_traffic(ctx, now=NOW + minutes(15)).fired == 0


def test_traffic_rule_incomplete_with_gap(ctx):
    evaluate_traffic(ctx, now=NOW)
    _blocked(ctx, NOW + minutes(5), 30)
    with ctx.flows().connect() as conn:
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW, NOW + minutes(2), "failed", "x", NOW)
    r = evaluate_traffic(ctx, now=NOW + minutes(5))
    pack = next(rid for rid, st in r.statuses.items() if st == "incomplete")
    [a] = _alerts(ctx)
    assert a["rule_id"] == pack and json.loads(a["confidence_json"])["incomplete_gaps"]


def test_events_only_mode_collection_off(tmp_path):
    ctx = configured_ctx(tmp_path, mode="events_only")
    r = evaluate_traffic(ctx, now=NOW)
    assert r.statuses and set(r.statuses.values()) == {"collection_off"}


def test_volume_no_byte_data_status(ctx):
    rule = {"id": "c" * 32, "name": "big", "pack_key": None, "enabled": True, "notify": True, "severity": "medium",
            "cooldown_minutes": 0, "throttle": None, "type": "volume", "condition": {}, "threshold_mb": 0.001,
            "window_minutes": 10}
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["alerts"]["rules"].append(rule))
    evaluate_traffic(ctx, now=NOW)
    _blocked(ctx, NOW + minutes(5), 30)
    assert evaluate_traffic(ctx, now=NOW + minutes(5)).statuses["c" * 32] == "no_data"


# ── lateral ──

def _detect(ctx, severity="medium", fp="fanout|h1", at=NOW):
    from illumio_ops.domain.filter import FilterSpec
    from illumio_ops.domain.segment import FlowSegment
    from illumio_ops.domain.values import SegmentView
    seg = FlowSegment(filter=FilterSpec(start=at - minutes(60), end=at), view=SegmentView.DETAIL, limit=200)
    with ctx.flows().connect() as conn:
        analysis.upsert_detections(conn, [DetectionWrite(
            detector="fanout", fingerprint=fp, subject_key="/orgs/1/workloads/h1", severity=severity,
            first_seen=at - minutes(30), last_seen=at, critical_asset=False,
            summary_json=json.dumps({"targets": 12, "window_minutes": 60}), segment_json=seg.model_dump_json(),
            confidence_json="{}")], dedup={"fanout": timedelta(hours=1)}, late=False, at=at)


def test_lateral_alert_on_new_detection(ctx):
    evaluate_lateral(ctx, now=NOW)
    _detect(ctx, at=NOW + minutes(1))
    assert evaluate_lateral(ctx, now=NOW + minutes(2)).fired == 1
    [a] = _alerts(ctx)
    assert a["message_key"] == "focus_title_fanout" and a["subject_key"] == "fanout|h1"


def test_lateral_realert_on_severity_rise_only(ctx):
    evaluate_lateral(ctx, now=NOW)
    _detect(ctx, at=NOW + minutes(1))
    evaluate_lateral(ctx, now=NOW + minutes(2))
    _detect(ctx, at=NOW + minutes(3))  # a repeat, same severity
    assert evaluate_lateral(ctx, now=NOW + minutes(4)).fired == 0
    _detect(ctx, severity="high", at=NOW + minutes(5))
    assert evaluate_lateral(ctx, now=NOW + minutes(6)).fired == 1
    assert [a["severity"] for a in _alerts(ctx)] == ["high", "medium"]


def test_lateral_notify_false_recorded(ctx):
    def quiet(d):
        for r in d["alerts"]["rules"]:
            if r["type"] == "lateral":
                r["notify"] = False
    ctx.settings.update(ctx.settings.current().revision, quiet)
    evaluate_lateral(ctx, now=NOW)
    _detect(ctx, at=NOW + minutes(1))
    evaluate_lateral(ctx, now=NOW + minutes(2))
    [a] = _alerts(ctx)
    with ctx.db() as conn:
        assert [d["status"] for d in store.deliveries(conn, [a["id"]])] == ["not_notified"]


# ── system ──

def test_collection_failing_after_three(ctx):
    evaluate_system(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        for _ in range(3):
            ingest_state.mark_failed(conn, IngestSource.TRAFFIC, NOW, "timeout")
    evaluate_system(ctx, now=NOW + minutes(1))
    assert [a["subject_key"] for a in _alerts(ctx)] == ["collection_failing:traffic"]


def test_data_loss_new_gap_once(ctx):
    evaluate_system(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        ingest_state.record_gap(conn, IngestSource.EVENTS, NOW - minutes(30), NOW, "truncated", "cap", NOW)
    assert evaluate_system(ctx, now=NOW + minutes(1)).fired == 1
    assert evaluate_system(ctx, now=NOW + timedelta(hours=2)).fired == 0


def test_probe_only_run_does_not_skip_gaps(ctx):
    from illumio_ops.domain.values import SystemCheck
    evaluate_system(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        ingest_state.record_gap(conn, IngestSource.EVENTS, NOW - minutes(30), NOW, "failed", "x", NOW)
    evaluate_system(ctx, now=NOW + minutes(1), checks={SystemCheck.PCE_HEALTH})
    assert evaluate_system(ctx, now=NOW + minutes(2)).fired == 1


def test_job_failing_uses_consecutive(ctx):
    from illumio_ops.jobs.health import record_finish, record_start
    evaluate_system(ctx, now=NOW)
    with ctx.db() as conn:
        record_start(conn, "collect_traffic", NOW)
        for err in ("a", "b", None, "c", "d"):
            record_finish(conn, "collect_traffic", NOW, err)
    assert evaluate_system(ctx, now=NOW + minutes(1)).fired == 0  # 2 in a row after a success
    with ctx.db() as conn:
        record_finish(conn, "collect_traffic", NOW, "e")
    assert evaluate_system(ctx, now=NOW + minutes(2)).fired == 1


def test_pce_health_from_probe(ctx, monkeypatch):
    from datetime import UTC, datetime

    from illumio_ops.domain.values import ProbeName
    from illumio_ops.pce.health import ProbeResult
    from illumio_ops.services import pce_health
    now = datetime.now(UTC)
    monkeypatch.setattr(pce_health, "latest", lambda c: (now, [ProbeResult(ProbeName.HEALTH, False, 503, "x", None)]))
    evaluate_system(ctx, now=now)
    r = evaluate_system(ctx, now=now)
    assert r.fired == 0  # within the cooldown of the first run's alert
    rows = [x for x in _alerts(ctx) if x["subject_key"] == "pce_health"]
    assert len(rows) == 1 and json.loads(rows[0]["params_json"])["failures"] == ["health"]


def test_lateral_batches_do_not_skip_detections_sharing_an_update_time(ctx, monkeypatch):
    # One detection run stamps every row it writes with the same updated_at (44k rows at scale, P3 Task 15):
    # a watermark on updated_at alone skipped the rest of a batch cut inside that stamp.
    evaluate_lateral(ctx, now=NOW)
    for i in range(3):
        _detect(ctx, fp=f"fanout|h{i}", at=NOW + minutes(1))
    monkeypatch.setattr(evaluate, "DETECTION_BATCH", 1)
    assert evaluate_lateral(ctx, now=NOW + minutes(2)).fired == 3
    assert evaluate_lateral(ctx, now=NOW + minutes(3)).fired == 0
