"""Traffic XLSX must contain real DataFrames per sheet, not empty shells."""
import pandas as pd
import pytest
from openpyxl import load_workbook


@pytest.fixture
def sample_flows():
    return pd.DataFrame([
        {"src": "10.0.0.1", "dst": "10.0.0.2", "port": 445, "policy_decision": "allowed", "num_connections": 1},
        {"src": "10.0.0.1", "dst": "10.0.0.3", "port": 445, "policy_decision": "potentially_blocked", "num_connections": 1},
        {"src": "10.0.0.4", "dst": "10.0.0.2", "port": 22,  "policy_decision": "blocked", "num_connections": 1},
        {"src": "10.0.0.5", "dst": "10.0.0.1", "port": 389, "policy_decision": "allowed", "num_connections": 1},
        {"src": "10.0.0.6", "dst": "10.0.0.1", "port": 389, "policy_decision": "allowed", "num_connections": 1},
        {"src": "10.0.0.7", "dst": "10.0.0.8", "port": 3389, "policy_decision": "allowed", "num_connections": 1},
        {"src": "10.0.0.8", "dst": "10.0.0.2", "port": 135, "policy_decision": "allowed", "num_connections": 1},
    ])


def test_traffic_xlsx_has_expected_sheets(sample_flows, tmp_path):
    from src.report.report_generator import generate_traffic_xlsx
    out_path = tmp_path / "traffic.xlsx"
    generate_traffic_xlsx(sample_flows, str(out_path), profile="security_risk")
    wb = load_workbook(str(out_path))
    expected = {"Executive Summary", "Policy Decisions", "Uncovered Flows", "Lateral Movement", "Top Talkers"}
    assert expected.issubset(set(wb.sheetnames)), f"missing: {expected - set(wb.sheetnames)}"


def test_traffic_xlsx_executive_sheet_has_kpis(sample_flows, tmp_path):
    from src.report.report_generator import generate_traffic_xlsx
    out_path = tmp_path / "traffic.xlsx"
    generate_traffic_xlsx(sample_flows, str(out_path), profile="security_risk")
    wb = load_workbook(str(out_path))
    sheet = wb["Executive Summary"]
    rows = list(sheet.iter_rows(values_only=True))
    flat = [str(c) for r in rows for c in r if c is not None]
    assert len(flat) > 0, "Executive Summary sheet is empty"


def test_traffic_xlsx_uncovered_sheet_has_rows(sample_flows, tmp_path):
    from src.report.report_generator import generate_traffic_xlsx
    out_path = tmp_path / "traffic.xlsx"
    generate_traffic_xlsx(sample_flows, str(out_path), profile="security_risk")
    wb = load_workbook(str(out_path))
    assert "Uncovered Flows" in wb.sheetnames
    sheet = wb["Uncovered Flows"]
    rows = list(sheet.iter_rows(values_only=True))
    assert len(rows) >= 1, f"Uncovered Flows sheet has no rows"


def test_lateral_sheet_has_demoted_table_titles(sample_flows, tmp_path, monkeypatch):
    """Lateral sheet must contain titles of demoted tables."""
    from src.report.report_generator import generate_traffic_xlsx
    from src.i18n import t

    # Mock lateral_movement_risk to return test data with demoted tables
    def mock_lateral_movement_risk(flows, top_n=20):
        return {
            "service_summary": pd.DataFrame([{"Service": "SMB", "Count": 5}]),
            "ip_top_talkers": pd.DataFrame([{"Host": "10.0.0.1", "Connections": 10}]),
            "ip_top_pairs": pd.DataFrame([{"Src": "10.0.0.1", "Dst": "10.0.0.2", "Count": 5}]),
            "source_risk_scores": pd.DataFrame([{"Source": "10.0.0.1", "Risk": 0.8}]),
            "bridge_nodes": pd.DataFrame([{"Node": "10.0.0.1", "Score": 0.6}]),
            "top_reachable_nodes": pd.DataFrame([{"Node": "10.0.0.2", "Depth": 3}]),
            "app_chains": pd.DataFrame([{"Chain": "app1->app2", "Count": 2}]),
            "fan_out_sources": pd.DataFrame(),
            "allowed_lateral_flows": pd.DataFrame(),
            "attack_paths": pd.DataFrame(),
            "attack_posture_items": [],
            "total_lateral_flows": 0,
            "unique_lateral_src": 0,
            "unique_lateral_dst": 0,
            "lateral_pct": 0.0,
            "node_ips": {},
            "chart_spec": None,
            "articulation_proxies": pd.DataFrame(),
        }

    monkeypatch.setattr("src.report.analysis.mod15_lateral_movement.lateral_movement_risk", mock_lateral_movement_risk)

    out_path = tmp_path / "traffic.xlsx"
    generate_traffic_xlsx(sample_flows, str(out_path), profile="security_risk")
    wb = load_workbook(str(out_path))
    assert "Lateral Movement" in wb.sheetnames
    sheet = wb["Lateral Movement"]
    rows = list(sheet.iter_rows(values_only=True))
    flat = [str(c) for r in rows for c in r if c is not None]
    flat_str = " ".join(flat)
    # 驗證下放表的標題出現在 XLSX 中
    for key in ("rpt_tr_ip_top_talkers", "rpt_tr_ip_top_pairs", "rpt_tr_top_risk_sources",
                "rpt_mod15_bridge_nodes", "rpt_mod15_top_reachable", "rpt_tr_app_chains"):
        title = t(key, lang="en")
        assert title in flat_str, f"demoted table title {key}='{title}' not in lateral sheet"
