"""C.5.4 驗證：run_schedule 用 `with ApiClient(cm) as api:` 確保排程結束後關閉
HTTP session（比照 src/scheduler/jobs.py 既有慣例），避免每次排程報表洩漏連線。
"""
from __future__ import annotations

from types import SimpleNamespace

from src.config_models import ConfigSchema
from src.report_scheduler import ReportScheduler


class _DummyReporter:
    pass


def _make_cm(tmp_path):
    # models: ApiClient.__init__ 直讀 cm.models.pce_cache.rate_limit_per_minute；
    # 真實 ConfigManager 一定有 .models，替身也必須遵守這個型別合約。
    cm = SimpleNamespace(models=ConfigSchema())
    cm.config = {
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "report": {"output_dir": str(tmp_path)},
        "settings": {},
    }
    return cm


def test_run_schedule_closes_api_client(tmp_path, monkeypatch):
    scheduler = ReportScheduler(_make_cm(tmp_path), _DummyReporter())
    captured = {}

    def fake_generate_report(self, report_type, api, fmt, output_dir, start_date,
                              end_date, name, filters=None, lang="en", schedule=None):
        captured["api"] = api
        # api must still be usable (session open) while inside the `with` block
        assert api._session is not None
        return SimpleNamespace(record_count=1), [str(tmp_path / "report.html")]

    monkeypatch.setattr(ReportScheduler, "_generate_report", fake_generate_report)
    monkeypatch.setattr(scheduler, "_prune_by_count", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "_prune_old_reports", lambda *a, **k: None)

    ok = scheduler.run_schedule({"id": 1, "name": "t", "report_type": "traffic",
                                 "format": ["html"], "email_report": False})

    assert ok is True
    assert "api" in captured, "ApiClient never reached _generate_report"
    assert captured["api"]._session is None, "ApiClient session was not closed after run_schedule"


def test_run_schedule_closes_api_client_even_on_failure(tmp_path, monkeypatch):
    """The ApiClient must be closed even when report generation raises."""
    scheduler = ReportScheduler(_make_cm(tmp_path), _DummyReporter())
    captured = {}

    def fake_generate_report(self, report_type, api, fmt, output_dir, start_date,
                              end_date, name, filters=None, lang="en", schedule=None):
        captured["api"] = api
        raise RuntimeError("boom")

    monkeypatch.setattr(ReportScheduler, "_generate_report", fake_generate_report)

    try:
        scheduler.run_schedule({"id": 1, "name": "t", "report_type": "traffic",
                                "format": ["html"], "email_report": False})
    except RuntimeError:
        pass

    assert "api" in captured
    assert captured["api"]._session is None, "ApiClient session was not closed on failure path"
