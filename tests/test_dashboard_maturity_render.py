"""Phase 3.1 Task 3 — dashboard-side Microsegmentation Maturity bar chart."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "src" / "templates" / "index.html"
DASHBOARD_JS = ROOT / "src" / "static" / "js" / "dashboard.js"


def test_index_has_maturity_fieldset():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="d-maturity"' in html
    assert 'id="d-maturity-bars"' in html


def test_js_has_renderMaturity_and_five_dims():
    js = DASHBOARD_JS.read_text(encoding="utf-8")
    assert "function renderMaturity" in js
    for dim in (
        "enforcement_coverage",
        "policy_coverage",
        "lateral_movement_control",
        "managed_asset_ratio",
        "risk_port_control",
    ):
        assert dim in js, f"missing maturity dim {dim}"


def test_snapshot_builder_includes_maturity_keys():
    from src.report.report_generator import _build_snapshot
    module_results = {
        "mod12": {
            "maturity_dimensions": {"enforcement_coverage": {"score": 8, "weight": 10}},
            "maturity_score": 78,
            "maturity_grade": "B",
        }
    }
    snap = _build_snapshot(module_results)
    assert snap["maturity_dimensions"] == {"enforcement_coverage": {"score": 8, "weight": 10}}
    assert snap["maturity_score"] == 78
    assert snap["maturity_grade"] == "B"
