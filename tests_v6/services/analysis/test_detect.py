"""run_detection: after each traffic cycle (and late, after the daily re-read), with a watermark that only
moves once the detections are stored."""
import json
from datetime import timedelta

import pytest

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin, IngestSource
from illumio_ops.services.analysis import detect
from illumio_ops.services.analysis.detect import run_detection
from illumio_ops.store.flowdb import analysis, ingest_state
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.services.collect.conftest import NOW, configured_ctx, minutes, raw_flow


def fanout(n=10, *, minutes_ago=5, origin=DataOrigin.INGEST):
    recs = []
    for i in range(n):
        raw = raw_flow(1, NOW - minutes(minutes_ago + 1), NOW - minutes(minutes_ago))
        raw["dst"]["ip"] = f"10.0.2.{i}"
        raw["dst"]["workload"]["href"] = f"/orgs/1/workloads/t{i}"
        recs.append(normalize_flow(raw))
    return recs, origin


def _collected(ctx, until=NOW):
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, NOW - timedelta(days=2), until)
        ingest_state.mark_ok(conn, IngestSource.TRAFFIC, until, watermark=until, rows=0)


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path)
    recs, origin = fanout()
    with c.flows().connect() as conn:
        upsert_flows(conn, recs, origin=origin, now=NOW)
    _collected(c)
    return c


def _detections(ctx):
    with ctx.flows().connect() as conn:
        return analysis.detections_since(conn, NOW - timedelta(days=30), limit=100)


def _run_row(ctx):
    with ctx.flows().connect() as conn:
        return analysis.get_run(conn, "detect")


def test_detection_watermark_advances_only_after_write(ctx, monkeypatch):
    r = run_detection(ctx, now=NOW)
    assert r.new == 1 and r.window[1] == NOW and _run_row(ctx)["watermark"].startswith("2026-10-24T12:00")
    _collected(ctx, until=NOW + minutes(10))

    def broken(*a, **kw):
        raise RuntimeError("disk full")
    monkeypatch.setattr(detect.analysis, "upsert_detections", broken)
    with pytest.raises(RuntimeError):
        run_detection(ctx, now=NOW + minutes(10))
    assert _run_row(ctx)["watermark"].startswith("2026-10-24T12:00")


def test_run_records_last_ok_and_last_error(ctx, monkeypatch):
    # The settings page shows when detection last ran from last_ok_at (Task 15 acceptance found it never set).
    run_detection(ctx, now=NOW)
    row = _run_row(ctx)
    assert row["last_ok_at"] is not None and row["last_ok_at"].startswith("2026-10-24T12:00") and row["last_error"] is None
    _collected(ctx, until=NOW + minutes(10))

    def broken(*a, **kw):
        raise RuntimeError("disk full")
    monkeypatch.setattr(detect.analysis, "upsert_detections", broken)
    with pytest.raises(RuntimeError):
        run_detection(ctx, now=NOW + minutes(10))
    row = _run_row(ctx)
    assert "disk full" in row["last_error"] and row["last_ok_at"].startswith("2026-10-24T12:00")


def test_overlap_reevaluation_does_not_duplicate(ctx):
    assert run_detection(ctx, now=NOW).new == 1
    _collected(ctx, until=NOW + minutes(10))
    again = run_detection(ctx, now=NOW + minutes(10))
    assert (again.new, again.updated) == (0, 1) and len(_detections(ctx)) == 1
    assert run_detection(ctx, now=NOW + minutes(10)).window is None  # nothing collected since


def test_late_reread_pass_marks_late(ctx):
    day = NOW.replace(hour=0)
    r = run_detection(ctx, now=NOW, window=(day, day + timedelta(days=1)), late=True)
    assert r.late and r.new == 1 and _detections(ctx)[0]["late"] == 1
    assert _run_row(ctx)["watermark"] is None  # a late pass never moves the live watermark


def test_lightweight_mode_collection_off(tmp_path):
    c = configured_ctx(tmp_path, mode="lightweight")
    r = run_detection(c, now=NOW)
    assert r.new == 0 and {s["state"] for s in r.statuses} == {"collection_off"}
    assert json.loads(_run_row(c)["status_json"])["fanout"]["state"] == "collection_off"


