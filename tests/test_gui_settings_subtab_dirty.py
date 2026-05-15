"""Dirty-tracking helpers exist and the save button label updates from them."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent
JS = ROOT / "src" / "static" / "js" / "settings.js"


def test_dirty_set_module_var():
    js = JS.read_text(encoding="utf-8")
    assert "_settingsDirty" in js, (
        "Expected a module-level _settingsDirty Set/object to track dirty sub-tabs"
    )


def test_mark_dirty_helper_exists():
    js = JS.read_text(encoding="utf-8")
    assert "function _markSettingsDirty" in js, (
        "Expected _markSettingsDirty(which) helper"
    )


def test_reset_dirty_helper_exists():
    js = JS.read_text(encoding="utf-8")
    assert "function _resetSettingsDirty" in js, (
        "Expected _resetSettingsDirty() helper to clear state after save"
    )


def test_wire_dirty_tracking_helper_exists():
    js = JS.read_text(encoding="utf-8")
    assert "function _wireSettingsDirtyTracking" in js, (
        "Expected _wireSettingsDirtyTracking() helper to attach listeners"
    )


def test_update_save_button_label_uses_i18n_templates():
    js = JS.read_text(encoding="utf-8")
    assert "function _updateSaveButtonLabel" in js
    assert "gui_settings_save_one" in js, (
        "Save label should use gui_settings_save_one when single tab dirty"
    )
    assert "gui_settings_save_many" in js, (
        "Save label should use gui_settings_save_many when 2+ tabs dirty"
    )
    assert "s-save-label" in js, (
        "Save label updater must target #s-save-label span"
    )


def test_save_settings_calls_reset_after_post():
    js = JS.read_text(encoding="utf-8")
    # The reset call appears somewhere inside saveSettings()
    start = js.index("async function saveSettings()")
    # Tolerant tail anchor — accept either the section banner or end-of-file
    candidates = [
        "/* ─── PCE Profile Management",
        "/* ─── PCE Profile",
        "function activatePceProfile",
    ]
    end = len(js)
    for c in candidates:
        idx = js.find(c, start)
        if idx != -1:
            end = idx
            break
    body = js[start:end]
    assert "_resetSettingsDirty()" in body, (
        "saveSettings() must call _resetSettingsDirty() after successful save"
    )
