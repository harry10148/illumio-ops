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


def test_empty_consumers_resolves_to_any():
    # An empty consumers list means "any source" — rows appear with src_ip=="ANY"
    # and src_kind=="any". Contrast: a NON-empty list with an unknown actor
    # (see test_missing_label_yields_no_rows_no_error) drops the rule entirely.
    rs = _ruleset([{
        "href": "/sec_rules/10",
        "consumers": [],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"port": 443, "proto": 6}],
    }])
    rows = resolve_ruleset(rs, **_lookups())
    assert len(rows) == 1
    assert rows[0]["src_ip"] == "ANY"
    assert rows[0]["src_kind"] == "any"
    assert rows[0]["dst_ip"] == "10.0.2.7"


def test_scope_narrows_providers():
    # Illumio scope 語意＝交集：provider(web) 的 IP 與 scope(db) 的 IP 不相交
    # → providers 解析為空 → 無列。（2026-07-13 修正前的舊實作是「provider label
    # 不在 scope label 清單就跳過」——語意寫反，造成所有帶 scope 的 ruleset 歸零。）
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


def test_disabled_ruleset_yields_no_rows():
    rs = _ruleset([{
        "href": "/sec_rules/d1",
        "consumers": [{"label": {"href": "/labels/web"}}],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"port": 443, "proto": 6}],
    }])
    rs["enabled"] = False
    assert resolve_ruleset(rs, **_lookups()) == []


def test_disabled_rule_is_skipped():
    rs = _ruleset([
        {"href": "/sec_rules/on", "enabled": True,
         "consumers": [{"label": {"href": "/labels/web"}}],
         "providers": [{"label": {"href": "/labels/db"}}],
         "ingress_services": [{"port": 443, "proto": 6}]},
        {"href": "/sec_rules/off", "enabled": False,
         "consumers": [{"label": {"href": "/labels/web"}}],
         "providers": [{"label": {"href": "/labels/db"}}],
         "ingress_services": [{"port": 22, "proto": 6}]},
    ])
    rows = resolve_ruleset(rs, **_lookups())
    assert {r["port"] for r in rows} == {443}


def test_service_name_uses_friendly_name():
    rs = _ruleset([{
        "href": "/sec_rules/6",
        "consumers": [{"workload": {"href": "/wl/jump"}}],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"href": "/services/https"}],
    }])
    rows = resolve_ruleset(
        rs, **_lookups(),
        service_to_ports={"/services/https": [{"port": 443, "proto": 6}]},
        service_to_names={"/services/https": "HTTPS"},
    )
    assert rows[0]["service_name"] == "HTTPS"
    assert rows[0]["port"] == 443


# ── Scope 交集語意與 deny rules（2026-07-13：報表恆空 bug 修復）────────────────
# 測資佈局：/labels/prod 的 IP 與 /labels/web 部分重疊（10.0.1.5），與 /labels/db
# 完全重疊（10.0.2.7）。
LABEL_TO_IPS_SCOPED = {
    "/labels/web": ["10.0.1.5", "10.0.1.6"],
    "/labels/db": ["10.0.2.7"],
    "/labels/prod": ["10.0.1.5", "10.0.2.7"],
}


def _scoped_lookups():
    lk = _lookups()
    lk["label_to_ips"] = LABEL_TO_IPS_SCOPED
    return lk


def _scoped_rs(rules, scopes, **kw):
    rs = _ruleset(rules, scopes=scopes)
    rs.update(kw)
    return rs


def test_scope_intersects_provider_label_ips():
    """scope(prod) ∩ provider(web) ＝ {10.0.1.5}：role label 幾乎不會是 scope
    label，正確語意是 IP 交集而非 href 比對。"""
    rs = _scoped_rs([{
        "href": "/sec_rules/s1",
        "consumers": [{"ip_list": {"href": "/ip_lists/dc"}}],
        "providers": [{"label": {"href": "/labels/web"}}],
        "ingress_services": [{"port": 443, "proto": 6}],
    }], scopes=[[{"label": {"href": "/labels/prod"}}]])
    rows = resolve_ruleset(rs, **_scoped_lookups())
    assert {r["dst_ip"] for r in rows} == {"10.0.1.5"}


