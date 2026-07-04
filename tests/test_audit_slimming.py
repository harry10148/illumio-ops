"""Audit 近期事件精簡（spec I1）：HTML 顯示前 10 筆、完整清單見 CSV/XLSX 匯出。"""
import pandas as pd

from src.report.exporters.audit_html_exporter import AuditHtmlExporter


def _recent_df(n=50):
    # 事件類型用「evt-NN」零填數字，避免 <wbr> 插入或子字串重疊造成誤判。
    return pd.DataFrame([{"timestamp": f"2026-06-01T00:{i:02d}:00Z",
                          "event_type": f"evt-{i:02d}", "severity": "info"} for i in range(n)])


def _results():
    return {"mod00": {"kpis": [], "attention_items": []},
            "mod01": {"summary": pd.DataFrame([{"Event Type": "x", "Count": 1}]),
                      "severity_breakdown": pd.DataFrame(), "connectivity_events": pd.DataFrame(),
                      "security_concerns": pd.DataFrame(), "recent": _recent_df(),
                      "total_health_events": 50, "security_concern_count": 0,
                      "connectivity_event_count": 0},
            "mod02": {}, "mod03": {}, "mod04": {}}


def test_html_recent_capped_at_10():
    html = AuditHtmlExporter(_results(), lang="en")._build()
    # 只保留前 10 筆（evt-00..evt-09），第 11 筆（evt-10）不應出現。
    assert html.count("evt-09") == 1
    assert "evt-10" not in html


def test_html_recent_none_is_noop():
    """recent 缺 key 或為 None 時不應噴錯（builder 未提供 recent 的模組）。"""
    results = _results()
    results["mod02"] = {"summary": pd.DataFrame()}
    html = AuditHtmlExporter(results, lang="en")._build()
    assert html  # 不噴錯即可
