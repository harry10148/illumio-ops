"""Failed analysis modules / failed sub-queries must be visible, not rendered
as real zeros or as an all-clear (review batch 3)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest


# ── Traffic: failed modules disclosed in the HTML hero ───────────────────────

def test_traffic_html_discloses_failed_modules():
    from src.report.exporters.html_exporter import SecurityRiskHtmlExporter

    results = {
        "mod01": {"error": "boom"},
        "_module_errors": [{"module": "mod01", "error": "boom"}],
    }
    html = SecurityRiskHtmlExporter(results).build()
    assert "mod01" in html
    # 沒有失敗模組時不得出現這個橫幅
    clean = SecurityRiskHtmlExporter({"_module_errors": []}).build()
    assert "rpt_module_errors_warning" not in clean


def test_run_modules_exposes_errors_on_the_generator(monkeypatch):
    from src.report import report_generator as rg

    def _boom(*a, **k):
        raise ValueError("groupby exploded")

    monkeypatch.setattr(rg, "get_traffic_modules",
                        lambda profile: [("mod01", _boom, lambda fn, *a: fn())],
                        raising=False)
    monkeypatch.setattr("src.report.analysis.get_traffic_modules",
                        lambda profile: [("mod01", _boom, lambda fn, *a: fn())])
    monkeypatch.setattr("src.report.analysis.get_summary_module",
                        lambda: ("mod12", lambda results, **k: {}))

    gen = rg.ReportGenerator(config_manager=MagicMock())
    results = gen._run_modules(pd.DataFrame([{"a": 1}]), [])
    assert results["_module_errors"] == [{"module": "mod01", "error": "groupby exploded"}]
    assert gen.last_module_errors == results["_module_errors"]


# ── Policy Usage: a failed draft-PD query is not "no draft policy risk" ──────

def _pu_generator(rows, fetch_error):
    from src.report.policy_usage_generator import PolicyUsageGenerator

    api = MagicMock()
    api.last_fetch_error = fetch_error
    api._traffic._submit_and_stream_async_query = lambda payload, **k: iter(rows)
    gen = PolicyUsageGenerator(config_manager=MagicMock(), api_client=api)
    gen.api = api
    return gen


def test_draft_pd_query_failure_is_flagged_as_failed():
    gen = _pu_generator([], "async query timed out after 900s")
    out = gen._fetch_draft_pd_analysis("2026-07-01", "2026-07-25")
    assert out["failed"] is True
    assert "900s" in out["reason"]


def test_draft_pd_zero_rows_without_error_stays_a_plain_skip():
    gen = _pu_generator([], None)
    out = gen._fetch_draft_pd_analysis("2026-07-01", "2026-07-25")
    assert out.get("failed") is not True
    assert out["skipped"] is True


# ── Audit: xlsx failures surface + no corrupt workbook left behind ───────────

def test_audit_xlsx_failure_records_error_and_removes_partial(tmp_path, monkeypatch):
    from src.report import audit_generator as ag

    def _boom(module_results, out_path, **k):
        with open(out_path, "wb") as fh:      # 模擬 openpyxl 已建檔後才失敗
            fh.write(b"PK\x03\x04partial")
        raise RuntimeError("ENOSPC")

    monkeypatch.setattr(ag, "generate_audit_xlsx", _boom)
    gen = ag.AuditGenerator(config_manager=MagicMock())
    result = ag.AuditReportResult(record_count=1, date_range=("2026-07-01", "2026-07-25"),
                                  module_results={}, dataframe=pd.DataFrame([{"a": 1}]),
                                  source="api")
    paths = gen.export(result, fmt="xlsx", output_dir=str(tmp_path))
    assert paths == []
    assert gen.last_export_errors["xlsx"] == "ENOSPC"
    assert list(tmp_path.glob("*.xlsx")) == [], "partial workbook left downloadable"


def test_audit_module_failure_skips_dashboard_summary_and_trend(tmp_path, monkeypatch):
    """失敗模組的 KPI 是 .get(key, 0) 讀出來的假 0；不可寫進儀表板摘要與趨勢
    基準，否則下一輪 delta 會顯示一次不存在的『歸零』。"""
    from src.report import audit_generator as ag

    called = {"summary": False}
    monkeypatch.setattr(ag, "write_audit_dashboard_summary",
                        lambda *a, **k: called.__setitem__("summary", True))
    gen = ag.AuditGenerator(config_manager=MagicMock())
    result = ag.AuditReportResult(
        record_count=1, date_range=("2026-07-01", "2026-07-25"),
        module_results={"mod03": {"error": "boom"},
                        "_module_errors": [{"module": "mod03", "error": "boom"}]},
        dataframe=pd.DataFrame([{"a": 1}]), source="api")
    gen.export(result, fmt="csv", output_dir=str(tmp_path))
    assert called["summary"] is False
    assert not list((tmp_path / "history").glob("**/*.json"))
