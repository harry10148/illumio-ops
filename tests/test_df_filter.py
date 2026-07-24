"""Post-fetch DataFrame filter for cache-served filtered reports."""
from __future__ import annotations

import pandas as pd
from src.report.df_filter import apply_df_traffic_filters


def _df():
    return pd.DataFrame([
        {"src_app": "Web", "dst_app": "DB", "src_env": "Prod", "dst_env": "Prod",
         "src_role": "fe", "dst_role": "db", "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2",
         "port": 443, "proto": "TCP", "src_extra_labels": {"team": "x"}, "dst_extra_labels": {}},
        {"src_app": "DB", "dst_app": "Web", "src_env": "Dev", "dst_env": "Prod",
         "src_role": "db", "dst_role": "fe", "src_ip": "10.0.1.5", "dst_ip": "10.0.0.9",
         "port": 22, "proto": "TCP", "src_extra_labels": {"team": "y"}, "dst_extra_labels": {}},
        {"src_app": "ERP", "dst_app": "DB", "src_env": "Prod", "dst_env": "Prod",
         "src_role": "app", "dst_role": "db", "src_ip": "192.168.1.1", "dst_ip": "10.0.0.2",
         "port": 443, "proto": "UDP", "src_extra_labels": {}, "dst_extra_labels": {}},
    ])


def test_no_filters_unchanged():
    df = _df()
    assert len(apply_df_traffic_filters(df, None)) == 3
    assert len(apply_df_traffic_filters(df, {})) == 3


def test_src_label_include_and():
    out = apply_df_traffic_filters(_df(), {"src_labels": ["app=Web"]})
    assert out["src_app"].tolist() == ["Web"]


def test_src_and_dst_labels_default_and():
    # default AND: src app=ERP AND dst app=DB → row 3 only
    out = apply_df_traffic_filters(_df(), {"src_labels": ["app=ERP"], "dst_labels": ["app=DB"]})
    assert len(out) == 1 and out["src_app"].tolist() == ["ERP"]


def test_query_operator_or():
    # OR: src app=DB OR dst app=DB → rows 1,2,3 all have DB on one side
    out = apply_df_traffic_filters(
        _df(), {"src_labels": ["app=DB"], "dst_labels": ["app=DB"], "query_operator": "or"})
    assert len(out) == 3


def test_exclusion_label():
    out = apply_df_traffic_filters(_df(), {"ex_src_labels": ["env=Dev"]})
    assert set(out["src_app"]) == {"Web", "ERP"}  # Dev row excluded


def test_custom_label_via_extra():
    out = apply_df_traffic_filters(_df(), {"src_labels": ["team=x"]})
    assert out["src_app"].tolist() == ["Web"]


def test_port_and_proto():
    out = apply_df_traffic_filters(_df(), {"port": "443", "proto": "TCP"})
    assert out["src_app"].tolist() == ["Web"]  # 443+TCP only row1 (row3 is 443 UDP)


def test_proto_numeric_alias():
    out = apply_df_traffic_filters(_df(), {"proto": "17"})  # 17 = UDP
    assert out["src_app"].tolist() == ["ERP"]


def test_ip_exact_and_cidr():
    assert apply_df_traffic_filters(_df(), {"src_ip": "10.0.1.5"})["src_app"].tolist() == ["DB"]
    out = apply_df_traffic_filters(_df(), {"src_ip": "10.0.0.0/16"})
    assert set(out["src_app"]) == {"Web", "DB"}  # 10.0.x.x, not 192.168


def _df_two_apps():
    return pd.DataFrame([
        {"src_app": "erp", "src_env": "prod", "dst_app": "", "dst_env": "",
         "src_extra_labels": {}, "dst_extra_labels": {},
         "src_ip": "10.0.0.1", "dst_ip": "10.0.0.9", "port": 443, "proto": "TCP"},
        {"src_app": "web", "src_env": "prod", "dst_app": "", "dst_env": "",
         "src_extra_labels": {}, "dst_extra_labels": {},
         "src_ip": "10.0.0.2", "dst_ip": "10.0.0.9", "port": 443, "proto": "TCP"},
        {"src_app": "hr", "src_env": "dr", "dst_app": "", "dst_env": "",
         "src_extra_labels": {}, "dst_extra_labels": {},
         "src_ip": "10.0.0.3", "dst_ip": "10.0.0.9", "port": 443, "proto": "TCP"},
    ])


def test_same_key_labels_or_in_df_path():
    out = apply_df_traffic_filters(_df_two_apps(), {"src_labels": ["app=erp", "app=web"]})
    assert sorted(out["src_ip"]) == ["10.0.0.1", "10.0.0.2"]


def test_cross_key_labels_still_and_in_df_path():
    out = apply_df_traffic_filters(_df_two_apps(), {"src_labels": ["app=erp", "env=prod"]})
    assert list(out["src_ip"]) == ["10.0.0.1"]


