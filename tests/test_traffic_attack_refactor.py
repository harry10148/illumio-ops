from unittest.mock import MagicMock

import pandas as pd

import src.i18n as _i18n
from src.report.analysis.mod12_executive_summary import executive_summary
from src.report.analysis.mod13_readiness import enforcement_readiness
from src.report.analysis.mod14_infrastructure import infrastructure_scoring
from src.report.analysis.mod15_lateral_movement import lateral_movement_risk
from src.report.exporters.html_exporter import HtmlExporter
from src.report.report_generator import ReportGenerator, _build_snapshot


def _traffic_df():
    rows = [
        {
            "src_app": "ordering",
            "src_env": "prod",
            "dst_app": "payment",
            "dst_env": "prod",
            "src_ip": "10.0.0.1",
            "dst_ip": "10.0.0.2",
            "src_managed": True,
            "dst_managed": True,
            "policy_decision": "allowed",
            "port": 443,
            "num_connections": 120,
            "first_detected": "2026-04-01T00:00:00Z",
            "last_detected": "2026-04-01T00:05:00Z",
            "bytes_total": 1024,
            "bandwidth_mbps": 1.0,
        },
        {
            "src_app": "ordering",
            "src_env": "prod",
            "dst_app": "db",
            "dst_env": "prod",
            "src_ip": "10.0.0.1",
            "dst_ip": "10.0.0.3",
            "src_managed": True,
            "dst_managed": True,
            "policy_decision": "allowed",
            "port": 3306,
            "num_connections": 80,
            "first_detected": "2026-04-01T00:00:00Z",
            "last_detected": "2026-04-01T00:05:00Z",
            "bytes_total": 2048,
            "bandwidth_mbps": 2.0,
        },
        {
            "src_app": "laptop",
            "src_env": "users",
            "dst_app": "db",
            "dst_env": "prod",
            "src_ip": "10.1.0.10",
            "dst_ip": "10.0.0.3",
            "src_managed": False,
            "dst_managed": True,
            "policy_decision": "potentially_blocked",
            "port": 3389,
            "num_connections": 60,
            "first_detected": "2026-04-01T00:00:00Z",
            "last_detected": "2026-04-01T00:05:00Z",
            "bytes_total": 4096,
            "bandwidth_mbps": 3.0,
        },
        {
            "src_app": "monitoring",
            "src_env": "dev",
            "dst_app": "ordering",
            "dst_env": "prod",
            "src_ip": "10.2.0.4",
            "dst_ip": "10.0.0.1",
            "src_managed": True,
            "dst_managed": True,
            "policy_decision": "blocked",
            "port": 22,
            "num_connections": 25,
            "first_detected": "2026-04-01T00:00:00Z",
            "last_detected": "2026-04-01T00:05:00Z",
            "bytes_total": 1024,
            "bandwidth_mbps": 1.5,
        },
    ]
    return pd.DataFrame(rows)


def test_mod13_returns_grouped_app_env_scores():
    out = enforcement_readiness(_traffic_df(), workloads=None, top_n=10)
    assert "app_env_scores" in out
    assert not out["app_env_scores"].empty
    assert "app_env_key" in out["app_env_scores"].columns
    assert set(out["app_env_scores"]["app_env_key"]).issuperset({"ordering|prod", "db|prod"})
    assert out["total_score"] >= 0


def test_mod14_applies_non_prod_penalty_and_tiers():
    out = infrastructure_scoring(_traffic_df(), top_n=20)
    assert "top_apps" in out
    assert not out["top_apps"].empty
    assert "app_env_key" in out["top_apps"].columns
    assert "tier" in out["top_apps"].columns

    prod = out["top_apps"][out["top_apps"]["app_env_key"] == "ordering|prod"]
    dev = out["top_apps"][out["top_apps"]["app_env_key"] == "monitoring|dev"]
    assert not prod.empty
    assert not dev.empty
    assert float(prod.iloc[0]["infrastructure_score"]) >= float(dev.iloc[0]["infrastructure_score"])


def test_mod15_outputs_graph_attack_views():
    out = lateral_movement_risk(_traffic_df(), top_n=20)
    assert "bridge_nodes" in out
    assert "top_reachable_nodes" in out
    assert "attack_paths" in out
    assert "app_chains" in out
    if not out["app_chains"].empty:
        assert "Source App (Env)" in out["app_chains"].columns


