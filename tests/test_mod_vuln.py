"""V-E lite: vulnerable IPs that are reachable (non-blocked inbound) ranked by exposure."""
import pandas as pd

from src.report.analysis.mod_vuln import vuln_exposure


def _flows():
    return pd.DataFrame([
        {"src_ip": "10.0.0.1", "src_app": "Web", "dst_ip": "10.0.0.5", "dst_app": "DB",
         "port": 3306, "proto": "TCP", "policy_decision": "allowed", "num_connections": 9},
        {"src_ip": "10.0.0.2", "src_app": "Batch", "dst_ip": "10.0.0.5", "dst_app": "DB",
         "port": 3306, "proto": "TCP", "policy_decision": "potentially_blocked", "num_connections": 3},
        {"src_ip": "10.0.0.3", "src_app": "X", "dst_ip": "10.0.0.7", "dst_app": "Y",
         "port": 22, "proto": "TCP", "policy_decision": "blocked", "num_connections": 5},
    ])


def _vulns():
    return pd.DataFrame([
        {"ip": "10.0.0.5", "cve_id": "CVE-2024-1", "severity": "Critical", "cvss": 9.8},
        {"ip": "10.0.0.7", "cve_id": "CVE-2024-2", "severity": "High", "cvss": 8.0},   # 只被 blocked 流量觸及
        {"ip": "10.9.9.9", "cve_id": "CVE-2024-3", "severity": "Low", "cvss": 2.0},    # 無流量
    ])


def test_only_reachable_vulns_exposed():
    res = vuln_exposure(_flows(), _vulns())
    assert res["available"] is True
    exposed = res["exposed"]
    assert list(exposed["IP"]) == ["10.0.0.5"]          # 10.0.0.7 blocked-only、10.9.9.9 無流量
    row = exposed.iloc[0]
    assert row["CVE"] == "CVE-2024-1"
    assert row["Inbound Sources"] == 2                   # 兩個不同 src_ip（allowed+pb 都算可達）
    assert row["Dst App"] == "DB"


def test_summary_counts():
    res = vuln_exposure(_flows(), _vulns())
    assert res["total_vulns"] == 3
    assert res["exposed_count"] == 1
    assert res["unreached_count"] == 2


def test_empty_vulns_unavailable():
    assert vuln_exposure(_flows(), None)["available"] is False
    assert vuln_exposure(_flows(), pd.DataFrame())["available"] is False


def test_no_flows_nothing_exposed():
    # df=None and all-blocked traffic both leave the reach table empty → nothing exposed.
    for flows in (None, _flows()[_flows()["policy_decision"] == "blocked"]):
        res = vuln_exposure(flows, _vulns())
        assert res["available"] is True
        assert res["exposed_count"] == 0
        assert res["unreached_count"] == 3
        assert list(res["exposed"]["IP"]) == []


def test_chart_labels_localized_zh():
    res = vuln_exposure(_flows(), _vulns(), lang="zh_TW")
    spec = res["chart_spec"]
    assert spec["data"]["labels"] == ["可達", "不可達"]
    assert spec["title"] == "可達 vs 不可達弱點"
