"""Ransomware breakdown and traffic overlay: per host on demand, every host in the hourly step."""
import json
from datetime import timedelta

import responses

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import CapabilityState, DataOrigin, IngestSource
from illumio_ops.services.analysis.hourly import HOURLY_STEPS
from illumio_ops.services.analysis.ransomware import host_ransomware, ransomware_overlay
from illumio_ops.store.flowdb import (
    analysis,
    capabilities,
    ingest_state,
    ransomware,
    workloads,
)
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.services.collect.conftest import NOW, PCE, configured_ctx, raw_flow

FIN, WEB = "/orgs/1/workloads/fin", "/orgs/1/workloads/web"


def _wl(href, name, percent, exposure="critical"):
    return workloads.WorkloadRow(href=href, hostname=name, name=None, managed=1, enforcement_mode="visibility_only",
                                 visibility_level=None, os_id=None, ven_version=None, ven_href=None, label_set=None,
                                 online=1, risk_exposure=exposure, risk_percent=percent, risk_updated_at=None,
                                 fetched_at="x")


def _svc(name, port, severity, state, status, active="blocked_by_override_deny"):
    return {"name": name, "port": port, "proto": 6, "severity": severity, "category": "admin",
            "protection_state": state, "port_status": status, "active_policy": active, "recommendation": ""}


def _ctx(tmp_path, *, covered_days=31, **collection):
    ctx = configured_ctx(tmp_path, **collection)
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, NOW - timedelta(days=covered_days), NOW)
        workloads.replace_inventory(conn, [_wl(FIN, "fin-db", 0.0, "fully_protected"), _wl(WEB, "web", 10.0)])
        ransomware.upsert_services(conn, FIN, [_svc("RDP", 3389, "critical", "protected_closed", "listening")],
                                   source_updated_at=None, at=NOW)
        ransomware.upsert_services(conn, WEB, [
            _svc("RDP", 3389, "critical", "unprotected", "listening", active="allowed"),
            _svc("SMB", 445, "high", "unprotected", "listening"),
            _svc("WinRM", 5985, "medium", "unprotected", "inactive")], source_updated_at=None, at=NOW)
        recs = []
        for i, port in enumerate((3389, 3389, 5985)):
            raw = raw_flow(10 + i, NOW - timedelta(days=2, minutes=5), NOW - timedelta(days=2), port=port)
            raw["dst"]["workload"]["href"] = WEB
            recs.append(normalize_flow(raw))
        upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW)
    return ctx


def test_overlay_written_by_hourly_step(tmp_path):
    assert ("ransomware", HOURLY_STEPS[1][1]) == HOURLY_STEPS[1] and HOURLY_STEPS[0][0] == "exposure"
    ctx = _ctx(tmp_path)
    ransomware_overlay(ctx, NOW)
    with ctx.flows().connect() as conn:
        res = json.loads(analysis.read_result(conn, "ransomware")["result_json"])
    assert [(s["host"], s["name"]) for s in res["priority"]] == [(WEB, "RDP")]
    assert [(s["host"], s["name"]) for s in res["safe_to_block"]] == [(WEB, "SMB")]
    assert [(s["host"], s["name"]) for s in res["suspicious"]] == [(WEB, "WinRM")]
    assert res["contradictions"] == 1 and res["unsupported"] is False
    hosts = {h["href"]: h for h in res["hosts"]}
    assert hosts[FIN]["contradiction"] is True and hosts[FIN]["computed_percent"] == 100.0


def test_contradiction_not_used_for_sorting(tmp_path):
    ctx = _ctx(tmp_path)
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [_wl(FIN, "fin-db", 0.0, "fully_protected"), _wl(WEB, "web", 99.0)])
    ransomware_overlay(ctx, NOW)
    with ctx.flows().connect() as conn:
        res = json.loads(analysis.read_result(conn, "ransomware")["result_json"])
    # the lists follow the services' own weight and traffic, never the PCE percent
    assert [s["name"] for s in res["priority"] + res["safe_to_block"] + res["suspicious"]] == ["RDP", "SMB", "WinRM"]


def test_unsupported_capability_reported(tmp_path):
    ctx = _ctx(tmp_path)
    with ctx.flows().connect() as conn:
        capabilities.record(conn, "ransomware_risk", CapabilityState.UNSUPPORTED, "no risk_summary", NOW)
    ransomware_overlay(ctx, NOW)
    with ctx.flows().connect() as conn:
        assert json.loads(analysis.read_result(conn, "ransomware")["result_json"]) == {"unsupported": True}