def test_same_key_or_with_custom_dimension():
    df = _df_two_apps()
    df.at[0, "src_extra_labels"] = {"Net": "Server-A"}
    df.at[2, "src_extra_labels"] = {"Net": "Server-B"}
    out = apply_df_traffic_filters(df, {"src_labels": ["Net=Server-A", "Net=Server-B"]})
    assert sorted(out["src_ip"]) == ["10.0.0.1", "10.0.0.3"]


def test_unparseable_spec_forces_and_fail():
    out = apply_df_traffic_filters(_df_two_apps(), {"src_labels": ["app=erp", "garbage"]})
    assert out.empty


def test_colon_separator_equivalent_to_equals():
    colon_out = apply_df_traffic_filters(_df_two_apps(), {"src_labels": ["app:erp"]})
    equals_out = apply_df_traffic_filters(_df_two_apps(), {"src_labels": ["app=erp"]})
    assert sorted(colon_out["src_ip"]) == sorted(equals_out["src_ip"])
    assert list(colon_out["src_ip"]) == ["10.0.0.1"]


def test_object_cidrs_include_src():
    out = apply_df_traffic_filters(_df_two_apps(), {"_src_object_cidrs": ["10.0.0.0/31"]})
    assert sorted(out["src_ip"]) == ["10.0.0.1"]


def test_object_cidrs_exclude_dst():
    out = apply_df_traffic_filters(_df_two_apps(), {"_ex_dst_object_cidrs": ["10.0.0.9"]})
    assert out.empty


def test_object_cidrs_any_side():
    out = apply_df_traffic_filters(_df_two_apps(), {"_any_object_cidrs": ["10.0.0.2"]})
    assert list(out["src_ip"]) == ["10.0.0.2"]


def test_ex_any_object_cidrs_excludes_either_side():
    df = _df_two_apps()  # src_ip 10.0.0.1/2/3, dst_ip 10.0.0.9
    out = apply_df_traffic_filters(df, {"_ex_any_object_cidrs": ["10.0.0.1"]})
    # src 命中 10.0.0.1 的列被剔除
    assert "10.0.0.1" not in out["src_ip"].tolist()
    # dst 側命中也剔除
    out2 = apply_df_traffic_filters(df, {"_ex_any_object_cidrs": ["10.0.0.9"]})
    assert out2.empty  # 全部列 dst 都是 10.0.0.9


def test_src_ip_in_list_matches_any():
    out = apply_df_traffic_filters(_df_two_apps(), {"src_ip_in": ["10.0.0.1", "10.0.0.3"]})
    assert sorted(out["src_ip"]) == ["10.0.0.1", "10.0.0.3"]


def test_src_ip_in_cidr():
    out = apply_df_traffic_filters(_df_two_apps(), {"src_ip_in": ["10.0.0.0/31"]})
    assert sorted(out["src_ip"]) == ["10.0.0.1"]


def test_dst_ip_in_matches():
    # dst_ip 全部列都是 10.0.0.9，dst_ip_in 命中應保留全部列
    out = apply_df_traffic_filters(_df_two_apps(), {"dst_ip_in": ["10.0.0.9"]})
    assert len(out) == 3


def test_ex_src_ip_in_excludes():
    out = apply_df_traffic_filters(_df_two_apps(), {"ex_src_ip_in": ["10.0.0.1", "10.0.0.3"]})
    assert sorted(out["src_ip"]) == ["10.0.0.2"]


def test_any_label_either_side():
    # src_app=erp/web/hr，dst_app 皆空字串 → any_label=app=erp 只有 row0（src 命中）
    out = apply_df_traffic_filters(_df_two_apps(), {"any_label": "app=erp"})
    assert "erp" in out["src_app"].tolist()
    assert set(out["src_app"]) == {"erp"}


def test_ex_any_label_excludes_either_side():
    out = apply_df_traffic_filters(_df_two_apps(), {"ex_any_label": "app=erp"})
    assert "erp" not in out["src_app"].tolist()
    assert set(out["src_app"]) == {"web", "hr"}


def test_ex_src_ip_scalar_excludes():
    # 舊前端送 scalar：既有行為不可回歸
    out = apply_df_traffic_filters(_df_two_apps(), {"ex_src_ip": "10.0.0.1"})
    assert sorted(out["src_ip"]) == ["10.0.0.2", "10.0.0.3"]


def test_ex_src_ip_list_excludes():
    # FilterBar 送 list（見 filter-bar.js 排除 IP pill 序列化）：list 須逐值 AND-exclude，
    # 不可被 str(list) 當成單一垃圾字串比對而靜默失效
    out = apply_df_traffic_filters(_df_two_apps(), {"ex_src_ip": ["10.0.0.1", "10.0.0.3"]})
    assert sorted(out["src_ip"]) == ["10.0.0.2"]


