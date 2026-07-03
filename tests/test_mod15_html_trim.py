"""橫向移動章 HTML 只留 4 張表；主機層明細下放 XLSX。"""
import pandas as pd
from src.report.exporters.html_exporter import SecurityRiskHtmlExporter


def _mod15():
    one = pd.DataFrame([{"A": 1}])
    return {
        "total_lateral_flows": 10, "lateral_pct": 5.0, "node_ips": {},
        "service_summary": pd.DataFrame([{"Service": "smb", "Connections": 9}]),
        "ip_top_talkers": one, "ip_top_pairs": one, "fan_out_sources": one,
        "app_chains": one, "bridge_nodes": one, "top_reachable_nodes": one,
        "attack_paths": pd.DataFrame([{"Path": "a→b"}]),
        "articulation_proxies": one, "source_risk_scores": one,
        "allowed_lateral_flows": one, "attack_posture_items": [],
    }


def _html():
    results = {"mod15": _mod15(), "mod12": {"kpis": [], "key_findings": []}, "findings": []}
    return SecurityRiskHtmlExporter(results, lang="en").build()


def test_kept_tables_render():
    html = _html()
    from src.report.exporters.report_i18n import STRINGS
    for key in ("rpt_tr_lateral_by_service", "rpt_tr_fan_out",
                "rpt_tr_allowed_lateral", "rpt_mod15_attack_paths"):
        title = STRINGS[key]["en"]
        assert title in html, f"kept table {key} not rendered"


def test_demoted_tables_absent():
    html = _html()
    from src.report.exporters.report_i18n import STRINGS
    for key in ("rpt_tr_ip_top_talkers", "rpt_tr_ip_top_pairs", "rpt_tr_top_risk_sources",
                "rpt_mod15_bridge_nodes", "rpt_mod15_top_reachable", "rpt_tr_app_chains"):
        title = STRINGS[key]["en"]
        assert title not in html, f"demoted table {key} still rendered"
