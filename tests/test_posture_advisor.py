"""Tests for score-impact remediation advisor (pure derivation)."""
from __future__ import annotations

from unittest.mock import patch

from src.report.posture import compute_posture
from src.report.posture_advisor import build_remediation


def _risk_kpis():
    return {
        "enforced_coverage_pct": 80.0,   # coverage value 80 -> recoverable 0.3*20=6.0
        "maturity_score": 70.0,          # readiness value 70 -> recoverable 0.3*30=9.0
        "risk_flows_total": 4,           # ransomware pts 20 -> recoverable 0.4*20=8.0
        "true_gap_pct": 20.0,            # flow_coverage pts 10 -> recoverable 0.4*10=4.0
        "maturity_dimensions": {
            "lateral_movement_control": {"ratio": 0.5},  # lateral pts 15 -> 0.4*15=6.0
        },
    }


def test_ranked_by_recoverable_points_desc():
    posture = compute_posture(_risk_kpis())
    items = build_remediation(posture)
    assert [i["key"] for i in items] == [
        "readiness", "ransomware_containment", "coverage",
        "lateral_containment", "flow_coverage",
    ]
    assert items[0]["recoverable_points"] == 9.0
    assert items[1]["recoverable_points"] == 8.0


def test_item_shape():
    posture = compute_posture(_risk_kpis())
    top = build_remediation(posture)[0]
    assert top["label_key"]
    assert top["target"] == 100
    assert "recommendation_key" in top
    assert isinstance(top["current"], (int, float))


def test_perfect_axis_excluded():
    # coverage already 100 -> no coverage remediation item.
    kpis = dict(_risk_kpis(), enforced_coverage_pct=100.0)
    items = build_remediation(compute_posture(kpis))
    assert all(i["key"] != "coverage" for i in items)


def test_unavailable_posture_returns_empty():
    assert build_remediation({"available": False}) == []
    assert build_remediation({}) == []


def test_renormalized_weight_single_component():
    # Only risk signals present -> risk_health effective_weight renormalizes to 1.0,
    # so recoverable_points must use the renormalized weight (1.0 * penalty_points).
    kpis = {
        "risk_flows_total": 4,           # ransomware pts 20
        "true_gap_pct": 0.0,             # flow_coverage clean (excluded)
        "maturity_dimensions": {
            "lateral_movement_control": {"ratio": 1.0},  # lateral clean (excluded)
        },
    }
    items = build_remediation(compute_posture(kpis))
    assert any(
        i["key"] == "ransomware_containment" and i["recoverable_points"] == 20.0
        for i in items
    )


def test_risk_health_no_subscores_returns_no_items():
    posture = {
        "available": True,
        "components": [
            {"key": "risk_health", "effective_weight": 0.4, "risk_subscores": []},
        ],
    }
    assert build_remediation(posture) == []


def test_overview_posture_attaches_remediation():
    from src.gui.routes.dashboard import _overview_posture
    snap = {"kpis": _risk_kpis(), "generated_at": "2026-06-08T00:00:00Z"}
    with patch("src.report.snapshot_store.read_latest", return_value=snap):
        result = _overview_posture({})
    assert result.get("available") is True
    assert "remediation" in result
    assert result["remediation"][0]["key"] == "readiness"


def test_overview_posture_fallback_attaches_remediation():
    """State-fallback path: read_latest returns None, state has posture_summary."""
    from src.gui.routes.dashboard import _overview_posture
    state = {"posture_summary": {**compute_posture(_risk_kpis()), "source_date": "2026-06-08"}}
    with patch("src.report.snapshot_store.read_latest", return_value=None):
        result = _overview_posture(state)
    assert result.get("available") is True
    assert "remediation" in result
