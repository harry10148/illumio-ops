"""Report schedules (create / update / delete / run now; the settings file holds them, so a write is validated as a
whole and guarded by its revision) and the report settings (GUI address for email links, how long reports are kept)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from flask import Blueprint
from pydantic import BaseModel, Field

from illumio_ops.domain.values import ReportStatus
from illumio_ops.services.reports import schedules
from illumio_ops.services.reports.generate import REFUSAL_FIELDS, refusal
from illumio_ops.services.reports.views import ReportItem, get_report
from illumio_ops.settings.schema import ReportSchedule, ReportScheduleFields
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation


class ScheduleItem(BaseModel):
    schedule: ReportSchedule
    next_run: datetime | None
    last_report_id: int | None
    last_status: ReportStatus | None
    last_finished_at: datetime | None
    consecutive_failures: int


class SchedulesView(BaseModel):
    revision: int
    items: list[ScheduleItem]
    smtp_enabled: bool


class ScheduleWrite(BaseModel):
    revision: int
    schedule: ReportScheduleFields


class ScheduleDelete(BaseModel):
    revision: int


class RunNow(BaseModel):
    pass


class ReportSettingsView(BaseModel):
    revision: int
    gui_external_url: str
    retention_days: int


class ReportSettingsUpdate(BaseModel):
    revision: int
    gui_external_url: str = Field(max_length=500)
    retention_days: int = Field(ge=1, le=3650)


OP_LIST = operation("report_schedules.list", "GET", "/api/report-schedules", None, SchedulesView)
OP_CREATE = operation("report_schedules.create", "POST", "/api/report-schedules", ScheduleWrite, SchedulesView)
OP_UPDATE = operation("report_schedules.update", "PUT", "/api/report-schedules/<schedule_id>", ScheduleWrite,
                      SchedulesView)
OP_DELETE = operation("report_schedules.delete", "DELETE", "/api/report-schedules/<schedule_id>", ScheduleDelete,
                      SchedulesView)
OP_RUN = operation("report_schedules.run_now", "POST", "/api/report-schedules/<schedule_id>/run", RunNow, ReportItem)
OP_SETTINGS_GET = operation("system.reports.get", "GET", "/api/system/reports", None, ReportSettingsView)
OP_SETTINGS_UPDATE = operation("system.reports.update", "PUT", "/api/system/reports", ReportSettingsUpdate,
                               ReportSettingsView)

bp = Blueprint("report_schedules", __name__)


def _view() -> SchedulesView:
    ctx = get_ctx()
    s = ctx.settings.current()
    status = schedules.schedule_status(ctx)
    items = [ScheduleItem(schedule=x, **vars(status[x.id])) for x in s.reports.schedules]
    return SchedulesView(revision=s.revision, items=items, smtp_enabled=s.alerts.channels.smtp.enabled)


def _check(fields: ReportScheduleFields) -> None:
    """The same refusal a manual request gets, at save time (a schedule that could never run is not saved)."""
    params = schedules.params_of(ReportSchedule(**fields.model_dump(), id="0" * 32))
    reason = refusal(get_ctx().settings.current(), params)
    if reason:
        raise ApiFailure(400, "invalid_input", reason, field=f"schedule.{REFUSAL_FIELDS[reason]}")


def _list(d: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = d["reports"]["schedules"]
    return items


@api_route(bp, OP_LIST)
def list_schedules() -> SchedulesView:
    return _view()


@api_route(bp, OP_CREATE)
def create_schedule(body: ScheduleWrite) -> SchedulesView:
    _check(body.schedule)
    new = body.schedule.model_dump(mode="json") | {"id": uuid.uuid4().hex}
    get_ctx().settings.update(body.revision, lambda d: _list(d).append(new))
    return _view()


@api_route(bp, OP_UPDATE)
def update_schedule(body: ScheduleWrite, schedule_id: str) -> SchedulesView:
    _check(body.schedule)
    def mutate(d: dict[str, Any]) -> None:
        items = _list(d)
        for i, old in enumerate(items):
            if old["id"] == schedule_id:
                items[i] = body.schedule.model_dump(mode="json") | {"id": schedule_id}
                return
        raise ApiFailure(404, "not_found", "err_not_found")
    get_ctx().settings.update(body.revision, mutate)
    return _view()


@api_route(bp, OP_DELETE)
def delete_schedule(body: ScheduleDelete, schedule_id: str) -> SchedulesView:
    """The schedule's reports already made stay (they list the schedule as deleted)."""
    def mutate(d: dict[str, Any]) -> None:
        items = _list(d)
        kept = [x for x in items if x["id"] != schedule_id]
        if len(kept) == len(items):
            raise ApiFailure(404, "not_found", "err_not_found")
        d["reports"]["schedules"] = kept
    get_ctx().settings.update(body.revision, mutate)
    return _view()


@api_route(bp, OP_RUN)
def run_now(body: RunNow, schedule_id: str) -> ReportItem:
    ctx = get_ctx()
    rid = schedules.run_now(ctx, schedule_id)
    found = get_report(ctx, rid) if rid is not None else None
    if found is None:
        raise ApiFailure(404, "not_found", "err_not_found")
    return found


def _settings_view() -> ReportSettingsView:
    s = get_ctx().settings.current()
    return ReportSettingsView(revision=s.revision, gui_external_url=s.reports.gui_external_url,
                              retention_days=s.reports.retention_days)


@api_route(bp, OP_SETTINGS_GET)
def get_settings() -> ReportSettingsView:
    return _settings_view()


@api_route(bp, OP_SETTINGS_UPDATE)
def update_settings(body: ReportSettingsUpdate) -> ReportSettingsView:
    get_ctx().settings.update(body.revision, lambda d: d["reports"].update(
        gui_external_url=body.gui_external_url, retention_days=body.retention_days))
    return _settings_view()
