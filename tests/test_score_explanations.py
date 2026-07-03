"""Three score explanation sentences (spec B6)."""
from src.report.exporters.html_exporter import SecurityRiskHtmlExporter
from src.report.exporters.report_i18n import STRINGS
import pandas as pd


def _results():
    return {
        "mod12": {"kpis": [], "key_findings": [], "maturity_score": 55,
                  "maturity_grade": "C", "maturity_dimensions": {}},
        "mod13": {"total_score": 60, "grade": "B", "factor_scores": {},
                  "factor_table": pd.DataFrame([{"Factor": "x", "Weight": 35, "Score": 20, "Ratio %": 57}])},
        "mod14": {"total_apps": 3, "total_edges": 5},
        "findings": [],
    }


def test_maturity_and_infra_subnotes_present():
    html = SecurityRiskHtmlExporter(_results(), lang="en").build()
    assert STRINGS["rpt_tr_maturity_subnote"]["en"] in html
    assert STRINGS["rpt_tr_infrastructure_subnote"]["en"] in html


def test_readiness_subnote_mentions_weights():
    # Existing key must mention the five factor weights after update
    assert "35" in STRINGS["rpt_tr_readiness_subnote"]["en"]
