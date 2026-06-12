"""Scheduler dispatch for the policy_diff and policy_resolver report types.

These two types are now selectable in the GUI schedule dropdown; this locks in
that _generate_report routes them to the correct report facade + exporter.

Covers:
- _generate_report dispatches policy_diff → PolicyDiffReport.build + PolicyDiffHtmlExporter.export
- _generate_report dispatches policy_resolver → PolicyResolverReport.resolve + PolicyResolverExporter.export
"""
from __future__ import annotations

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


def test_generate_report_dispatches_policy_diff(monkeypatch, tmp_path):
    sched = _make_scheduler()
    calls = {}

    class _FakeDiffReport:
        def __init__(self, cm, api_client=None, config_dir="config", cache_reader=None):
            calls["init"] = True

        def build(self, lang="en"):
            calls["build_lang"] = lang
            return {"summary": {"total_changes": 3}}

    class _FakeDiffExporter:
        def __init__(self, diff, lang="en"):
            calls["exporter_diff"] = diff
            calls["exporter_lang"] = lang

        def export(self, output_dir):
            calls["export_dir"] = output_dir
            return str(tmp_path / "Illumio_Policy_Diff_Report.html")

    import src.report.policy_diff_report as pdr_mod
    import src.report.exporters.policy_diff_html_exporter as pde_mod
    monkeypatch.setattr(pdr_mod, "PolicyDiffReport", _FakeDiffReport)
    monkeypatch.setattr(pde_mod, "PolicyDiffHtmlExporter", _FakeDiffExporter)
    monkeypatch.setattr("src.main._make_cache_reader", lambda cm: None)

    result, paths = sched._generate_report(
        report_type="policy_diff",
        api=object(),
        fmt="html",
        output_dir=str(tmp_path),
        start_date="2026-04-01T00:00:00Z",
        end_date="2026-04-08T23:59:59Z",
        name="Policy Diff",
        lang="en",
    )

    assert calls["build_lang"] == "en"
    assert calls["export_dir"] == str(tmp_path)
    assert result.record_count == 3
    assert paths == [str(tmp_path / "Illumio_Policy_Diff_Report.html")]


def test_generate_report_dispatches_policy_resolver(monkeypatch, tmp_path):
    sched = _make_scheduler()
    calls = {}

    class _FakeResolverReport:
        def __init__(self, cm, api_client=None, config_dir="config"):
            calls["init"] = True

        def resolve(self):
            calls["resolved"] = True
            return {"record_count": 5}

    class _FakeResolverExporter:
        def __init__(self, results, lang="en"):
            calls["exporter_results"] = results
            calls["exporter_lang"] = lang

        def export(self, output_dir, fmt="all"):
            calls["export_dir"] = output_dir
            calls["export_fmt"] = fmt
            return [str(tmp_path / "Illumio_Policy_Resolver.html")]

    import src.report.policy_resolver_report as prr_mod
    import src.report.exporters.policy_resolver_exporter as pre_mod
    monkeypatch.setattr(prr_mod, "PolicyResolverReport", _FakeResolverReport)
    monkeypatch.setattr(pre_mod, "PolicyResolverExporter", _FakeResolverExporter)
    monkeypatch.setattr("src.main._make_cache_reader", lambda cm: None)

    result, paths = sched._generate_report(
        report_type="policy_resolver",
        api=object(),
        fmt="html",
        output_dir=str(tmp_path),
        start_date="2026-04-01T00:00:00Z",
        end_date="2026-04-08T23:59:59Z",
        name="Policy Resolver",
        lang="en",
    )

    assert calls["resolved"] is True
    assert calls["export_dir"] == str(tmp_path)
    assert calls["export_fmt"] == "all"
    assert result.record_count == 5
    assert paths == [str(tmp_path / "Illumio_Policy_Resolver.html")]


def test_generate_report_policy_resolver_empty_skips_export(monkeypatch, tmp_path):
    """A resolver run with no rows must skip export (return None, [])."""
    sched = _make_scheduler()

    class _FakeResolverReport:
        def __init__(self, cm, api_client=None, config_dir="config"):
            pass

        def resolve(self):
            return {"record_count": 0}

    import src.report.policy_resolver_report as prr_mod
    monkeypatch.setattr(prr_mod, "PolicyResolverReport", _FakeResolverReport)
    monkeypatch.setattr("src.main._make_cache_reader", lambda cm: None)

    result, paths = sched._generate_report(
        report_type="policy_resolver",
        api=object(),
        fmt="html",
        output_dir=str(tmp_path),
        start_date="2026-04-01T00:00:00Z",
        end_date="2026-04-08T23:59:59Z",
        name="Empty Resolver",
        lang="en",
    )

    assert result is None
    assert paths == []
