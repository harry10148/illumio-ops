"""Traffic collector: windows, bisection on the cap, gaps, watermark and binding rules."""
from datetime import timedelta

from illumio_ops.domain.values import IngestSource
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.services.collect.traffic import run_traffic_cycle
from illumio_ops.store.flowdb import binding, ingest_state

from .conftest import NOW, configured_ctx, minutes, raw_flow


def _state(ctx):
    with ctx.flows().connect() as conn:
        return ingest_state.get(conn, IngestSource.TRAFFIC), ingest_state.open_gaps(conn)


def _count(ctx, sql="SELECT count(*) FROM flows"):
    with ctx.flows().connect() as conn:
        return conn.execute(sql).fetchone()[0]


def test_traffic_cycle_writes_and_advances_watermark(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    fake_traffic.answer = lambda s, e, m: [raw_flow(i, e - minutes(5), e - minutes(1)) for i in range(3)] if e == NOW else []
    result = run_traffic_cycle(ctx, now=NOW)
    assert (result.rows, result.gaps) == (3, 0)
    state, gaps = _state(ctx)
    assert state.watermark == NOW and state.last_ok_at == NOW and state.consecutive_failures == 0
    assert gaps == [] and _count(ctx) == 3
    assert _count(ctx, "SELECT count(*) FROM flow_rollup_daily") >= 1
    assert fake_traffic.calls[0][0] == "2026-10-23T12:00:00Z"  # cold start: 24 hours back


def test_next_cycle_overlaps_previous_window_by_30_minutes(tmp_path, fake_traffic):
    # Records reach the PCE late: on lab 32% more than 10 min after first_detected, max ≈ 16–18 min
    # (P2 Task 15 probe). A record arriving d after its last_detected is caught in every cycle phase
    # only if d <= overlap, whatever the interval.
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)
    run_traffic_cycle(ctx, now=NOW + minutes(10))
    assert fake_traffic.calls[-1] == ("2026-10-24T11:30:00Z", "2026-10-24T12:10:00Z")


def test_failed_window_keeps_watermark_and_records_gap(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)
    def boom(s, e, m):
        raise PceQueryError("failed", detail="failed")
    fake_traffic.answer = boom
    result = run_traffic_cycle(ctx, now=NOW + minutes(10))
    assert result.gaps == 1
    state, gaps = _state(ctx)
    assert state.watermark == NOW and state.consecutive_failures == 1 and "failed" in state.last_error
    [gap] = gaps
    assert gap.kind == "failed" and gap.window_end == NOW + minutes(10)


def test_repeat_cycle_resolves_failed_gap(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)
    fake_traffic.answer = lambda s, e, m: (_ for _ in ()).throw(PceQueryError("timeout"))
    run_traffic_cycle(ctx, now=NOW + minutes(10))
    fake_traffic.answer = lambda s, e, m: []
    run_traffic_cycle(ctx, now=NOW + minutes(20))
    state, gaps = _state(ctx)
    assert gaps == [] and state.watermark == NOW + minutes(20) and state.consecutive_failures == 0


def test_cap_bisects_until_under_cap(tmp_path, fake_traffic, monkeypatch):
    from illumio_ops.services.collect import traffic
    monkeypatch.setattr(traffic, "MAX_RESULTS", 4)
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)
    # 6 flows spread over the next window [NOW-30m, NOW+10m]: the whole window caps, halves do not.
    flows = [raw_flow(i, NOW - minutes(28 - 6 * i), NOW - minutes(27 - 6 * i)) for i in range(6)]
    fake_traffic.answer = lambda s, e, m: [f for f in flows
                                           if s.strftime("%Y-%m-%dT%H:%M:%SZ") <= f["timestamp_range"]["first_detected"]
                                           < e.strftime("%Y-%m-%dT%H:%M:%SZ")][:m]
    result = run_traffic_cycle(ctx, now=NOW + minutes(10))
    assert result.windows == 3 and result.gaps == 0 and _count(ctx) == 6


def test_cap_at_bisect_floor_records_truncated_gap(tmp_path, fake_traffic, monkeypatch):
    from illumio_ops.services.collect import traffic
    monkeypatch.setattr(traffic, "MAX_RESULTS", 2)
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)
    burst = [raw_flow(i, NOW + minutes(9), NOW + minutes(9)) for i in range(5)]
    fake_traffic.answer = lambda s, e, m: burst[:m]  # every window, however small, is full
    result = run_traffic_cycle(ctx, now=NOW + minutes(10))
    assert result.gaps >= 1
    state, gaps = _state(ctx)
    assert {g.kind for g in gaps} == {"truncated"}
    assert all(g.window_end - g.window_start <= timedelta(seconds=60) for g in gaps)
    assert state.watermark == NOW + minutes(10)  # what we could read is in; the gap says what is missing
    assert _count(ctx) == 2


