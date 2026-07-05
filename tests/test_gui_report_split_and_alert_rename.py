"""GUI report 3-way split + Rules→Alert rename: i18n + template contracts."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = json.loads((ROOT / "src" / "i18n_en.json").read_text(encoding="utf-8"))
ZH = json.loads((ROOT / "src" / "i18n_zh_TW.json").read_text(encoding="utf-8"))
ZH_EXPLICIT = json.loads(
    (ROOT / "src" / "i18n" / "data" / "zh_explicit.json").read_text(encoding="utf-8")
)

NEW_KEYS = [
    "gui_tab_alerts",
    "gui_rcard_security_title", "gui_rcard_security_desc",
    "gui_rcard_inventory_title", "gui_rcard_inventory_desc",
    "gui_gen_security_title", "gui_gen_inventory_title",
    "gui_sched_rt_security", "gui_sched_rt_inventory",
]


def test_new_keys_present_in_all_three_i18n_files():
    for k in NEW_KEYS:
        assert k in EN and EN[k].strip(), f"{k} missing/empty in i18n_en.json"
        assert k in ZH and ZH[k].strip(), f"{k} missing/empty in i18n_zh_TW.json"
        assert k in ZH_EXPLICIT and ZH_EXPLICIT[k].strip(), f"{k} missing in zh_explicit.json"


def test_changed_values_updated():
    assert EN["gui_rules_count"] == "Alerts"
    assert ZH["gui_rules_count"] == "告警數"
    assert ZH_EXPLICIT["gui_rules_count"] == "告警數"
    assert "alerts" in EN["gui_hdr_chip_aria"]
    assert "告警" in ZH["gui_hdr_chip_aria"]
    # traffic card description no longer references the old profile views
    assert "Security Risk" not in EN["gui_rcard_traffic_desc"]
    assert "Network Inventory" not in EN["gui_rcard_traffic_desc"]


def test_tab_alerts_label():
    assert EN["gui_tab_alerts"] == "Alerts"
    assert ZH["gui_tab_alerts"] == "告警"
    # gui_tab_rules unchanged — still used by the in-page sub-tab
    assert EN["gui_tab_rules"] == "Rules"
    assert ZH["gui_tab_rules"] == "規則"
