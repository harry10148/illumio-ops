"""Enforcement Readiness standalone report generator tests."""
from __future__ import annotations

import pandas as pd

from src.report.readiness_report import ReadinessReportGenerator, ReadinessResult


def _flows_df():
    # appA|prod: all allowed + ringfenced -> high score
    # appB|prod: all potentially_blocked -> low score, blocking factor = policy_coverage
    rows = []
    for _ in range(6):
        rows.append({"src_app": "appA", "src_env": "prod", "dst_app": "appA",
                     "dst_env": "prod", "policy_decision": "allowed",
                     "port": 443, "num_connections": 2,
                     "src_managed": True, "dst_managed": True})
    for _ in range(6):
        rows.append({"src_app": "appB", "src_env": "prod", "dst_app": "other",
                     "dst_env": "prod", "policy_decision": "potentially_blocked",
                     "port": 443, "num_connections": 1,
                     "src_managed": False, "dst_managed": False})
    return pd.DataFrame(rows)


def _workloads():
    return [
        {"href": "/w/1", "enforcement_mode": "full",
         "labels": [{"key": "app", "value": "appA"}, {"key": "env", "value": "Prod"}]},
        {"href": "/w/2", "enforcement_mode": "visibility_only",
         "labels": [{"key": "app", "value": "appB"}, {"key": "env", "value": "prod"}]},
    ]


def _gen(monkeypatch, df, workloads):
    gen = ReadinessReportGenerator(config_manager=None, api_client=None)
    monkeypatch.setattr(gen, "_fetch_estate_df", lambda *a, **k: df)
    monkeypatch.setattr(gen, "_fetch_workloads", lambda: workloads)
    return gen


def test_empty_flows_returns_zero_records(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, pd.DataFrame(), None)
    result = gen.generate_from_api(output_dir=str(tmp_path))
    assert isinstance(result, ReadinessResult)
    assert result.record_count == 0


def test_queue_sorted_ready_first(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, _flows_df(), _workloads())
    result = gen.generate_from_api(output_dir=str(tmp_path))
    q = result.module_results["queue_df"]
    assert list(q["app_env_key"])[0] == "appa|prod"          # highest score first
    assert q["readiness_score"].is_monotonic_decreasing


def test_blocking_factor_is_lowest_ratio(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, _flows_df(), _workloads())
    q = gen.generate_from_api(output_dir=str(tmp_path)).module_results["queue_df"]
    row = q[q["app_env_key"] == "appb|prod"].iloc[0]
    # appB has zero allowed flows -> policy_coverage ratio 0 is the minimum
    assert row["blocking_factor_key"] == "policy_coverage"


def test_current_mode_from_workloads_with_key_normalization(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, _flows_df(), _workloads())
    q = gen.generate_from_api(output_dir=str(tmp_path)).module_results["queue_df"]
    # 'Prod' label must normalize to 'prod' to match the flow-derived key
    assert q[q["app_env_key"] == "appa|prod"].iloc[0]["current_mode"] == "full×1"
    assert q[q["app_env_key"] == "appb|prod"].iloc[0]["current_mode"] == "visibility_only×1"


def test_kpis_count_ready_and_blocked(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, _flows_df(), _workloads())
    kpis = gen.generate_from_api(output_dir=str(tmp_path)).module_results["kpis"]
    by_key = {k["i18n_key"]: k["value"] for k in kpis}
    q = gen.generate_from_api(output_dir=str(tmp_path)).module_results["queue_df"]
    assert by_key["rpt_readiness_kpi_ready"] == int(q["grade"].isin(["A", "B"]).sum())
    assert by_key["rpt_readiness_kpi_blocked"] == int(q["grade"].isin(["D", "F"]).sum())
    assert "rpt_readiness_kpi_score" in by_key and "rpt_readiness_kpi_grade" in by_key


def test_trend_snapshot_saved_and_deltas_on_second_run(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, _flows_df(), _workloads())
    r1 = gen.generate_from_api(output_dir=str(tmp_path))
    assert (tmp_path / "history" / "readiness").is_dir()
    assert r1.module_results["_trend_deltas"] == []
    r2 = gen.generate_from_api(output_dir=str(tmp_path))
    metrics = {d["metric"] for d in r2.module_results["_trend_deltas"]}
    assert "rpt_readiness_kpi_score" in metrics
