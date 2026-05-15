"""Section Card unified wrapper for settings/integrations sub-sections."""
from __future__ import annotations

import re
from pathlib import Path

from tests._inline_scanner import count_inline_fieldset_sections


CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"
INDEX = Path(__file__).parent.parent / "src" / "templates" / "index.html"


def test_settings_card_class_exists():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"^\s*\.settings-card\s*\{", css, re.MULTILINE)


def test_settings_card_has_header_slot():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"\.settings-card-header\s*\{", css)


def test_settings_card_has_body_slot():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"\.settings-card-body\s*\{", css)


def test_settings_card_has_footer_slot():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"\.settings-card-footer\s*\{", css)


def test_settings_card_used_in_index_html():
    html = INDEX.read_text(encoding="utf-8")
    count = len(re.findall(r"settings-card", html))
    assert count >= 1, f"Expected 1+ `.settings-card` markers in index.html, got {count}"


def test_fieldset_inline_count_decreased():
    # Baseline = 4 (measured); after migrating 2 in Task 5.B -> <=2
    assert count_inline_fieldset_sections() <= 2
