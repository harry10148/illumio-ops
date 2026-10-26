"""FlowSource: the one way to read flows, saying where every part of the answer came from."""
from datetime import timedelta

import pytest

from illumio_ops.domain.filter import EndpointFilter, FilterSpec, LabelCond
from illumio_ops.domain.values import IngestSource
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.services.collect.traffic import run_traffic_cycle
from illumio_ops.services.flowsource import query_flows
from illumio_ops.store.flowdb import ingest_state
from tests_v6.services.collect.conftest import (
    NOW,
    FakeTraffic,
    configured_ctx,
    minutes,
    raw_flow,
)


@pytest.fixture
def fake_traffic(monkeypatch):
    """One fake PCE for both the collector and FlowSource's gap filling."""
    from illumio_ops.services import flowsource
    from illumio_ops.services.collect import traffic
    fake = FakeTraffic()
    monkeypatch.setattr(traffic, "run_traffic_query", fake)
    monkeypatch.setattr(flowsource, "run_traffic_query", fake)
    return fake


@pytest.fixture
def collected(tmp_path, fake_traffic):
    """Store covers [NOW-24h, NOW] with three flows; the PCE fake answers later queries."""
    ctx = configured_ctx(tmp_path)
    fake_traffic.answer = lambda s, e, m: [raw_flow(i, NOW - minutes(30 + i), NOW - minutes(20 + i), user=f"LAB\\u{i}")
                                           for i in range(3)]
    run_traffic_cycle(ctx, now=NOW)
    fake_traffic.calls.clear()
    fake_traffic.answer = lambda s, e, m: []
    return ctx


def _spec(start, end, **kw):
    return FilterSpec(start=start, end=end, **kw)


def test_store_only_window_source_store(collected, fake_traffic):
    q = query_flows(collected, _spec(NOW - minutes(60), NOW), limit=100, order="last_detected_desc")
    assert q.coverage.source == "store" and len(q.rows) == 3 and q.coverage.gaps == []
    assert fake_traffic.calls == [] and q.limit_hit is False
    assert q.rows[0].last_detected >= q.rows[-1].last_detected
    assert q.rows[0].src_labels == {"env": "Dev"}


def test_filter_is_applied_in_store(collected):
    q = query_flows(collected, _spec(NOW - minutes(60), NOW, initiator_user="u1"), limit=100,
                    order="last_detected_desc")
    assert [r.initiator_user for r in q.rows] == ["LAB\\u1"]
    q = query_flows(collected, _spec(NOW - minutes(60), NOW,
                                     src=EndpointFilter(labels=(LabelCond(key="env", values=("Dev",)),))),
                    limit=100, order="last_detected_desc")
    assert len(q.rows) == 3


def test_uncovered_windows_list_gaps_without_pce_call(collected, fake_traffic):
    q = query_flows(collected, _spec(NOW - timedelta(days=3), NOW), limit=100, order="last_detected_desc", now=NOW)
    assert q.coverage.gaps == [(NOW - timedelta(days=3), NOW - timedelta(days=1), "not_yet_collected")]
    q = query_flows(collected, _spec(NOW - timedelta(days=40), NOW - timedelta(days=36)), limit=100,
                    order="last_detected_desc", now=NOW)
    assert [g[2] for g in q.coverage.gaps] == ["before_retention"]
    assert fake_traffic.calls == [] and q.coverage.source == "store"


def test_window_after_watermark_is_not_yet_collected(collected):
    q = query_flows(collected, _spec(NOW - minutes(60), NOW + minutes(15)), limit=100, order="last_detected_desc")
    assert [(g[0], g[1], g[2]) for g in q.coverage.gaps] == [(NOW, NOW + minutes(15), "not_yet_collected")]


def test_fill_gaps_queries_pce_and_marks_mixed(collected, fake_traffic):
    fake_traffic.answer = lambda s, e, m: [raw_flow(7, e - minutes(2), e - minutes(1))]
    q = query_flows(collected, _spec(NOW - minutes(60), NOW + minutes(15)), limit=100,
                    order="last_detected_desc", fill_gaps=True)
    assert q.coverage.source == "mixed" and len(q.rows) == 4
    assert q.coverage.filled_from_pce == [(NOW, NOW + minutes(15))] and q.coverage.gaps == []
    with collected.flows().connect() as conn:
        assert conn.execute("SELECT count(*) FROM flows").fetchone()[0] == 3  # never written to the store


def test_fill_gaps_with_zero_rows_is_still_mixed(collected, fake_traffic):
    q = query_flows(collected, _spec(NOW - minutes(60), NOW + minutes(15)), limit=100,
                    order="last_detected_desc", fill_gaps=True)
    assert q.coverage.source == "mixed" and len(q.rows) == 3


