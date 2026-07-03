"""mod02 稽核清單（allowed 且來源非受管）——自 mod10 遷入的回歸測試。"""
import pandas as pd
from src.report.analysis.mod02_policy_decisions import policy_decision_analysis


def _df():
    return pd.DataFrame([
        # allowed + 非受管來源 → 應入 audit_flags
        {"src_ip": "10.0.0.9", "dst_ip": "10.0.1.5", "port": 445, "proto": "TCP",
         "src_app": "unknown", "dst_app": "fileserver", "policy_decision": "allowed",
         "src_managed": False, "dst_managed": True, "num_connections": 7},
        # allowed + 受管來源 → 不入
        {"src_ip": "10.0.0.2", "dst_ip": "10.0.1.5", "port": 443, "proto": "TCP",
         "src_app": "web", "dst_app": "fileserver", "policy_decision": "allowed",
         "src_managed": True, "dst_managed": True, "num_connections": 3},
        # blocked + 非受管來源 → 不入（僅看 allowed）
        {"src_ip": "10.0.0.9", "dst_ip": "10.0.1.7", "port": 22, "proto": "TCP",
         "src_app": "unknown", "dst_app": "db", "policy_decision": "blocked",
         "src_managed": False, "dst_managed": True, "num_connections": 2},
    ])


def test_mod02_returns_audit_flags():
    out = policy_decision_analysis(_df())
    assert "audit_flags" in out
    assert "audit_flag_count" in out
    flags = out["audit_flags"]
    assert list(flags["Unmanaged Source"]) == ["10.0.0.9"]
    assert list(flags["Destination"]) == ["10.0.1.5"]
    assert int(flags["Port"].iloc[0]) == 445
    assert int(flags["Connections"].iloc[0]) == 7
    assert out["audit_flag_count"] == 1


def test_mod02_audit_flags_empty_when_all_managed():
    df = _df()
    df["src_managed"] = True
    out = policy_decision_analysis(df)
    assert out["audit_flag_count"] == 0
    assert out["audit_flags"].empty
