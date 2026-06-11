# tests/test_trend_store_canonical.py
"""Trend snapshots must use stable canonical keys, not localized labels."""
import json

from src.report.trend_store import (
    build_kpi_dict_from_metadata,
    canonicalize_legacy_keys,
    compute_deltas,
    load_previous,
    save_snapshot,
)


def test_build_kpi_dict_prefers_label_key():
    kpis = [
        {"label_key": "mod12_kpi_total_flows", "label": "流量總數", "value": "22,620"},
        {"i18n_key": "rpt_ven_kpi_online", "label": "Online VENs", "value": 18},
        {"label": "Legacy Only", "value": 5},  # 無 key 時退回 label
    ]
    d = build_kpi_dict_from_metadata(kpis)
    assert d == {
        "mod12_kpi_total_flows": "22,620",
        "rpt_ven_kpi_online": 18,
        "Legacy Only": 5,
    }


def test_canonicalize_legacy_keys_maps_zh_and_en_labels():
    # 舊 snapshot 用本地化標籤當 key（zh 與 en 都可能存在）
    legacy = {"_generated_at": "x", "流量總數": "20,282", "Total Connections": "16,171,812"}
    canon = canonicalize_legacy_keys(
        legacy, candidate_keys=["mod12_kpi_total_flows", "mod12_kpi_total_connections"]
    )
    assert canon["mod12_kpi_total_flows"] == "20,282"
    assert canon["mod12_kpi_total_connections"] == "16,171,812"
    assert canon["_generated_at"] == "x"


def test_canonicalize_legacy_enforcement_mode_composed_label():
    legacy = {"Enforcement: Full": 7}
    canon = canonicalize_legacy_keys(legacy, candidate_keys=["mod12_kpi_enforce_mode_full"])
    assert canon == {"mod12_kpi_enforce_mode_full": 7}


def test_cross_language_snapshots_now_produce_deltas(tmp_path):
    out = str(tmp_path)
    # 模擬：前一份報表以 zh_TW 產生（舊格式：本地化 key）
    save_snapshot(out, "traffic", {"流量總數": "100"}, generated_at="2026-06-01T00:00:00")
    # 本次報表以 en 產生（新格式：canonical key）
    current = build_kpi_dict_from_metadata(
        [{"label_key": "mod12_kpi_total_flows", "label": "Total Flows", "value": "150"}]
    )
    save_snapshot(out, "traffic", current, generated_at="2026-06-02T00:00:00")
    prev = load_previous(out, "traffic")
    prev = canonicalize_legacy_keys(prev, candidate_keys=list(current.keys()))
    deltas = compute_deltas(current, prev)
    assert len(deltas) == 1
    assert deltas[0]["metric"] == "mod12_kpi_total_flows"
    assert deltas[0]["delta"] == 50.0
