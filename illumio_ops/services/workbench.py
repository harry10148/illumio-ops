"""The investigation workbench (spec §6.5.3, P6a): a request is an analysis segment, computed through the one entry
screens and reports share (services.analysis.segments.run_segment), so the workbench and a report give the same
number. The dimension panel is one single-level ranking per dimension, computed when the panel expands it (P2
Task 14: six dimensions over 7 days scan 25 s on 1,000 hosts)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from illumio_ops.domain.filter import FlowCondition
from illumio_ops.domain.segment import EventFilter, EventSegment, FlowSegment, GroupBy
from illumio_ops.domain.values import (
    CollectionMode,
    SegmentDimension,
    SegmentMetric,
    SegmentView,
)
from illumio_ops.services import workbench_store
from illumio_ops.services.alerts.views import evidence_segment
from illumio_ops.services.analysis.segments import SegmentResult, run_segment
from illumio_ops.services.context import AppContext
from illumio_ops.services.coverage import Coverage
from illumio_ops.services.eventsource import aggregate_events
from illumio_ops.services.flowsource import AggRow, aggregate_flows
from illumio_ops.services.workbench_store import PullInfo
from illumio_ops.store.flowdb import labels

MAX_DAYS = 30
DEFAULT_DAYS = 1
DIMENSION_TOP = 10
VIEWS = (SegmentView.DETAIL, SegmentView.RANKING)  # the predicted-block view is its own action (P6e)


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start: AwareDatetime
    end: AwareDatetime
    view: SegmentView
    group_by: tuple[GroupBy, ...] = Field(default=(), max_length=2)
    limit: int = Field(default=200, ge=1, le=1000)

    @model_validator(mode="after")
    def _period(self) -> _Request:
        if self.end <= self.start or self.end - self.start > timedelta(days=MAX_DAYS):
            raise ValueError(f"the period is up to {MAX_DAYS} days")
        if self.view not in VIEWS:
            raise ValueError("detail or ranking")
        return self


class FlowRequest(_Request):
    mode: Literal["flows"]
    condition: FlowCondition = FlowCondition()
    metric: SegmentMetric = SegmentMetric.FLOWS

    def segment(self, *, view: SegmentView | None = None, group_by: tuple[GroupBy, ...] | None = None,
                limit: int | None = None) -> FlowSegment:
        return FlowSegment(filter=self.condition.within(self.start, self.end), view=view or self.view,
                           group_by=self.group_by if group_by is None else group_by, metric=self.metric,
                           limit=limit or self.limit)


class EventRequest(_Request):
    mode: Literal["events"]
    event_types: tuple[str, ...] = ()
    severities: tuple[str, ...] = ()
    host_hrefs: tuple[str, ...] = ()
    actor: str | None = Field(default=None, min_length=1)

    def segment(self, *, view: SegmentView | None = None, group_by: tuple[GroupBy, ...] | None = None,
                limit: int | None = None) -> EventSegment:
        return EventSegment(filter=EventFilter(start=self.start, end=self.end, event_types=self.event_types,
                                               severities=self.severities, host_hrefs=self.host_hrefs,
                                               actor=self.actor),
                            view=view or self.view, group_by=self.group_by if group_by is None else group_by,
                            metric=SegmentMetric.EVENTS, limit=limit or self.limit)


WorkbenchRequest = Annotated[FlowRequest | EventRequest, Field(discriminator="mode")]


class DimensionTop(BaseModel):
    rows: list[AggRow]
    limit_hit: bool  # more values than DIMENSION_TOP
    coverage: Coverage
    pulled: PullInfo | None = None  # read from the PCE for this period (lightweight mode)


class WorkbenchResult(BaseModel):
    result: SegmentResult
    pulled: PullInfo | None  # read from the PCE for this period (lightweight mode, or older than the kept traffic)


class WorkbenchMeta(BaseModel):
    label_keys: list[str]  # the label dimensions offered (from the inventory)
    mode: CollectionMode
    default_days: int
    max_days: int
    dimension_top: int


@contextmanager
def _read_ctx(ctx: AppContext, req: FlowRequest | EventRequest,
              now: datetime | None) -> Iterator[tuple[AppContext, PullInfo | None]]:
    """Traffic the install does not keep is read from the PCE once and held for the request (workbench_store);
    events are always collected."""
    if isinstance(req, EventRequest):
        yield ctx, None
        return
    with workbench_store.lease(ctx, req.start, req.end, now=now) as got:
        yield got


_HOST_DIMENSIONS = frozenset({SegmentDimension.SRC_HOST, SegmentDimension.DST_HOST, SegmentDimension.EVENT_HOST})


def _named(ctx: AppContext, rows: list[AggRow], group_by: tuple[GroupBy, ...]) -> list[AggRow]:
    """A host the flows carry no hostname for is shown by the inventory's hostname or name, not its href (lab
    acceptance 2026-10-30: the PCE sends some workloads without one)."""
    levels = [i for i, g in enumerate(group_by) if g.dimension in _HOST_DIMENSIONS]
    hrefs = {str(r.keys[i]) for r in rows for i in levels if r.display[i] is None and str(r.keys[i]).startswith("/orgs/")}
    if not hrefs:
        return rows
    with ctx.flows().connect() as conn:
        found = conn.execute(f"SELECT href, COALESCE(hostname, name) FROM workloads WHERE href IN "
                             f"({','.join('?' * len(hrefs))})", sorted(hrefs)).fetchall()
    names = {h: n for h, n in found if n}
    out = []
    for r in rows:
        display = list(r.display)
        for i in levels:
            if display[i] is None and str(r.keys[i]) in names:
                display[i] = names[str(r.keys[i])]
        out.append(r.model_copy(update={"display": display}))
    return out


def run(ctx: AppContext, req: FlowRequest | EventRequest, *, now: datetime | None = None) -> WorkbenchResult:
    with _read_ctx(ctx, req, now) as (read, pulled):
        result = run_segment(read, req.segment(), now=now)
        if result.ranking:
            result = result.model_copy(update={"ranking": _named(read, result.ranking, req.group_by)})
        return WorkbenchResult(result=result, pulled=pulled)


def dimension(ctx: AppContext, req: FlowRequest | EventRequest, dim: SegmentDimension, *,
              label_key: str | None = None, now: datetime | None = None) -> DimensionTop:
    """One dimension's top values under the request's conditions: a one-level ranking (the same definition a
    report's ranking uses). A dimension of the other data source is refused by the segment's own check."""
    seg = req.segment(view=SegmentView.RANKING, group_by=(GroupBy(dimension=dim, label_key=label_key),),
                      limit=DIMENSION_TOP)
    if isinstance(seg, EventSegment):
        e = aggregate_events(ctx, seg, now=now)
        return DimensionTop(rows=_named(ctx, e.rows, seg.group_by), limit_hit=e.limit_hit, coverage=e.coverage)
    with _read_ctx(ctx, req, now) as (read, pulled):
        f = aggregate_flows(read, seg, now=now, with_field_coverage=False)
        return DimensionTop(rows=_named(read, f.rows, seg.group_by), limit_hit=f.limit_hit, coverage=f.coverage,
                            pulled=pulled)


def from_alert(ctx: AppContext, alert_id: int) -> FlowRequest | EventRequest | None:
    """The alert's evidence segment as the workbench's starting conditions and period (spec §6.5.2)."""
    found = evidence_segment(ctx, alert_id)
    if found is None or found[1] is None:
        return None
    kind, raw = found
    if kind == "flow":
        fs = FlowSegment.model_validate(raw)
        return FlowRequest(mode="flows", condition=fs.filter.condition(), start=fs.filter.start, end=fs.filter.end,
                           view=SegmentView.DETAIL, metric=fs.metric)
    es = EventSegment.model_validate(raw)
    f = es.filter
    return EventRequest(mode="events", start=f.start, end=f.end, view=SegmentView.DETAIL, event_types=f.event_types,
                        severities=f.severities, host_hrefs=f.host_hrefs, actor=f.actor)


def meta(ctx: AppContext) -> WorkbenchMeta:
    with ctx.flows().connect() as conn:
        keys = sorted({k for k, _ in labels.known_labels(conn)})
    return WorkbenchMeta(label_keys=keys, mode=ctx.settings.current().collection.mode, default_days=DEFAULT_DAYS,
                         max_days=MAX_DAYS, dimension_top=DIMENSION_TOP)


def default_period(now: datetime | None = None) -> tuple[datetime, datetime]:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    return at - timedelta(days=DEFAULT_DAYS), at
