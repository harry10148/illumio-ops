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
