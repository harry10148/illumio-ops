# tests/test_trend_meta.py
"""Trend 快照中繼資料（window/data_source/profile）與不一致警語。"""
from src.report.trend_store import (
    canonicalize_legacy_keys,
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


# ── (a2) load_previous 呼叫序為 load-before-save：最新檔即上一次 run ────────

def test_load_previous_returns_the_latest_snapshot_not_the_one_before(tmp_path):
    """四個 generator 都是「先 load 後 save」：load_previous 被呼叫的當下，
    磁碟上最新的快照就是「上一次 run」，不是「上上次 run」。"""
    out = str(tmp_path)
    save_snapshot(out, "traffic", {"mod12_kpi_total_flows": "100"}, generated_at="2026-06-01T00:00:00")
    save_snapshot(out, "traffic", {"mod12_kpi_total_flows": "150"}, generated_at="2026-06-02T00:00:00")
    save_snapshot(out, "traffic", {"mod12_kpi_total_flows": "200"}, generated_at="2026-06-03T00:00:00")
    prev = load_previous(out, "traffic")
    assert prev["mod12_kpi_total_flows"] == "200"


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


def test_snapshot_mismatch_invalid_date_string_skips_window_comparison():
    """window 內含無法解析的日期字串時不炸，且該欄位比較被跳過。"""
    current_meta = {"window": {"start": "not-a-date", "end": "2026-06-08"}}
    previous_payload = {"_meta": {"window": {"start": "2026-05-01", "end": "2026-05-02"}}}
    assert snapshot_mismatch(current_meta, previous_payload) == []


def test_snapshot_mismatch_one_sided_missing_window_skips_comparison():
    """只有一邊有 window（另一邊缺）時跳過 window 比較，不誤判為不一致。"""
    # 前一份 _meta 非空（避免走 not previous_meta 的 early-return）但無 window——
    # 讓斷言真正命中 window guard（review 複核發現原 fixture 走錯路徑）
    current_meta = {"window": {"start": "2026-06-01", "end": "2026-06-08"},
                    "data_source": "api"}
    previous_payload = {"_meta": {"data_source": "api"}}
    assert snapshot_mismatch(current_meta, previous_payload) == []


# ── (e) canonicalize_legacy_keys 不動 _meta ─────────────────────────────────

def test_canonicalize_legacy_keys_preserves_meta_key():
    """_meta 的值應原樣保留，不被當成 KPI 標籤改名。"""
    meta = {"window": {"start": "2026-06-01", "end": "2026-06-07"}, "data_source": "api"}
    legacy = {"_generated_at": "x", "_meta": meta, "流量總數": "20,282"}
    canon = canonicalize_legacy_keys(legacy, candidate_keys=["mod12_kpi_total_flows"])
    assert canon["_meta"] == meta
    assert canon["mod12_kpi_total_flows"] == "20,282"


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
