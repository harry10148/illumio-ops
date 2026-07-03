"""mod_change_impact: compare current KPIs to a previous snapshot."""
import pandas as pd
import pytest

from src.report.analysis import mod_change_impact


def _kpis(**overrides):
    base = {"true_gap_pct": 10.0, "risk_flows_total": 50,
            "enforced_coverage_pct": 60.0, "maturity_score": 50}
    base.update(overrides)
    return base


def test_returns_skipped_when_no_previous():
    out = mod_change_impact.compare(current_kpis=_kpis(), previous=None)
    assert out["skipped"] is True
    assert "no_previous_snapshot" in out["reason"]


def test_detects_improvement():
    previous = {"kpis": _kpis(enforced_coverage_pct=50.0, maturity_score=40)}
    out = mod_change_impact.compare(current_kpis=_kpis(enforced_coverage_pct=60.0,
                                                       maturity_score=50),
                                    previous=previous)
    assert out["overall_verdict"] == "improved"
    deltas = out["deltas"]
    assert deltas["enforced_coverage_pct"]["delta"] == 10.0
    assert deltas["enforced_coverage_pct"]["direction"] == "improved"


def test_detects_regression():
    previous = {"kpis": _kpis(true_gap_pct=5.0, risk_flows_total=10)}
    out = mod_change_impact.compare(current_kpis=_kpis(true_gap_pct=20.0, risk_flows_total=100),
                                    previous=previous)
    assert out["overall_verdict"] == "regressed"


def test_mixed_returns_mixed():
    previous = {"kpis": _kpis(enforced_coverage_pct=50.0, true_gap_pct=5.0)}
    out = mod_change_impact.compare(current_kpis=_kpis(enforced_coverage_pct=60.0, true_gap_pct=20.0),
                                    previous=previous)
    assert out["overall_verdict"] == "mixed"
