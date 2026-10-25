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


def test_events_only_mode_collection_off(tmp_path):
    c = configured_ctx(tmp_path, mode="events_only")
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
