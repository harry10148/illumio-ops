"""Per-app inbound/outbound connection baseline tables."""
import pandas as pd

from src.report.analysis.mod_app_baseline import app_baseline, filter_app_flows


def test_policy_impact_from_mod02():
    from src.report.analysis.mod_app_baseline import policy_impact
    mod02 = {
        "allowed": {"count": 8},
        "potentially_blocked": {"count": 3},
        "blocked": {"count": 1},
        "unknown": {"count": 0},
    }
    res = policy_impact(mod02)
    assert res["allowed"] == 8 and res["potentially_blocked"] == 3
    assert res["blocked"] == 1 and res["unknown"] == 0
    assert res["total"] == 12
    assert res["coverage_pct"] == round(8 / 12 * 100, 1)
    assert res["would_be_blocked"] == 3
    assert res["available"] is True


def test_policy_impact_handles_error_or_empty():
    from src.report.analysis.mod_app_baseline import policy_impact
    assert policy_impact({"error": "No data"})["available"] is False
    assert policy_impact({})["available"] is False


def test_enforcement_summary_filters_by_app():
    from src.report.analysis.mod_app_baseline import enforcement_summary
    wls = [
        {"hostname": "web1", "enforcement_mode": "full",
         "labels": [{"key": "app", "value": "DB"}, {"key": "env", "value": "Prod"}]},
        {"hostname": "web2", "enforcement_mode": "visibility_only",
         "labels": [{"key": "app", "value": "DB"}, {"key": "env", "value": "Prod"}]},
        {"hostname": "other", "enforcement_mode": "full",
         "labels": [{"key": "app", "value": "Web"}]},
    ]
    res = enforcement_summary(wls, app="DB")
    assert res["available"] is True
    assert res["total"] == 2
    assert res["by_mode"] == {"full": 1, "visibility_only": 1}
    assert res["enforced"] == 1
    assert list(res["table"]["Workload"]) == ["web1", "web2"]


def test_enforcement_summary_env_refines_and_unavailable():
    from src.report.analysis.mod_app_baseline import enforcement_summary
    wls = [{"hostname": "web1", "enforcement_mode": "full",
            "labels": [{"key": "app", "value": "DB"}, {"key": "env", "value": "Prod"}]}]
    assert enforcement_summary(wls, app="DB", env="Dev")["total"] == 0
    assert enforcement_summary(None, app="DB")["available"] is False
    assert enforcement_summary([], app="DB")["available"] is False


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
