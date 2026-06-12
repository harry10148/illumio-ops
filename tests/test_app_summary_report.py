"""App Summary facade: fetch → scope → modules subset → export."""
import pandas as pd
from unittest.mock import MagicMock, patch

from src.report.app_summary_report import AppSummaryReport, _safe_filename_token


def _row(src_app, dst_app, dst_ip, port):
    return {
        "src_app": src_app, "src_env": "P", "dst_app": dst_app, "dst_env": "P",
        "port": port, "proto": "TCP", "policy_decision": "allowed",
        "num_connections": 1, "src_ip": "a", "dst_ip": dst_ip,
        "src_managed": True, "dst_managed": True, "bytes_total": 0,
        "first_detected": pd.Timestamp("2026-01-01"),
        "last_detected": pd.Timestamp("2026-01-02"),
    }


def test_safe_filename_token():
    assert _safe_filename_token("My App/v2 (Prod)") == "My_App_v2_Prod"


def test_build_scopes_and_runs_modules():
    df = pd.DataFrame([
        _row("Web", "DB", "b", 3306),
        _row("Web", "Cache", "c", 6379),
    ])
    rep = AppSummaryReport(cm=MagicMock(), api_client=MagicMock())
    with patch.object(rep, "_fetch_estate_df", return_value=df):
        result = rep.build(app="DB", lang="en")
    assert result["app"] == "DB"
    assert result["baseline"]["flow_count"] == 1            # 只剩 DB 相關
    assert result["mod01"]["total_flows"] == 1              # 模組看到的是已過濾 df
    assert "findings" in result


def test_build_unknown_app_flags_empty():
    rep = AppSummaryReport(cm=MagicMock(), api_client=MagicMock())
    with patch.object(rep, "_fetch_estate_df", return_value=pd.DataFrame()):
        result = rep.build(app="Nope", lang="en")
    assert result["empty"] is True


def test_export_writes_html(tmp_path):
    df = pd.DataFrame([
        _row("Web", "DB", "b", 3306),
        _row("Web", "Cache", "c", 6379),
    ])
    rep = AppSummaryReport(cm=MagicMock(), api_client=MagicMock())
    with patch.object(rep, "_fetch_estate_df", return_value=df):
        results = rep.build(app="DB", lang="zh_TW")
    from src.report.exporters.app_summary_html_exporter import AppSummaryHtmlExporter
    path = AppSummaryHtmlExporter(results, lang="zh_TW").export(str(tmp_path))
    html = open(path, encoding="utf-8").read()
    assert "App Summary" in html or "App 摘要" in html
    assert 'id="inbound"' in html and 'id="outbound"' in html
    assert "Illumio_App_Summary_DB_" in path
