"""Tests for the PURE policy resolution core (synthetic lookups, zero I/O)."""
from __future__ import annotations

from src.report.analysis.policy_resolver import resolve_ruleset


# Shared synthetic lookups -------------------------------------------------
LABEL_TO_IPS = {
    "/labels/web": ["10.0.1.5", "10.0.1.6"],
    "/labels/db": ["10.0.2.7"],
}
IPLIST_TO_CIDRS = {"/ip_lists/dc": ["10.9.0.0/16"]}
LABELGROUP_TO_LABELS = {"/lg/apps": ["/labels/web", "/labels/db"]}
WORKLOAD_TO_IPS = {"/wl/jump": ["172.16.0.10"]}


def _lookups():
    return dict(
        label_to_ips=LABEL_TO_IPS,
        iplist_to_cidrs=IPLIST_TO_CIDRS,
        label_group_to_labels=LABELGROUP_TO_LABELS,
        workload_to_ips=WORKLOAD_TO_IPS,
    )


def _ruleset(rules, name="App-Tier", scopes=None):
    return {"name": name, "scopes": scopes or [], "rules": rules}


def test_label_to_label_cartesian_with_port():
    rs = _ruleset([{
        "href": "/sec_rules/1",
        "consumers": [{"label": {"href": "/labels/web"}}],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"port": 443, "proto": 6}],
    }])
    rows = resolve_ruleset(rs, **_lookups())
    pairs = {(r["src_ip"], r["dst_ip"], r["port"], r["protocol"]) for r in rows}
    assert pairs == {
        ("10.0.1.5", "10.0.2.7", 443, "TCP"),
        ("10.0.1.6", "10.0.2.7", 443, "TCP"),
    }
    assert all(r["ruleset_name"] == "App-Tier" for r in rows)
    assert all(r["src_kind"] == "label" and r["dst_kind"] == "label" for r in rows)


def test_udp_proto_17():
    rs = _ruleset([{
        "href": "/sec_rules/2",
        "consumers": [{"workload": {"href": "/wl/jump"}}],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"port": 53, "proto": 17}],
    }])
    rows = resolve_ruleset(rs, **_lookups())
    assert rows[0]["protocol"] == "UDP"
    assert rows[0]["src_ip"] == "172.16.0.10"
    assert rows[0]["src_kind"] == "workload"


def test_label_group_expands_recursively():
    rs = _ruleset([{
        "href": "/sec_rules/3",
        "consumers": [{"ip_list": {"href": "/ip_lists/dc"}}],
        "providers": [{"label_group": {"href": "/lg/apps"}}],
        "ingress_services": [{"port": 22, "proto": 6}],
    }])
    rows = resolve_ruleset(rs, **_lookups())
    dsts = {r["dst_ip"] for r in rows}
    assert dsts == {"10.0.1.5", "10.0.1.6", "10.0.2.7"}
    assert all(r["src_ip"] == "10.9.0.0/16" for r in rows)
    assert all(r["src_kind"] == "ip_list" and r["dst_kind"] == "label_group" for r in rows)


def test_ip_address_literal_and_ams_sentinel():
    rs = _ruleset([{
        "href": "/sec_rules/4",
        "consumers": [{"actors": "ams"}],
        "providers": [{"ip_address": {"value": "8.8.8.8"}}],
        "ingress_services": [{"port": 443, "proto": 6}],
    }])
    rows = resolve_ruleset(rs, **_lookups())
    assert rows[0]["src_ip"] == "ANY"
    assert rows[0]["src_kind"] == "any"
    assert rows[0]["dst_ip"] == "8.8.8.8"


def test_port_range_kept_as_from_to():
    rs = _ruleset([{
        "href": "/sec_rules/5",
        "consumers": [{"workload": {"href": "/wl/jump"}}],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"port": 8000, "to_port": 8100, "proto": 6}],
    }])
    rows = resolve_ruleset(rs, **_lookups())
    assert rows[0]["port"] == 8000
    assert rows[0]["port_to"] == 8100


def test_named_service_via_lookup():
    rs = _ruleset([{
        "href": "/sec_rules/6",
        "consumers": [{"workload": {"href": "/wl/jump"}}],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"href": "/services/https"}],
    }])
    rows = resolve_ruleset(
        rs, **_lookups(),
        service_to_ports={"/services/https": [{"port": 443, "proto": 6}]},
    )
    assert rows[0]["port"] == 443
    assert rows[0]["service_name"] == "/services/https"


def test_missing_label_yields_no_rows_no_error():
    rs = _ruleset([{
        "href": "/sec_rules/7",
        "consumers": [{"label": {"href": "/labels/UNKNOWN"}}],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"port": 443, "proto": 6}],
    }])
    rows = resolve_ruleset(rs, **_lookups())
    assert rows == []


def test_dedup_identical_rows():
    rs = _ruleset([{
        "href": "/sec_rules/8",
        "consumers": [{"label": {"href": "/labels/db"}},
                      {"label": {"href": "/labels/db"}}],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"port": 443, "proto": 6}],
    }])
    rows = resolve_ruleset(rs, **_lookups())
    assert len(rows) == 1


def test_scope_narrows_providers():
    # provider label /labels/web; scope restricts to /labels/db only -> no rows.
    rs = _ruleset(
        [{
            "href": "/sec_rules/9",
            "consumers": [{"workload": {"href": "/wl/jump"}}],
            "providers": [{"label": {"href": "/labels/web"}}],
            "ingress_services": [{"port": 443, "proto": 6}],
        }],
        scopes=[[{"label": {"href": "/labels/db"}}]],
    )
    rows = resolve_ruleset(rs, **_lookups())
    assert rows == []
