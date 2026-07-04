"""spec N1：所有 HTML exporter 輸出必含列印/PDF 按鈕（守門掃描）。

六個 exporter（html_exporter 涵蓋 SecurityRisk/TrafficFlows 共用模組、
Audit、VEN、PolicyUsage、PolicyDiff、AppSummary）各以最小 fixture 產出
HTML，斷言輸出都含 `window.print()` 與 `class="print-btn"`。不可參數化
跳過難建構者——policy_diff/app_summary 的最小建構抄自其現有測試檔。
"""
from __future__ import annotations

import pandas as pd

_PRINT_BTN = 'class="print-btn"'
_PRINT_JS = 'window.print()'


def _minimal_traffic_results() -> dict:
    return {k: {} for k in [
        "mod01", "mod02", "mod03", "mod04", "mod05", "mod06",
        "mod07", "mod08", "mod09", "mod11", "mod12",
        "mod13", "mod14", "mod15",
    ]}


def test_traffic_flows_html_exporter_has_print_button():
    from src.report.exporters.html_exporter import TrafficFlowsHtmlExporter
    html = TrafficFlowsHtmlExporter(_minimal_traffic_results(), lang="en").build()
    assert _PRINT_JS in html
    assert _PRINT_BTN in html


def test_audit_html_exporter_has_print_button():
    from src.report.exporters.audit_html_exporter import AuditHtmlExporter
    html = AuditHtmlExporter({}, lang="en")._build()
    assert _PRINT_JS in html
    assert _PRINT_BTN in html


def test_ven_html_exporter_has_print_button():
    from src.report.exporters.ven_html_exporter import VenHtmlExporter
    df = pd.DataFrame([{"hostname": "h1", "os": "linux"}])
    html = VenHtmlExporter({"online": df}, lang="en")._build()
    assert _PRINT_JS in html
    assert _PRINT_BTN in html


def test_policy_usage_html_exporter_has_print_button():
    from src.report.exporters.policy_usage_html_exporter import PolicyUsageHtmlExporter
    html = PolicyUsageHtmlExporter({}, lang="en")._build()
    assert _PRINT_JS in html
    assert _PRINT_BTN in html


def _policy_diff_results() -> dict:
    rs = pd.DataFrame([{
        "change_type": "modified", "ruleset_name": "RS-A", "ruleset_id": "1",
        "field": "enabled", "draft_value": "False", "active_value": "True",
        "last_actor": "bob", "last_changed": "2026-06-05T12:00:00Z",
        "last_event": "rule_set.update",
    }])
    rule = pd.DataFrame(columns=["change_type", "ruleset_name", "rule_id", "field",
                                 "draft_value", "active_value",
                                 "last_actor", "last_changed", "last_event"])
    return {"ruleset_changes": rs, "rule_changes": rule,
            "summary": {"rulesets_added": 0, "rulesets_removed": 0, "rulesets_modified": 1,
                        "rules_added": 0, "rules_removed": 0, "rules_modified": 0,
                        "total_changes": 1}}


def test_policy_diff_html_exporter_has_print_button():
    from src.report.exporters.policy_diff_html_exporter import PolicyDiffHtmlExporter
    html = PolicyDiffHtmlExporter(_policy_diff_results(), lang="en")._render_html()
    assert _PRINT_JS in html
    assert _PRINT_BTN in html


def _app_summary_results() -> dict:
    return {"app": "DB", "env": "Prod", "empty": True, "baseline": {}, "mod03": {},
            "policy_impact": {}, "enforcement": {}, "findings": []}


def test_app_summary_html_exporter_has_print_button():
    from src.report.exporters.app_summary_html_exporter import AppSummaryHtmlExporter
    html = AppSummaryHtmlExporter(_app_summary_results(), lang="en")._render_html()
    assert _PRINT_JS in html
    assert _PRINT_BTN in html
