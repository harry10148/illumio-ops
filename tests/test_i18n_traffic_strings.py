"""i18n keys required by the traffic panel / report dialogs must exist
in both en and zh_TW dictionaries and be referenced from index.html."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parent.parent
EN = ROOT / "src" / "i18n_en.json"
ZH = ROOT / "src" / "i18n_zh_TW.json"

REQUIRED_KEYS = {
    # The traffic table's empty state (v2: areas/investigate.mjs, XC-09)
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


def test_traffic_empty_state_is_rendered_by_the_v2_cause_hints():
    """Task 11, a REPLACED string recorded rather than dropped.

    The legacy assertion was that `data-i18n="gui_traffic_run_query_empty"`
    ("Run a query to view real-time traffic anomalies.") appears on the
    traffic table's empty <td> in src/templates/index.html. That file is
    gone, and v2 does not reuse the key: areas/investigate.mjs's XC-09 empty
    state explains WHY the result set is empty (window / source / archive
    range / filter) through the gui_iv_cause_* family instead of showing one
    static sentence. gui_traffic_run_query_empty is therefore an orphaned
    catalogue entry — still translated (asserted above), no longer read.

    What replaced it is asserted here, so the empty state keeps a gate.
    """
    js = (ROOT / "src" / "static" / "js" / "v2" / "areas" / "investigate.mjs").read_text(
        encoding="utf-8"
    )
    assert 'data-cov": "XC-09"' in js, "the traffic empty state lost its anchor"
    assert js.count("gui_iv_cause_") >= 3, "XC-09 no longer explains the cause"

    v2 = "".join(
        p.read_text(encoding="utf-8")
        for p in sorted((ROOT / "src" / "static" / "js" / "v2").rglob("*.mjs"))
    )
    assert "gui_traffic_run_query_empty" not in v2, (
        "gui_traffic_run_query_empty gained a v2 consumer — update this test, "
        "it is documented above as orphaned"
    )


def test_zh_explicit_matches_zh_tw_for_traffic_keys():
    """zh_explicit.json is the source of truth for precompute_zh_translations.py.
    Any zh_TW value we set must also exist in zh_explicit.json to avoid silent revert."""
    import json
    explicit_path = ROOT / "src" / "i18n" / "data" / "zh_explicit.json"
    explicit = json.loads(explicit_path.read_text(encoding="utf-8"))
    assert explicit.get("rpt_filter_toggle") == "流量篩選條件（選填）"
    assert explicit.get("gui_traffic_run_query_empty") == "執行查詢以檢視即時流量異常。"
