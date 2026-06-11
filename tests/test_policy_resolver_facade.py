"""Tests for the policy-resolver facade: lookup builders + run()."""
from __future__ import annotations

from unittest.mock import MagicMock

from src.report.policy_resolver_report import (
    build_workload_to_ips,
    build_label_to_ips,
    build_iplist_to_cidrs,
    build_label_group_to_labels,
    build_service_to_ports,
    build_service_to_names,
    PolicyResolverReport,
)


def test_build_workload_to_ips_skips_missing_address():
    wls = [{"href": "/wl/1", "interfaces": [
        {"address": "10.0.0.1"}, {"name": "eth1"}, {"address": "10.0.0.2"}]}]
    assert build_workload_to_ips(wls) == {"/wl/1": ["10.0.0.1", "10.0.0.2"]}


def test_build_label_to_ips_single_pass_groups_by_label():
    wls = [
        {"href": "/wl/1", "interfaces": [{"address": "10.0.0.1"}],
         "labels": [{"href": "/labels/web"}, {"href": "/labels/prod"}]},
        {"href": "/wl/2", "interfaces": [{"address": "10.0.0.2"}],
         "labels": [{"href": "/labels/web"}]},
    ]
    out = build_label_to_ips(wls)
    assert set(out["/labels/web"]) == {"10.0.0.1", "10.0.0.2"}
    assert out["/labels/prod"] == ["10.0.0.1"]


def test_build_iplist_to_cidrs_ranges_and_fqdn():
    ipls = [{"href": "/ip_lists/5",
             "ip_ranges": [{"from_ip": "10.0.0.0", "to_ip": "10.0.255.255"},
                           {"from_ip": "192.168.1.1"}],
             "fqdns": [{"fqdn": "db.corp.local"}]}]
    out = build_iplist_to_cidrs(ipls)
    assert out["/ip_lists/5"] == ["10.0.0.0-10.0.255.255", "192.168.1.1",
                                  "db.corp.local"]


def test_build_label_group_to_labels_recursive():
    groups = [
        {"href": "/lg/outer", "labels": [{"href": "/labels/a"}],
         "sub_groups": [{"href": "/lg/inner"}]},
        {"href": "/lg/inner", "labels": [{"href": "/labels/b"}], "sub_groups": []},
    ]
    out = build_label_group_to_labels(groups)
    assert set(out["/lg/outer"]) == {"/labels/a", "/labels/b"}
    assert out["/lg/inner"] == ["/labels/b"]


def test_build_label_group_to_labels_cycle_safe():
    groups = [
        {"href": "/lg/A", "labels": [{"href": "/labels/x"}],
         "sub_groups": [{"href": "/lg/B"}]},
        {"href": "/lg/B", "labels": [{"href": "/labels/y"}],
         "sub_groups": [{"href": "/lg/A"}]},
    ]
    out = build_label_group_to_labels(groups)
    assert set(out["/lg/A"]) == {"/labels/x", "/labels/y"}
    assert set(out["/lg/B"]) == {"/labels/x", "/labels/y"}


def test_build_service_to_ports():
    svcs = [{"href": "/services/2", "service_ports": [{"port": 443, "proto": 6}]}]
    assert build_service_to_ports(svcs) == {"/services/2": [{"port": 443, "proto": 6}]}


def test_run_produces_module_results_per_ruleset():
    api = MagicMock()
    api.get_active_rulesets.return_value = [{
        "name": "App-Tier",
        "scopes": [],
        "rules": [{
            "href": "/sec_rules/1",
            "consumers": [{"label": {"href": "/labels/web"}}],
            "providers": [{"label": {"href": "/labels/db"}}],
            "ingress_services": [{"port": 443, "proto": 6}],
        }],
    }]
    api.fetch_managed_workloads.return_value = [
        {"href": "/wl/1", "interfaces": [{"address": "10.0.1.5"}],
         "labels": [{"href": "/labels/web"}]},
        {"href": "/wl/2", "interfaces": [{"address": "10.0.2.7"}],
         "labels": [{"href": "/labels/db"}]},
    ]
    api.get_ip_lists.return_value = []
    api.get_label_groups.return_value = []
    api.get_services.return_value = []

    rep = PolicyResolverReport(cm=MagicMock(), api_client=api)
    results = rep.resolve()                      # build lookups + resolve, no export
    rows = results["rulesets"]["App-Tier"]
    assert {(r["src_ip"], r["dst_ip"], r["port"]) for r in rows} == {
        ("10.0.1.5", "10.0.2.7", 443)}


def test_build_service_to_names_skips_nameless():
    svcs = [{"href": "/services/2", "name": "HTTPS",
             "service_ports": [{"port": 443, "proto": 6}]},
            {"href": "/services/3"}]  # no name -> skipped
    assert build_service_to_names(svcs) == {"/services/2": "HTTPS"}
