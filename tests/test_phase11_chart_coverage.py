"""Phase 11 coverage meta-test: all 10 new traffic modules must emit chart_spec."""

from __future__ import annotations

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _assert_chart_spec(result: dict, *, allow_none: bool = False) -> None:
    assert "chart_spec" in result, "chart_spec key missing from result"
    if not allow_none:
        spec = result["chart_spec"]
        assert spec is not None, "chart_spec is None (expected a non-None dict)"
        assert isinstance(spec, dict), f"chart_spec is not a dict: {type(spec)}"
        for key in ("type", "title", "data"):
            assert key in spec, f"chart_spec missing required key '{key}'"


def _make_traffic_df() -> pd.DataFrame:
    """Minimal traffic DataFrame satisfying most module column requirements."""
    return pd.DataFrame({
        "src_ip":              ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"],
        "dst_ip":              ["10.0.1.1", "10.0.1.2", "10.0.1.3", "10.0.1.4"],
        "src_hostname":        ["host-a", "host-b", "host-c", "host-d"],
        "dst_hostname":        ["svc-a", "svc-b", "svc-c", "svc-d"],
        "port":                [445, 3389, 22, 80],
        "proto":               ["TCP", "TCP", "TCP", "TCP"],
        "bytes_total":         [10_000, 5_000, 20_000, 3_000],
        "num_connections":     [5, 3, 10, 2],
        "bandwidth_mbps":      [1.0, 0.5, 2.0, 0.3],
        "policy_decision":     ["allowed", "blocked", "allowed", "potentially_blocked"],
        "src_managed":         [True, True, False, True],
        "dst_managed":         [True, False, True, True],
        "first_detected":      pd.to_datetime(["2024-01-01"] * 4),
        "last_detected":       pd.to_datetime(["2024-01-02"] * 4),
        "src_app":             ["web", "db", "admin", "web"],
        "dst_app":             ["db", "cache", "web", "api"],
        "src_env":             ["prod", "prod", "dev", "prod"],
        "dst_env":             ["prod", "prod", "dev", "prod"],
        "src_role":            ["frontend", "backend", "ops", "frontend"],
        "dst_role":            ["backend", "cache", "frontend", "api"],
        "src_loc":             ["us-east", "us-east", "eu-west", "us-west"],
        "dst_loc":             ["us-east", "us-east", "eu-west", "us-west"],
        "user_name":           ["alice", "bob", "", "alice"],
        "process_name":        ["nginx", "postgres", "", "nginx"],
    })


_RANSOMWARE_CONFIG = {
    "ransomware_risk_ports": {
        "critical": [{"ports": [445], "service": "SMB"}, {"ports": [3389], "service": "RDP"}],
        "high":     [{"ports": [5900], "service": "VNC"}],
        "medium":   [{"ports": [22],   "service": "SSH"}, {"ports": [80], "service": "HTTP"}],
        "low":      [],
    }
}


# ---------------------------------------------------------------------------
# mod01 — traffic_overview
# ---------------------------------------------------------------------------

class TestMod01TrafficOverview:
    def test_chart_spec_present(self) -> None:
        from src.report.analysis.mod01_traffic_overview import traffic_overview
        result = traffic_overview(_make_traffic_df())
        _assert_chart_spec(result)

    def test_chart_spec_structure(self) -> None:
        from src.report.analysis.mod01_traffic_overview import traffic_overview
        spec = traffic_overview(_make_traffic_df())["chart_spec"]
        assert spec["type"] in ("bar", "pie", "line")
        assert "data" in spec
        assert "title" in spec


# ---------------------------------------------------------------------------
# mod03 — uncovered_flows
# ---------------------------------------------------------------------------

class TestMod03UncoveredFlows:
    def test_chart_spec_present(self) -> None:
        from src.report.analysis.mod03_uncovered_flows import uncovered_flows
        result = uncovered_flows(_make_traffic_df())
        _assert_chart_spec(result)

    def test_chart_spec_structure(self) -> None:
        from src.report.analysis.mod03_uncovered_flows import uncovered_flows
        spec = uncovered_flows(_make_traffic_df())["chart_spec"]
        assert spec["type"] in ("bar", "pie")
        assert "labels" in spec["data"]
        assert "values" in spec["data"]


# ---------------------------------------------------------------------------
# mod04 — ransomware_exposure
# ---------------------------------------------------------------------------

class TestMod04RansomwareExposure:
    def test_chart_spec_present(self) -> None:
        from src.report.analysis.mod04_ransomware_exposure import ransomware_exposure
        result = ransomware_exposure(_make_traffic_df(), _RANSOMWARE_CONFIG)
        _assert_chart_spec(result)

    def test_chart_spec_structure(self) -> None:
        from src.report.analysis.mod04_ransomware_exposure import ransomware_exposure
        spec = ransomware_exposure(_make_traffic_df(), _RANSOMWARE_CONFIG)["chart_spec"]
        assert spec["type"] in ("bar", "pie")
        assert "data" in spec


# ---------------------------------------------------------------------------
# mod06 — user_process
# ---------------------------------------------------------------------------

class TestMod06UserProcess:
    def test_chart_spec_present(self) -> None:
        from src.report.analysis.mod06_user_process import user_process_analysis
        result = user_process_analysis(_make_traffic_df())
        _assert_chart_spec(result)

    def test_chart_spec_structure(self) -> None:
        from src.report.analysis.mod06_user_process import user_process_analysis
        spec = user_process_analysis(_make_traffic_df())["chart_spec"]
        assert spec["type"] == "bar"
        assert "labels" in spec["data"]
        assert "values" in spec["data"]


