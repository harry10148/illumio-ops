# tests/test_mod_labels.py
"""Label hygiene: unlabeled workloads, flow label coverage, conflicting labels."""
import pandas as pd

from src.report.analysis.mod_labels import label_hygiene


def _workloads():
    def wl(hostname, labels):
        return {"hostname": hostname,
                "labels": [{"key": k, "value": v} for k, v in labels.items()]}
    return [
        wl("web01", {"app": "Web", "env": "Prod", "loc": "DC1", "role": "Web"}),
        wl("db01", {"app": "DB", "env": "Prod"}),          # 缺 loc, role
        wl("tmp01", {}),                                    # 全缺
    ]


def _flows():
    return pd.DataFrame([
        {"src_ip": "10.0.0.1", "src_app": "Web", "src_env": "Prod", "src_loc": "DC1", "src_role": "Web",
         "dst_ip": "10.0.0.2", "dst_app": "", "dst_env": "", "dst_loc": "", "dst_role": "",
         "src_managed": True, "dst_managed": True, "port": 443, "proto": "TCP", "num_connections": 5},
        {"src_ip": "10.0.0.1", "src_app": "Web2", "src_env": "Prod", "src_loc": "DC1", "src_role": "Web",
         "dst_ip": "8.8.8.8", "dst_app": "", "dst_env": "", "dst_loc": "", "dst_role": "",
         "src_managed": True, "dst_managed": False, "port": 53, "proto": "UDP", "num_connections": 2},
    ])


def test_workload_label_coverage():
    res = label_hygiene(_flows(), _workloads())
    assert res["workload_data_available"] is True
    assert res["total_workloads"] == 3
    assert res["fully_labeled_pct"] == round(1 / 3 * 100, 1)
    unl = res["unlabeled_workloads"]
    assert set(unl["Hostname"]) == {"db01", "tmp01"}
    assert "loc, role" in list(unl["Missing Keys"])


def test_flow_label_gap_counts_managed_only():
    res = label_hygiene(_flows(), _workloads())
    # dst 10.0.0.2 是 managed 且無標籤 → 算 gap；8.8.8.8 unmanaged 不算
    assert res["managed_unlabeled_flow_count"] == 1


def test_label_conflicts_detected():
    # 10.0.0.1 同 IP 出現兩組不同標籤（Web vs Web2）→ 衝突
    res = label_hygiene(_flows(), _workloads())
    conflicts = res["label_conflicts"]
    assert len(conflicts) == 1
    assert conflicts.iloc[0]["IP"] == "10.0.0.1"


def test_no_workloads_still_reports_flow_side():
    res = label_hygiene(_flows(), None)
    assert res["workload_data_available"] is False
    assert res["managed_unlabeled_flow_count"] == 1