def test_gap_in_window_marks_incomplete(ctx):
    with ctx.flows().connect() as conn:
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW - minutes(20), NOW - minutes(15), "failed", "x", NOW)
    r = run_detection(ctx, now=NOW)
    assert [g[2] for g in r.gaps] == ["ingest_failed"]
    fan = next(s for s in r.statuses if s["detector"] == "fanout")
    assert fan["state"] == "incomplete" and fan["params"]["incomplete"] is True
    stored = json.loads(_detections(ctx)[0]["confidence_json"])
    assert stored["incomplete_gaps"]


def test_pce_switch_during_run_writes_nothing(ctx, monkeypatch):
    real = detect.run_detectors

    def switch_meanwhile(inp):
        ctx.flows().reset()
        return real(inp)
    monkeypatch.setattr(detect, "run_detectors", switch_meanwhile)
    r = run_detection(ctx, now=NOW)
    assert r.new == 0 and r.window is None
    assert _detections(ctx) == [] and _run_row(ctx) is None


def test_precursor_event_raises_the_detection(ctx):
    from illumio_ops.domain.events import normalize_event
    from illumio_ops.store.flowdb import workloads
    from illumio_ops.store.flowdb.events import upsert_events
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href="/orgs/1/workloads/src-1", hostname="s1", name=None, managed=1, enforcement_mode=None,
            visibility_level=None, os_id=None, ven_version=None, ven_href="/v/1", label_set=None, online=1,
            risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x")])
        upsert_events(conn, [normalize_event({
            "href": "/orgs/1/events/t1", "event_type": "agent.tampering", "severity": "info",
            "timestamp": (NOW - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "created_by": {"ven": {"href": "/v/1", "hostname": "s1"}},
            "notifications": [{"info": {"event_classification": "confirmed"}}]})], origin=DataOrigin.INGEST, now=NOW)
    run_detection(ctx, now=NOW)
    [row] = _detections(ctx)
    assert row["severity"] == "high" and json.loads(row["summary_json"])["precursors"][0]["kind"] == "tamper"


def test_blocked_history_damps_a_usual_burst(tmp_path):
    from illumio_ops.domain.values import DataOrigin as Origin
    c = configured_ctx(tmp_path)
    recs = []
    for day_ago, n in ((3, 4), (0, 6)):  # 4 blocked targets three days ago, 6 now: 6 < 3 x 4
        for i in range(n):
            raw = raw_flow(2, NOW - timedelta(days=day_ago, minutes=6), NOW - timedelta(days=day_ago, minutes=5),
                           port=8000 + i)
            raw["dst"]["ip"] = f"10.0.4.{i}"
            raw["dst"]["workload"]["href"] = f"/orgs/1/workloads/b{i}"
            raw["policy_decision"] = "blocked"
            recs.append(normalize_flow(raw))
    with c.flows().connect() as conn:
        upsert_flows(conn, recs, origin=Origin.INGEST, now=NOW)
    _collected(c)
    assert run_detection(c, now=NOW).new == 0


def test_all_stale_admin_groups_disable_the_detector(ctx):
    # Final review #7 (plan Review Focus 4): admin groups whose labels are all gone are not "configured".
    ctx.settings.update(ctx.settings.current().revision,
                        lambda d: d["lateral"].update({"admin_groups": [{"key": "role", "value": "DeletedJump"}]}))
    r = run_detection(ctx, now=NOW)
    nag = next(s for s in r.statuses if s["detector"] == "non_admin_group")
    assert (nag["state"], nag["reason_key"]) == ("disabled", "detector_admin_groups_stale")
    assert not [d for d in _detections(ctx) if d["detector"] == "non_admin_group"]


def test_gap_in_lookback_marks_incomplete(ctx):
    # Final review #9: the detectors look back a window before the evaluated range; a gap there counts.
    with ctx.flows().connect() as conn:
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW - minutes(120), NOW - minutes(110), "failed", "x", NOW)
    r = run_detection(ctx, now=NOW)
    assert r.window[0] == NOW - minutes(90) and [g[2] for g in r.gaps] == ["ingest_failed"]
    assert next(s for s in r.statuses if s["detector"] == "fanout")["state"] == "incomplete"