def test_fill_gaps_pce_failure_keeps_gap(collected, fake_traffic):
    fake_traffic.answer = lambda s, e, m: (_ for _ in ()).throw(PceQueryError("timeout"))
    q = query_flows(collected, _spec(NOW - minutes(60), NOW + minutes(15)), limit=100,
                    order="last_detected_desc", fill_gaps=True)
    assert [g[2] for g in q.coverage.gaps] == ["ingest_failed"] and q.coverage.source == "store"
    assert len(q.rows) == 3


def test_unresolved_ingest_gap_is_reported(collected):
    with collected.flows().connect() as conn:
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW - minutes(50), NOW - minutes(40), "failed", "x", NOW)
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW - minutes(10), NOW - minutes(9), "truncated", "y", NOW)
    q = query_flows(collected, _spec(NOW - minutes(60), NOW), limit=100, order="last_detected_desc")
    assert sorted(g[2] for g in q.coverage.gaps) == ["ingest_failed", "truncated"] and q.coverage.truncated


def test_dedupe_across_store_and_pce(collected, fake_traffic):
    same = raw_flow(1, NOW - minutes(31), NOW - minutes(21), user="LAB\\u1")
    fake_traffic.answer = lambda s, e, m: [same]
    q = query_flows(collected, _spec(NOW - timedelta(hours=30), NOW), limit=100, order="last_detected_desc",
                    fill_gaps=True)
    assert len(q.rows) == 3


def test_limit_hit_flag(collected):
    q = query_flows(collected, _spec(NOW - minutes(60), NOW), limit=2, order="last_detected_desc")
    assert len(q.rows) == 2 and q.limit_hit is True


def test_never_collected_is_one_gap(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    q = query_flows(ctx, _spec(NOW - minutes(60), NOW), limit=10, order="last_detected_desc")
    assert q.rows == [] and [g[2] for g in q.coverage.gaps] == ["not_yet_collected"]
    assert q.coverage.store_to is None


def test_a_pce_switch_during_a_filled_query_is_not_answered_with_both_pces(collected, fake_traffic):
    from illumio_ops.services.collect.reset import reset_for_new_pce
    from illumio_ops.store.flowdb.db import StaleGeneration

    def switch_then_answer(s, e, m):
        reset_for_new_pce(collected, now=NOW)  # the operator saves another PCE meanwhile
        return [raw_flow(7, e - minutes(2), e - minutes(1))]
    fake_traffic.answer = switch_then_answer
    with pytest.raises(StaleGeneration):
        query_flows(collected, _spec(NOW - minutes(60), NOW + minutes(15)), limit=100,
                    order="last_detected_desc", fill_gaps=True)


def test_reads_refuse_while_the_store_still_holds_another_pces_data(collected):
    # A switch whose clearing did not finish yet (the next collector run finishes it): answering from
    # the store would show the previous PCE's flows and events as the new one's.
    from illumio_ops.services.collect.guard import BindingMismatch
    from illumio_ops.services.eventsource import query_events
    collected.settings.update(collected.settings.current().revision,
                              lambda d: d["pce"].update({"url": "https://pce-b.example.com:8443"}))
    with pytest.raises(BindingMismatch):
        query_flows(collected, _spec(NOW - minutes(60), NOW), limit=100, order="last_detected_desc")
    with pytest.raises(BindingMismatch):
        query_events(collected, start=NOW - minutes(60), end=NOW, limit=100)


def test_gap_filling_stops_at_its_row_budget(collected, fake_traffic, monkeypatch):
    # What a query reads from the PCE is held in memory: bounded over all its gaps, not per gap.
    from illumio_ops.services import flowsource
    monkeypatch.setattr(flowsource, "FILL_BUDGET", 3)
    fake_traffic.answer = lambda s, e, m: [raw_flow(10 + i, e - minutes(3), e - minutes(2)) for i in range(5)][:m]
    q = query_flows(collected, _spec(NOW - timedelta(hours=25), NOW + minutes(15)), limit=100,
                    order="last_detected_desc", fill_gaps=True)
    assert len(fake_traffic.calls) == 1  # the second gap is not read once the budget is spent
    assert [g[2] for g in q.coverage.gaps] == ["truncated", "truncated"]


def test_fill_keeps_connection_whose_partner_is_stored(collected, fake_traffic):
    # F7: flow 1's outbound record is stored; its inbound half (with the serving account) lies in a failed
    # window only the PCE can fill. A query naming both ends must still find the connection.
    with collected.flows().connect() as conn:
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW - minutes(35), NOW - minutes(15), "failed", "x", NOW)
    out = raw_flow(1, NOW - minutes(31), NOW - minutes(21), user="LAB\\u1")
    inn = raw_flow(1, NOW - minutes(31), NOW - minutes(21), direction="inbound", user="svc-db")
    fake_traffic.answer = lambda s, e, m: [out, inn]
    q = query_flows(collected, _spec(NOW - minutes(60), NOW, initiator_user="u1", service_user="svc-db"), limit=100,
                    order="last_detected_desc", fill_gaps=True)
    assert [(r.initiator_user, r.service_user) for r in q.rows] == [("LAB\\u1", "svc-db")]
    everything = query_flows(collected, _spec(NOW - minutes(60), NOW), limit=100, order="last_detected_desc",
                             fill_gaps=True)
    assert len(everything.rows) == 3  # the stored row of flow 1 is not listed a second time


