"""PCE 查詢碰到單次上限時，報表要揭露（舊版只寫 log，讀者無從得知只涵蓋前 N 筆）。"""
from __future__ import annotations

from unittest.mock import MagicMock


def test_banner_shown_when_query_truncated():
    from src.report.exporters.html_exporter import SecurityRiskHtmlExporter
    html = SecurityRiskHtmlExporter(
        {"_query_truncation": {"returned": 200000, "max_results": 200000}}, lang="en")._build()
    assert "200,000" in html and "per-query limit" in html


def test_no_banner_without_truncation():
    from src.report.exporters.html_exporter import SecurityRiskHtmlExporter
    html = SecurityRiskHtmlExporter({}, lang="en")._build()
    assert "per-query limit" not in html


def test_fetch_traffic_for_report_flags_cap_in_diagnostics(monkeypatch):
    import src.api.traffic_query as tq
    from src.api.traffic_query import TrafficQueryBuilder

    monkeypatch.setattr(tq, "MAX_TRAFFIC_RESULTS", 3)
    client = MagicMock()
    client.last_traffic_query_diagnostics = {}
    builder = TrafficQueryBuilder.__new__(TrafficQueryBuilder)
    builder._client = client
    builder.build_traffic_query_spec = MagicMock(return_value=MagicMock(fallback_filters={}))
    builder.execute_traffic_query_stream = MagicMock(return_value=iter([{}, {}, {}]))
    builder.fetch_traffic_for_report("2026-10-01T00:00:00Z", "2026-10-01T01:00:00Z")
    assert client.last_traffic_query_diagnostics["query_truncated"] == {
        "returned": 3, "max_results": 3}
