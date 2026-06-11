# tests/test_mod_drift.py
"""Baseline drift: new / disappeared app-to-app flows vs previous run."""
import pandas as pd

from src.report.analysis.mod_drift import baseline_drift


def _df():
    return pd.DataFrame([
        {"src_app": "Web", "dst_app": "DB", "port": 3306, "proto": "TCP", "num_connections": 40},
        {"src_app": "Web", "dst_app": "Cache", "port": 6379, "proto": "TCP", "num_connections": 7},
    ])


def test_no_previous_returns_unavailable():
    res = baseline_drift(_df(), prev_signatures=None, prev_generated_at=None)
    assert res["available"] is False


def test_new_and_disappeared_pairs_detected():
    prev = {"Web|DB|3306|TCP", "Batch|DB|3306|TCP"}
    res = baseline_drift(_df(), prev_signatures=prev, prev_generated_at="2026-06-01T00:00:00")
    assert res["available"] is True
    assert res["new_count"] == 1                       # Web→Cache:6379 是新的
    assert res["disappeared_count"] == 1               # Batch→DB 不見了
    new_rows = res["new_pairs"]
    assert list(new_rows.iloc[0][["Src App", "Dst App"]]) == ["Web", "Cache"]
    assert int(new_rows.iloc[0]["Connections"]) == 7
    gone = res["disappeared_pairs"]
    assert list(gone.iloc[0][["Src App", "Dst App"]]) == ["Batch", "DB"]
    assert res["prev_generated_at"] == "2026-06-01T00:00:00"


def test_identical_periods_produce_zero_drift():
    prev = {"Web|DB|3306|TCP", "Web|Cache|6379|TCP"}
    res = baseline_drift(_df(), prev_signatures=prev, prev_generated_at="x")
    assert res["new_count"] == 0 and res["disappeared_count"] == 0
