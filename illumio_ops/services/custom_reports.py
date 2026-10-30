"""Custom reports (spec §6.5.5, P6e): reports made of sections saved from the workbench. A section is the workbench's
analysis segment without its period — conditions, view, grouping, metric, limit — so the report made from it on any
period runs the same segment the workbench runs (spec §6.3 point 4: the same number on the page and in the report).
The predicted-block view is not saved: it changes with every Draft edit and is asked for on the page. Bounded: at most
SECTIONS_MAX sections, names and titles at most TITLE_MAX characters, each section's rows at most its view's cap (a
section saved with more says so in the report, as every ranking does when it reaches its limit)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from illumio_ops.domain.filter import FlowCondition
from illumio_ops.domain.segment import EventFilter, EventSegment, FlowSegment, GroupBy
from illumio_ops.domain.values import ReportType, SegmentMetric, SegmentView
from illumio_ops.services.context import AppContext
from illumio_ops.services.workbench import EventRequest, FlowRequest
from illumio_ops.store import custom_reports as store

SECTIONS_MAX = 20
TITLE_MAX = 120
DETAIL_MAX = 200   # rows a detail section lists
RANKING_MAX = 50   # rows a ranking section lists
_CAP = {SegmentView.DETAIL: DETAIL_MAX, SegmentView.RANKING: RANKING_MAX}


class InUse(Exception):
    def __init__(self, schedules: list[str]) -> None:
        super().__init__(", ".join(schedules))
        self.schedules = schedules


class CustomSegment(BaseModel):
    """An analysis segment without its period."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["flows", "events"]
    view: SegmentView
    group_by: tuple[GroupBy, ...] = Field(default=(), max_length=2)
    metric: SegmentMetric = SegmentMetric.FLOWS
    limit: int = Field(ge=1, le=DETAIL_MAX)  # and at most its view's cap (_shape)
    condition: FlowCondition | None = None  # flows
    event_types: tuple[str, ...] = ()       # events
    severities: tuple[str, ...] = ()
    host_hrefs: tuple[str, ...] = ()
    actor: str | None = None
    actors: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _shape(self) -> CustomSegment:
        if self.view not in _CAP:
            raise ValueError("only a detail or a ranking is saved")
        if self.limit > _CAP[self.view]:
            raise ValueError("more rows than a section lists")
        self.materialize(datetime.fromtimestamp(0).astimezone(), datetime.fromtimestamp(86_400).astimezone())
        return self

    def materialize(self, start: datetime, end: datetime) -> FlowSegment | EventSegment:
        """The segment on a period: the report's."""
        if self.mode == "flows":
            return FlowSegment(filter=(self.condition or FlowCondition()).within(start, end), view=self.view,
                               group_by=self.group_by, metric=self.metric, limit=self.limit)
        return EventSegment(filter=EventFilter(start=start, end=end, event_types=self.event_types,
                                               severities=self.severities, host_hrefs=self.host_hrefs,
                                               actor=self.actor, actors=self.actors),
                            view=self.view, group_by=self.group_by, metric=SegmentMetric.EVENTS, limit=self.limit)

    def request(self, start: datetime, end: datetime) -> FlowRequest | EventRequest | None:
        """The workbench's request for this section on a period; None when the workbench cannot take it (longer than
        its 30 days)."""
        common: dict[str, Any] = {"start": start, "end": end, "view": self.view, "group_by": self.group_by,
                                  "limit": self.limit}
        try:
            if self.mode == "flows":
                return FlowRequest(mode="flows", condition=self.condition or FlowCondition(), metric=self.metric,
                                   **common)
            return EventRequest(mode="events", event_types=self.event_types, severities=self.severities,
                                host_hrefs=self.host_hrefs, actor=self.actor, actors=self.actors, **common)
        except (ValidationError, ValueError):
            return None


def from_request(req: FlowRequest | EventRequest) -> CustomSegment:
    view = req.view
    limit = min(req.limit, _CAP.get(view, DETAIL_MAX))
    if isinstance(req, FlowRequest):
        return CustomSegment(mode="flows", view=view, group_by=req.group_by, metric=req.metric, limit=limit,
                             condition=req.condition)
    return CustomSegment(mode="events", view=view, group_by=req.group_by, metric=SegmentMetric.EVENTS, limit=limit,
                         event_types=req.event_types, severities=req.severities, host_hrefs=req.host_hrefs,
                         actor=req.actor, actors=req.actors)


class CustomSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    segment: CustomSegment


class CustomReport(BaseModel):
    id: int
    name: str
    sections: list[CustomSection]
    created_by: str
    updated_at: AwareDatetime
    schedules: list[str]  # the schedules that make it


def _name(name: str) -> str:
    name = name.strip()
    if not name or len(name) > TITLE_MAX:
        raise ValueError(f"a name of 1 to {TITLE_MAX} characters")
    return name


def _schedules(ctx: AppContext) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for s in ctx.settings.current().reports.schedules:
        if s.report_type is ReportType.CUSTOM and s.custom_id is not None:
            out.setdefault(s.custom_id, []).append(s.name)
    return out


def _view(row: Any, schedules: dict[int, list[str]]) -> CustomReport:
    return CustomReport(id=row["id"], name=row["name"],
                        sections=[CustomSection.model_validate(s) for s in json.loads(row["sections_json"])],
                        created_by=row["created_by"], updated_at=datetime.fromisoformat(row["updated_at"]),
                        schedules=schedules.get(row["id"], []))


def _dump(sections: list[CustomSection]) -> str:
    return json.dumps([s.model_dump(mode="json") for s in sections])


def list_reports(ctx: AppContext) -> list[CustomReport]:
    with ctx.db() as conn:
        rows = store.all_rows(conn)
    schedules = _schedules(ctx)
    return [_view(r, schedules) for r in rows]


def get(ctx: AppContext, report_id: int) -> CustomReport | None:
    with ctx.db() as conn:
        row = store.get(conn, report_id)
    return _view(row, _schedules(ctx)) if row is not None else None


def add_section(ctx: AppContext, *, report_id: int | None, name: str | None, title: str,
                request: FlowRequest | EventRequest, by: str, now: datetime) -> CustomReport:
    """Save the workbench's request as a section: of an existing custom report, or of a new one named `name`."""
    section = CustomSection(title=title.strip(), segment=from_request(request))
    with ctx.db() as conn:
        if report_id is None:
            new_id = store.insert(conn, name=_name(name or ""), sections_json=_dump([section]), by=by, at=now)
            return _view(store.get(conn, new_id), _schedules(ctx))
        row = store.get(conn, report_id)
        if row is None:
            raise LookupError("no such custom report")
        current = _view(row, {})
        if len(current.sections) >= SECTIONS_MAX:
            raise ValueError(f"at most {SECTIONS_MAX} sections")
        store.update(conn, report_id, name=current.name, sections_json=_dump([*current.sections, section]), at=now)
        return _view(store.get(conn, report_id), _schedules(ctx))


def remove_section(ctx: AppContext, report_id: int, index: int, *, now: datetime) -> CustomReport:
    with ctx.db() as conn:
        row = store.get(conn, report_id)
        if row is None:
            raise LookupError("no such custom report")
        current = _view(row, {})
        if not 0 <= index < len(current.sections):
            raise ValueError("no such section")
        if len(current.sections) == 1:
            raise ValueError("a custom report keeps at least one section: delete the report instead")
        kept = [s for i, s in enumerate(current.sections) if i != index]
        store.update(conn, report_id, name=current.name, sections_json=_dump(kept), at=now)
        return _view(store.get(conn, report_id), _schedules(ctx))


def rename(ctx: AppContext, report_id: int, name: str, *, now: datetime) -> CustomReport:
    with ctx.db() as conn:
        row = store.get(conn, report_id)
        if row is None:
            raise LookupError("no such custom report")
        store.update(conn, report_id, name=_name(name), sections_json=row["sections_json"], at=now)
        return _view(store.get(conn, report_id), _schedules(ctx))


def delete(ctx: AppContext, report_id: int) -> None:
    """Raises InUse with the schedules that make it: they are not deleted along with it."""
    using = _schedules(ctx).get(report_id)
    if using:
        raise InUse(using)
    with ctx.db() as conn:
        if not store.delete(conn, report_id):
            raise LookupError("no such custom report")


def needs_traffic(ctx: AppContext, report_id: int | None) -> bool:
    """Whether making it reads flows (a report of event sections alone pulls nothing in lightweight mode)."""
    rep = get(ctx, report_id) if report_id is not None else None
    return rep is not None and any(s.segment.mode == "flows" for s in rep.sections)
