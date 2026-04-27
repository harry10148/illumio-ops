"""Policy Usage XLSX: sheets with real rows."""
import pandas as pd
import pytest
from openpyxl import load_workbook


@pytest.fixture
def sample_rules():
    return pd.DataFrame([
        {"rule_id": "r-1", "name": "allow web→db", "hit_count": 1234, "is_deny": False,
         "ruleset_name": "default", "scope": "all", "enabled": True},
        {"rule_id": "r-2", "name": "deny untrusted", "hit_count": 0, "is_deny": True,
         "ruleset_name": "default", "scope": "all", "enabled": True},
        {"rule_id": "r-3", "name": "old broad allow", "hit_count": 0, "is_deny": False,
         "ruleset_name": "legacy", "scope": "all", "enabled": True},
    ])


def test_policy_usage_xlsx_has_expected_sheets(sample_rules, tmp_path):
    from src.report.policy_usage_generator import generate_policy_usage_xlsx
    out_path = tmp_path / "pu.xlsx"
    generate_policy_usage_xlsx(sample_rules, str(out_path))
    wb = load_workbook(str(out_path))
    expected = {"Hit Rules", "Unused Rules", "Deny Effectiveness", "Execution Stats"}
    assert expected.issubset(set(wb.sheetnames)), f"missing: {expected - set(wb.sheetnames)}"


def test_policy_usage_xlsx_unused_sheet_has_rows(sample_rules, tmp_path):
    from src.report.policy_usage_generator import generate_policy_usage_xlsx
    out_path = tmp_path / "pu.xlsx"
    generate_policy_usage_xlsx(sample_rules, str(out_path))
    wb = load_workbook(str(out_path))
    assert "Unused Rules" in wb.sheetnames
    sheet = wb["Unused Rules"]
    rows = list(sheet.iter_rows(values_only=True))
    assert len(rows) >= 1, "Unused Rules sheet is empty"
