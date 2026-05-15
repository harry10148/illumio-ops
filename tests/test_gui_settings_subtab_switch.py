"""switchSettingsTab() exists, toggles the right elements, persists to URL,
and init() reads stab param on page load."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent
SETTINGS_JS = ROOT / "src" / "static" / "js" / "settings.js"
UTILS_JS = ROOT / "src" / "static" / "js" / "utils.js"


def test_switch_settings_tab_function_defined():
    js = SETTINGS_JS.read_text(encoding="utf-8")
    assert "function switchSettingsTab" in js, (
        "Expected switchSettingsTab(which) function in settings.js"
    )


def test_switch_toggles_active_class_on_button_and_panel():
    js = SETTINGS_JS.read_text(encoding="utf-8")
    # Button id pattern: sbtn-<which>; panel id pattern: settings-<which>
    assert "'sbtn-' +" in js or '"sbtn-" +' in js, (
        "switchSettingsTab must compute button id as 'sbtn-' + which"
    )
    assert "'settings-' +" in js or '"settings-" +' in js, (
        "switchSettingsTab must compute panel id as 'settings-' + which"
    )
    # Active class manipulation
    assert "classList.add('active')" in js
    assert "classList.remove('active')" in js


def test_switch_writes_stab_url_param():
    js = SETTINGS_JS.read_text(encoding="utf-8")
    assert "updateUrlState('stab'" in js, (
        "switchSettingsTab must call updateUrlState('stab', which) for deep-linking"
    )


def test_init_reads_stab_param():
    js = UTILS_JS.read_text(encoding="utf-8")
    # init() in utils.js around line 314-328 must pick up stab param
    assert "stab" in js, "init() must reference 'stab' URL parameter"
    assert "switchSettingsTab" in js, (
        "init() must call switchSettingsTab(stab, false) when stab present"
    )


def test_valid_settings_tabs_listed():
    js = UTILS_JS.read_text(encoding="utf-8")
    for tab in ("pce", "channels", "display", "security"):
        assert f"'{tab}'" in js or f'"{tab}"' in js, (
            f"init() should whitelist sub-tab {tab!r}"
        )