# ---------------------------------------------------------------------------
# mod08 — unmanaged_hosts
# ---------------------------------------------------------------------------

class TestMod08UnmanagedHosts:
    def test_chart_spec_present(self) -> None:
        from src.report.analysis.mod08_unmanaged_hosts import unmanaged_traffic
        result = unmanaged_traffic(_make_traffic_df())
        _assert_chart_spec(result)

    def test_chart_spec_structure(self) -> None:
        from src.report.analysis.mod08_unmanaged_hosts import unmanaged_traffic
        spec = unmanaged_traffic(_make_traffic_df())["chart_spec"]
        assert spec["type"] in ("bar", "pie")
        assert "data" in spec


# ---------------------------------------------------------------------------
# mod09 — traffic_distribution
# ---------------------------------------------------------------------------

class TestMod09TrafficDistribution:
    def test_chart_spec_present(self) -> None:
        from src.report.analysis.mod09_traffic_distribution import traffic_distribution
        result = traffic_distribution(_make_traffic_df())
        _assert_chart_spec(result)

    def test_chart_spec_structure(self) -> None:
        from src.report.analysis.mod09_traffic_distribution import traffic_distribution
        spec = traffic_distribution(_make_traffic_df())["chart_spec"]
        assert spec["type"] == "bar"
        assert "labels" in spec["data"]
        assert "values" in spec["data"]


# ---------------------------------------------------------------------------
# mod11 — bandwidth
# ---------------------------------------------------------------------------

class TestMod11Bandwidth:
    def test_chart_spec_present(self) -> None:
        from src.report.analysis.mod11_bandwidth import bandwidth_analysis
        result = bandwidth_analysis(_make_traffic_df())
        _assert_chart_spec(result)

    def test_chart_spec_structure(self) -> None:
        from src.report.analysis.mod11_bandwidth import bandwidth_analysis
        spec = bandwidth_analysis(_make_traffic_df())["chart_spec"]
        assert spec["type"] in ("bar", "line")
        assert "data" in spec


# ---------------------------------------------------------------------------
# mod12 — executive_summary (takes results dict, not DataFrame)
# ---------------------------------------------------------------------------

def _make_exec_results() -> dict:
    return {
        "mod01": {
            "total_flows": 4,
            "allowed_flows": 2,
            "blocked_flows": 1,
            "potentially_blocked_flows": 1,
            "policy_coverage_pct": 50.0,
            "src_managed_pct": 75.0,
            "total_mb": 0.04,
            "total_connections": 20,
            "unique_src_ips": 4,
            "unique_dst_ips": 4,
            "date_range": "2024-01-01 → 2024-01-02",
        },
        "mod03": {
            "enforced_coverage_pct": 50.0,
            "staged_coverage_pct": 25.0,
            "true_gap_pct": 25.0,
            "n_allowed": 2,
            "n_potentially_blocked": 1,
            "n_blocked": 1,
        },
        "mod04": {"risk_flows_total": 3},
        "mod05": {"total_lateral_flows": 1},
        "mod08": {"unique_unmanaged_src": 1},
        "mod11": {"bytes_data_available": True, "total_mb": 0.04},
        "mod13": {"attack_posture_items": [], "enforcement_mode_distribution": {"full": 2, "visibility_only": 1}},
        "mod14": {"attack_posture_items": []},
        "mod15": {"attack_posture_items": []},
        "findings": [],
    }


class TestMod12ExecutiveSummary:
    def test_chart_spec_present(self) -> None:
        from src.report.analysis.mod12_executive_summary import executive_summary
        result = executive_summary(_make_exec_results())
        _assert_chart_spec(result)

    def test_chart_spec_structure(self) -> None:
        from src.report.analysis.mod12_executive_summary import executive_summary
        spec = executive_summary(_make_exec_results())["chart_spec"]
        assert spec["type"] in ("bar", "pie")
        assert "data" in spec


# ---------------------------------------------------------------------------
# mod13 — enforcement_readiness
# ---------------------------------------------------------------------------

class TestMod13Readiness:
    def test_chart_spec_present(self) -> None:
        from src.report.analysis.mod13_readiness import enforcement_readiness
        result = enforcement_readiness(_make_traffic_df())
        _assert_chart_spec(result)

    def test_chart_spec_structure(self) -> None:
        from src.report.analysis.mod13_readiness import enforcement_readiness
        spec = enforcement_readiness(_make_traffic_df())["chart_spec"]
        assert spec["type"] in ("bar", "pie")
        assert "data" in spec


# ---------------------------------------------------------------------------
# mod14 — infrastructure_scoring
# ---------------------------------------------------------------------------

class TestMod14Infrastructure:
    def test_chart_spec_present(self) -> None:
        from src.report.analysis.mod14_infrastructure import infrastructure_scoring
        result = infrastructure_scoring(_make_traffic_df())
        _assert_chart_spec(result)

    def test_chart_spec_structure(self) -> None:
        from src.report.analysis.mod14_infrastructure import infrastructure_scoring
        spec = infrastructure_scoring(_make_traffic_df())["chart_spec"]
        assert spec["type"] in ("bar", "pie", "network")
        assert "data" in spec
