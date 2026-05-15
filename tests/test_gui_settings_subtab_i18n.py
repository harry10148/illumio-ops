"""Sub-tab labels exist in both i18n dictionaries with the expected values,
and the .s-subpanel display rule exists in app.css."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parent.parent
EN = ROOT / "src" / "i18n_en.json"
ZH = ROOT / "src" / "i18n_zh_TW.json"
CSS = ROOT / "src" / "static" / "css" / "app.css"


EXPECTED_EN = {
    "gui_settings_tab_pce": "PCE Connection",
    "gui_settings_tab_channels": "Notification Channels",
    "gui_settings_tab_display": "Interface & Reports",
    "gui_settings_tab_security": "Security",
    "gui_settings_save_one": "Save {section}",
    "gui_settings_save_many": "Save all changes ({n} sections)",
    "gui_settings_section_pce": "PCE Connection",
    "gui_settings_section_channels": "Notification Channels",
    "gui_settings_section_display": "Interface & Reports",
    "gui_settings_section_security": "Security",
}

EXPECTED_ZH = {
    "gui_settings_tab_pce": "PCE 連線",
    "gui_settings_tab_channels": "通知通道",
    "gui_settings_tab_display": "介面與報表",
    "gui_settings_tab_security": "安全",
    "gui_settings_save_one": "儲存 {section}",
    "gui_settings_save_many": "儲存所有變更（{n} 個區塊）",
    "gui_settings_section_pce": "PCE 連線",
    "gui_settings_section_channels": "通知通道",
    "gui_settings_section_display": "介面與報表",
    "gui_settings_section_security": "安全",
}


def test_en_keys_present_with_expected_values():
    en = json.loads(EN.read_text(encoding="utf-8"))
    for k, v in EXPECTED_EN.items():
        assert en.get(k) == v, f"EN key {k!r} expected {v!r}, got {en.get(k)!r}"


def test_zh_keys_present_with_expected_values():
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    for k, v in EXPECTED_ZH.items():
        assert zh.get(k) == v, f"ZH key {k!r} expected {v!r}, got {zh.get(k)!r}"


def test_css_has_s_subpanel_rule():
    css = CSS.read_text(encoding="utf-8")
    # Default = hidden; .active = shown
    assert ".s-subpanel {" in css or ".s-subpanel{" in css, (
        "Expected .s-subpanel selector in app.css"
    )
    # The .active modifier shows the panel
    assert ".s-subpanel.active" in css, (
        "Expected .s-subpanel.active selector in app.css"
    )
