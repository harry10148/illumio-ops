# tests/test_drift_meta.py
"""Drift baseline 中繼資料 + 視窗不一致拒絕比較（spec L1 之 drift）。

三組：
  (a) flow_history roundtrip 含 meta + 舊檔無 meta 相容；
  (b) baseline_drift 四情境（視窗差拒絕 / 同窗照常 / data_source 警語 / 無 meta 現行）；
  (c) 渲染級兩情境（comparable False 出 note 且兩表消失 / 警語情境 head 加警語）。
"""
import pandas as pd

from src.report.analysis.mod_drift import baseline_drift
from src.report.exporters.html_exporter import SecurityRiskHtmlExporter
from src.report.flow_history import (
    load_previous_baseline,
    load_previous_signatures,
    save_signatures,
)


def _df():
    return pd.DataFrame([
        {"src_app": "Web", "dst_app": "DB", "port": 3306, "proto": "TCP", "num_connections": 40},
        {"src_app": "Web", "dst_app": "Cache", "port": 6379, "proto": "TCP", "num_connections": 7},
    ])


_META_7D = {"window": {"start": "2026-05-01", "end": "2026-05-08"},
            "data_source": "cache", "profile": "security_risk"}
_META_1D = {"window": {"start": "2026-06-01", "end": "2026-06-02"},
            "data_source": "cache", "profile": "security_risk"}
_META_1D_API = {"window": {"start": "2026-06-01", "end": "2026-06-02"},
                "data_source": "api", "profile": "security_risk"}


# ── (a) flow_history roundtrip + 舊檔相容 ────────────────────────────────
def test_save_load_baseline_roundtrip_with_meta(tmp_path):
    out = str(tmp_path)
    save_signatures(out, "traffic", {"A|B|443|TCP"},
                    generated_at="2026-06-01T00:00:00", meta=_META_1D)
    sigs, ts, meta = load_previous_baseline(out, "traffic")
    assert sigs == {"A|B|443|TCP"}
    assert ts == "2026-06-01T00:00:00"
    assert meta == _META_1D


def test_load_baseline_old_file_without_meta(tmp_path):
    out = str(tmp_path)
    # 舊寫入路徑：不帶 meta（模擬升級前的 baseline 檔）
    save_signatures(out, "traffic", {"A|B|443|TCP"}, generated_at="2026-06-01T00:00:00")
    sigs, ts, meta = load_previous_baseline(out, "traffic")
    assert sigs == {"A|B|443|TCP"}
    assert ts == "2026-06-01T00:00:00"
    assert meta is None
    # 舊委派函式維持兩元組相容
    sigs2, ts2 = load_previous_signatures(out, "traffic")
    assert sigs2 == {"A|B|443|TCP"} and ts2 == "2026-06-01T00:00:00"


# ── (b) baseline_drift 四情境 ────────────────────────────────────────────
def test_window_mismatch_refuses_comparison():
    prev = {"Web|DB|3306|TCP", "Batch|DB|3306|TCP"}
    res = baseline_drift(_df(), prev_signatures=prev, prev_generated_at="2026-05-08T00:00:00",
                         prev_meta=_META_7D, current_meta=_META_1D)
    assert res["available"] is True
    assert res["comparable"] is False
    # 拒絕比較時不做差集，不含兩表 key
    assert "new_pairs" not in res
    assert "disappeared_pairs" not in res
    assert "new_count" not in res
    assert res["prev_generated_at"] == "2026-05-08T00:00:00"
    assert any(m.get("field") == "window" for m in res["mismatch"])


def test_same_window_compares_normally():
    prev = {"Web|DB|3306|TCP", "Batch|DB|3306|TCP"}
    res = baseline_drift(_df(), prev_signatures=prev, prev_generated_at="x",
                         prev_meta=_META_1D, current_meta=_META_1D)
    assert res["comparable"] is True
    assert res["new_count"] == 1          # Web→Cache 是新的
    assert res["disappeared_count"] == 1  # Batch→DB 消失
    assert res["mismatch"] == []          # 視窗與 data_source 皆一致


def test_data_source_mismatch_compares_with_warning():
    prev = {"Web|DB|3306|TCP", "Batch|DB|3306|TCP"}
    res = baseline_drift(_df(), prev_signatures=prev, prev_generated_at="x",
                         prev_meta=_META_1D, current_meta=_META_1D_API)
    assert res["comparable"] is True
    # data_source 不一致 → 照常比較（有兩表），但 mismatch 欄非空
    assert res["new_count"] == 1
    assert any(m.get("field") == "data_source" for m in res["mismatch"])


def test_no_meta_preserves_current_behavior():
    prev = {"Web|DB|3306|TCP", "Batch|DB|3306|TCP"}
    # 舊 baseline：prev_meta=None（升級前檔無 _meta）
    res = baseline_drift(_df(), prev_signatures=prev, prev_generated_at="x",
                         prev_meta=None, current_meta=_META_1D)
    assert res["available"] is True
    assert res["new_count"] == 1 and res["disappeared_count"] == 1
    # 無 meta 比較 → 完全現行形狀，不含 comparable/mismatch key
    assert "comparable" not in res
    assert "mismatch" not in res


# ── (c) 渲染級兩情境 ─────────────────────────────────────────────────────
def _render_drift(mod_drift: dict) -> str:
    exp = SecurityRiskHtmlExporter({"mod_drift": mod_drift}, lang="en")
    return exp._mod_drift_html()


def test_render_incomparable_shows_note_and_hides_tables():
    mod_drift = {
        "available": True,
        "comparable": False,
        "prev_generated_at": "2026-05-08T00:00:00",
        "mismatch": [{"field": "window",
                      "previous": {"start": "2026-05-01", "end": "2026-05-08"},
                      "current": {"start": "2026-06-01", "end": "2026-06-02"}}],
    }
    html = _render_drift(mod_drift)
    assert "drift comparison skipped" in html          # 拒絕比較 note 出現
    assert "New App-to-App Pairs" not in html          # 兩表消失
    assert "Disappeared Pairs" not in html


def test_render_data_source_mismatch_adds_head_warning():
    mod_drift = {
        "available": True,
        "comparable": True,
        "prev_generated_at": "2026-06-01T00:00:00",
        "new_count": 1,
        "disappeared_count": 0,
        "new_unlabeled_collapsed": 0,
        "disappeared_unlabeled_collapsed": 0,
        "new_pairs": pd.DataFrame([{"Src App": "Web", "Dst App": "Cache",
                                    "Port": "6379", "Proto": "TCP", "Connections": 7}]),
        "disappeared_pairs": pd.DataFrame(),
        "mismatch": [{"field": "data_source", "previous": "cache", "current": "api"}],
    }
    html = _render_drift(mod_drift)
    assert "Comparison caveat" in html                 # 重用 Task 2 警語 key
    assert "New App-to-App Pairs" in html              # 兩表照常出現
