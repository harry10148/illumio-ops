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


INDEX_HTML = (ROOT / "src" / "templates" / "index.html").read_text(encoding="utf-8")


def test_three_adhoc_report_cards_present():
    for args in ('["traffic"]', '["security_risk"]', '["network_inventory"]'):
        assert f"data-action=\"openReportGenModal\" data-args='{args}'" in INDEX_HTML, \
            f"missing ad-hoc report card button for {args}"


def test_security_and_inventory_cards_use_new_i18n_keys():
    assert "gui_rcard_security_title" in INDEX_HTML
    assert "gui_rcard_inventory_title" in INDEX_HTML


DASHBOARD_JS = (ROOT / "src" / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")


def test_modal_meta_has_three_profile_types():
    assert "security_risk:" in DASHBOARD_JS
    assert "network_inventory:" in DASHBOARD_JS
    assert "gui_gen_security_title" in DASHBOARD_JS
    assert "gui_gen_inventory_title" in DASHBOARD_JS


def test_profile_dropdown_removed():
    assert "m-gen-profile-row" not in INDEX_HTML, "profile dropdown row must be removed"
    assert "m-gen-profile" not in DASHBOARD_JS, "no code should read the removed profile select"


def test_shared_traffic_profile_types_constant():
    assert "TRAFFIC_PROFILE_TYPES" in DASHBOARD_JS


def test_scheduler_has_security_and_inventory_options():
    assert 'value="security_risk"' in INDEX_HTML
    assert 'value="network_inventory"' in INDEX_HTML
    assert "gui_sched_rt_security" in INDEX_HTML
    assert "gui_sched_rt_inventory" in INDEX_HTML


def test_schedule_list_typelabels_cover_new_types():
    # both scheduler typeLabels maps must resolve the new report types
    assert DASHBOARD_JS.count("gui_sched_rt_security") >= 1
    assert DASHBOARD_JS.count("gui_sched_rt_inventory") >= 1


import re


def test_main_tab_uses_alerts_key_subtab_keeps_rules():
    # main nav tab button (controls p-rules) now labelled via gui_tab_alerts
    main_tab = re.search(
        r'<button[^>]*aria-controls="p-rules"[^>]*data-i18n="([^"]+)"', INDEX_HTML
    )
    assert main_tab and main_tab.group(1) == "gui_tab_alerts", \
        "main Rules tab should use gui_tab_alerts"
    # in-page sub-tab button still uses gui_tab_rules
    assert 'id="rules-tab-rules" data-i18n="gui_tab_rules"' in INDEX_HTML
    # tab wiring unchanged
    assert 'data-tab="rules"' in INDEX_HTML
    assert 'aria-controls="p-rules"' in INDEX_HTML
