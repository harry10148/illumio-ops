"""Empty State unified component with icon / title / description / action slots."""
from __future__ import annotations

import json
import re
from pathlib import Path

from tests._inline_scanner import count_inline_empty_states


CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"
EN = Path(__file__).parent.parent / "src" / "i18n_en.json"
ZH = Path(__file__).parent.parent / "src" / "i18n_zh_TW.json"


def test_empty_state_class_exists():
    css = CSS.read_text(encoding="utf-8")
    # already exists; this test guards against accidental removal
    assert re.search(r"^\s*\.empty-state\s*\{", css, re.MULTILINE)


def test_empty_state_has_action_slot():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"\.empty-state\s+\.empty-state-action\s*\{", css) or re.search(
        r"\.empty-state-action\s*\{", css
    ), "Expected `.empty-state-action { ... }` rule"


def test_empty_state_has_title_and_description_rules():
    css = CSS.read_text(encoding="utf-8")
    # already defined: .empty-state h3 and .empty-state p
    assert re.search(r"\.empty-state\s+h3", css)
    assert re.search(r"\.empty-state\s+p", css)


def test_i18n_default_titles_exist():
    en = json.loads(EN.read_text(encoding="utf-8"))
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    assert en.get("gui_empty_state_default_title") == "Nothing here yet"
    assert zh.get("gui_empty_state_default_title") == "目前沒有資料"


def test_empty_state_inline_count_decreased():
    # Baseline = 44; pragmatic Task 4 migrates 3 index.html instances.
    # Threshold locked at 41.
    assert count_inline_empty_states() <= 41
