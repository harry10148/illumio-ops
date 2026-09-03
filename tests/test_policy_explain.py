"""Phase 3A Task 5 — src/api/policy_explain: actor resolution, PCE call, result shape."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.api import policy_explain as pe

FIX = Path(__file__).parent / "fixtures" / "pce_rule_search"


def _fixture(name):
    return json.loads((FIX / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def _fresh_caches():
    from src.gui import filter_object_cache as foc
    pe.clear_result_cache()
    foc._cache.clear()
    foc._last_good.clear()
    yield
    pe.clear_result_cache()
    foc._cache.clear()
    foc._last_good.clear()


def _api(hit="allow_hit", status=None):
    api = MagicMock()
    api.base_url = "https://pce.test/api/v2/orgs/1"
    api.fetch_managed_workloads.return_value = [
        {"href": "/orgs/1/workloads/w-web", "interfaces": [{"address": "10.1.1.10"}, {"address": "fe80::1"}]},
        {"href": "/orgs/1/workloads/w-db", "interfaces": [{"address": "10.1.2.20"}]},
    ]
    api.get_ip_lists.return_value = [
        {"href": "/orgs/1/sec_policy/active/ip_lists/corp", "name": "corp",
         "ip_ranges": [{"from_ip": "192.168.0.0/16"}, {"from_ip": "192.168.99.0/24", "exclusion": True}]},
        {"href": "/orgs/1/sec_policy/active/ip_lists/range", "name": "range",
         "ip_ranges": [{"from_ip": "172.16.0.1", "to_ip": "172.16.0.50"}]},
        {"href": "/orgs/1/sec_policy/active/ip_lists/fqdn", "name": "fqdn", "fqdns": [{"fqdn": "x.example"}]},
    ]
    fx = _fixture(hit)
    api.rule_search.return_value = (status or fx["status"], fx["response"])
    return api


# ── helpers ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("proto, n", [("TCP", 6), ("udp", 17), ("ICMP", 1), (6, 6), ("17", 17)])
def test_proto_number(proto, n):
    assert pe.proto_number(proto) == n


def test_proto_number_rejects_unknown():
    with pytest.raises(ValueError):
        pe.proto_number("carrier-pigeon")


def test_kind_from_href():
    assert pe.kind_from_href("/orgs/1/workloads/abc") == "workload"
    assert pe.kind_from_href("/orgs/1/kubernetes_workloads/abc") == "kubernetes_workload"
    assert pe.kind_from_href("/orgs/1/container_workloads/abc") == "container_workload"
    assert pe.kind_from_href("/orgs/1/sec_policy/active/ip_lists/1") == "ip_list"
    assert pe.kind_from_href("/orgs/1/labels/1") is None


# ── actor resolution ────────────────────────────────────────────────────────

def test_resolve_prefers_href_from_the_flow_row():
    api = _api()
    a = pe.resolve_actor(api, href="/orgs/1/kubernetes_workloads/k1", ip="10.85.58.213")
    assert a.kind == "kubernetes_workload" and a.href.endswith("/k1")
    api.fetch_managed_workloads.assert_not_called()


def test_resolve_ip_to_managed_workload():
    a = pe.resolve_actor(_api(), href=None, ip="10.1.2.20")
    assert a.kind == "workload" and a.href == "/orgs/1/workloads/w-db"


def test_resolve_ip_to_iplist_cidr_and_range_with_exclusion():
    api = _api()
    assert pe.resolve_actor(api, href=None, ip="192.168.5.5").href.endswith("/corp")
    assert pe.resolve_actor(api, href=None, ip="192.168.99.5").kind == "unresolved"   # excluded range
    assert pe.resolve_actor(api, href=None, ip="172.16.0.33").href.endswith("/range")
    assert pe.resolve_actor(api, href=None, ip="8.8.8.8").kind == "unresolved"


def test_resolve_unparsable_ip_is_unresolved():
    assert pe.resolve_actor(_api(), href=None, ip="not-an-ip").kind == "unresolved"


def test_workload_lookup_is_cached_across_calls():
    api = _api()
    pe.resolve_actor(api, href=None, ip="10.1.1.10")
    pe.resolve_actor(api, href=None, ip="10.1.2.20")
    assert api.fetch_managed_workloads.call_count == 1


# ── explain_flow ────────────────────────────────────────────────────────────

def test_explain_sends_resolved_sides_only_and_shapes_hits():
    api = _api()
    r = pe.explain_flow(api, src={"ip": "10.1.1.10"}, dst={"href": "/orgs/1/workloads/w-db"},
                        port=22, proto="TCP")
    body, kw = api.rule_search.call_args[0][0], api.rule_search.call_args[1]
    assert body["consumers"] == [{"workload": {"href": "/orgs/1/workloads/w-web"}}]
    assert body["providers"] == [{"workload": {"href": "/orgs/1/workloads/w-db"}}]
    assert body["ingress_services"] == [{"port": 22, "proto": 6}]
    assert body["rule_types"] == pe.RULE_TYPES and kw["pversion"] == "active"
    assert r["source"] == "pce_rule_search" and r["pce_status"] == 200 and r["pce_error"] is None
    assert len(r["allow"]) == 1 and r["deny"] == [] and r["override_deny"] == []
    hit = r["allow"][0]
    assert hit["ruleset_href"].startswith("/orgs/") and hit["ruleset_name"]
    assert hit["rule_href"].startswith("/orgs/") and hit["rule_enabled"] is True
    assert hit["consumers"] == ["role=Web"] or hit["consumers"][0].startswith("role=")
    assert hit["ingress_services"] == ["22/TCP"]
    assert "update_type" in hit
    assert r["counts"]["sec_rules"]["matched"] == 1
    assert "partial" not in r


def test_explain_no_match_returns_empty_lists_from_pce():
    r = pe.explain_flow(_api(hit="no_match"), src={"ip": "10.1.1.10"}, dst={"ip": "10.1.2.20"}, port=65000, proto=6)
    assert r["source"] == "pce_rule_search" and r["allow"] == [] and r["counts"]["sec_rules"]["matched"] == 0


def test_explain_skips_pce_when_neither_side_resolves():
    api = _api()
    r = pe.explain_flow(api, src={"ip": "8.8.8.8"}, dst={"ip": "9.9.9.9"}, port=443, proto="TCP")
    assert r["source"] == "none" and r["allow"] == [] and r["pce_status"] is None
    api.rule_search.assert_not_called()


def test_explain_marks_partial_when_one_side_unresolved():
    api = _api()
    r = pe.explain_flow(api, src={"ip": "8.8.8.8"}, dst={"ip": "10.1.2.20"}, port=443, proto="TCP")
    body = api.rule_search.call_args[0][0]
    assert "consumers" not in body and body["providers"]
    assert r["partial"] is True and r["src"]["kind"] == "unresolved"


def test_explain_surfaces_pce_error_body():
    api = _api(hit="schema_error_destinations")
    r = pe.explain_flow(api, src={"ip": "10.1.1.10"}, dst={"ip": "10.1.2.20"}, port=22, proto=6)
    assert r["pce_status"] == 406 and r["pce_error"] and r["allow"] == []


def test_explain_transport_failure_is_reported_not_swallowed():
    api = _api()
    api.rule_search.return_value = (0, None)
    r = pe.explain_flow(api, src={"ip": "10.1.1.10"}, dst={"ip": "10.1.2.20"}, port=22, proto=6)
    assert r["pce_status"] == 0 and r["pce_error"] == "no response"


def test_explain_rejects_bad_basis_and_proto():
    with pytest.raises(ValueError):
        pe.explain_flow(_api(), src={"ip": "10.1.1.10"}, dst={"ip": "10.1.2.20"}, port=22, proto=6, basis="live")
    with pytest.raises(ValueError):
        pe.explain_flow(_api(), src={"ip": "10.1.1.10"}, dst={"ip": "10.1.2.20"}, port=22, proto="x")


def test_explain_result_cache_hits_within_ttl():
    api = _api()
    kw = dict(src={"ip": "10.1.1.10"}, dst={"ip": "10.1.2.20"}, port=22, proto=6)
    first = pe.explain_flow(api, **kw)
    second = pe.explain_flow(api, **kw)
    assert api.rule_search.call_count == 1
    assert second["cached"] is True and "cached" not in first
    pe.explain_flow(api, **{**kw, "basis": "draft"})
    assert api.rule_search.call_count == 2
