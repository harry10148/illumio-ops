"""Status Pill unified class with data-status attribute selector."""
from __future__ import annotations

import json
import re
from pathlib import Path

from tests._inline_scanner import count_inline_status_pills


CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"
EN = Path(__file__).parent.parent / "src" / "i18n_en.json"
ZH = Path(__file__).parent.parent / "src" / "i18n_zh_TW.json"


def test_status_pill_base_class():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"^\s*\.status-pill\s*\{", css, re.MULTILINE)


def test_status_pill_has_all_status_variants():
    css = CSS.read_text(encoding="utf-8")
    for status in ("success", "warning", "danger", "info", "neutral"):
        pattern = rf'\.status-pill\[data-status=["\']{status}["\']\]'
        assert re.search(pattern, css), f"Missing variant: {status}"


def test_i18n_a11y_keys_exist_en():
    en = json.loads(EN.read_text(encoding="utf-8"))
    for status in ("success", "warning", "danger", "info", "neutral"):
        key = f"gui_status_pill_label_{status}"
        assert key in en, f"Missing en key: {key}"


def test_i18n_a11y_keys_exist_zh():
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    for status in ("success", "warning", "danger", "info", "neutral"):
        key = f"gui_status_pill_label_{status}"
        assert key in zh, f"Missing zh key: {key}"


def test_status_pill_inline_count_decreased():
    # Baseline = 5; expect threshold to be reduced after migration
    # (Task 2 migrates 2-3 of 5 instances per pragmatism rule;
    # remaining 2-3 in bandwidth/uncovered tables stay for Phase 1.)
    assert count_inline_status_pills() <= 3
