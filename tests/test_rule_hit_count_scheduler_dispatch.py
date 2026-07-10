"""Scheduler dispatch for the rule_hit_count report type (native-only, no prompts)."""
from __future__ import annotations

from src.report_scheduler import ReportScheduler
from src.report.rule_hit_count_enablement import EnablementStatus, RuleHitCountNotEnabled


class _DummyConfigManager:
    def __init__(self):
        self.config = {"report": {"output_dir": "reports"}, "settings": {}}

    def load(self):
        pass


def _make_scheduler():
    return ReportScheduler(_DummyConfigManager(), reporter=None)


def test_generate_report_dispatches_rule_hit_count(monkeypatch, tmp_path):
    sched = _make_scheduler()
    calls = {}

    class _FakeResult:
        record_count = 4

    class _FakeGen:
        def __init__(self, cm, api_client=None, config_dir="config"):
            calls["init"] = True

        def generate_from_native(self, start_date=None, end_date=None, lang="en"):
            calls["lang"] = lang
            return _FakeResult()

        def export(self, result, fmt="html", output_dir="reports", lang=None):
            calls["fmt"] = fmt
            calls["out"] = output_dir
            return [str(tmp_path / "Illumio_Rule_Hit_Count_Report_x.html")]

    import src.report.rule_hit_count_generator as rhc_mod
    monkeypatch.setattr(rhc_mod, "RuleHitCountGenerator", _FakeGen)
    monkeypatch.setattr("src.main._make_cache_reader", lambda cm: None)

    result, paths = sched._generate_report(
        report_type="rule_hit_count", api=object(), fmt="html",
        output_dir=str(tmp_path), start_date="2026-06-01T00:00:00Z",
        end_date="2026-07-01T23:59:59Z", name="RHC", lang="en")

    assert calls["lang"] == "en"
    assert calls["out"] == str(tmp_path)
    assert result.record_count == 4
    assert paths == [str(tmp_path / "Illumio_Rule_Hit_Count_Report_x.html")]


def test_not_enabled_skips_without_prompting(monkeypatch, tmp_path):
    sched = _make_scheduler()

    class _FakeGen:
        def __init__(self, cm, api_client=None, config_dir="config"):
            pass

        def generate_from_native(self, start_date=None, end_date=None, lang="en"):
            raise RuleHitCountNotEnabled(
                EnablementStatus("disabled", False, False, "off"))

    import src.report.rule_hit_count_generator as rhc_mod
    monkeypatch.setattr(rhc_mod, "RuleHitCountGenerator", _FakeGen)
    monkeypatch.setattr("src.main._make_cache_reader", lambda cm: None)

    result, paths = sched._generate_report(
        report_type="rule_hit_count", api=object(), fmt="html",
        output_dir=str(tmp_path), start_date=None, end_date=None,
        name="RHC off", lang="en")
    assert result is None
    assert paths == []


def test_rule_hit_count_prefix_registered():
    assert ReportScheduler._REPORT_PREFIXES["rule_hit_count"] == "Illumio_Rule_Hit_Count_Report_"
