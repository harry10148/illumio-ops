"""變更影響章端到端渲染（spec C4a）：首次 note、次次 delta 表。"""
import pandas as pd
from src.report.exporters.html_exporter import NetworkInventoryHtmlExporter
from src.report.analysis.mod_change_impact import collect_current_kpis


def _results():
    return {
        "mod12": {"kpis": [{"label": "x", "value": 1}],  # 顯示用 list（現況）
                  "key_findings": [],
                  "enforced_coverage_pct": 60.0, "true_gap_pct": 10.0,
                  "maturity_score": 55},
        "mod04": {"risk_flows_total": 7},
        "findings": [],
    }


def test_collect_current_kpis():
    kpis = collect_current_kpis(_results())
    assert kpis["enforced_coverage_pct"] == 60.0
    assert kpis["risk_flows_total"] == 7


def test_first_run_shows_note(monkeypatch):
    import src.report.exporters.html_exporter as he
    monkeypatch.setattr("src.report.snapshot_store.read_latest", lambda *a, **k: None)
    html = NetworkInventoryHtmlExporter(_results(), lang="en").build()
    assert "No previous snapshot" in html or "無先前快照" in html


def test_second_run_renders_delta_table(monkeypatch):
    prev = {"kpis": {"enforced_coverage_pct": 50.0, "true_gap_pct": 15.0,
                     "maturity_score": 50, "risk_flows_total": 9},
            "generated_at": "2026-07-01T00:00:00+00:00"}
    monkeypatch.setattr("src.report.snapshot_store.read_latest", lambda *a, **k: prev)
    html = NetworkInventoryHtmlExporter(_results(), lang="en").build()
    assert "enforced_coverage_pct" in html          # delta 表列
    assert "IMPROVED" in html                        # coverage 上升 + gap 下降 → improved
