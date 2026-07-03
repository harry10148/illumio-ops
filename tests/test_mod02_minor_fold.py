"""Policy 判定章 <1% decision 摺疊（僅 security_risk）。"""
import pandas as pd
from src.report.exporters.html_exporter import (
    SecurityRiskHtmlExporter, NetworkInventoryHtmlExporter,
)


def _results():
    summary = pd.DataFrame([
        {"Decision": "allowed", "Flows": 990, "% of Total": 97.1, "Inbound": 500, "Outbound": 490},
        {"Decision": "blocked", "Flows": 20, "% of Total": 2.0, "Inbound": 10, "Outbound": 10},
        {"Decision": "potentially_blocked", "Flows": 5, "% of Total": 0.5, "Inbound": 3, "Outbound": 2},
        {"Decision": "unknown", "Flows": 4, "% of Total": 0.4, "Inbound": 2, "Outbound": 2},
    ])
    return {
        "mod02": {
            "summary": summary,
            "allowed": {"count": 990, "pct_of_total": 97.1, "inbound_count": 500,
                        "outbound_count": 490, "top_app_flows": pd.DataFrame(),
                        "top_inbound_ports": pd.DataFrame(), "top_outbound_ports": pd.DataFrame()},
            "blocked": {"count": 20, "pct_of_total": 2.0, "inbound_count": 10,
                        "outbound_count": 10, "top_app_flows": pd.DataFrame(),
                        "top_inbound_ports": pd.DataFrame(), "top_outbound_ports": pd.DataFrame()},
            "potentially_blocked": {"count": 5, "pct_of_total": 0.5, "inbound_count": 3,
                                    "outbound_count": 2, "top_app_flows": pd.DataFrame(),
                                    "top_inbound_ports": pd.DataFrame(), "top_outbound_ports": pd.DataFrame()},
        },
        "mod12": {"kpis": [], "key_findings": []},
        "findings": [],
    }


def test_security_folds_minor_decisions():
    html = SecurityRiskHtmlExporter(_results(), lang="en").build()
    # 摺疊列出現、minor decision 的明細標題消失
    assert "Other (&lt;1% each)" in html or "Other (<1% each)" in html
    # potentially_blocked 明細段（heading 帶 0.5%）不應渲染
    assert "0.5%" not in html


def test_inventory_keeps_all_rows():
    html = NetworkInventoryHtmlExporter(_results(), lang="en").build()
    assert "Other (<1% each)" not in html and "Other (&lt;1% each)" not in html
