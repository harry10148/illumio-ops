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


# Phase 2A Task 11 removed everything below this line: nine tests that made
# static string assertions about src/templates/index.html and
# src/static/js/dashboard.js (the three ad-hoc report cards, the scheduler's
# security_risk/network_inventory <option>s, the removed profile dropdown,
# the TRAFFIC_PROFILE_TYPES constant, the traffic-family "last run" filename
# disambiguation, and the main-tab/sub-tab i18n key split). Both files were
# deleted with the legacy frontend. The v2 equivalents are real browser
# tests against the real endpoints:
#
#   ad-hoc report cards + generate drawer   tests/test_v2_reports_e2e.py (RP-01/RP-02)
#   report schedules and their type list    tests/test_v2_automation_e2e.py (#/automation/reports)
#   "last run" per report family            tests/test_v2_reports_e2e.py (RP-07 float host)
#   the Alerts area label                   tests/test_v2_shell_e2e.py (XC-14 nav, gui_nav_alerting)
#
# What survives here is the part with no browser equivalent and no other
# owner: the catalogue contract for the keys that split introduced, across
# all three i18n files. Note that gui_hdr_chip_aria (asserted in
# test_changed_values_updated) is now an ORPHANED key — the v2 chrome has no
# header chip — kept because its wording still has to agree with
# gui_rules_count if the chip ever comes back. See task-11-report.md.