def test_scope_constrains_ams_provider_to_scope_ips():
    """provider 為 All Workloads（ams）時，有 scope 的 ruleset 應展開為
    scope 內全部 workload IP，而非全域 ANY。"""
    rs = _scoped_rs([{
        "href": "/sec_rules/s2",
        "consumers": [{"ip_list": {"href": "/ip_lists/dc"}}],
        "providers": [{"actors": "ams"}],
        "ingress_services": [{"port": 22, "proto": 6}],
    }], scopes=[[{"label": {"href": "/labels/prod"}}]])
    rows = resolve_ruleset(rs, **_scoped_lookups())
    assert {r["dst_ip"] for r in rows} == {"10.0.1.5", "10.0.2.7"}


def test_scope_applies_to_consumers_unless_unscoped():
    """intra-scope ruleset 的 consumers 也受 scope 約束；
    unscoped_consumers=True 時 consumers 恢復全域。"""
    rule = {
        "href": "/sec_rules/s3",
        "consumers": [{"label": {"href": "/labels/web"}}],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"port": 5432, "proto": 6}],
    }
    scopes = [[{"label": {"href": "/labels/prod"}}]]
    rows = resolve_ruleset(_scoped_rs([dict(rule)], scopes), **_scoped_lookups())
    assert {r["src_ip"] for r in rows} == {"10.0.1.5"}
    rows = resolve_ruleset(
        _scoped_rs([dict(rule, unscoped_consumers=True)], scopes), **_scoped_lookups())
    assert {r["src_ip"] for r in rows} == {"10.0.1.5", "10.0.1.6"}


def test_scope_passes_explicit_ip_actors_through():
    """ip_list / ip_address 是明確 IP 來源，不受 scope 過濾。"""
    rs = _scoped_rs([{
        "href": "/sec_rules/s4",
        "consumers": [{"ip_address": {"value": "203.0.113.9"}}],
        "providers": [{"ip_list": {"href": "/ip_lists/dc"}}],
        "ingress_services": [{"port": 80, "proto": 6}],
    }], scopes=[[{"label": {"href": "/labels/prod"}}]])
    rows = resolve_ruleset(rs, **_scoped_lookups())
    assert {r["src_ip"] for r in rows} == {"203.0.113.9"}
    assert {r["dst_ip"] for r in rows} == {"10.9.0.0/16"}


def test_scope_and_within_one_scope_or_across_scopes():
    """同一 scope 內多 entry 取 AND（交集）；多個 scope 取 OR（聯集）。"""
    rs = _scoped_rs([{
        "href": "/sec_rules/s5",
        "consumers": [{"ip_list": {"href": "/ip_lists/dc"}}],
        "providers": [{"actors": "ams"}],
        "ingress_services": [{"port": 443, "proto": 6}],
    }], scopes=[
        [{"label": {"href": "/labels/prod"}}, {"label": {"href": "/labels/web"}}],
        [{"label": {"href": "/labels/db"}}],
    ])
    rows = resolve_ruleset(rs, **_scoped_lookups())
    # scope1: prod ∩ web = {10.0.1.5}; scope2: db = {10.0.2.7}; 聯集
    assert {r["dst_ip"] for r in rows} == {"10.0.1.5", "10.0.2.7"}


def test_deny_rules_expand_with_action_column():
    """deny_rules 也要展開（第三方防火牆實作需要 deny 列）；
    override=True → override_deny。allow 列 action='allow'。"""
    rs = _scoped_rs(
        [{
            "href": "/sec_rules/a1",
            "consumers": [{"ip_list": {"href": "/ip_lists/dc"}}],
            "providers": [{"label": {"href": "/labels/db"}}],
            "ingress_services": [{"port": 5432, "proto": 6}],
        }],
        scopes=[],
    )
    rs["deny_rules"] = [
        {"href": "/deny_rules/d1", "enabled": True, "override": True,
         "consumers": [{"actors": "ams"}],
         "providers": [{"label": {"href": "/labels/web"}}],
         "ingress_services": [{"port": 23, "proto": 6}]},
        {"href": "/deny_rules/d2", "enabled": True,
         "consumers": [{"actors": "ams"}],
         "providers": [{"label": {"href": "/labels/db"}}],
         "ingress_services": [{"port": 21, "proto": 6}]},
    ]
    rows = resolve_ruleset(rs, **_scoped_lookups())
    by_action = {}
    for r in rows:
        by_action.setdefault(r["action"], set()).add(r["port"])
    assert by_action == {"allow": {5432}, "override_deny": {23}, "deny": {21}}


