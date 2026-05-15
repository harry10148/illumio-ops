"""Verify settings panel has 4 sub-tab navigation buttons and 4 panel
containers with the expected anchor ids."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).parent.parent
INDEX = ROOT / "src" / "templates" / "index.html"


def _settings_block() -> str:
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(
        r'<div class="panel" id="p-settings">(.*?)<!-- Rule Scheduler -->',
        html,
        flags=re.DOTALL,
    )
    assert m is not None, "#p-settings panel block not found"
    return m.group(1)


def test_sub_nav_has_four_buttons():
    block = _settings_block()
    for btn_id in ("sbtn-pce", "sbtn-channels", "sbtn-display", "sbtn-security"):
        assert f'id="{btn_id}"' in block, f"Missing sub-nav button id={btn_id!r}"


def test_sub_nav_uses_existing_classes():
    block = _settings_block()
    # Each sub-nav-btn carries class="sub-nav-btn" (active or not)
    matches = re.findall(r'class="sub-nav-btn[^"]*"', block)
    assert len(matches) >= 4, (
        f"Expected at least 4 .sub-nav-btn buttons in settings, got {len(matches)}"
    )


def test_sub_nav_dispatches_to_switchSettingsTab():
    block = _settings_block()
    for arg in ("pce", "channels", "display", "security"):
        assert (
            f'data-action="switchSettingsTab" data-args=\'["{arg}"]\'' in block
            or f"data-action=\"switchSettingsTab\" data-args='[\"{arg}\"]'" in block
        ), f"Missing data-action wiring for sub-tab {arg!r}"


def test_four_panel_containers_with_anchor_ids():
    block = _settings_block()
    for anchor in (
        "settings-pce",
        "settings-channels",
        "settings-display",
        "settings-security",
    ):
        assert f'id="{anchor}"' in block, f"Missing anchor id={anchor!r}"
    # The runtime-content containers — settings.js will inject HTML into these.
    for pid in (
        "s-panel-pce",
        "s-panel-channels",
        "s-panel-display",
        "s-panel-security",
    ):
        assert f'id="{pid}"' in block, f"Missing render target id={pid!r}"


def test_legacy_s_form_div_removed():
    """The old single-form container is replaced by 4 sub-panels.
    The id 's-form' must no longer appear inside #p-settings."""
    block = _settings_block()
    assert 'id="s-form"' not in block, (
        "Legacy <div id='s-form'> should be removed when sub-tabs are introduced"
    )


def test_save_button_still_present():
    block = _settings_block()
    assert 'data-action="saveSettings"' in block, (
        "Sticky save button (data-action=saveSettings) must remain"
    )
    # Save button label is dynamic — we expect a span with id we can update from JS
    assert 'id="s-save-label"' in block, (
        "Save button label span id='s-save-label' must exist for dynamic label"
    )
