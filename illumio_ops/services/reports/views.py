"""What the reports page reads: the catalog with what is available now, the report list and one report."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from illumio_ops.domain.values import Language, ReportFormat, ReportStatus, ReportType
from illumio_ops.services import custom_reports
from illumio_ops.services.context import AppContext
from illumio_ops.services.reports.generate import (
    availability,
    earliest_start,
    enqueue,
    first_day,
    reach,
)
from illumio_ops.services.reports.registry import ReportParams, ReportSpec, specs
from illumio_ops.store import reports as store

PAGE_SIZE = 50


class CatalogEntry(BaseModel):
    report_type: ReportType
    group: str
    available: bool
    reason_key: str | None
    accepts_filter: bool  # a label filter narrows the report
    requires_app: bool  # the filter must name an app
    max_lookback: int | None  # the most days back this type can read
    # The days a named period may span, in the display zone: from the first day the data reaches (the archive's
    # first day when it goes further back than the store) to yesterday. None: no first day.
    earliest_day: date | None
    latest_day: date
    formats: list[ReportFormat]  # the formats this type makes
    ui_group: Literal["assessment", "traffic", "policy", "operations"]  # the reports page's column (spec §4.7)
    # common: one of the templates the reports page leads with; topic: the rest (UI redesign spec §9.1)
    tier: Literal["common", "topic"]
    mode: Literal["basic", "on_demand"]  # on_demand: reads traffic, pulled from the PCE where none is kept (§5)
    schedules: int  # schedules that make this type
    copies: int  # finished reports of this type kept


class Catalog(BaseModel):
    entries: list[CatalogEntry]
    smtp_enabled: bool
    gui_external_url_set: bool


class ReportItem(BaseModel):
    id: int
    report_type: str
    status: ReportStatus
    trigger: str
    schedule_id: str | None
    schedule_name: str | None  # None also when the schedule was deleted since
    pce_label: str
    period_start: datetime
    period_end: datetime
    created_at: datetime
    finished_at: datetime | None
    error_key: str | None
    error_detail: str | None
    files: list[str]
    email_status: str | None
    email_detail: str | None
    conclusion: str = ""  # the report's opening sentence ("" for one made before it existed, or not finished)
    lookback_days: int | None
    lang: Language | None
    custom_name: str | None = None  # a custom report's name (None also when it was deleted since)


class ReportPage(BaseModel):
    items: list[ReportItem]
    total: int
    page: int
    page_size: int


# The templates the reports page leads with, the weekly overview first (UI redesign spec §9.1, §9.2).
COMMON = (ReportType.WEEKLY_OVERVIEW, ReportType.SECURITY_RISK, ReportType.VEN_STATUS, ReportType.NEW_CONNECTIONS,
          ReportType.AUDIT)
UI_GROUPS = {"lateral": "assessment", "assessment": "assessment", "analysis": "traffic", "inventory": "traffic",
             "custom": "traffic", "policy": "policy", "operations": "operations"}


def catalog(ctx: AppContext) -> Catalog:
    avail = availability(ctx)
    settings = ctx.settings.current()
    with ctx.db() as conn:
        copies = store.done_counts(conn)
    scheduled: dict[str, int] = {}
    for sch in settings.reports.schedules:
        scheduled[sch.report_type.value] = scheduled.get(sch.report_type.value, 0) + 1
    now = datetime.now(UTC)
    tz = settings.display.zone()
    reached = reach(ctx, now)
    latest = now.astimezone(tz).date() - timedelta(days=1)

    def first(s: ReportSpec) -> date | None:
        own = first_day(earliest_start(settings, s, now, reached), tz)
        if s.reads_events:  # not refused: a period before the events kept shows its gaps; the picker starts there
            floor = now - timedelta(days=settings.collection.retention.event_days)
            events = first_day(min(floor, reached["events"]) if "events" in reached else floor, tz)
            # a type with a limit of its own as well (the weekly overview) is refused before it: the later of the two
            return max(own, events) if own is not None and events is not None else events
        return own

    return Catalog(entries=[CatalogEntry(report_type=t, group=s.group, available=avail.get(t) is None,
                                         reason_key=avail.get(t), accepts_filter=s.accepts_filter,
                                         requires_app=s.requires_app,
                                         max_lookback=s.max_lookback(settings) if s.max_lookback else None,
                                         earliest_day=first(s), latest_day=latest,
                                         formats=list(s.formats), ui_group=UI_GROUPS.get(s.group, "traffic"),  # type: ignore[arg-type]
                                         tier="common" if t in COMMON else "topic",
                                         mode="on_demand" if s.needs_traffic or s.own_traffic else "basic",
                                         schedules=scheduled.get(t.value, 0), copies=copies.get(t.value, 0))
                            for t, s in specs().items()],
                   smtp_enabled=settings.alerts.channels.smtp.enabled,
                   gui_external_url_set=bool(settings.reports.gui_external_url))


def _item(ctx: AppContext, row: store.ReportRow) -> ReportItem:
    names = {s.id: s.name for s in ctx.settings.current().reports.schedules}
    lang = row.params.get("lang")
    custom_id = row.params.get("custom_id")
    custom = custom_reports.get(ctx, int(custom_id)) if isinstance(custom_id, int) else None
    return ReportItem(id=row.id, report_type=row.report_type, status=row.status, trigger=row.trigger,
                      schedule_id=row.schedule_id, schedule_name=names.get(row.schedule_id or ""),
                      pce_label=row.pce_label, period_start=row.period_start, period_end=row.period_end,
                      created_at=row.created_at, finished_at=row.finished_at, error_key=row.error_key,
                      error_detail=row.error_detail, files=row.files, email_status=row.email_status,
                      email_detail=row.email_detail,
                      lookback_days=None if row.params.get("period_from") else row.params.get("lookback_days"),
                      lang=Language(lang) if lang else None, custom_name=custom.name if custom else None,
                      conclusion=row.conclusion)


def list_reports(ctx: AppContext, *, page: int) -> ReportPage:
    with ctx.db() as conn:
        rows, total = store.list_reports(conn, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
    return ReportPage(items=[_item(ctx, r) for r in rows], total=total, page=page, page_size=PAGE_SIZE)


def get_report(ctx: AppContext, report_id: int) -> ReportItem | None:
    with ctx.db() as conn:
        row = store.get(conn, report_id)
    return _item(ctx, row) if row else None


def generate_now(ctx: AppContext, params: ReportParams) -> ReportItem:
    rid = enqueue(ctx, params, trigger="manual", schedule_id=None, now=datetime.now(UTC))
    found = get_report(ctx, rid)
    assert found is not None
    return found


def report_file(ctx: AppContext, report_id: int, name: str) -> Path | None:
    """The file only when it is one of this report's own (never a path built from the request alone)."""
    item = get_report(ctx, report_id)
    if item is None or item.status is not ReportStatus.DONE or name not in item.files:
        return None
    path = ctx.paths.reports_dir / str(report_id) / name
    return path if path.is_file() else None
