"""run_segment: the one entry the screens and the reports compute a segment through."""
import pytest

from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.segment import FlowSegment, GroupBy
from illumio_ops.domain.values import SegmentDimension as D
from illumio_ops.domain.values import SegmentView as V
from illumio_ops.services.analysis.segments import run_segment
from illumio_ops.services.collect.traffic import run_traffic_cycle
from tests_v6.services.collect.conftest import (
    NOW,
    FakeTraffic,
    configured_ctx,
    minutes,
    raw_flow,
)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    from illumio_ops.services.collect import traffic
    fake = FakeTraffic()
    monkeypatch.setattr(traffic, "run_traffic_query", fake)
    c = configured_ctx(tmp_path)
    fake.answer = lambda s, e, m: [raw_flow(i, NOW - minutes(30), NOW - minutes(20), user="u") for i in range(3)] \
        if e == NOW else []
    run_traffic_cycle(c, now=NOW)
    return c


SPEC = FilterSpec(start=NOW - minutes(60), end=NOW)


def test_run_segment_dispatches_detail_and_ranking(ctx):
    detail = run_segment(ctx, FlowSegment(filter=SPEC, view=V.DETAIL, limit=10), now=NOW)
    assert detail.view is V.DETAIL and len(detail.detail) == 3 and detail.ranking is None
    assert detail.field_coverage.total == 3 and detail.latency_seconds == 0
    assert (detail.observed_from, detail.observed_to) == (SPEC.start, SPEC.end)
    ranking = run_segment(ctx, FlowSegment(filter=SPEC, view=V.RANKING, limit=10,
                                           group_by=(GroupBy(dimension=D.DST_HOST),)), now=NOW)
    assert [r.value for r in ranking.ranking] == [3] and ranking.coverage.source == "store"
    later = run_segment(ctx, FlowSegment(filter=SPEC, view=V.DETAIL, limit=10), now=NOW + minutes(5))
    assert later.latency_seconds == 300


