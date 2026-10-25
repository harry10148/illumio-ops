"""In-process scheduler. Every job runs through instrument(): its start, end and failure
land in job_health, and a failing job never takes the scheduler down with it."""
from __future__ import annotations

import traceback
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

from illumio_ops.jobs.health import record_finish, record_start
from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.services import pce_health
from illumio_ops.services.analysis.detect import run_detection
from illumio_ops.services.analysis.hourly import run_hourly_analysis
from illumio_ops.services.collect.archive import run_archive
from illumio_ops.services.collect.backfill import ensure_initial_backfill
from illumio_ops.services.collect.events import run_events_cycle
from illumio_ops.services.collect.inventory import run_inventory_cycle
from illumio_ops.services.collect.reread import ensure_daily_reread, last_reread_day
from illumio_ops.services.collect.reset import finish_pending_switch
from illumio_ops.services.collect.retention import run_retention
from illumio_ops.services.collect.traffic import run_traffic_cycle
from illumio_ops.services.context import AppContext
from illumio_ops.settings.schema import Settings
from illumio_ops.web.tls import ensure_self_signed

PCE_PROBE_SECONDS = 300
TLS_RENEW_SECONDS = 86400
DAILY_SECONDS = 86400
# Checks whether a first backfill (or an interrupted one) or the nightly re-read needs to run;
# cheap when nothing is due.
BACKFILL_CHECK_SECONDS = 600
# Moves committed flow-store pages from the WAL into the database outside the write lock (FlowDb).
FLOWS_CHECKPOINT_SECONDS = 60
# The exposure graph, ransomware overlay, tamper summary and focus list (services.analysis.hourly).
ANALYSIS_HOURLY_SECONDS = 3600
# Collectors wait a little after start-up so the listener and the first probe come first.
COLLECTOR_FIRST_RUN_DELAY = timedelta(seconds=30)


def job_intervals(settings: Settings) -> dict[str, int]:
    """job id -> interval in seconds (the home page and the jobs page read this too)."""
    c = settings.collection
    return {
        "pce_probe": PCE_PROBE_SECONDS,
        "tls_renew_check": TLS_RENEW_SECONDS,
        "collect_traffic": c.traffic_interval_seconds,
        "collect_events": c.events_interval_seconds,
        "collect_inventory": c.inventory_interval_seconds,
        "collect_backfill": BACKFILL_CHECK_SECONDS,
        "collect_archive": DAILY_SECONDS,
        "collect_retention": DAILY_SECONDS,
        "flows_checkpoint": FLOWS_CHECKPOINT_SECONDS,
        "analysis_hourly": ANALYSIS_HOURLY_SECONDS,
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


def _tls_renew_job(ctx: AppContext) -> Callable[[], None]:
    def renew() -> None:
        tls = ctx.settings.current().web.tls
        if tls.enabled and tls.mode == "self_signed" and tls.auto_renew:
            # A renewed certificate is used after the next restart (the listener keeps the
            # one it started with); the certificate page says so.
            ensure_self_signed(ctx.paths.tls_dir, tls)
    return renew


def _collector_jobs(ctx: AppContext) -> dict[str, Callable[[], None]]:
    # Each collector first finishes a PCE switch whose clearing did not complete (services.collect.reset).
    def traffic() -> None:
        finish_pending_switch(ctx)
        run_traffic_cycle(ctx)
        run_detection(ctx)  # the detectors evaluate what the cycle just collected

    def events() -> None:
        finish_pending_switch(ctx)
        run_events_cycle(ctx)

    def inventory() -> None:
        finish_pending_switch(ctx)
        run_inventory_cycle(ctx)

    def backfill() -> None:
        finish_pending_switch(ctx)
        ensure_initial_backfill(ctx)
        reread = ensure_daily_reread(ctx)
        day = last_reread_day(ctx) if reread is not None and reread.rows > 0 else None
        if day is not None:  # records found late are evaluated now, marked late
            start = datetime.combine(day, time(0), UTC)
            run_detection(ctx, window=(start, start + timedelta(days=1)), late=True)

    def archive() -> None:
        run_archive(ctx)

    def retention() -> None:
        run_retention(ctx)

    def checkpoint() -> None:
        ctx.flows().checkpoint()

    def hourly_analysis() -> None:
        run_hourly_analysis(ctx)

    # Archive runs before retention so that, with archiving on, expiring days are written first.
    return {"collect_traffic": traffic, "collect_events": events, "collect_inventory": inventory,
            "collect_backfill": backfill, "collect_archive": archive, "collect_retention": retention,
            "flows_checkpoint": checkpoint, "analysis_hourly": hourly_analysis}


def build_scheduler(ctx: AppContext) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=UTC, job_defaults={"coalesce": True, "max_instances": 1})
    intervals = job_intervals(ctx.settings.current())
    # coalesce/max_instances are passed per job: job_defaults only apply once the
    # scheduler starts, and a job must never pile up behind a slow previous run.
    sched.add_job(instrument("pce_probe", _probe_job(ctx), ctx), "interval", id="pce_probe",
                  seconds=intervals["pce_probe"], next_run_time=datetime.now(UTC),
                  coalesce=True, max_instances=1)
    sched.add_job(instrument("tls_renew_check", _tls_renew_job(ctx), ctx), "interval", id="tls_renew_check",
                  seconds=intervals["tls_renew_check"], coalesce=True, max_instances=1)
    first = datetime.now(UTC) + COLLECTOR_FIRST_RUN_DELAY
    for job_id, fn in _collector_jobs(ctx).items():
        sched.add_job(instrument(job_id, fn, ctx), "interval", id=job_id, seconds=intervals[job_id],
                      next_run_time=first, coalesce=True, max_instances=1)
    return sched


def apply_schedule(sched: BackgroundScheduler, settings: Settings) -> None:
    """Follow interval changes made in settings without restarting the service."""
    for job_id, seconds in job_intervals(settings).items():
        job = sched.get_job(job_id)
        if job is not None and job.trigger.interval.total_seconds() != seconds:
            sched.reschedule_job(job_id, trigger="interval", seconds=seconds)
