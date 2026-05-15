"""i18n keys required by the traffic panel / report dialogs must exist
in both en and zh_TW dictionaries and be referenced from index.html."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parent.parent
EN = ROOT / "src" / "i18n_en.json"
ZH = ROOT / "src" / "i18n_zh_TW.json"
INDEX = ROOT / "src" / "templates" / "index.html"

REQUIRED_KEYS = {
    # New empty-state for traffic table at index.html:340
    "gui_traffic_run_query_empty": "Run a query to view real-time traffic anomalies.",
    # Existing key but mis-valued — should describe a section toggle, not action
    "rpt_filter_toggle": "Traffic Filters (optional)",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_required_keys_in_en():
    en = _load(EN)
    for key in REQUIRED_KEYS:
        assert key in en, f"Missing key {key!r} in en"


def test_required_keys_in_zh():
    zh = _load(ZH)
    for key in REQUIRED_KEYS:
        assert key in zh, f"Missing key {key!r} in zh_TW"


def test_rpt_filter_toggle_value_in_en():
    en = _load(EN)
    assert en["rpt_filter_toggle"] == REQUIRED_KEYS["rpt_filter_toggle"]


def test_index_html_uses_data_i18n_on_traffic_empty_state():
    html = INDEX.read_text(encoding="utf-8")
    # The "Run a query..." cell must carry data-i18n now
    assert 'data-i18n="gui_traffic_run_query_empty"' in html, (
        "Traffic empty-state <td> should have data-i18n=\"gui_traffic_run_query_empty\""
    )


def test_zh_explicit_matches_zh_tw_for_traffic_keys():
    """zh_explicit.json is the source of truth for precompute_zh_translations.py.
    Any zh_TW value we set must also exist in zh_explicit.json to avoid silent revert."""
    import json
    explicit_path = ROOT / "src" / "i18n" / "data" / "zh_explicit.json"
    explicit = json.loads(explicit_path.read_text(encoding="utf-8"))
    assert explicit.get("rpt_filter_toggle") == "流量篩選條件（選填）"
    assert explicit.get("gui_traffic_run_query_empty") == "執行查詢以檢視即時流量異常。"
