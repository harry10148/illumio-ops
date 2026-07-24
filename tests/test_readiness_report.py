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


def test_estate_pb_uncovered_not_double_counted():
    """Estate PB total must count each cross-app flow ONCE, not once per endpoint
    group. A single appA->appB PB flow lands in both appA's and appB's per-app
    group; summing the per-app column would report 2 for a 1-flow estate."""
    from src.report.analysis.mod13_readiness import enforcement_readiness
    df = pd.DataFrame([
        {"src_app": "appA", "src_env": "prod", "dst_app": "appB", "dst_env": "prod",
         "policy_decision": "potentially_blocked", "port": 443, "num_connections": 1,
         "src_managed": True, "dst_managed": True},
        {"src_app": "appA", "src_env": "prod", "dst_app": "appC", "dst_env": "prod",
         "policy_decision": "potentially_blocked", "port": 443, "num_connections": 1,
         "src_managed": True, "dst_managed": True},
    ])
    result = enforcement_readiness(df)
    assert result["pb_uncovered_count"] == 2, (
        f"expected 2 PB flows counted once each, got {result['pb_uncovered_count']}")


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


def test_export_html_writes_sidecar_with_report_type(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, _flows_df(), _workloads())
    result = gen.generate_from_api(output_dir=str(tmp_path))
    paths = gen.export(result, fmt="html", output_dir=str(tmp_path))
    assert len(paths) == 1 and paths[0].endswith(".html")
    import json
    with open(paths[0] + ".metadata.json", encoding="utf-8") as fh:
        meta = json.load(fh)
    assert meta["report_type"] == "readiness"
    assert meta["record_count"] == result.record_count


def test_export_all_writes_html_and_csv_zip(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, _flows_df(), _workloads())
    result = gen.generate_from_api(output_dir=str(tmp_path))
    paths = gen.export(result, fmt="all", output_dir=str(tmp_path))
    exts = sorted(p.rsplit(".", 1)[-1] for p in paths)
    assert exts == ["html", "zip"]
    import os
    assert all(os.path.basename(p).startswith("Illumio_Readiness_Report_") for p in paths)


def test_recommended_action_matches_blocking_factor(monkeypatch, tmp_path):
    """建議動作必須依該列 blocking factor 分化——原本一律取全域 P1
    （通常是 MOVE_TO_ENFORCEMENT），與該列的阻塞因素對不上
    （2026-07-23 視覺實檢：整欄同一句樣板）。"""
    gen = _gen(monkeypatch, _flows_df(), _workloads())
    q = gen.generate_from_api(output_dir=str(tmp_path)).module_results["queue_df"]
    row_b = q[q["app_env_key"] == "appb|prod"].iloc[0]
    assert row_b["blocking_factor_key"] == "policy_coverage"
    # policy_coverage 阻塞 → 動作講 allow policy/覆蓋率，不是推進 enforcement
    assert "allow" in row_b["recommended_action"].lower() or "覆蓋" in row_b["recommended_action"]
    row_a = q[q["app_env_key"] == "appa|prod"].iloc[0]
    # 兩列 blocking factor 不同 → 動作文字不同
    if row_a["blocking_factor_key"] != row_b["blocking_factor_key"]:
        assert row_a["recommended_action"] != row_b["recommended_action"]


def test_enforcement_blocking_full_mode_variant(monkeypatch, tmp_path):
    """blocking=enforcement_mode 且 current_mode 已含 selective →
    文字用「推進到 full enforcement」變體，不再說「由 visibility/testing 推進」。"""
    from src.report.readiness_report import ReadinessReportGenerator
    gen = ReadinessReportGenerator(config_manager=None, api_client=None)
    gen._lang = "zh_TW"
    txt = gen._action_for_blocking("enforcement_mode", {"selective": 3})
    assert "full" in txt.lower()
    txt2 = gen._action_for_blocking("enforcement_mode", {"visibility_only": 2})
    assert "visibility" in txt2.lower() or "selective" in txt2.lower()
