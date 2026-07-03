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


def test_no_lateral_note_absent_when_any_table_has_data(monkeypatch, sample_flows, tmp_path):
    """service_summary empty but extra table has data: no-lateral note must not appear."""
    from src.report.report_generator import generate_traffic_xlsx
    from src.i18n import t

    def _fake_lateral(flows, top_n=20, **kwargs):
        return {
            "service_summary": pd.DataFrame(),
            "ip_top_talkers": pd.DataFrame([{"IP": "10.0.0.1", "Connections": 5}]),
            "ip_top_pairs": pd.DataFrame(),
            "source_risk_scores": pd.DataFrame(),
            "bridge_nodes": pd.DataFrame(),
            "top_reachable_nodes": pd.DataFrame(),
            "app_chains": pd.DataFrame(),
        }

    monkeypatch.setattr(
        "src.report.analysis.mod15_lateral_movement.lateral_movement_risk",
        _fake_lateral
    )
    out_path = tmp_path / "traffic.xlsx"
    generate_traffic_xlsx(sample_flows, str(out_path), profile="security_risk")
    wb = load_workbook(str(out_path))
    sheet = wb["Lateral Movement"]
    rows = list(sheet.iter_rows(values_only=True))
    flat = [str(c) for r in rows for c in r if c is not None]
    flat_text = " ".join(flat)

    assert "10.0.0.1" in flat_text, "Expected IP data should be in sheet"
    no_lateral_text = t("rpt_xlsx_no_lateral", lang="en")
    assert no_lateral_text not in flat_text, f"'{no_lateral_text}' must not appear when extra tables have data"