def test_fill_that_re_pairs_a_stored_record_does_not_count_twice(collected, fake_traffic):
    # Final review #3: a live record that takes over a stored pair's partner left the old pair's merged row.
    from illumio_ops.domain.flows import normalize_flow
    from illumio_ops.domain.values import DataOrigin
    from illumio_ops.store.flowdb.flows import upsert_flows

    def rec(direction, first, last, bytes_in):
        raw = raw_flow(5, first, last, direction=direction)
        if bytes_in is not None:
            raw["dst_bi"], raw["dst_bo"] = bytes_in, 0
        return raw
    a, b = rec("outbound", NOW - minutes(30), NOW - minutes(25), 100), rec("inbound", NOW - minutes(30), NOW - minutes(25), 500)
    with collected.flows().connect() as conn:
        upsert_flows(conn, [normalize_flow(a), normalize_flow(b)], origin=DataOrigin.INGEST, now=NOW)
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW - minutes(35), NOW - minutes(15), "failed", "x", NOW)
    a2 = rec("outbound", NOW - minutes(31), NOW - minutes(24), None)  # earlier: pairing takes b from a
    fake_traffic.answer = lambda s, e, m: [a, b, a2]
    q = query_flows(collected, _spec(NOW - minutes(60), NOW), limit=100, order="last_detected_desc", fill_gaps=True)
    mine = [r for r in q.rows if r.src_ip == "10.0.1.5"]
    assert len(mine) == 2 and sum(r.bytes_in or 0 for r in mine) == 600


# ── flow increments ──

def _grow(ctx, fake_traffic, at, conns):
    def answer(s, e, m):
        rows = [raw_flow(i, NOW - minutes(30 + i), NOW - minutes(20 + i), user=f"LAB\\u{i}") for i in range(3)]
        for r in rows:
            r["num_connections"] = conns
            r["timestamp_range"]["last_detected"] = at.strftime("%Y-%m-%dT%H:%M:%SZ")
        return rows
    fake_traffic.answer = answer
    run_traffic_cycle(ctx, now=at)


def _increments(ctx):
    with ctx.flows().connect() as conn:
        return [dict(r) for r in conn.execute("SELECT connections, late FROM flow_increments ORDER BY id")]


def test_cold_start_catch_up_is_late_and_a_cycle_is_not(collected, fake_traffic):
    assert _increments(collected) and all(i["late"] == 1 for i in _increments(collected))
    _grow(collected, fake_traffic, NOW + minutes(10), 4)
    assert [i for i in _increments(collected) if i["late"] == 0] == [{"connections": 3, "late": 0}] * 3


def test_increment_totals_window_by_observed_at(collected, fake_traffic):
    from illumio_ops.domain.filter import FlowCondition
    from illumio_ops.services.flowsource import increment_totals
    _grow(collected, fake_traffic, NOW + minutes(10), 4)
    t = increment_totals(collected, FlowCondition(), start=NOW, end=NOW + minutes(20), new_after=NOW,
                         rank_by="connections", now=NOW + minutes(20))
    assert (t.connections, t.rows, t.new_rows, t.bytes, t.bytes_rows) == (9, 3, 3, None, 0)
    assert len(t.top) == 3 and t.top[0].connections == 3
    assert t.coverage.gaps == [(NOW + minutes(10), NOW + minutes(20), "not_yet_collected")]  # past the watermark
    later = increment_totals(collected, FlowCondition(), start=NOW + minutes(10), end=NOW + minutes(20),
                             new_after=NOW, rank_by="connections", now=NOW + minutes(20))
    assert later.rows == 0  # observed at NOW+10 is not after the window's start
    seen = increment_totals(collected, FlowCondition(), start=NOW, end=NOW + minutes(20), new_after=NOW + minutes(10),
                            rank_by="connections", now=NOW + minutes(20))
    assert (seen.rows, seen.new_rows) == (3, 0)


