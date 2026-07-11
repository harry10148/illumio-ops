"""Scheduler dispatch for the readiness report type."""
from __future__ import annotations

from src.report_scheduler import ReportScheduler


class _DummyConfigManager:
    def __init__(self):
        self.config = {"report": {"output_dir": "reports"}, "settings": {}}

    def load(self):
        pass


def _make_scheduler():
    return ReportScheduler(_DummyConfigManager(), reporter=None)


def test_generate_report_dispatches_readiness(monkeypatch, tmp_path):
    sched = _make_scheduler()
    calls = {}

    class _FakeResult:
        record_count = 9

    class _FakeGen:
        def __init__(self, cm, api_client=None, config_dir="config", cache_reader=None):
            calls["init"] = True

        def generate_from_api(self, start_date=None, end_date=None, lang="en",
                              use_cache=True, output_dir="reports"):
            calls["lang"] = lang
            calls["trend_out"] = output_dir
            return _FakeResult()

        def export(self, result, fmt="html", output_dir="reports", lang=None):
            calls["fmt"] = fmt
            return [str(tmp_path / "Illumio_Readiness_Report_x.html")]

    import src.report.readiness_report as mod
    monkeypatch.setattr(mod, "ReadinessReportGenerator", _FakeGen)
    monkeypatch.setattr("src.main._make_cache_reader", lambda cm: None)

    result, paths = sched._generate_report(
        report_type="readiness", api=object(), fmt="html",
        output_dir=str(tmp_path), start_date="2026-07-01T00:00:00Z",
        end_date="2026-07-08T23:59:59Z", name="Readiness", lang="zh_TW")

    assert calls["lang"] == "zh_TW"
    assert calls["trend_out"] == str(tmp_path)
    assert result.record_count == 9
    assert paths == [str(tmp_path / "Illumio_Readiness_Report_x.html")]


def test_zero_records_skips_export(monkeypatch, tmp_path):
    sched = _make_scheduler()

    class _FakeGen:
        def __init__(self, cm, api_client=None, config_dir="config", cache_reader=None):
            pass

        def generate_from_api(self, **kw):
            class _R:
                record_count = 0
            return _R()

    import src.report.readiness_report as mod
    monkeypatch.setattr(mod, "ReadinessReportGenerator", _FakeGen)
    monkeypatch.setattr("src.main._make_cache_reader", lambda cm: None)

    result, paths = sched._generate_report(
        report_type="readiness", api=object(), fmt="html",
        output_dir=str(tmp_path), start_date=None, end_date=None,
        name="Readiness empty", lang="en")
    assert result is None and paths == []


def test_readiness_prefix_registered():
    assert ReportScheduler._REPORT_PREFIXES["readiness"] == "Illumio_Readiness_Report_"
