"""In-process scheduler. Every job runs through instrument(): its start, end and failure
land in job_health, and a failing job never takes the scheduler down with it."""
from __future__ import annotations

import traceback
from collections.abc import Callable
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

from illumio_ops.jobs.health import record_finish, record_start
from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.services import pce_health
from illumio_ops.services.context import AppContext

# job id -> interval in seconds (the home page and the jobs page read this too)
JOB_INTERVALS: dict[str, int] = {
    "pce_probe": 300,
}


def instrument(job_id: str, fn: Callable[[], None], ctx: AppContext) -> Callable[[], None]:
    def run() -> None:
        with ctx.db() as conn:
            record_start(conn, job_id, datetime.now(UTC))
        error: str | None = None
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - job boundary: record every failure, never propagate
            logger.error("job {} failed: {}", job_id, traceback.format_exc())
            error = f"{type(exc).__name__}: {exc}"[:500]
        with ctx.db() as conn:
            record_finish(conn, job_id, datetime.now(UTC), error)

    run.__name__ = f"job_{job_id}"
    return run


def _probe_job(ctx: AppContext) -> Callable[[], None]:
    def probe() -> None:
        try:
            pce_health.run_probe(ctx)
        except PceNotConfigured:
            return  # nothing to check yet; not a failure
    return probe


def build_scheduler(ctx: AppContext) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=UTC, job_defaults={"coalesce": True, "max_instances": 1})
    # coalesce/max_instances are passed per job: job_defaults only apply once the
    # scheduler starts, and a job must never pile up behind a slow previous run.
    sched.add_job(instrument("pce_probe", _probe_job(ctx), ctx), "interval", id="pce_probe",
                  seconds=JOB_INTERVALS["pce_probe"], next_run_time=datetime.now(UTC),
                  coalesce=True, max_instances=1)
    return sched
