"""run_segment: the one entry through which screens and reports compute an analysis segment, so the same
definition gives the same number in both (spec §6.3 point 4)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from illumio_ops.domain.segment import EventSegment, FlowSegment
from illumio_ops.domain.values import IngestSource, SegmentView
from illumio_ops.services.analysis.predicted_block import predict_blocks
from illumio_ops.services.context import AppContext
from illumio_ops.services.coverage import Coverage
from illumio_ops.services.eventsource import EventRow, aggregate_events, event_detail
from illumio_ops.services.flowsource import (
    AggRow,
    FieldCoverage,
    FlowRow,
    aggregate_flows,
    field_coverage,
    query_flows,
)
from illumio_ops.store.flowdb import ingest_state


class SegmentResult(BaseModel):
    view: SegmentView
    detail: list[FlowRow] | list[EventRow] | None = None
    ranking: list[AggRow] | None = None
    predicted: Any = None
    coverage: Coverage
    field_coverage: FieldCoverage | None
    limit_hit: bool
    observed_from: datetime
    observed_to: datetime
    latency_seconds: int | None  # now minus the collection watermark of the segment's data source


def _latency(ctx: AppContext, source: IngestSource, at: datetime) -> int | None:
    with ctx.flows().connect() as conn:
        state = ingest_state.get(conn, source)
    if state is None or state.watermark is None:
        return None
    return max(0, int((at - state.watermark).total_seconds()))


def run_segment(ctx: AppContext, seg: FlowSegment | EventSegment, *, now: datetime | None = None) -> SegmentResult:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    start, end = seg.filter.start, seg.filter.end
    if isinstance(seg, EventSegment):
        latency = _latency(ctx, IngestSource.EVENTS, at)
        if seg.view is SegmentView.RANKING:
            eagg = aggregate_events(ctx, seg, now=at)
            return SegmentResult(view=seg.view, ranking=eagg.rows, coverage=eagg.coverage, field_coverage=None,
                                 limit_hit=eagg.limit_hit, observed_from=start, observed_to=end,
                                 latency_seconds=latency)
        eq = event_detail(ctx, seg, now=at)
        return SegmentResult(view=seg.view, detail=eq.rows, coverage=eq.coverage, field_coverage=None,
                             limit_hit=eq.limit_hit, observed_from=start, observed_to=end, latency_seconds=latency)
    latency = _latency(ctx, IngestSource.TRAFFIC, at)
    if seg.view is SegmentView.RANKING:
        fagg = aggregate_flows(ctx, seg, now=at)
        return SegmentResult(view=seg.view, ranking=fagg.rows, coverage=fagg.coverage,
                             field_coverage=fagg.field_coverage, limit_hit=fagg.limit_hit, observed_from=start,
                             observed_to=end, latency_seconds=latency)
    if seg.view is SegmentView.PREDICTED_BLOCK:
        pb = predict_blocks(ctx, seg.filter, limit=seg.limit)
        return SegmentResult(view=seg.view, predicted=pb, field_coverage=None, limit_hit=pb.limit_hit,
                             observed_from=start, observed_to=end, latency_seconds=None,
                             coverage=Coverage(source="pce", store_from=None, store_to=None, gaps=[],
                                               filled_from_pce=[(start, end)], truncated=pb.capped))
    fq = query_flows(ctx, seg.filter, limit=seg.limit, order="last_detected_desc", now=at)
    return SegmentResult(view=seg.view, detail=fq.rows, coverage=fq.coverage,
                         field_coverage=field_coverage(ctx, seg.filter), limit_hit=fq.limit_hit,
                         observed_from=start, observed_to=end, latency_seconds=latency)
