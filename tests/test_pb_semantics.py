"""potentially_blocked is uncovered exposure, not staged/ready coverage.
This test guards against regressing the wording or metric calculation."""
import pandas as pd
import pytest

from src.report.analysis import mod03_uncovered_flows
from src.report.analysis import mod12_executive_summary
from src.report.analysis import mod13_readiness


def _flows_pb_only():
    return pd.DataFrame({
        "src_ip":          ["10.0.0.1", "10.0.0.2"],
        "dst_ip":          ["10.0.1.1", "10.0.1.2"],
        "src_hostname":    ["host-a", "host-b"],
        "dst_hostname":    ["svc-a", "svc-b"],
        "port":            [443, 80],
        "proto":           ["TCP", "TCP"],
        "num_connections": [5, 3],
        "policy_decision": ["potentially_blocked", "potentially_blocked"],
        "src_managed":     [True, True],
        "dst_managed":     [True, True],
        "src_app":         ["web", "web"],
        "dst_app":         ["db", "api"],
        "src_env":         ["prod", "prod"],
        "dst_env":         ["prod", "prod"],
    })


def _flows_allowed_only():
    return pd.DataFrame({
        "src_ip":          ["10.0.0.1"],
        "dst_ip":          ["10.0.1.1"],
        "src_hostname":    ["host-a"],
        "dst_hostname":    ["svc-a"],
        "port":            [443],
        "proto":           ["TCP"],
        "num_connections": [5],
        "policy_decision": ["allowed"],
        "src_managed":     [True],
        "dst_managed":     [True],
        "src_app":         ["web"],
        "dst_app":         ["db"],
        "src_env":         ["prod"],
        "dst_env":         ["prod"],
    })


def test_mod03_counts_pb_as_uncovered():
    out = mod03_uncovered_flows.uncovered_flows(_flows_pb_only())
    # PB flows are uncovered exposure
    pb = out.get("n_potentially_blocked", out.get("pb_count"))
    assert pb == 2, f"expected 2 PB uncovered, got {pb}; full output: {out}"


def test_mod13_pb_does_not_increase_readiness():
    out_pb = mod13_readiness.enforcement_readiness(_flows_pb_only())
    out_allow = mod13_readiness.enforcement_readiness(_flows_allowed_only())
    # Readiness should NOT credit PB as ready coverage; allowed-only should be >= PB-only
    ready_pb = out_pb.get("total_score", out_pb.get("ready_share", 0))
    ready_allow = out_allow.get("total_score", out_allow.get("ready_share", 0))
    assert ready_allow >= ready_pb, (
        "PB credited toward readiness — must not. "
        f"PB-only={ready_pb}, allowed-only={ready_allow}"
    )


def test_mod12_exposes_pb_uncovered_exposure_kpi():
    # Build minimal results dict with only mod03 populated
    results = {
        "mod01": {},
        "mod03": mod03_uncovered_flows.uncovered_flows(_flows_pb_only()),
        "mod04": {},
        "mod08": {},
        "mod11": {},
        "mod15": {},
        "findings": [],
    }
    out = mod12_executive_summary.executive_summary(results)
    # KPI must exist with new name (alias staged_coverage may also exist for one release)
    kpis_dict = {}
    if "kpis" in out and isinstance(out["kpis"], list):
        for kpi in out["kpis"]:
            if isinstance(kpi, dict) and "label" in kpi:
                kpis_dict[kpi["label"]] = kpi.get("value")
    assert "pb_uncovered_exposure" in kpis_dict or "PB Uncovered Exposure" in kpis_dict, (
        f"pb_uncovered_exposure KPI not found. Available KPIs: {list(kpis_dict.keys())}"
    )
    assert int(kpis_dict.get("pb_uncovered_exposure", kpis_dict.get("PB Uncovered Exposure", 0))) >= 1


def test_mod12_legacy_alias_present_for_one_release():
    """staged_coverage is preserved as a deprecated alias; remove in v3.21."""
    results = {
        "mod01": {},
        "mod03": mod03_uncovered_flows.uncovered_flows(_flows_pb_only()),
        "mod04": {},
        "mod08": {},
        "mod11": {},
        "mod15": {},
        "findings": [],
    }
    out = mod12_executive_summary.executive_summary(results)
    # The alias must still exist to not break dashboards on this release.
    kpis_dict = {}
    if "kpis" in out and isinstance(out["kpis"], list):
        for kpi in out["kpis"]:
            if isinstance(kpi, dict) and "label" in kpi:
                kpis_dict[kpi["label"]] = kpi.get("value")
    # Either in kpis or in kpi_aliases (if that structure exists)
    has_alias = (
        "staged_coverage" in kpis_dict or
        "Staged Coverage" in kpis_dict or
        "staged_coverage" in out.get("kpi_aliases", {})
    )
    assert has_alias, (
        f"staged_coverage alias not found for backward compatibility. "
        f"Available KPIs: {list(kpis_dict.keys())}, aliases: {out.get('kpi_aliases', {})}"
    )


def test_mod03_flow_label_includes_protocol():
    """Uncovered-flow labels must carry the protocol (443/TCP vs 443/UDP differ)."""
    out = mod03_uncovered_flows.uncovered_flows(_flows_pb_only())
    labels = out["top_flows"]["Flow"].tolist()
    assert "web → db:443/TCP" in labels, labels
    assert "web → api:80/TCP" in labels, labels
    for s in labels:
        dst = s.split("→", 1)[1]
        assert "/" in dst, f"missing protocol in flow label: {s}"


def test_mod03_flow_label_graceful_without_proto_column():
    """No proto column -> bare port, no crash, no dangling slash."""
    df = _flows_pb_only().drop(columns=["proto"])
    out = mod03_uncovered_flows.uncovered_flows(df)
    labels = out["top_flows"]["Flow"].tolist()
    assert "web → db:443" in labels, labels
    assert all(not s.endswith("/") for s in labels), labels
