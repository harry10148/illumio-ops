"""Rule scheduling (UI redesign spec §4.5): the schedules of the current PCE with their state, the targets to pick from,
and create / change / pause / resume / delete. Writes need the optional write key; a refusal from the PCE is answered
with its status and words."""
from __future__ import annotations

from flask import Blueprint, request
from flask_login import current_user
from pydantic import BaseModel, Field

from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.services import rule_schedule_targets as targets
from illumio_ops.services import rule_schedules as rs
from illumio_ops.services.rule_schedule_targets import TargetSearch
from illumio_ops.services.rule_schedules import (
    DeleteResult,
    PlanField,
    RunView,
    ScheduleOverview,
    ScheduleView,
)
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, Empty, api_route, operation


class RuleSchedulesView(BaseModel):
    overview: ScheduleOverview
    items: list[ScheduleView]


class ScheduleCreate(BaseModel):
    href: str = Field(pattern=r"^/orgs/\d+/sec_policy/(active|draft)/rule_sets/\d+(/sec_rules/\d+)?$")
    plan: PlanField
    name: str = Field(min_length=1, max_length=200)
    ruleset_name: str = Field(max_length=200)
    summary: str = Field(max_length=1000)


class RunList(BaseModel):
    items: list[RunView]


OP_LIST = operation("rule_schedules.list", "GET", "/api/rule-schedules", None, RuleSchedulesView)
OP_TARGETS = operation("rule_schedules.targets", "GET", "/api/rule-schedules/targets", None, TargetSearch)
OP_RUNS = operation("rule_schedules.runs", "GET", "/api/rule-schedules/runs", None, RunList)
OP_CREATE = operation("rule_schedules.create", "POST", "/api/rule-schedules", ScheduleCreate, ScheduleView)
OP_PAUSE = operation("rule_schedules.pause", "POST", "/api/rule-schedules/<int:schedule_id>/pause", Empty, ScheduleView)
OP_RESUME = operation("rule_schedules.resume", "POST", "/api/rule-schedules/<int:schedule_id>/resume", Empty,
                      ScheduleView)
OP_DELETE = operation("rule_schedules.delete", "DELETE", "/api/rule-schedules/<int:schedule_id>", None, DeleteResult)

bp = Blueprint("rule_schedules", __name__)


def _mapped(exc: Exception) -> ApiFailure:
    if isinstance(exc, rs.NoWriteKey | PceNotConfigured):
        return ApiFailure(412, "no_write_key", "rs_err_no_write_key")
    if isinstance(exc, rs.DraftPending):
        return ApiFailure(409, "draft_pending", "rs_err_draft_pending")
    if isinstance(exc, rs.AlreadyScheduled):
        return ApiFailure(409, "already_scheduled", "rs_err_already_scheduled")
    if isinstance(exc, rs.NotProvisioned):
        return ApiFailure(409, "not_provisioned", "rs_err_not_provisioned")
    if isinstance(exc, rs.PceRefused):
        return ApiFailure(502, "pce_refused", "rs_err_pce_refused",
                          params={"status": str(exc.status or "—"), "detail": exc.detail})
    return ApiFailure(404, "not_found", "rs_err_not_found")


@api_route(bp, OP_LIST)
def list_schedules() -> RuleSchedulesView:
    overview, items = rs.schedules(get_ctx())
    return RuleSchedulesView(overview=overview, items=items)


@api_route(bp, OP_TARGETS)
def search_targets() -> TargetSearch:
    q = request.args.get("q", "")
    if len(q) > 200:
        raise ApiFailure(400, "invalid_input", "err_invalid_input", field="q")
    try:
        return targets.search(get_ctx(), q)
    except PceNotConfigured:
        raise ApiFailure(409, "pce_not_configured", "err_pce_not_configured") from None


@api_route(bp, OP_RUNS)
def list_runs() -> RunList:
    raw = request.args.get("schedule_id")
    return RunList(items=rs.runs(get_ctx(), schedule_id=int(raw) if raw and raw.isdigit() else None))


@api_route(bp, OP_CREATE)
def create(body: ScheduleCreate) -> ScheduleView:
    try:
        return rs.create(get_ctx(), href=body.href, plan=body.plan, name=body.name, ruleset_name=body.ruleset_name,
                         summary=body.summary, by=str(current_user.get_id()))
    except (rs.NoWriteKey, PceNotConfigured, rs.DraftPending, rs.AlreadyScheduled, rs.NotProvisioned,
            rs.PceRefused) as exc:
        raise _mapped(exc) from None


@api_route(bp, OP_PAUSE)
def pause(body: Empty, schedule_id: int) -> ScheduleView:
    try:
        return rs.set_paused(get_ctx(), schedule_id, True)
    except LookupError as exc:
        raise _mapped(exc) from None


@api_route(bp, OP_RESUME)
def resume(body: Empty, schedule_id: int) -> ScheduleView:
    try:
        return rs.set_paused(get_ctx(), schedule_id, False)
    except LookupError as exc:
        raise _mapped(exc) from None


@api_route(bp, OP_DELETE)
def delete(schedule_id: int) -> DeleteResult:
    try:
        return rs.delete(get_ctx(), schedule_id, by=str(current_user.get_id()))
    except LookupError as exc:
        raise _mapped(exc) from None
