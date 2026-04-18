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

def build_scheduler(cm, interval_minutes: int = 10) -> BackgroundScheduler:
    """Factory for a BackgroundScheduler wired with illumio_ops jobs.

    Does NOT call sched.start() — caller owns lifecycle.
    """
    rule_interval = cm.config.get("rule_scheduler", {}).get("check_interval_seconds", 300)

    executors = {"default": ThreadPoolExecutor(max_workers=5)}
    job_defaults = {
        "coalesce": True,          # if we miss ticks during suspension, run just once
        "max_instances": 1,        # prevent concurrent re-entry
        "misfire_grace_time": 60,  # allow up to 60s late fire
    }

    sched = BackgroundScheduler(executors=executors, job_defaults=job_defaults)

    sched.add_job(
        run_monitor_cycle,
        trigger=IntervalTrigger(minutes=interval_minutes),
        args=[cm],
        id="monitor_cycle",
        name="Monitor analysis cycle",
    )
    sched.add_job(
        tick_report_schedules,
        trigger=IntervalTrigger(seconds=60),
        args=[cm],
        id="tick_report_schedules",
        name="Report schedule tick",
    )
    sched.add_job(
        tick_rule_schedules,
        trigger=IntervalTrigger(seconds=rule_interval),
        args=[cm],
        id="tick_rule_schedules",
        name="Rule schedule tick",
    )

    logger.info(
        "Scheduler built: monitor=%dm report=60s rule=%ds",
        interval_minutes,
        rule_interval,
    )
    return sched