def test_increment_totals_excludes_late(collected):
    from illumio_ops.domain.filter import FlowCondition
    from illumio_ops.services.flowsource import increment_totals
    t = increment_totals(collected, FlowCondition(), start=NOW - timedelta(hours=25), end=NOW, new_after=NOW,
                         rank_by="connections", now=NOW)
    assert t.rows == 0 and t.connections == 0


def test_increment_totals_condition_applies(collected, fake_traffic):
    from illumio_ops.domain.filter import FlowCondition, PortProto
    from illumio_ops.services.flowsource import increment_totals
    _grow(collected, fake_traffic, NOW + minutes(10), 4)
    kw = {"start": NOW, "end": NOW + minutes(20), "new_after": NOW, "rank_by": "connections", "now": NOW + minutes(20)}
    assert increment_totals(collected, FlowCondition(ports=(PortProto(port=445),)), **kw).rows == 3
    assert increment_totals(collected, FlowCondition(ports=(PortProto(port=22),)), **kw).rows == 0


def test_increment_totals_reports_gaps(collected, fake_traffic):
    from illumio_ops.domain.filter import FlowCondition
    from illumio_ops.services.flowsource import increment_totals, increments_watermark
    _grow(collected, fake_traffic, NOW + minutes(10), 4)
    with collected.flows().connect() as conn:
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW + minutes(1), NOW + minutes(5), "failed", "x", NOW)
    t = increment_totals(collected, FlowCondition(), start=NOW, end=NOW + minutes(10), new_after=NOW,
                         rank_by="mbps", now=NOW + minutes(10))
    assert [g[2] for g in t.coverage.gaps] == ["ingest_failed"]
    assert increments_watermark(collected) == NOW + minutes(10)


# ── increments follow connections (review: they were the tuple's, pinned to a conn_key pairing rewrites) ──

def _put(ctx, records, at):
    from illumio_ops.domain.flows import normalize_flow
    from illumio_ops.domain.values import DataOrigin
    from illumio_ops.store.flowdb.flows import upsert_flows
    with ctx.flows().write_lock, ctx.flows().connect() as conn:
        upsert_flows(conn, [normalize_flow(r) for r in records], origin=DataOrigin.INGEST, now=at, increments="cycle")


def _flow(first, last, *, direction="outbound", conns=1, decision="potentially_blocked"):
    r = raw_flow(9, first, last, direction=direction)
    r["num_connections"], r["policy_decision"] = conns, decision
    return r


def _total(ctx, at, **cond):
    from illumio_ops.domain.filter import FlowCondition
    from illumio_ops.services.flowsource import increment_totals
    return increment_totals(ctx, FlowCondition(**cond), start=at - minutes(180), end=at, new_after=at - minutes(180),
                            rank_by="connections", now=at).connections


T = NOW + minutes(30)


def test_increment_survives_its_record_pairing_later(collected):
    """The inbound side first, alone; the outbound side pairs with it a cycle later: still 5 connections."""
    _put(collected, [_flow(T - minutes(20), T - minutes(15), direction="inbound", conns=5)], T)
    _put(collected, [_flow(T - minutes(20), T - minutes(15), direction="outbound", conns=5)], T + minutes(10))
    assert _total(collected, T + minutes(10)) == 5


def test_increments_keep_each_connections_decision(collected):
    """Allowed 50 and a newer blocked 1 on one tuple: the blocked rule sees 1, not 51."""
    from illumio_ops.domain.values import PolicyDecision
    _put(collected, [_flow(T - minutes(40), T - minutes(30), conns=50, decision="allowed"),
                     _flow(T - minutes(10), T - minutes(5), conns=1, decision="blocked")], T)
    assert _total(collected, T, decisions=(PolicyDecision.BLOCKED,)) == 1
    assert _total(collected, T, decisions=(PolicyDecision.ALLOWED,)) == 50


def test_repairing_shrink_is_not_counted_again(collected):
    """An inbound 10 and a separate outbound 1; the inbound's range grows until the two pair, and the outbound
    grows to 10: one connection of 10 plus the 1 counted before the pairing, never 16."""
    inbound = lambda last: _flow(T - minutes(60), last, direction="inbound", conns=10)
    outbound = lambda conns: _flow(T - minutes(30), T - minutes(29), conns=conns)
    _put(collected, [inbound(T - minutes(50)), outbound(1)], T)
    _put(collected, [inbound(T - minutes(35)), outbound(5)], T + minutes(10))
    _put(collected, [outbound(10)], T + minutes(20))
    assert _total(collected, T + minutes(20)) == 11
