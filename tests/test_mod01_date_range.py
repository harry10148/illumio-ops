"""mod01 date_range 容錯（spec C4）：字串時間戳可解析、全缺時單一 N/A。"""
import pandas as pd
from src.report.analysis.mod01_traffic_overview import traffic_overview


def _base_row(**kw):
    row = {"src_ip": "10.0.0.1", "dst_ip": "10.1.0.1", "port": 443, "proto": "TCP",
           "src_app": "web", "dst_app": "api", "policy_decision": "allowed",
           "src_managed": True, "dst_managed": True,
           "num_connections": 3, "bytes_total": 100,
           "first_detected": pd.NaT, "last_detected": pd.NaT}
    row.update(kw)
    return row


def test_string_timestamps_parse():
    df = pd.DataFrame([
        _base_row(first_detected="2026-01-01T00:00:00Z", last_detected="2026-01-02T00:00:00Z"),
        _base_row(first_detected="2026-01-03T00:00:00Z", last_detected="2026-01-04T00:00:00Z"),
    ])
    out = traffic_overview(df)
    assert out["date_range"] == "2026-01-01 → 2026-01-04"


def test_all_missing_yields_single_na():
    df = pd.DataFrame([_base_row(), _base_row()])
    out = traffic_overview(df)
    assert out["date_range"] == "N/A"
    assert "N/A → N/A" not in out["date_range"]


def test_datetime_path_unchanged():
    df = pd.DataFrame([
        _base_row(first_detected=pd.Timestamp("2026-02-01"), last_detected=pd.Timestamp("2026-02-03")),
    ])
    out = traffic_overview(df)
    assert out["date_range"] == "2026-02-01 → 2026-02-03"
