"""object_diff：三種 policy 物件的 added/removed/modified 純函式比對。"""

import pandas as pd

from src.report.analysis.policy_diff.object_diff import (
    diff_objects,
    object_change_counts,
    scan_object_refs,
)


def _ipl(oid, name, ranges=None, fqdns=None, desc="", side="draft"):
    return {
        "href": f"/orgs/1/sec_policy/{side}/ip_lists/{oid}",
        "name": name,
        "ip_ranges": ranges or [],
        "fqdns": fqdns or [],
        "description": desc,
    }


def test_added_object_single_star_row():
    df = diff_objects([_ipl(1, "New-L")], [], kind="ip_list",
                      fields=["ip_ranges", "fqdns", "description"])
    assert len(df) == 1
    row = df.iloc[0]
    assert row["change_type"] == "added"
    assert row["object_kind"] == "ip_list"
    assert row["field"] == "*"
    assert row["draft_value"] == "New-L"
    assert row["object_id"] == "1"
    assert bool(row["scope_expanded"]) is False


def test_removed_object_single_star_row():
    df = diff_objects([], [_ipl(2, "Old-L", side="active")], kind="ip_list",
                      fields=["ip_ranges", "fqdns", "description"])
    assert df.iloc[0]["change_type"] == "removed"
    assert df.iloc[0]["active_value"] == "Old-L"


def test_modified_ip_ranges_expansion_flagged():
    draft = [_ipl(3, "L", ranges=[{"from_ip": "10.0.0.0/8"}, {"from_ip": "192.168.1.0/24"}])]
    active = [_ipl(3, "L", ranges=[{"from_ip": "10.0.0.0/8"}], side="active")]
    df = diff_objects(draft, active, kind="ip_list",
                      fields=["ip_ranges", "fqdns", "description"])
    assert len(df) == 1
    row = df.iloc[0]
    assert row["change_type"] == "modified"
    assert row["field"] == "ip_ranges"
    assert "192.168.1.0/24" in row["draft_value"]
    assert bool(row["scope_expanded"]) is True


def test_modified_shrink_not_expansion():
    draft = [_ipl(3, "L", ranges=[{"from_ip": "10.0.0.0/8"}])]
    active = [_ipl(3, "L", ranges=[{"from_ip": "10.0.0.0/8"}, {"from_ip": "172.16.0.0/12"}], side="active")]
    df = diff_objects(draft, active, kind="ip_list",
                      fields=["ip_ranges", "fqdns", "description"])
    assert bool(df.iloc[0]["scope_expanded"]) is False


def test_same_content_different_order_no_diff():
    a = [{"from_ip": "10.0.0.0/8"}, {"from_ip": "172.16.0.0/12"}]
    b = [{"from_ip": "172.16.0.0/12"}, {"from_ip": "10.0.0.0/8"}]
    df = diff_objects([_ipl(4, "L", ranges=a)], [_ipl(4, "L", ranges=b, side="active")],
                      kind="ip_list", fields=["ip_ranges", "fqdns", "description"])
    assert df.empty


def test_description_change_not_scope_expanded():
    df = diff_objects([_ipl(5, "L", desc="new")], [_ipl(5, "L", desc="old", side="active")],
                      kind="ip_list", fields=["ip_ranges", "fqdns", "description"])
    assert df.iloc[0]["field"] == "description"
    assert bool(df.iloc[0]["scope_expanded"]) is False


def _svc(oid, name, ports=None, side="draft"):
    return {
        "href": f"/orgs/1/sec_policy/{side}/services/{oid}",
        "name": name,
        "service_ports": ports or [],
        "windows_services": [],
        "description": "",
    }


def test_service_port_summary_and_expansion():
    draft = [_svc(7, "S", ports=[{"port": 443, "proto": 6}, {"port": 1024, "to_port": 2048, "proto": 6}])]
    active = [_svc(7, "S", ports=[{"port": 443, "proto": 6}], side="active")]
    df = diff_objects(draft, active, kind="service",
                      fields=["service_ports", "windows_services", "description"])
    row = df.iloc[0]
    assert row["field"] == "service_ports"
    assert "6/1024-2048" in row["draft_value"]
    assert bool(row["scope_expanded"]) is True


def _lg(oid, name, labels=None, side="draft"):
    return {
        "href": f"/orgs/1/sec_policy/{side}/label_groups/{oid}",
        "name": name,
        "labels": labels or [],
        "sub_groups": [],
        "description": "",
    }


def test_label_group_members_use_names_map():
    names = {"/orgs/1/labels/9": "role-web"}
    draft = [_lg(8, "G", labels=[{"href": "/orgs/1/labels/9"}])]
    active = [_lg(8, "G", side="active")]
    df = diff_objects(draft, active, kind="label_group",
                      fields=["labels", "sub_groups", "description"],
                      names=names)
    assert "role-web" in df.iloc[0]["draft_value"]
    assert bool(df.iloc[0]["scope_expanded"]) is True


def test_empty_inputs_empty_frame_with_columns():
    df = diff_objects([], [], kind="service",
                      fields=["service_ports", "windows_services", "description"])
    assert df.empty
    assert "object_kind" in df.columns and "scope_expanded" in df.columns


def test_object_change_counts():
    draft = [_ipl(1, "A"), _ipl(3, "C", ranges=[{"from_ip": "10.0.0.0/8"}], fqdns=[{"fqdn": "x.example.com"}])]
    active = [_ipl(2, "B", side="active"), _ipl(3, "C", side="active")]
    df = diff_objects(draft, active, kind="ip_list",
                      fields=["ip_ranges", "fqdns", "description"])
    added, removed, modified = object_change_counts(df)
    assert (added, removed, modified) == (1, 1, 1)  # C 改兩欄仍算 1 個 modified 物件


def _active_rs(rules=None, enabled=True):
    return {"href": "/orgs/1/sec_policy/active/rule_sets/1", "name": "RS",
            "enabled": enabled, "rules": rules or [], "scopes": [[]]}


def test_scan_object_refs_counts_allow_rule_references():
    rule = {"enabled": True,
            "providers": [{"ip_list": {"href": "/orgs/1/sec_policy/active/ip_lists/5"}}],
            "consumers": [{"label_group": {"href": "/orgs/1/sec_policy/active/label_groups/8"}}],
            "ingress_services": [{"href": "/orgs/1/sec_policy/active/services/7"},
                                 {"port": 22, "proto": 6}]}
    refs = scan_object_refs([_active_rs(rules=[rule, rule])])
    assert refs == {"ip_list:5": 2, "label_group:8": 2, "service:7": 2}


def test_scan_object_refs_skips_disabled():
    rule = {"enabled": False,
            "providers": [{"ip_list": {"href": "/orgs/1/sec_policy/active/ip_lists/5"}}],
            "consumers": [], "ingress_services": []}
    assert scan_object_refs([_active_rs(rules=[rule])]) == {}
    on_rule = dict(rule, enabled=True)
    assert scan_object_refs([_active_rs(rules=[on_rule], enabled=False)]) == {}