def test_ex_dst_ip_list_excludes():
    df = _df_two_apps()
    out = apply_df_traffic_filters(df, {"ex_dst_ip": ["10.0.0.9"]})
    assert out.empty  # 全部列 dst_ip 皆為 10.0.0.9


def test_any_ip_matches_src_side():
    # src_ip 10.0.0.1/2/3，dst_ip 皆為 10.0.0.9 → any_ip=10.0.0.1 只命中 row0 的 src 側
    out = apply_df_traffic_filters(_df_two_apps(), {"any_ip": "10.0.0.1"})
    assert sorted(out["src_ip"]) == ["10.0.0.1"]


def test_any_ip_matches_dst_side():
    # any_ip=10.0.0.9 命中所有列的 dst 側
    out = apply_df_traffic_filters(_df_two_apps(), {"any_ip": "10.0.0.9"})
    assert len(out) == 3


def test_any_ip_cidr_form():
    # CIDR 涵蓋 10.0.0.0-10.0.0.3，透過 src 側命中全部三列
    out = apply_df_traffic_filters(_df_two_apps(), {"any_ip": "10.0.0.0/30"})
    assert len(out) == 3


def test_ex_any_ip_excludes_either_side():
    # ex_any_ip=10.0.0.1 命中 row0 的 src 側 → 該列被剔除，其餘保留
    out = apply_df_traffic_filters(_df_two_apps(), {"ex_any_ip": "10.0.0.1"})
    assert sorted(out["src_ip"]) == ["10.0.0.2", "10.0.0.3"]


def _ports_df():
    return pd.DataFrame([
        {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 80, "proto": "TCP"},
        {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 443, "proto": "TCP"},
        {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 1500, "proto": "UDP"},
    ])


def test_ports_tokens_include_or():
    out = apply_df_traffic_filters(_ports_df(), {"ports": ["80", "1000-2000/udp"]})
    assert sorted(out["port"].tolist()) == [80, 1500]


def test_ex_ports_exclude():
    out = apply_df_traffic_filters(_ports_df(), {"ex_ports": ["443/tcp"]})
    assert 443 not in out["port"].tolist()


def test_svc_port_entries_internal_keys():
    out = apply_df_traffic_filters(_ports_df(), {"_svc_port_entries": [{"port": 443, "proto": 6}]})
    assert out["port"].tolist() == [443]
    out2 = apply_df_traffic_filters(_ports_df(), {"_ex_svc_port_entries": [{"port": 443, "proto": 6}]})
    assert 443 not in out2["port"].tolist()


def test_svc_port_entries_wildcard_matches_all():
    """All Services 展開後的 {"wildcard": True} 條目在 fallback df 比對層
    須全命中，不可因無 port/proto key 被當成「空條目」而全不命中。"""
    out = apply_df_traffic_filters(_ports_df(), {"_svc_port_entries": [{"wildcard": True}]})
    assert sorted(out["port"].tolist()) == [80, 443, 1500]


def test_ports_include_all_invalid_fail_closed():
    out = apply_df_traffic_filters(_ports_df(), {"ports": ["nonsense"]})
    assert out.empty


def test_ports_scalar_string_matches_exact():
    # Scalar string "80" should match port 80 only, not iterate as "8", "0"
    out = apply_df_traffic_filters(_ports_df(), {"ports": "80"})
    assert out["port"].tolist() == [80]


def test_ex_ports_scalar_string_excludes():
    # Scalar string "443/tcp" should exclude port 443/TCP, not fail silently
    out = apply_df_traffic_filters(_ports_df(), {"ex_ports": "443/tcp"})
    assert 443 not in out["port"].tolist()
    assert sorted(out["port"].tolist()) == [80, 1500]


def test_illegal_exclude_cidr_does_not_empty_table():
    """L6（2026-07-24 審查）：排除欄帶非法 CIDR/range 不得清空整表——
    fail-open 在 exclude 側（mask &= ~Series(True)）會反轉成清空所有列。"""
    out = apply_df_traffic_filters(_df(), {"ex_src_ip": "10.0.0.0/99"})
    assert len(out) == 3  # 非法排除不排任何列（不是清空）
    out2 = apply_df_traffic_filters(_df(), {"ex_src_ip": "not-an-ip-range-x"})
    assert len(out2) == 3


def test_valid_exclude_cidr_still_excludes():
    out = apply_df_traffic_filters(_df(), {"ex_src_ip": "10.0.0.0/24"})
    # 10.0.0.1 被排除，剩 10.0.1.5 與 192.168.1.1
    assert len(out) == 2
    assert "10.0.0.1" not in set(out["src_ip"])
