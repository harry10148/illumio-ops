"""KPI Card unified class must exist with label / value / trend slots."""
from __future__ import annotations

import re
from pathlib import Path

from tests._inline_scanner import count_inline_kpi_cards


CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"


def test_kpi_card_class_exists():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"^\s*\.kpi-card\s*\{", css, re.MULTILINE), (
        "Expected `.kpi-card { ... }` rule in app.css"
    )


def test_kpi_card_has_label_slot():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"\.kpi-card\s+\.kpi-label\s*\{", css), (
        "Expected `.kpi-card .kpi-label { ... }` rule"
    )


def test_kpi_card_has_value_slot():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"\.kpi-card\s+\.kpi-value\s*\{", css), (
        "Expected `.kpi-card .kpi-value { ... }` rule"
    )


def test_kpi_card_has_trend_slot():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"\.kpi-card\s+\.kpi-trend\s*\{", css), (
        "Expected `.kpi-card .kpi-trend { ... }` rule"
    )


def test_kpi_inline_count_decreased():
    # Day-0 baseline = 4; after Task 1.B all 4 migrate -> expect <= 0
    assert count_inline_kpi_cards() <= 0
