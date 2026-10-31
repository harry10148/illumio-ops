"""Collection status: per-source health, open gaps, capacity, visibility and capabilities."""
from datetime import timedelta

import pytest

from illumio_ops.domain.values import IngestSource
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.pce.client import PceBudgetExhausted, PceTransportError
from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.services.collect.status import collection_status, error_reason
from illumio_ops.services.collect.traffic import run_traffic_cycle
from illumio_ops.store.flowdb import ingest_state

from .conftest import NOW, configured_ctx, minutes


def _source(status, name):
    return next(s for s in status.sources if s.source == name)


def test_status_marks_stale_after_two_intervals(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)
    fresh = _source(collection_status(ctx, now=NOW + minutes(19)), "traffic")
    assert fresh.stale is False and fresh.lag_seconds == 19 * 60 and fresh.interval_seconds == 600
    late = _source(collection_status(ctx, now=NOW + minutes(21)), "traffic")
    assert late.stale is True


def test_never_run_source_is_not_stale(tmp_path):
    s = _source(collection_status(configured_ctx(tmp_path), now=NOW), "events")
    assert s.stale is False and s.last_ok_at is None and s.last_started_at is None


def test_failing_source_reports_error_and_failures(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    fake_traffic.answer = lambda s, e, m: (_ for _ in ()).throw(PceQueryError("timeout"))
    run_traffic_cycle(ctx, now=NOW)
    run_traffic_cycle(ctx, now=NOW + minutes(10))
    s = _source(collection_status(ctx, now=NOW + minutes(11)), "traffic")
    assert s.consecutive_failures == 2 and "timeout" in s.last_error


def test_status_reports_truncated_windows(tmp_path):
    ctx = configured_ctx(tmp_path)
    with ctx.flows().connect() as conn:
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW - minutes(10), NOW - minutes(9), "truncated", "cap", NOW)
        ingest_state.record_gap(conn, IngestSource.EVENTS, NOW - timedelta(days=3), NOW - timedelta(days=3) + minutes(1),
                                "failed", "old", NOW - timedelta(days=3))
    st = collection_status(ctx, now=NOW + minutes(1))
    assert [(g.source, g.kind) for g in st.open_gaps] == [("traffic", "truncated")]  # last 24 hours only
    assert st.open_gap_counts == {"truncated": 1, "failed": 1}


def test_status_disk_low(tmp_path, monkeypatch):
    import shutil
    from collections import namedtuple
    ctx = configured_ctx(tmp_path, disk_free_warn_gb=10)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: usage(100 * 1024**3, 95 * 1024**3, 5 * 1024**3))
    st = collection_status(ctx, now=NOW)
    assert st.disk_low is True and st.disk_free_bytes == 5 * 1024**3 and st.db_bytes > 0


def test_status_binding_shows_host_only(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)
    st = collection_status(ctx, now=NOW)
    assert st.binding_host == "pce.example.com" and st.pce_configured and st.enabled


def _detail(exc):
    return f"{type(exc).__name__}: {exc}"  # what cycle.fail records


@pytest.mark.parametrize(("detail", "reason"), [
    (_detail(PceQueryError("submit", 503)), "pce_error"),
    (_detail(PceCollectionIncomplete("/workloads", 0, "HTTP 502")), "pce_error"),
    (_detail(PceQueryError("timeout")), "timeout"),
    (_detail(PceCollectionIncomplete("/workloads", 10, "async collection did not finish in time")), "timeout"),
    (_detail(PceTransportError("/x", "timeout")), "timeout"),
    (_detail(PceTransportError("/x", "refused")), "unreachable"),
    (_detail(PceTransportError("/x", "dns")), "unreachable"),
    (_detail(PceTransportError("/x", "tls")), "tls"),
    (_detail(PceTransportError("/x", "ca_bundle")), "tls"),
    (_detail(PceQueryError("submit", 401)), "auth"),
    (_detail(PceQueryError("poll", 403)), "auth"),
    (_detail(PceBudgetExhausted()), "rate_limit"),
    ("binding: the flow database belongs to another PCE", "another_pce"),
    (_detail(ValueError("boom")), "other"),
    (None, None),
])
def test_error_reason_in_words(detail, reason):
    assert error_reason(detail) == reason


def test_failing_source_carries_its_reason(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    fake_traffic.answer = lambda s, e, m: (_ for _ in ()).throw(PceQueryError("submit", 503))
    run_traffic_cycle(ctx, now=NOW)
    assert _source(collection_status(ctx, now=NOW + minutes(1)), "traffic").last_error_reason == "pce_error"


def test_ok_source_has_no_error_reason(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)
    assert _source(collection_status(ctx, now=NOW), "traffic").last_error_reason is None


def test_overlapping_gaps_are_listed_once(tmp_path):
    """Retries of a failed cold start record windows that share a start; the page lists one."""
    ctx = configured_ctx(tmp_path)
    with ctx.flows().connect() as conn:
        for end in (NOW, NOW + minutes(10)):
            ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW - timedelta(hours=24), end, "failed", "x", end)
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW + minutes(10), NOW + minutes(20), "failed", "y",
                                NOW + minutes(20))  # touching: merged too
        ingest_state.record_gap(conn, IngestSource.EVENTS, NOW - minutes(5), NOW, "failed", "z", NOW)
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW - minutes(5), NOW, "truncated", "cap", NOW)
    st = collection_status(ctx, now=NOW + minutes(21))
    assert sorted((g.source, g.kind, g.window_start, g.window_end) for g in st.open_gaps) == [
        ("events", "failed", NOW - minutes(5), NOW),
        ("traffic", "failed", NOW - timedelta(hours=24), NOW + minutes(20)),
        ("traffic", "truncated", NOW - minutes(5), NOW),
    ]
    assert st.open_gap_counts == {"failed": 4, "truncated": 1}
