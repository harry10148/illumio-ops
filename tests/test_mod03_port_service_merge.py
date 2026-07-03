"""mod03 port gap 與 service gap 合併表。"""
import pandas as pd
from src.report.analysis.mod03_uncovered_flows import uncovered_flows


def _df():
    rows = []
    # port 445：兩個目的 app 的未覆蓋流量 + 一筆 allowed
    rows.append({"src_ip": "10.0.0.1", "dst_ip": "10.1.0.1", "port": 445, "proto": "TCP",
                 "src_app": "web", "dst_app": "fileserver", "policy_decision": "blocked",
                 "src_managed": True, "dst_managed": True, "num_connections": 30})
    rows.append({"src_ip": "10.0.0.2", "dst_ip": "10.1.0.2", "port": 445, "proto": "TCP",
                 "src_app": "web", "dst_app": "backup", "policy_decision": "potentially_blocked",
                 "src_managed": True, "dst_managed": True, "num_connections": 10})
    rows.append({"src_ip": "10.0.0.3", "dst_ip": "10.1.0.1", "port": 445, "proto": "TCP",
                 "src_app": "app", "dst_app": "fileserver", "policy_decision": "allowed",
                 "src_managed": True, "dst_managed": True, "num_connections": 60})
    return pd.DataFrame(rows)


def test_merged_table_present_with_top_apps():
    out = uncovered_flows(_df())
    merged = out["uncovered_port_services"]
    assert not merged.empty
    row = merged.iloc[0]
    assert int(row["Port"]) == 445
    assert int(row["Uncovered Flows"]) == 40
    # 依未覆蓋連線數排序：fileserver(30) 在 backup(10) 前
    assert row["Top Destination Apps"] == "fileserver, backup"
    # 原兩表照舊保留（供 XLSX 統一案使用）
    assert "uncovered_ports" in out and "uncovered_services" in out


def test_merged_table_empty_when_no_uncovered():
    df = _df()
    df["policy_decision"] = "allowed"
    out = uncovered_flows(df)
    assert out["uncovered_port_services"].empty
