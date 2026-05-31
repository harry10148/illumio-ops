"""Tests for APScheduler SQLAlchemy persistent jobstore configuration."""

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


class TestSchedulerPersistence:
    def test_sqlalchemy_jobstore_configured_when_persist_true(self, tmp_path):
        """build_scheduler wires SQLAlchemyJobStore when persist=True."""
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        from src.scheduler import build_scheduler

        db = tmp_path / "sched.db"
        cm = _make_cm(db)
        sched = build_scheduler(cm, interval_minutes=5)
        store = sched._jobstores.get("default")
        assert isinstance(store, SQLAlchemyJobStore), \
            f"expected SQLAlchemyJobStore, got {type(store)}"

    def test_memory_jobstore_when_persist_false(self, tmp_path):
        """build_scheduler uses MemoryJobStore (default) when persist=False."""
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        from src.scheduler import build_scheduler

        cm = _make_cm(tmp_path / "sched.db", persist=False)
        sched = build_scheduler(cm, interval_minutes=5)
        store = sched._jobstores.get("default")
        assert not isinstance(store, SQLAlchemyJobStore)

    def test_three_jobs_registered(self, tmp_path):
        """build_scheduler registers core jobs (monitor, report, rule, ven_summary)."""
        from src.scheduler import build_scheduler

        cm = _make_cm(tmp_path / "sched.db")
        sched = build_scheduler(cm, interval_minutes=5)
        # Pending jobs are accessible before start
        job_ids = {j.id for j in sched.get_jobs(jobstore=None)}
        required = {"monitor_cycle", "tick_report_schedules", "tick_rule_schedules", "ven_summary"}
        assert required.issubset(job_ids), f"Missing jobs: {required - job_ids}"

    def test_db_dir_created(self, tmp_path):
        """build_scheduler creates parent directories for the DB path."""
        from src.scheduler import build_scheduler

        db = tmp_path / "subdir" / "nested" / "sched.db"
        cm = _make_cm(db)
        build_scheduler(cm, interval_minutes=5)
        assert db.parent.exists()

    def test_scheduler_settings_in_config_schema(self):
        """SchedulerSettings is part of ConfigSchema (pydantic round-trip)."""
        from src.config_models import ConfigSchema
        schema = ConfigSchema.model_validate({})
        assert hasattr(schema, "scheduler")
        assert schema.scheduler.persist is False
        assert schema.scheduler.db_path == "config/scheduler.db"
