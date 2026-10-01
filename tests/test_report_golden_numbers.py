"""Golden numbers: a hand-built traffic set whose KPIs were worked out on paper.

Every expected value below is derived in the comments from the ten flows, not
copied from a run. If one of these assertions fails, either the arithmetic of a
report KPI changed (decide whether that is intended and update the derivation)
or a module stopped receiving what it should from the pipeline.

The flows go through the real path: PCE-shaped records → APIParser → the
module registry for the security_risk profile → mod12, with the shipped
config/report_config.yaml (ransomware and lateral-movement port lists). The
audit half does the same for PCE events → AuditGenerator's DataFrame build →
its module pipeline.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.report.parsers.api_parser import APIParser
from src.report.report_generator import ReportGenerator

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

# ip -> (app, env, enforcement_mode); a missing ip is an unmanaged host.
_WORKLOADS = {
    "10.0.0.1": ("web", "prod", "full"),
    "10.0.0.2": ("web", "prod", "full"),
    "10.0.0.3": ("app", "dev", "selective"),
    "10.0.1.1": ("db", "prod", "full"),
    "10.0.1.2": ("db", "prod", "visibility_only"),
}

# (src, dst, port, proto, connections, decision)
_FLOWS = [
    ("10.0.0.1", "10.0.1.1", 5432, 6, 10, "allowed"),               # 1
    ("10.0.0.1", "10.0.1.1", 443, 6, 5, "allowed"),                 # 2
    ("10.0.0.2", "10.0.1.2", 445, 6, 3, "potentially_blocked"),     # 3  SMB
    ("10.0.0.2", "10.0.1.2", 3389, 6, 2, "blocked"),                # 4  RDP
    ("10.0.0.3", "10.0.1.2", 22, 6, 4, "potentially_blocked"),      # 5  SSH
    ("10.0.0.3", "10.0.1.1", 8080, 6, 1, "allowed"),                # 6
    ("192.168.1.5", "10.0.1.1", 443, 6, 6, "blocked"),              # 7  unmanaged src
    ("10.0.0.1", "10.0.1.2", 53, 17, 7, "potentially_blocked"),     # 8  DNS/UDP
    ("10.0.0.2", "10.0.1.1", 443, 6, 8, "allowed"),                 # 9
    ("10.0.0.3", "10.0.1.2", 9000, 6, 1, "unknown"),                # 10
]


def _endpoint(ip: str) -> dict:
    wl = _WORKLOADS.get(ip)
    if wl is None:
        return {"ip": ip}
    app, env, mode = wl
    return {"ip": ip, "workload": {
        "hostname": f"h-{ip}", "enforcement_mode": mode,
        "labels": [{"key": "app", "value": app}, {"key": "env", "value": env}],
    }}


def _records() -> list[dict]:
    return [{
        "src": _endpoint(src), "dst": _endpoint(dst),
        "service": {"port": port, "proto": proto},
        "num_connections": conns, "policy_decision": decision,
        "first_detected": f"2026-09-0{i % 9 + 1}T00:00:00Z",
        "last_detected": f"2026-09-0{i % 9 + 1}T01:00:00Z",
    } for i, (src, dst, port, proto, conns, decision) in enumerate(_FLOWS)]


@pytest.fixture(scope="module")
def results() -> dict:
    df = APIParser().parse(_records())
    gen = ReportGenerator(config_dir=str(CONFIG_DIR))
    out = gen._run_modules(df, findings=[], traffic_report_profile="security_risk", lang="en")
    assert out["_module_errors"] == []
    return out


def test_traffic_overview(results):
    m = results["mod01"]
    assert m["total_flows"] == 10
    # 10+5+3+2+4+1+6+7+8+1
    assert m["total_connections"] == 47
    # allowed: #1 #2 #6 #9; PB: #3 #5 #8; blocked: #4 #7; unknown: #10
    assert (m["allowed_flows"], m["potentially_blocked_flows"],
            m["blocked_flows"], m["unknown_flows"]) == (4, 3, 2, 1)
    assert m["policy_coverage_pct"] == 40.0
    # .1 .2 .3 and the unmanaged 192.168.1.5; destinations .1.1 and .1.2
    assert (m["unique_src_ips"], m["unique_dst_ips"]) == (4, 2)
    # only #7 has an unmanaged source
    assert m["src_managed_pct"] == 90.0
    assert m["dst_managed_pct"] == 100.0


def test_coverage_tiers(results):
    m = results["mod03"]
    assert m["enforced_coverage_pct"] == 40.0        # 4 allowed / 10
    assert m["pb_uncovered_share"] == 30.0           # 3 PB / 10 — exposure, not progress
    assert m["true_gap_pct"] == 30.0                 # (2 blocked + 1 unknown) / 10
    assert m["total_uncovered"] == 6
    # destination enforced (full): #1 #2 #6 #7 #9 → 5 of 10
    assert m["dst_enforced_flow_pct"] == 50.0


def test_ransomware_exposure_counts_blocked_as_controlled(results):
    m = results["mod04"]
    # risk ports in config: 445 (#3), 3389 (#4), 22 (#5)
    assert m["risk_flows_total"] == 3
    # #4 is blocked, so it is controlled
    assert m["risk_flows_unblocked"] == 2


def test_lateral_movement_excludes_blocked(results):
    m = results["mod15"]
    # lateral ports: 445 (#3, PB), 3389 (#4, blocked), 22 (#5, PB)
    assert m["blocked_lateral_flows"] == 1
    assert m["total_lateral_flows"] == 2
    assert m["lateral_pct"] == 20.0                  # 2 / 10


def test_enforcement_progress_and_breaks(results):
    m = results["mod_enforcement"]
    progress = m["progress"].set_index("App (Env)")["Enforced %"].to_dict()
    # web(prod): .1 full, .2 full; app(dev): .3 selective (counts half);
    # db(prod): .1.1 full, .1.2 visibility_only; the unmanaged host has no mode.
    assert progress == {"web (prod)": 100.0, "app (dev)": 50.0, "db (prod)": 50.0}
    rules = m["breaks_on_enforcement"][["Suggested Allow Rule", "Connections"]]
    # The three PB flows, ordered by connections (7, 4, 3).
    assert [tuple(r) for r in rules.itertuples(index=False)] == [
        ("web (prod) → db (prod) : 53/UDP", 7),
        ("app (dev) → db (prod) : 22/TCP", 4),
        ("web (prod) → db (prod) : 445/TCP", 3),
    ]


def test_maturity_score(results):
    m = results["mod12"]
    dims = m["maturity_dimensions"]
    # No workload list, so enforcement comes from flow destinations: 50% → 0.5
    assert dims["enforcement_coverage"]["source"] == "flow_destinations"
    assert dims["enforcement_coverage"]["ratio"] == 0.5
    assert dims["policy_coverage"]["ratio"] == 0.4                 # 40% allowed
    assert dims["lateral_movement_control"]["ratio"] == 0.3333     # 1 - 20/30
    assert dims["managed_asset_ratio"]["ratio"] == 0.8             # 1 - 10/50
    assert dims["risk_port_control"]["ratio"] == 0.0               # 1 - min(2/10*5, 1)
    # 40*0.5 + 25*0.4 + 15*(1/3) + 10*0.8 + 10*0 = 20 + 10 + 5 + 8 + 0
    assert m["maturity_score"] == 43.0
    assert m["maturity_grade"] == "D"
    kpi = next(k for k in m["kpis"] if k["label_key"] == "mod12_kpi_maturity_score")
    assert kpi["value"] == "43.0/100 (D)"


# ── Audit (events) ───────────────────────────────────────────────────────────

def _event(i: int, event_type: str, status: str = "success", **extra) -> dict:
    return {"href": f"/orgs/1/events/{i}", "event_type": event_type, "status": status,
            "severity": "info", "timestamp": f"2026-09-01T00:{i:02d}:00Z",
            "created_by": {"user": {"username": "alice@example.com"}}, **extra}


_EVENTS = [
    _event(1, "user.sign_in"),                                   # ok login
    _event(2, "user.sign_in", status="failure"),                 # failed login
    _event(3, "user.sign_in", status="failure"),                 # failed login
    _event(4, "request.authentication_failed", status="failure"),  # failed login (401)
    _event(5, "request.authorization_failed", status="failure"),   # 403 — not a login failure
    _event(6, "sec_rule.create"),                                # draft rule change
    _event(7, "rule_set.update"),                                # draft rule change
    _event(8, "sec_policy.create", resource_changes=[            # provision, 60 workloads
        {"changes": {"workloads_affected": {"before": 0, "after": 60}}}]),
    _event(9, "sec_policy.create", resource_changes=[            # provision, 4 workloads
        {"changes": {"workloads_affected": {"before": 0, "after": 4}}}]),
    _event(10, "api_key.create"),                                # high-risk policy event
    _event(11, "agent.tampering", severity="err"),               # security concern
    _event(12, "agent.goodbye"),                                 # connectivity
    _event(13, "system_task.agent_offline_check"),               # connectivity
]


@pytest.fixture(scope="module")
def audit_results() -> dict:
    from src.report.audit_generator import AuditGenerator
    gen = AuditGenerator(config_dir=str(CONFIG_DIR))
    df = gen._build_dataframe(_EVENTS)
    out = gen._run_pipeline(df, "2026-09-01", "2026-09-02").module_results
    assert out["_module_errors"] == []
    return out


def test_audit_login_failures_keep_403_apart(audit_results):
    m = audit_results["mod02"]
    # #2 #3 failed sign-ins + #4 401; the 403 (#5) is counted on its own
    assert m["failed_logins"] == 3
    assert m["authorization_failures"] == 1
    # #1-#5 are user/auth events
    assert m["total_user_events"] == 5


def test_audit_policy_changes(audit_results):
    m = audit_results["mod03"]
    assert m["provision_count"] == 2                  # #8 #9
    assert m["rule_change_count"] == 2                # #6 #7
    assert m["high_risk_count"] == 1                  # #10
    assert m["total_policy_events"] == 5              # #6-#10
    assert m["total_workloads_affected"] == 64        # 60 + 4
    assert m["max_workloads_affected"] == 60
    # only #8 crosses the 50-workload high-impact threshold
    assert [p["workloads_affected"] for p in m["high_impact_provisions"]] == [60]


def test_audit_health(audit_results):
    m = audit_results["mod01"]
    assert m["security_concern_count"] == 1           # #11
    assert m["connectivity_event_count"] == 2         # #12 #13
    assert m["total_health_events"] == 3


def test_audit_executive_kpis(audit_results):
    kpis = {k["label_key"]: k["value"] for k in audit_results["mod00"]["kpis"]}
    assert kpis["rpt_au_kpi_total_events"] == "13"
    assert kpis["rpt_au_kpi_failed_logins"] == "3"
    assert kpis["rpt_au_kpi_security_concerns"] == "1"
