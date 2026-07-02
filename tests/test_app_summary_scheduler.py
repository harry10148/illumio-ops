"""Scheduler support for the app_summary report type.

Covers:
- _generate_report dispatches app_summary → AppSummaryReport.run(app=..., env=...)
- a tick() run of an app_summary schedule missing 'app' records an ERROR
  state (does not crash the scheduler).
"""
from __future__ import annotations

from types import SimpleNamespace

import src.report_scheduler as rs
from src.report_scheduler import ReportScheduler


class _DummyConfigManager:
    def __init__(self):
        self.config = {
            "report": {"output_dir": "reports"},
            "settings": {},
        }

    def load(self):
        pass


def _make_scheduler():
    return ReportScheduler(_DummyConfigManager(), reporter=None)


def test_generate_report_dispatches_app_summary(monkeypatch, tmp_path):
    sched = _make_scheduler()

    calls = {}

    class _FakeAppSummary:
        def __init__(self, cm, api_client=None, config_dir="config", cache_reader=None):
            calls["init"] = {"config_dir": config_dir}

        def run(self, app, env=None, output_dir="reports", lang="en"):
            calls["run"] = {"app": app, "env": env, "output_dir": output_dir, "lang": lang}
            return str(tmp_path / "Illumio_App_Summary_DB.html")

    import src.report.app_summary_report as asr_mod
    monkeypatch.setattr(asr_mod, "AppSummaryReport", _FakeAppSummary)
    monkeypatch.setattr("src.main._make_cache_reader", lambda cm: None)

    result, paths = sched._generate_report(
        report_type="app_summary",
        api=object(),
        fmt="html",
        output_dir=str(tmp_path),
        start_date="2026-04-01T00:00:00Z",
        end_date="2026-04-08T23:59:59Z",
        name="DB App",
        lang="en",
        schedule={"app": "DB", "env": "Production"},
    )

    assert calls["run"]["app"] == "DB"
    assert calls["run"]["env"] == "Production"
    assert result.record_count == 1
    assert paths == [str(tmp_path / "Illumio_App_Summary_DB.html")]


def test_app_summary_schedule_missing_app_records_error(monkeypatch):
    cm = _DummyConfigManager()
    cm.config = {
        "settings": {},
        "report": {"output_dir": "reports"},
        "report_schedules": [
            {
                "id": 42,
                "name": "Bad App Summary",
                "enabled": True,
                "report_type": "app_summary",
                # NOTE: no "app" key
                "schedule_type": "daily",
                "hour": 8,
                "minute": 0,
            }
        ],
    }
    sched = ReportScheduler(cm, reporter=None)
    monkeypatch.setattr(sched, "should_run", lambda s, now: True)
    # ApiClient is constructed in run_schedule before dispatch (as a context
    # manager, see run_schedule's `with ApiClient(cm) as api:`); stub it with a
    # minimal context-manager fake so the missing-app ValueError (not an
    # ApiClient error) is what gets recorded.
    class _FakeApiClient:
        def __init__(self, cm):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("src.api_client.ApiClient", _FakeApiClient)

    saved = {}

    def _fake_save(schedule_id, last_run, status, error=""):
        saved["id"] = schedule_id
        saved["status"] = status
        saved["error"] = error

    monkeypatch.setattr(sched, "_save_state", _fake_save)

    # Must not raise out of tick()
    sched.tick()

    assert saved["status"] == "failed"
    assert "app" in saved["error"].lower()
