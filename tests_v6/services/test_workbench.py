"""Workbench service (P6a): every number through the one segment entry (run_segment / the rankings), dimension tops
as one-level rankings, an alert's evidence as the starting conditions."""
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from illumio_ops.domain.filter import EndpointFilter, FlowCondition
from illumio_ops.domain.segment import FlowSegment, GroupBy
from illumio_ops.domain.values import (
    DataOrigin,
    SegmentDimension,
    SegmentMetric,
    SegmentView,
)
from illumio_ops.services import workbench
from illumio_ops.services.analysis.segments import run_segment
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.services.collect.conftest import configured_ctx
from tests_v6.services.reports.test_audit import _write, event
from tests_v6.services.reports.test_findings import flow

NOW = datetime(2026, 10, 27, 1, tzinfo=UTC)
START, END = datetime(2026, 10, 21, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path, mode="full")
    flows = [flow(src="a", dst="db", port=445), flow(src="a", dst="db", port=445), flow(src="b", dst="db", port=3389),
             *(flow(src=f"h{i}", dst="web", port=443) for i in range(12))]
    with c.flows().connect() as conn:
        upsert_flows(conn, flows, origin=DataOrigin.INGEST, now=NOW)
    _write(c, [event("user.sign_in", datetime(2026, 10, 22, tzinfo=UTC), user="alice"),
               event("rule_set.update", datetime(2026, 10, 23, tzinfo=UTC), user="bob")])
    return c


def _flows(**kw):
    return workbench.FlowRequest(**{"mode": "flows", "condition": FlowCondition(), "start": START, "end": END,
                                    "view": SegmentView.DETAIL, **kw})


def test_run_detail_and_ranking_match_run_segment(ctx):
    req = _flows(view=SegmentView.RANKING, group_by=(GroupBy(dimension=SegmentDimension.DST_HOST),))
    got = workbench.run(ctx, req, now=NOW)
    direct = run_segment(ctx, FlowSegment(filter=FlowCondition().within(START, END), view=SegmentView.RANKING,
                                          group_by=req.group_by, limit=req.limit), now=NOW)
    assert [(r.keys, r.value) for r in got.ranking] == [(r.keys, r.value) for r in direct.ranking]
    detail = workbench.run(ctx, _flows(condition=FlowCondition(dst=EndpointFilter(hrefs=("/orgs/1/workloads/db",)))),
                           now=NOW)
    assert len(detail.detail) == 3


def test_dimension_top_ten(ctx):
    top = workbench.dimension(ctx, _flows(), SegmentDimension.SRC_HOST, now=NOW)
    assert len(top.rows) == 10 and top.limit_hit
    by_dst = workbench.dimension(ctx, _flows(metric=SegmentMetric.CONNECTIONS), SegmentDimension.DST_HOST, now=NOW)
    assert by_dst.rows[0].value == 12


def test_label_dimension_needs_key(ctx):
    with pytest.raises(ValidationError):
        workbench.dimension(ctx, _flows(), SegmentDimension.SRC_LABEL, now=NOW)
    top = workbench.dimension(ctx, _flows(), SegmentDimension.SRC_LABEL, label_key="app", now=NOW)
    assert top.rows[0].keys == ["Web"]


def test_event_dimensions_only(ctx):
    req = workbench.EventRequest(mode="events", start=START, end=END, view=SegmentView.DETAIL)
    top = workbench.dimension(ctx, req, SegmentDimension.EVENT_TYPE, now=NOW)
    assert {tuple(r.keys) for r in top.rows} == {("user.sign_in",), ("rule_set.update",)}
    with pytest.raises(ValidationError):
        workbench.dimension(ctx, req, SegmentDimension.SRC_HOST, now=NOW)
    assert len(workbench.run(ctx, req, now=NOW).detail) == 2


def test_period_capped_30_days():
    with pytest.raises(ValidationError):
        _flows(start=END - timedelta(days=31))


def test_predicted_block_not_here():
    """P6e: the predicted-block view is its own explicit action."""
    with pytest.raises(ValidationError):
        _flows(view=SegmentView.PREDICTED_BLOCK)


def test_from_alert_carries_segment(ctx, monkeypatch):
    seg = FlowSegment(filter=FlowCondition(dst=EndpointFilter(hrefs=("/orgs/1/workloads/db",))).within(START, END),
                      view=SegmentView.DETAIL, limit=50)
    monkeypatch.setattr(workbench, "evidence_segment", lambda ctx, alert_id: ("flow", seg.model_dump(mode="json")))
    req = workbench.from_alert(ctx, 7)
    assert isinstance(req, workbench.FlowRequest)
    assert (req.start, req.end, req.condition) == (START, END, seg.filter.condition())
    monkeypatch.setattr(workbench, "evidence_segment", lambda ctx, alert_id: None)
    assert workbench.from_alert(ctx, 8) is None


def test_meta_lists_label_keys(ctx):
    m = workbench.meta(ctx)
    assert m.max_days == 30 and m.default_days == 1 and m.mode == "full"
