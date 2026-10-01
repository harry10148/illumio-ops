"""抽樣上限的保留順序，以及趨勢比較基準。"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from src.report.analysis.mod_change_impact import basis_mismatch, compare
from src.report.report_generator import ReportGenerator, comparison_basis
from src.report.trend_store import snapshot_mismatch


def test_cap_keeps_busiest_and_newest_not_oldest():
    df = pd.DataFrame({
        "last_detected": [f"2026-09-{d:02d}T00:00:00Z" for d in range(24, 32 - 1)],
        "num_connections": [1, 1, 1, 1, 1, 50, 1],
    })
    out = ReportGenerator._cap_records(df, 3)
    assert out["num_connections"].tolist()[0] == 50
    assert sorted(out["last_detected"].tolist())[-1] == "2026-09-30T00:00:00Z"
    assert "2026-09-24T00:00:00Z" not in out["last_detected"].tolist()


def _result(filters=None, pds=None, truncated=False):
    mr = {"_analysis_truncation": {"from": 10, "to": 5}} if truncated else {}
    return SimpleNamespace(query_context={"start_date": "2026-09-01T00:00:00Z", "end_date": "2026-09-08T00:00:00Z",
                                          "filters": filters or {}, "policy_decisions": pds},
                           module_results=mr, date_range=("", ""))


def test_basis_captures_filters_and_decisions():
    a = comparison_basis(_result())
    b = comparison_basis(_result(filters={"src_labels": ["app:web"]}, pds=["blocked"]))
    assert a["policy_decisions"] == "abpu" and a["filters"] == ""
    assert b["policy_decisions"] == "b" and b["filters"]
    assert a["window"]["start"] == "2026-09-01T00:00:00Z"


def test_trend_flags_different_filters_and_truncation():
    cur = {"filters": "abc", "truncated": False, "policy_decisions": "abpu"}
    prev = {"_meta": {"filters": "", "truncated": True, "policy_decisions": "abpu"}}
    fields = {m["field"] for m in snapshot_mismatch(cur, prev)}
    assert {"filters", "truncated"} <= fields


def test_change_impact_flags_unlike_basis():
    prev = {"kpis": {"maturity_score": 50}, "basis": {"policy_decisions": "abpu", "filters": ""}}
    out = compare(current_kpis={"maturity_score": 60}, previous=prev,
                  current_basis={"policy_decisions": "b", "filters": "x"})
    assert out["basis_mismatch"] == ["policy_decisions", "filters"]
    assert basis_mismatch({"policy_decisions": "abpu"}, {"kpis": {}}) == ["basis"]
