# tests/test_trend_meta.py
"""Trend 快照中繼資料（window/data_source/profile）與不一致警語。"""
from src.report.trend_store import (
    compute_deltas,
    load_previous,
    save_snapshot,
    snapshot_mismatch,
)
from src.report.exporters.html_exporter import _trend_deltas_section


# ── (a) save→load roundtrip 含 _meta ────────────────────────────────────────

def test_save_snapshot_roundtrips_meta(tmp_path):
    out = str(tmp_path)
    meta = {"window": {"start": "2026-06-01", "end": "2026-06-07"}, "data_source": "api", "profile": "security_risk"}
    save_snapshot(out, "traffic", {"mod12_kpi_total_flows": "100"}, generated_at="2026-06-07T00:00:00", meta=meta)
    save_snapshot(out, "traffic", {"mod12_kpi_total_flows": "150"}, generated_at="2026-06-08T00:00:00", meta=meta)
    prev = load_previous(out, "traffic")
    assert prev["_meta"] == meta


def test_save_snapshot_without_meta_omits_key(tmp_path):
    out = str(tmp_path)
    save_snapshot(out, "traffic", {"mod12_kpi_total_flows": "100"}, generated_at="2026-06-07T00:00:00")
    save_snapshot(out, "traffic", {"mod12_kpi_total_flows": "150"}, generated_at="2026-06-08T00:00:00")
    prev = load_previous(out, "traffic")
    assert "_meta" not in prev


# ── (b) compute_deltas 不把 _meta 當 KPI ────────────────────────────────────

def test_compute_deltas_skips_meta_key():
    meta = {"window": {"start": "2026-06-01", "end": "2026-06-07"}, "data_source": "api", "profile": "security_risk"}
    current = {"_generated_at": "t2", "_meta": meta, "mod12_kpi_total_flows": "150"}
    previous = {"_generated_at": "t1", "_meta": meta, "mod12_kpi_total_flows": "100"}
    deltas = compute_deltas(current, previous)
    assert [d["metric"] for d in deltas] == ["mod12_kpi_total_flows"]


# ── (c) snapshot_mismatch ────────────────────────────────────────────────────

def test_snapshot_mismatch_window_span_differs():
    current_meta = {"window": {"start": "2026-06-01", "end": "2026-06-08"}}  # 7 天
    previous_payload = {"_meta": {"window": {"start": "2026-05-01", "end": "2026-05-02"}}}  # 1 天
    result = snapshot_mismatch(current_meta, previous_payload)
    assert result == [{
        "field": "window",
        "previous": {"start": "2026-05-01", "end": "2026-05-02"},
        "current": {"start": "2026-06-01", "end": "2026-06-08"},
    }]


def test_snapshot_mismatch_window_within_one_day_is_ok():
    current_meta = {"window": {"start": "2026-06-01", "end": "2026-06-08"}}  # 7 天
    previous_payload = {"_meta": {"window": {"start": "2026-05-01", "end": "2026-05-07"}}}  # 6 天
    result = snapshot_mismatch(current_meta, previous_payload)
    assert result == []


def test_snapshot_mismatch_data_source_differs():
    current_meta = {"data_source": "api"}
    previous_payload = {"_meta": {"data_source": "cache"}}
    result = snapshot_mismatch(current_meta, previous_payload)
    assert result == [{"field": "data_source", "previous": "cache", "current": "api"}]


def test_snapshot_mismatch_no_previous_meta_is_silent():
    current_meta = {"data_source": "api", "profile": "security_risk"}
    previous_payload = {"_generated_at": "t1", "mod12_kpi_total_flows": "100"}  # 舊快照無 _meta
    assert snapshot_mismatch(current_meta, previous_payload) == []


def test_snapshot_mismatch_no_current_meta_is_silent():
    assert snapshot_mismatch(None, {"_meta": {"data_source": "api"}}) == []


# ── (d) 渲染級：警語只在 mismatch 非空時出現 ─────────────────────────────────

def test_trend_deltas_section_shows_warning_when_mismatch_present():
    deltas = [{"metric": "mod12_kpi_total_flows", "current": 150, "previous": 100,
               "delta": 50.0, "delta_pct": 50.0, "direction": "up"}]
    mismatch = [{"field": "data_source", "previous": "cache", "current": "api"}]
    html = _trend_deltas_section(deltas, lang="en", mismatch=mismatch)
    assert "note-warn" in html
    assert "data_source" in html


def test_trend_deltas_section_no_warning_when_mismatch_empty():
    deltas = [{"metric": "mod12_kpi_total_flows", "current": 150, "previous": 100,
               "delta": 50.0, "delta_pct": 50.0, "direction": "up"}]
    html = _trend_deltas_section(deltas, lang="en", mismatch=[])
    assert "note-warn" not in html
