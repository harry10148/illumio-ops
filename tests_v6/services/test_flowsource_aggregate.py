"""FlowSource aggregation: segment rankings answered from the store, with coverage and field coverage."""
import pytest

from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.segment import FlowSegment, GroupBy
from illumio_ops.domain.values import IngestSource
from illumio_ops.domain.values import SegmentDimension as D
from illumio_ops.domain.values import SegmentMetric as M
from illumio_ops.domain.values import SegmentView as V
from illumio_ops.services.collect.traffic import run_traffic_cycle
from illumio_ops.services.flowsource import aggregate_flows, query_flows
from illumio_ops.store.flowdb import ingest_state
from tests_v6.services.collect.conftest import (
    NOW,
    FakeTraffic,
    configured_ctx,
    minutes,
    raw_flow,
)


def flow(i, *, src=1, dst="a", user=None, env="Dev", decision="potentially_blocked", port=445, bytes_in=None):
    r = raw_flow(i, NOW - minutes(40), NOW - minutes(20 + i % 10), port=port, user=user)
    r["src"]["ip"] = f"10.0.1.{src}"
    r["src"]["workload"].update({"href": f"/orgs/1/workloads/src-{src}", "hostname": f"s{src}",
                                 "labels": [{"key": "env", "value": env}]})
    r["dst"]["ip"] = f"10.0.2.{ord(dst)}"
    r["dst"]["workload"].update({"href": f"/orgs/1/workloads/dst-{dst}", "hostname": f"d-{dst}"})
    r["policy_decision"] = decision
    if bytes_in is not None:
        r["dst_bi"], r["dst_bo"] = bytes_in, 1
    return r


ROWS = [
    flow(1, src=1, dst="a", user="LAB\\Alice", bytes_in=100),
    flow(2, src=1, dst="b", user="lab\\alice", bytes_in=50),
    flow(3, src=1, dst="c", user="LAB\\bob", decision="allowed"),
    flow(4, src=2, dst="a", user="LAB\\alice", env="Prod"),
    flow(5, src=3, dst="a", user="root", env="Prod", port=22),
    flow(6, src=3, dst="b", user="Root", env="Prod", port=22),
]


@pytest.fixture
def fake(monkeypatch):
    from illumio_ops.services import flowsource
    from illumio_ops.services.collect import traffic
    f = FakeTraffic()
    monkeypatch.setattr(traffic, "run_traffic_query", f)
    monkeypatch.setattr(flowsource, "run_traffic_query", f)
    return f


@pytest.fixture
def ctx(tmp_path, fake):
    c = configured_ctx(tmp_path)
    fake.answer = lambda s, e, m: ROWS if e == NOW else []
    run_traffic_cycle(c, now=NOW)
    return c


def rank(*dims, metric=M.FLOWS, label_key=None, **flt):
    return FlowSegment(filter=FilterSpec(start=NOW - minutes(60), end=NOW, **flt), view=V.RANKING, limit=50,
                       metric=metric, group_by=tuple(GroupBy(dimension=d, label_key=label_key if "label" in d else None)
                                                     for d in dims))


def test_ranking_two_levels_src_then_user(ctx):
    a = aggregate_flows(ctx, rank(D.SRC_HOST, D.INITIATOR_USER), now=NOW)
    got = [(r.keys[0], r.keys[1], r.value) for r in a.rows]
    assert got[0] == ("/orgs/1/workloads/src-1", "lab\\alice", 2)
    assert ("/orgs/1/workloads/src-1", "lab\\bob", 1) in got and ("/orgs/1/workloads/src-2", "lab\\alice", 1) in got
    assert a.rows[0].display[0] == "s1" and a.limit_hit is False


def test_label_dimension_groups_by_key_value(ctx):
    a = aggregate_flows(ctx, rank(D.SRC_LABEL, label_key="env"), now=NOW)
    assert {r.keys[0]: r.value for r in a.rows} == {"Dev": 3, "Prod": 3}


def test_metric_distinct_dst(ctx):
    a = aggregate_flows(ctx, rank(D.SRC_HOST, metric=M.DISTINCT_DST), now=NOW)
    assert {r.keys[0]: r.value for r in a.rows} == {"/orgs/1/workloads/src-1": 3, "/orgs/1/workloads/src-2": 1,
                                                    "/orgs/1/workloads/src-3": 2}


def test_bytes_metric_reports_coverage(ctx):
    a = aggregate_flows(ctx, rank(D.SRC_HOST, metric=M.BYTES), now=NOW)
    src1 = next(r for r in a.rows if r.keys[0].endswith("src-1"))
    assert src1.value == 152 and src1.bytes_known == 2
    assert a.field_coverage.total == 6 and a.field_coverage.bytes == 2 and a.field_coverage.initiator_user == 6


def test_windows_user_grouped_case_insensitive(ctx):
    a = aggregate_flows(ctx, rank(D.INITIATOR_USER), now=NOW)
    counts = {r.keys[0]: r.value for r in a.rows}
    assert counts["lab\\alice"] == 3 and counts["root"] == 1 and counts["Root"] == 1  # Linux keeps its case


def test_aggregate_total_equals_detail_count(ctx):
    spec = FilterSpec(start=NOW - minutes(60), end=NOW, ports=())
    a = aggregate_flows(ctx, rank(D.DECISION), now=NOW)
    detail = query_flows(ctx, spec, limit=1000, order="last_detected_desc", now=NOW)
    assert sum(r.value for r in a.rows) == len(detail.rows) == 6


def test_events_only_mode_reports_collection_off(tmp_path, fake):
    c = configured_ctx(tmp_path, mode="events_only")
    a = aggregate_flows(c, rank(D.SRC_HOST), now=NOW)
    assert a.rows == [] and [g[2] for g in a.coverage.gaps] == ["collection_off"]


def test_gap_listed_in_aggregate_coverage(ctx):
    with ctx.flows().connect() as conn:
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW - minutes(50), NOW - minutes(40), "failed", "x", NOW)
    a = aggregate_flows(ctx, rank(D.SRC_HOST), now=NOW)
    assert [g[2] for g in a.coverage.gaps] == ["ingest_failed"] and a.coverage.source == "store"


def test_new_user_pairs_since(ctx):
    from illumio_ops.domain.filter import PortProto
    from illumio_ops.services.flowsource import new_user_pairs
    pairs = new_user_pairs(ctx, (PortProto(port=22, proto=6),), since=NOW - minutes(60))
    assert sorted((p.user, p.dst_key) for p in pairs) == [("Root", "/orgs/1/workloads/dst-b"),
                                                          ("root", "/orgs/1/workloads/dst-a")]
    assert new_user_pairs(ctx, (PortProto(port=22, proto=6),), since=NOW) == []
    assert len(new_user_pairs(ctx, (), since=NOW - minutes(60))) == 6
    assert new_user_pairs(ctx, (PortProto(port=22, proto=17),), since=NOW - minutes(60)) == []  # UDP 22: none
