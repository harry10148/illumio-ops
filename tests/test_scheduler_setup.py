"""Tests for APScheduler factory — runs failing before src/scheduler is created."""
import pytest
from unittest.mock import MagicMock
from apscheduler.schedulers.base import STATE_STOPPED


def _fake_cm(rule_check_interval=300):
    cm = MagicMock()
    cm.config = {
        "api": {"url": "https://pce", "org_id": "1", "key": "k", "secret": "s", "verify_ssl": False},
        "rule_scheduler": {"check_interval_seconds": rule_check_interval},
        "settings": {"timezone": "UTC"},
    }
    cm.models.pce_cache.enabled = False
    cm.models.siem.enabled = False
    return cm


def test_build_scheduler_returns_background_scheduler():
    from src.scheduler import build_scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    cm = _fake_cm()
    sched = build_scheduler(cm, interval_minutes=10)
    assert isinstance(sched, BackgroundScheduler)


def test_build_scheduler_registers_three_jobs():
    from src.scheduler import build_scheduler
    cm = _fake_cm()
    sched = build_scheduler(cm, interval_minutes=10)
    job_ids = {j.id for j in sched.get_jobs()}
    assert "monitor_cycle" in job_ids
    assert "tick_report_schedules" in job_ids
    assert "tick_rule_schedules" in job_ids


def test_monitor_job_uses_interval_trigger():
    from src.scheduler import build_scheduler
    sched = build_scheduler(_fake_cm(), interval_minutes=5)
    job = sched.get_job("monitor_cycle")
    assert job.trigger.interval.total_seconds() == 300


def test_report_tick_runs_every_60s():
    from src.scheduler import build_scheduler
    sched = build_scheduler(_fake_cm(), interval_minutes=10)
    assert sched.get_job("tick_report_schedules").trigger.interval.total_seconds() == 60


def test_rule_tick_uses_configured_interval():
    from src.scheduler import build_scheduler
    cm = _fake_cm(rule_check_interval=180)
    sched = build_scheduler(cm, interval_minutes=10)
    assert sched.get_job("tick_rule_schedules").trigger.interval.total_seconds() == 180


def test_scheduler_not_started_by_factory():
    """build_scheduler must NOT call sched.start() — caller owns lifecycle."""
    from src.scheduler import build_scheduler
    sched = build_scheduler(_fake_cm(), interval_minutes=10)
    assert sched.state == STATE_STOPPED


def test_misfire_grace_time_is_set():
    """I2: misfire_grace_time now comes from job_defaults, not per-job kwargs."""
    from src.scheduler import build_scheduler
    sched = build_scheduler(_fake_cm(), interval_minutes=10)
    assert sched._job_defaults.get("misfire_grace_time") == 60


def test_max_instances_is_one():
    """I2: max_instances now comes from job_defaults, not per-job kwargs."""
    from src.scheduler import build_scheduler
    sched = build_scheduler(_fake_cm(), interval_minutes=10)
    assert sched._job_defaults.get("max_instances") == 1


def test_cache_ingest_jobs_have_next_run_time_within_30s(monkeypatch, tmp_path):
    """Ingest jobs must fire within ~10s of scheduler start, not after
    a full traffic_poll_interval_seconds delay. Otherwise daemon restarts
    keep resetting the timer and ingest never runs."""
    import datetime as _dt
    from src.scheduler import build_scheduler

    class _CM:
        def __init__(self):
            self.config = {"scheduler": {}, "rule_scheduler": {"check_interval_seconds": 300}}
            class _PCE:
                enabled = True
                db_path = str(tmp_path / "c.sqlite")
                events_poll_interval_seconds = 300
                traffic_poll_interval_seconds = 600
                rate_limit_per_minute = 400
                async_threshold_events = 10000
                class _S:
                    sample_ratio_allowed = 1
                    max_rows_per_batch = 200000
                traffic_sampling = _S()
                traffic_filter = type("F", (), {"actions": [], "workload_label_env": [],
                                                "ports": [], "protocols": [], "exclude_src_ips": []})()
                events_retention_days = 90
                traffic_raw_retention_days = 7
                traffic_agg_retention_days = 90
            class _SIEM:
                enabled = False
            self.models = type("M", (), {"pce_cache": _PCE(), "siem": _SIEM()})()

    sched = build_scheduler(_CM(), interval_minutes=10)
    now = _dt.datetime.now(_dt.timezone.utc)
    job = sched.get_job("pce_cache_ingest_traffic")
    assert job is not None
    delta = (job.next_run_time - now).total_seconds()
    assert -5 <= delta <= 30, f"expected first fire within ~30s of start; got delta={delta}s"
