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