@responses.activate
def test_allow_attribution_only_for_allowed_services(tmp_path):
    org = f"{PCE['url']}/api/v2/orgs/1"
    responses.add(responses.POST, f"{org}/sec_policy/active/rule_search", json={
        "sec_rules": [{"href": "/orgs/1/sec_policy/active/rule_sets/5/sec_rules/9", "enabled": True,
                       "consumers": [{"actors": "ams"}], "providers": [{"workload": {"href": WEB}}],
                       "ingress_services": [{"port": 3389, "proto": 6}],
                       "rule_set": {"href": "/orgs/1/sec_policy/active/rule_sets/5", "name": "Admin access"}}],
        "deny_rules": [], "override_deny_rules": []})
    r = host_ransomware(_ctx(tmp_path), WEB, now=NOW)
    assert list(r.allow_rules) == ["3389/6"] and r.allow_rules["3389/6"][0].ruleset_name == "Admin access"
    assert len(responses.calls) == 1  # SMB and WinRM are blocked by an override deny: nothing to explain
    assert {s.name: s.traffic.value for s in r.breakdown.services} == {"RDP": "priority", "SMB": "safe_to_block",
                                                                        "WinRM": "suspicious"}
    assert r.breakdown.hostname == "web" and r.breakdown.pce_percent == 10.0


def _classes(ctx):
    ransomware_overlay(ctx, NOW)
    with ctx.flows().connect() as conn:
        res = json.loads(analysis.read_result(conn, "ransomware")["result_json"])
    return {(h["href"], s["name"]): s["traffic"] for h in res["hosts"] for s in h["services"]}, res


def test_traffic_not_collected_is_unknown_not_safe_to_block(tmp_path):
    # Final review #4: no traffic collected read as "nobody connects", so a listening RDP was "safe to block".
    classes, res = _classes(_ctx(tmp_path, mode="lightweight"))
    assert classes[(WEB, "SMB")] == "unknown" and res["safe_to_block"] == []


def test_traffic_watched_shorter_than_the_window_is_unknown(tmp_path):
    classes, _ = _classes(_ctx(tmp_path, covered_days=1))
    assert classes[(WEB, "SMB")] == "unknown"


def test_hole_or_failed_gap_in_the_window_is_unknown(tmp_path):
    # Security review of 92d642b1: a period watched with a hole, or with a failed read, proves no "nobody".
    ctx = _ctx(tmp_path)
    with ctx.flows().connect() as conn:
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW - timedelta(days=3), NOW - timedelta(days=2, hours=23),
                                "failed", "x", NOW)
    assert _classes(ctx)[0][(WEB, "SMB")] == "unknown"
    holed = configured_ctx(tmp_path / "holed")
    with holed.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, NOW - timedelta(days=31), NOW - timedelta(days=10))
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, NOW - timedelta(days=9), NOW)
        workloads.replace_inventory(conn, [_wl(WEB, "web", 10.0)])
        ransomware.upsert_services(conn, WEB, [_svc("SMB", 445, "high", "unprotected", "listening")],
                                   source_updated_at=None, at=NOW)
    assert _classes(holed)[0][(WEB, "SMB")] == "unknown"


def test_collection_that_stopped_is_unknown(tmp_path):
    # Security review of 2e8efd82: coverage must reach the present, not only start early enough.
    ctx = configured_ctx(tmp_path)
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, NOW - timedelta(days=40), NOW - timedelta(days=10))
        workloads.replace_inventory(conn, [_wl(WEB, "web", 10.0)])
        ransomware.upsert_services(conn, WEB, [_svc("SMB", 445, "high", "unprotected", "listening")],
                                   source_updated_at=None, at=NOW)
    assert _classes(ctx)[0][(WEB, "SMB")] == "unknown"


@responses.activate
def test_failed_allow_explanation_is_kept_per_service(tmp_path):
    # Final review #17: a Rule Search failure left an empty list, indistinguishable from "no allow rule".
    org = f"{PCE['url']}/api/v2/orgs/1"
    responses.add(responses.POST, f"{org}/sec_policy/active/rule_search", status=500, json={})
    r = host_ransomware(_ctx(tmp_path), WEB, now=NOW)
    assert r.allow_rules == {"3389/6": []} and r.allow_status == {"3389/6": "error"}
