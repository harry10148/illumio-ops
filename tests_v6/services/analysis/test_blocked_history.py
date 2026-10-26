"""The 7-day blocked history from an hourly cache plus a live tail (P3 Task 15: 40 s of an 85 s detection run)."""
from datetime import timedelta

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin, IngestSource
from illumio_ops.services.analysis import blocked_history, detect
from illumio_ops.services.analysis.blocked_history import (
    build_blocked_history,
    cached_history,
    history_for,
)
from illumio_ops.services.analysis.detect import run_detection
from illumio_ops.store.flowdb import analysis, ingest_state
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.services.collect.conftest import NOW, configured_ctx, raw_flow

SRC = "10.0.1.2"  # raw_flow(2, ...) — its key is the workload href
WINDOW = timedelta(minutes=60)


def _blocked(ctx, *times_and_targets):
    """(minutes before NOW, target number) pairs; each a blocked flow from source 2."""
    recs = []
    for minutes_ago, t in times_and_targets:
        last = NOW - timedelta(minutes=minutes_ago)
        raw = raw_flow(2, last - timedelta(minutes=1), last, port=9000 + t)
        raw["dst"]["ip"] = f"10.0.5.{t}"
        raw["dst"]["workload"]["href"] = f"/orgs/1/workloads/x{t}"
        raw["policy_decision"] = "blocked"
        recs.append(normalize_flow(raw))
    with ctx.flows().connect() as conn:
        upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW)


def _watermark(ctx, at):
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, NOW - timedelta(days=9), at)
        ingest_state.mark_ok(conn, IngestSource.TRAFFIC, at, watermark=at, rows=0)


def _src_key(ctx):
    return "/orgs/1/workloads/src-2"


def _data(ctx):
    # Two days ago: 3 targets in one hour. Around the cache boundary (NOW - 120 min): 2 targets 10 minutes
    # before it and 3 within 15 minutes after it — 5 in one window that straddles the boundary.
    _blocked(ctx, (2 * 1440, 1), (2 * 1440 + 5, 2), (2 * 1440 + 10, 3),
             (130, 10), (128, 11), (115, 12), (110, 13), (106, 14))


def test_cache_matches_live_computation(tmp_path):
    ctx = configured_ctx(tmp_path)
    _data(ctx)
    lo = NOW - timedelta(minutes=30)
    _watermark(ctx, lo)
    live, mode = history_for(ctx, [_src_key(ctx)], window=WINDOW, lo=lo, now=NOW)
    assert mode == "live" and live == {_src_key(ctx): 5}
    _watermark(ctx, NOW - timedelta(minutes=120))
    build_blocked_history(ctx, NOW - timedelta(minutes=110))
    cached, mode = history_for(ctx, [_src_key(ctx)], window=WINDOW, lo=lo, now=NOW)
    assert mode == "cached" and cached == live


def test_stale_cache_falls_back_to_live(tmp_path):
    ctx = configured_ctx(tmp_path)
    _data(ctx)
    _watermark(ctx, NOW - timedelta(minutes=120))
    build_blocked_history(ctx, NOW - timedelta(hours=3))
    assert cached_history(ctx, window=WINDOW, before=NOW - timedelta(minutes=30), now=NOW) is None
    _, mode = history_for(ctx, [_src_key(ctx)], window=WINDOW, lo=NOW - timedelta(minutes=30), now=NOW)
    assert mode == "live"


def test_window_change_invalidates_cache(tmp_path):
    ctx = configured_ctx(tmp_path)
    _data(ctx)
    _watermark(ctx, NOW - timedelta(minutes=120))
    build_blocked_history(ctx, NOW - timedelta(minutes=110))
    assert cached_history(ctx, window=WINDOW, before=NOW, now=NOW) is not None
    assert cached_history(ctx, window=timedelta(minutes=30), before=NOW, now=NOW) is None


def test_cache_newer_than_the_window_is_not_used(tmp_path):
    # A late pass over an old day: history must end where that window begins, which the cache is past.
    ctx = configured_ctx(tmp_path)
    _data(ctx)
    _watermark(ctx, NOW)
    build_blocked_history(ctx, NOW)
    assert cached_history(ctx, window=WINDOW, before=NOW - timedelta(days=1), now=NOW) is None


def test_detection_reads_only_tail_with_cache(tmp_path, monkeypatch):
    ctx = configured_ctx(tmp_path)
    _data(ctx)
    through = NOW - timedelta(minutes=120)
    _watermark(ctx, through)
    build_blocked_history(ctx, NOW - timedelta(minutes=110))
    starts = []
    real = blocked_history.observations

    def spy(c, spec, **kw):
        starts.append(spec.start)
        return real(c, spec, **kw)
    monkeypatch.setattr(blocked_history, "observations", spy)
    history_for(ctx, [_src_key(ctx)], window=WINDOW, lo=NOW - timedelta(minutes=30), now=NOW)
    assert starts == [through - WINDOW]


def test_detection_status_says_where_history_came_from(tmp_path):
    ctx = configured_ctx(tmp_path)
    # Six targets blocked now (over the default threshold of 5), nothing before: the history is read.
    _blocked(ctx, *((5, t) for t in range(20, 26)))
    _watermark(ctx, NOW)
    r = run_detection(ctx, now=NOW)
    surge = next(s for s in r.statuses if s["detector"] == "blocked_surge")
    assert surge["params"]["history"] == "live"
    with ctx.flows().connect() as conn:
        assert analysis.read_result(conn, blocked_history.KIND) is None
    assert detect.HISTORY == timedelta(days=7)