def test_scope_unknown_label_fails_closed():
    """scope label 解析不到任何 IP → scope 集為空 → 受 scope 約束的側歸零、
    規則被丟棄（fail-closed，與未知 actor 一致）。"""
    rs = _scoped_rs([{
        "href": "/sec_rules/s6",
        "consumers": [{"ip_list": {"href": "/ip_lists/dc"}}],
        "providers": [{"actors": "ams"}],
        "ingress_services": [{"port": 443, "proto": 6}],
    }], scopes=[[{"label": {"href": "/labels/ghost"}}]])
    assert resolve_ruleset(rs, **_scoped_lookups()) == []


def test_actor_level_exclusion_subtracts_ips():
    """真 PCE 形狀（2026-07-13）：consumers/providers 的 entry 可帶
    exclusion: true（如「PrivateIP ip_list 排除 Jumpdesk label」）。
    被排除 actor 的 IP 必須從同側 include 集合中扣除，不得聯集進來。"""
    rs = _scoped_rs([{
        "href": "/sec_rules/x1",
        "consumers": [
            {"label": {"href": "/labels/prod"}, "exclusion": False},
            {"label": {"href": "/labels/db"}, "exclusion": True},
        ],
        "providers": [{"ip_list": {"href": "/ip_lists/dc"}}],
        "ingress_services": [{"port": 443, "proto": 6}],
    }], scopes=[])
    rows = resolve_ruleset(rs, **_scoped_lookups())
    # prod={10.0.1.5,10.0.2.7} − db={10.0.2.7} = {10.0.1.5}
    assert {r["src_ip"] for r in rows} == {"10.0.1.5"}


def test_ams_with_exclusion_expands_to_workload_universe():
    """無 scope 的 ams + exclusion：ANY 無法表達「全部除了 X」，
    改以 workload_to_ips 全集展開後扣除（fail-closed，寧窄勿寬）。"""
    lk = _scoped_lookups()
    lk["workload_to_ips"] = {"/wl/a": ["10.0.1.5"], "/wl/b": ["10.0.2.7"],
                             "/wl/c": ["10.0.3.9"]}
    rs = _scoped_rs([{
        "href": "/sec_rules/x2",
        "consumers": [{"ip_list": {"href": "/ip_lists/dc"}}],
        "providers": [
            {"actors": "ams"},
            {"label": {"href": "/labels/db"}, "exclusion": True},
        ],
        "ingress_services": [{"port": 22, "proto": 6}],
    }], scopes=[])
    rows = resolve_ruleset(rs, **lk)
    assert {r["dst_ip"] for r in rows} == {"10.0.1.5", "10.0.3.9"}


def test_scoped_ams_with_exclusion():
    """有 scope 的 ams + exclusion：scope 集扣除被排除 label 的 IP。"""
    rs = _scoped_rs([{
        "href": "/sec_rules/x3",
        "consumers": [{"ip_list": {"href": "/ip_lists/dc"}}],
        "providers": [
            {"actors": "ams"},
            {"label": {"href": "/labels/web"}, "exclusion": True},
        ],
        "ingress_services": [{"port": 443, "proto": 6}],
    }], scopes=[[{"label": {"href": "/labels/prod"}}]])
    rows = resolve_ruleset(rs, **_scoped_lookups())
    # scope prod={10.0.1.5,10.0.2.7} − web={10.0.1.5,10.0.1.6} = {10.0.2.7}
    assert {r["dst_ip"] for r in rows} == {"10.0.2.7"}
