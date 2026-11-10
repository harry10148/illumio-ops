"""System › Background jobs, and the focus list the detection page shows."""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint
from pydantic import BaseModel

from illumio_ops.jobs.scheduler import job_intervals
from illumio_ops.services import home
from illumio_ops.services.collect.guard import BindingMismatch
from illumio_ops.services.home import FocusView
from illumio_ops.store.job_health import list_health
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation


class JobView(BaseModel):
    job_id: str
    interval_seconds: int | None
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_ok: bool | None
    last_error: str | None
    runs: int
    failures: int


class JobList(BaseModel):
    jobs: list[JobView]


OP_JOBS = operation("system.jobs.list", "GET", "/api/system/jobs", None, JobList)
OP_FOCUS = operation("home.focus", "GET", "/api/home/focus", None, FocusView)

bp = Blueprint("system_jobs", __name__)


@api_route(bp, OP_JOBS)
def list_jobs() -> JobList:
    ctx = get_ctx()
    intervals = job_intervals(ctx.settings.current())
    with ctx.db() as conn:
        health = {h.job_id: h for h in list_health(conn)}
    out = []
    for job_id in sorted(set(intervals) | set(health)):
        h = health.get(job_id)
        out.append(JobView(
            job_id=job_id,
            interval_seconds=intervals.get(job_id),
            last_started_at=h.last_started_at if h else None,
            last_finished_at=h.last_finished_at if h else None,
            last_ok=h.last_ok if h else None,
            last_error=h.last_error if h else None,
            runs=h.runs if h else 0,
            failures=h.failures if h else 0,
        ))
    return JobList(jobs=out)


@api_route(bp, OP_FOCUS)
def home_focus() -> FocusView:
    try:
        return home.focus_view(get_ctx())
    except BindingMismatch:
        raise ApiFailure(409, "pce_switched", "wb_pce_switched") from None
