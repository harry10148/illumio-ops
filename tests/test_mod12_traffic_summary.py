"""Phase 1: mod12 traffic-profile summary branch."""
from src.report.analysis.mod12_executive_summary import executive_summary


def _results():
    return {
        "mod01": {
            "total_flows": 100, "total_connections": 5000,
            "unique_src_ips": 10, "unique_dst_ips": 20,
            "allowed_flows": 30, "blocked_flows": 5,
            "potentially_blocked_flows": 65,
            "total_mb": 2048.0, "date_range": "2026-04-27 ~ 2026-05-04",
        },
        "findings": [],
    }


def test_traffic_profile_kpis_only():
    out = executive_summary(_results(), profile="traffic", lang="en")
    keys = {k["label_key"] for k in out["kpis"]}
    assert "mod12_kpi_total_flows" in keys
    assert "mod12_kpi_allowed_flows" in keys
    assert "mod12_kpi_pb_flows" in keys
    assert "mod12_kpi_maturity_score" not in keys


def test_traffic_profile_no_security_analysis():
    out = executive_summary(_results(), profile="traffic", lang="en")
    assert out["key_findings"] == []
    assert out["findings_summary"] == {}
    assert out["action_matrix"] == []
    assert out["boundary_breaches"] == []
    assert "maturity_score" not in out
    assert "chart_spec" not in out


def test_security_profile_still_has_maturity():
    out = executive_summary(_results(), profile="security_risk", lang="en")
    assert "maturity_score" in out