def test_executive_summary_contains_attack_sections():
    results = {
        "mod01": {"total_flows": 4, "policy_coverage_pct": 50, "src_managed_pct": 70, "total_mb": 2, "total_connections": 10, "unique_src_ips": 3, "unique_dst_ips": 3, "blocked_flows": 1, "potentially_blocked_flows": 1, "allowed_flows": 2, "date_range": "2026-04-01 ~ 2026-04-01"},
        "mod03": {},
        "mod04": {"risk_flows_total": 1},
        "mod05": {"total_lateral_flows": 2},
        "mod08": {"unique_unmanaged_src": 1},
        "mod11": {"bytes_data_available": True, "total_mb": 2},
        "mod13": {"attack_posture_items": []},
        "mod14": {"attack_posture_items": []},
        "mod15": {"attack_posture_items": []},
        "findings": [],
    }
    mod12 = executive_summary(results)
    for key in ("boundary_breaches", "suspicious_pivot_behavior", "blast_radius", "blind_spots", "action_matrix"):
        assert key in mod12


def test_html_exporter_renders_attack_summary_sections():
    results = {
        "mod12": {
            "generated_at": "2026-04-10 00:00:00",
            "kpis": [{"label": "Total Flows", "value": "4"}],
            "key_findings": [],
            "boundary_breaches": [{"severity": "HIGH", "finding": "Cross-env lateral flows found.", "action": "Restrict boundary rules."}],
            "suspicious_pivot_behavior": [],
            "blast_radius": [],
            "blind_spots": [],
            "action_matrix": [],
        },
        "mod01": {"total_flows": 4},
        "mod02": {},
        "mod03": {},
        "mod04": {},
        "mod05": {},
        "mod06": {},
        "mod07": {},
        "mod08": {},
        "mod09": {},
        "mod10": {},
        "mod11": {},
        "mod13": {"error": "No data"},
        "mod14": {"error": "No data"},
        "mod15": {"error": "No data"},
        "findings": [],
    }
    html = HtmlExporter(results)._build()
    assert "Boundary Breaches" in html
    assert "Action Matrix" in html


def test_report_email_body_renders_attack_summary():
    prev_lang = _i18n.get_language()
    _i18n.set_language("en")
    try:
        cm = MagicMock()
        cm.config = {"settings": {}}
        gen = ReportGenerator(cm, api_client=MagicMock())
        body = gen._build_email_body(
            {
                "generated_at": "2026-04-10 00:00:00",
                "kpis": [{"label": "Total Flows", "value": "4"}],
                "key_findings": [],
                "boundary_breaches": [{"severity": "HIGH", "finding": "Cross-env lateral flows found.", "action": "Restrict boundary rules."}],
                "suspicious_pivot_behavior": [],
                "blast_radius": [],
                "blind_spots": [],
                "action_matrix": [],
            }
        )
        assert "Attack Summary" in body
        assert "Boundary Breaches" in body
    finally:
        _i18n.set_language(prev_lang)


def test_snapshot_contains_attack_summary_keys():
    snap = _build_snapshot(
        {
            "mod01": {"total_flows": 1, "total_connections": 1, "policy_coverage_pct": 100, "allowed_flows": 1, "blocked_flows": 0, "potentially_blocked_flows": 0, "total_mb": 1, "date_range": "x", "top_ports": pd.DataFrame(), "top_protocols": pd.DataFrame()},
            "mod02": {},
            "mod03": {"total_uncovered": 0, "coverage_pct": 100, "top_flows": pd.DataFrame()},
            "mod04": {"risk_flows_total": 0},
            "mod08": {"unique_unmanaged_src": 0, "top_unmanaged_src": pd.DataFrame()},
            "mod11": {"bytes_data_available": False, "total_mb": 0, "top_by_bytes": pd.DataFrame(), "top_bandwidth": pd.DataFrame()},
            "mod12": {
                "generated_at": "2026-04-10 00:00:00",
                "kpis": [],
                "key_findings": [],
                "boundary_breaches": [],
                "suspicious_pivot_behavior": [],
                "blast_radius": [],
                "blind_spots": [],
                "action_matrix": [],
            },
        }
    )
    for key in ("boundary_breaches", "suspicious_pivot_behavior", "blast_radius", "blind_spots", "action_matrix"):
        assert key in snap