def test_disabled_collection_is_noop_not_failure(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path, enabled=False)
    result = run_traffic_cycle(ctx, now=NOW)
    assert (result.rows, result.windows, result.gaps) == (0, 0, 0) and fake_traffic.calls == []
    assert _state(ctx)[0] is None


def test_unconfigured_pce_is_noop(tmp_path, fake_traffic):
    from tests_v6.web.conftest import make_ctx
    result = run_traffic_cycle(make_ctx(tmp_path), now=NOW)
    assert result.windows == 0 and fake_traffic.calls == []


def test_collector_refuses_mismatched_binding(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    with ctx.flows().connect() as conn:
        binding.bind(conn, "https://other-pce.example.com:8443", "7", NOW)
    fake_traffic.answer = lambda s, e, m: [raw_flow(1, e - minutes(2), e - minutes(1))]
    run_traffic_cycle(ctx, now=NOW)
    state, _ = _state(ctx)
    assert _count(ctx) == 0 and "binding" in state.last_error and state.watermark is None


def test_first_cycle_binds_the_database(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        b = binding.current(conn)
    assert (b.pce_url, b.org_id) == ("https://pce.example.com:8443", "1")


def test_malformed_records_are_skipped_not_fatal(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    good = raw_flow(1, NOW - minutes(5), NOW - minutes(4))
    fake_traffic.answer = lambda s, e, m: [good, {"src": {"ip": "1.1.1.1"}}] if e == NOW else []
    result = run_traffic_cycle(ctx, now=NOW)
    assert result.rows == 1 and result.skipped == 1 and _count(ctx) == 1


def test_a_long_window_is_read_an_hour_at_a_time(tmp_path, fake_traffic):
    # A cold start or a catch-up after an outage reads a day: at 1,000 workloads ~1M records, ~6 GB
    # once parsed (P2 Task 15), so one query covers at most an hour and is written before the next.
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)
    assert len(fake_traffic.calls) == 24
    assert fake_traffic.calls[0] == ("2026-10-23T12:00:00Z", "2026-10-23T13:00:00Z")
    assert fake_traffic.calls[-1][1] == "2026-10-24T12:00:00Z"
    state, gaps = _state(ctx)
    assert state.watermark == NOW and gaps == []


def test_a_failure_mid_catch_up_keeps_the_hours_already_read(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    stop = NOW - timedelta(hours=19)

    def answer(s, e, m):
        if s >= stop:
            raise PceQueryError("timeout")
        return [raw_flow(s.hour, s + minutes(1), s + minutes(2))]
    fake_traffic.answer = answer
    run_traffic_cycle(ctx, now=NOW)
    state, gaps = _state(ctx)
    assert _count(ctx) == 5 and state.watermark == stop
    [gap] = gaps
    assert (gap.window_start, gap.window_end, gap.kind) == (stop, NOW, "failed")
    fake_traffic.answer = lambda s, e, m: []
    fake_traffic.calls.clear()
    run_traffic_cycle(ctx, now=NOW + minutes(10))
    assert fake_traffic.calls[0][0] == "2026-10-23T16:30:00Z"  # from the watermark, overlap included
    state, gaps = _state(ctx)
    assert state.watermark == NOW + minutes(10) and gaps == []


def test_a_gap_left_by_an_earlier_partial_cycle_is_resolved_once_covered(tmp_path, fake_traffic):
    # Two cycles each read part of a catch-up and failed; the third finished it. The first gap starts
    # before the third cycle's window, so only the coverage can tell it has been read.
    ctx = configured_ctx(tmp_path)
    stops = iter([NOW - timedelta(hours=22), NOW - timedelta(hours=19)])
    stop = next(stops)

    def answer(s, e, m):
        if s >= stop:
            raise PceQueryError("timeout")
        return []
    fake_traffic.answer = answer
    run_traffic_cycle(ctx, now=NOW)
    stop = next(stops)
    run_traffic_cycle(ctx, now=NOW + minutes(10))
    assert len(_state(ctx)[1]) == 2
    fake_traffic.answer = lambda s, e, m: []
    run_traffic_cycle(ctx, now=NOW + minutes(20))
    state, gaps = _state(ctx)
    assert gaps == [] and state.watermark == NOW + minutes(20)
