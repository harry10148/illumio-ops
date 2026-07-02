"""Tests for scheduler.persist deprecation.

scheduler.persist used to wire a SQLAlchemyJobStore for daemon-restart
durability. It was removed (args=[cm] can't be pickled — ConfigManager holds
an RLock — and every job is interval-typed and rebuilt via
replace_existing=True on each build_scheduler() call, so persistence had no
benefit). The config field is kept for backward compatibility: persist=true
must not prevent the daemon from booting, it just logs a warning.
"""

from __future__ import annotations

from unittest.mock import MagicMock


def _make_cm(tmp_db, persist=True):
    cm = MagicMock()
    cm.config = {
        "api": {"url": "https://p.test", "org_id": "1", "key": "k", "secret": "s"},
        "scheduler": {"persist": persist, "db_path": str(tmp_db)},
        "rule_scheduler": {"check_interval_seconds": 300},
    }
    return cm


class TestSchedulerPersistDeprecated:
    def test_persist_true_boots_with_memory_jobstore(self, tmp_path):
        """persist=true no longer wires SQLAlchemyJobStore; the scheduler still
        boots successfully using the default in-memory job store."""
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        from src.scheduler import build_scheduler

        db = tmp_path / "sched.db"
        cm = _make_cm(db, persist=True)
        sched = build_scheduler(cm, interval_minutes=5)
        store = sched._jobstores.get("default")
        assert not isinstance(store, SQLAlchemyJobStore)

    def test_persist_true_logs_deprecation_warning(self, tmp_path, caplog):
        """persist=true logs a warning instead of silently doing nothing."""
        from src.scheduler import build_scheduler

        cm = _make_cm(tmp_path / "sched.db", persist=True)
        build_scheduler(cm, interval_minutes=5)
        assert any("persist" in rec.message and "deprecated" in rec.message
                    for rec in caplog.records), caplog.text

    def test_persist_false_no_warning(self, tmp_path, caplog):
        """persist=false (default) does not log the deprecation warning."""
        from src.scheduler import build_scheduler

        cm = _make_cm(tmp_path / "sched.db", persist=False)
        build_scheduler(cm, interval_minutes=5)
        assert not any("persist" in rec.message and "deprecated" in rec.message
                        for rec in caplog.records), caplog.text

    def test_three_jobs_registered(self, tmp_path):
        """build_scheduler registers core jobs (monitor, report, rule, ven_summary)
        regardless of persist."""
        from src.scheduler import build_scheduler

        cm = _make_cm(tmp_path / "sched.db")
        sched = build_scheduler(cm, interval_minutes=5)
        # Pending jobs are accessible before start
        job_ids = {j.id for j in sched.get_jobs(jobstore=None)}
        required = {"monitor_cycle", "tick_report_schedules", "tick_rule_schedules", "ven_summary"}
        assert required.issubset(job_ids), f"Missing jobs: {required - job_ids}"

    def test_scheduler_settings_in_config_schema(self):
        """SchedulerSettings is part of ConfigSchema (pydantic round-trip);
        old configs with persist/db_path still validate (deprecated, not rejected)."""
        from src.config_models import ConfigSchema
        schema = ConfigSchema.model_validate({})
        assert hasattr(schema, "scheduler")
        assert schema.scheduler.persist is False
        assert schema.scheduler.db_path == "config/scheduler.db"

        schema_old = ConfigSchema.model_validate({"scheduler": {"persist": True, "db_path": "x.db"}})
        assert schema_old.scheduler.persist is True
