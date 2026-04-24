"""BackgroundScheduler factory for illumio_ops daemon."""
from __future__ import annotations

from loguru import logger

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.executors.pool import ThreadPoolExecutor

from src.scheduler.jobs import (
    run_monitor_cycle,
    tick_report_schedules,
    tick_rule_schedules,
)
from src.siem.preview import emit_preview_warning
from src.i18n import t

def build_scheduler(cm, interval_minutes: int = 10) -> BackgroundScheduler:
    """Factory for a BackgroundScheduler wired with illumio_ops jobs.

    Does NOT call sched.start() — caller owns lifecycle.
    When config.scheduler.persist=true, uses SQLAlchemyJobStore so jobs
    survive daemon restarts (requires SQLAlchemy installed).
    """
    import os

    rule_interval = cm.config.get("rule_scheduler", {}).get("check_interval_seconds", 300)
    sched_cfg = cm.config.get("scheduler", {}) or {}

    executors = {"default": ThreadPoolExecutor(max_workers=5)}
    job_defaults = {
        "coalesce": True,          # if we miss ticks during suspension, run just once
        "max_instances": 1,        # prevent concurrent re-entry
        "misfire_grace_time": 60,  # allow up to 60s late fire
    }

    kwargs: dict = {"executors": executors, "job_defaults": job_defaults}

    if sched_cfg.get("persist"):
        try:
            from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
            db_path = sched_cfg.get("db_path", "config/scheduler.db")
            if not os.path.isabs(db_path):
                pkg_dir = os.path.dirname(os.path.abspath(__file__))
                root_dir = os.path.dirname(os.path.dirname(pkg_dir))
                db_path = os.path.join(root_dir, db_path)
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            url = f"sqlite:///{db_path}"
            kwargs["jobstores"] = {"default": SQLAlchemyJobStore(url=url)}
            logger.info("Scheduler using persistent SQLite jobstore: {}", db_path)
        except ImportError:
            logger.warning("scheduler.persist=true but SQLAlchemy not installed; using MemoryJobStore")

    sched = BackgroundScheduler(**kwargs)

    try:
        _cache_enabled = cm.models.pce_cache.enabled
    except Exception as e:
        logger.warning("Cache config unavailable, defaulting to API interval: {}", e)
        _cache_enabled = False

    if _cache_enabled:
        monitor_trigger = IntervalTrigger(seconds=30)
        logger.info(t("monitor_cache_enabled_hint"))
    else:
        monitor_trigger = IntervalTrigger(minutes=interval_minutes)

    sched.add_job(
        run_monitor_cycle,
        trigger=monitor_trigger,
        args=[cm],
        id="monitor_cycle",
        name="Monitor analysis cycle",
        replace_existing=True,
    )
    sched.add_job(
        tick_report_schedules,
        trigger=IntervalTrigger(seconds=60),
        args=[cm],
        id="tick_report_schedules",
        name="Report schedule tick",
        replace_existing=True,
    )
    sched.add_job(
        tick_rule_schedules,
        trigger=IntervalTrigger(seconds=rule_interval),
        args=[cm],
        id="tick_rule_schedules",
        name="Rule schedule tick",
        replace_existing=True,
    )

    try:
        cache_cfg = cm.models.pce_cache
        if cache_cfg.enabled:
            from apscheduler.triggers.interval import IntervalTrigger as _IT
            from src.scheduler.jobs import (
                run_events_ingest, run_traffic_ingest,
                run_traffic_aggregate, run_cache_retention,
            )
            from src.pce_cache.lag_monitor import run_cache_lag_monitor
            sched.add_job(run_events_ingest, _IT(seconds=cache_cfg.events_poll_interval_seconds),
                          args=[cm], id="pce_cache_ingest_events", replace_existing=True)
            sched.add_job(run_traffic_ingest, _IT(seconds=cache_cfg.traffic_poll_interval_seconds),
                          args=[cm], id="pce_cache_ingest_traffic", replace_existing=True)
            sched.add_job(run_traffic_aggregate, _IT(hours=1),
                          args=[cm], id="pce_cache_aggregate", replace_existing=True)
            sched.add_job(run_cache_retention, _IT(hours=24),
                          args=[cm], id="pce_cache_retention", replace_existing=True)
            sched.add_job(run_cache_lag_monitor, _IT(seconds=60),
                          args=[cm], id="cache_lag_monitor", replace_existing=True)
    except Exception as exc:
        logger.exception("Failed to register pce_cache scheduler jobs: {}", exc)

    try:
        siem_cfg = cm.models.siem
        if siem_cfg.enabled:
            emit_preview_warning(cm, context="scheduler_startup")
            from apscheduler.triggers.interval import IntervalTrigger as _IT
            from src.scheduler.jobs import run_siem_dispatch
            sched.add_job(run_siem_dispatch, _IT(seconds=siem_cfg.dispatch_tick_seconds),
                          args=[cm], id="siem_dispatch", replace_existing=True)
    except Exception as exc:
        logger.exception("Failed to register SIEM scheduler jobs: {}", exc)

    logger.info(
        "Scheduler built: monitor=%dm report=60s rule=%ds persist=%s",
        interval_minutes,
        rule_interval,
        bool(sched_cfg.get("persist")),
    )
    return sched
