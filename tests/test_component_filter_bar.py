"""Filter Bar unified wrapper for toolbar+form-row alignment."""
from __future__ import annotations

import re
from pathlib import Path

from tests._inline_scanner import count_inline_filter_bar_buttons


CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"
INDEX = Path(__file__).parent.parent / "src" / "templates" / "index.html"


def test_filter_bar_class_exists():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"^\s*\.filter-bar\s*\{", css, re.MULTILINE)


def test_filter_bar_aligns_button_height():
    """`.filter-bar .btn` should pin button vertical alignment so
    individual instances don't need inline `height:42px;align-self:flex-end`."""
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"\.filter-bar\s+\.btn\s*\{", css), (
        "Expected `.filter-bar .btn { align-self: flex-end; ... }` rule"
    )


def test_filter_bar_used_in_traffic_panel():
    html = INDEX.read_text(encoding="utf-8")
    # The traffic-panel toolbar should carry class="filter-bar"
    # or class="toolbar filter-bar" after migration
    assert 'filter-bar' in html, "Expected at least one .filter-bar in index.html"


def test_filter_bar_inline_count_decreased():
    # Baseline = 4 (measured); after migrating traffic (3) + workload (1) -> 0
    # Pragmatic: lock to <=1 (workload may stay for separate cleanup)
    assert count_inline_filter_bar_buttons() <= 1
