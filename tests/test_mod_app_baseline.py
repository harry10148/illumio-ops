"""Per-app inbound/outbound connection baseline tables."""
import pandas as pd

from src.report.analysis.mod_app_baseline import app_baseline, filter_app_flows


def _df():
    return pd.DataFrame([
        # inbound to DB
        {"src_app": "Web", "src_env": "Prod", "dst_app": "DB", "dst_env": "Prod",
         "port": 3306, "proto": "TCP", "policy_decision": "allowed", "num_connections": 9,
         "src_ip": "10.0.0.1", "dst_ip": "10.0.0.5"},
        # outbound from DB
        {"src_app": "DB", "src_env": "Prod", "dst_app": "Backup", "dst_env": "Prod",
         "port": 443, "proto": "TCP", "policy_decision": "potentially_blocked", "num_connections": 2,
         "src_ip": "10.0.0.5", "dst_ip": "10.0.0.9"},
        # unrelated
        {"src_app": "Web", "src_env": "Prod", "dst_app": "Cache", "dst_env": "Prod",
         "port": 6379, "proto": "TCP", "policy_decision": "allowed", "num_connections": 7,
         "src_ip": "10.0.0.1", "dst_ip": "10.0.0.6"},
    ])


def test_filter_app_flows_keeps_both_directions():
    sub = filter_app_flows(_df(), app="DB")
    assert len(sub) == 2
    assert set(sub["dst_app"]) | set(sub["src_app"]) >= {"DB"}


def test_filter_with_env():
    assert len(filter_app_flows(_df(), app="DB", env="Prod")) == 2
    assert len(filter_app_flows(_df(), app="DB", env="Dev")) == 0


def test_baseline_tables():
    res = app_baseline(_df(), app="DB")
    inb = res["inbound"]
    assert list(inb.iloc[0][["Src App", "Port", "Proto"]]) == ["Web", 3306, "TCP"]
    assert inb.iloc[0]["Decision"] == "allowed"
    out = res["outbound"]
    assert list(out.iloc[0][["Dst App", "Port"]]) == ["Backup", 443]
    assert res["inbound_count"] == 1 and res["outbound_count"] == 1
