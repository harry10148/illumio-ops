"""Data Table unified class with density attribute."""
from __future__ import annotations

import re
from pathlib import Path

from tests._inline_scanner import count_inline_styled_tables


CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"


def test_data_table_class_exists():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"^\s*\.data-table\s*[,{]", css, re.MULTILINE), (
        "Expected `.data-table` class in app.css"
    )


def test_data_table_density_compact():
    css = CSS.read_text(encoding="utf-8")
    pattern = r'\.data-table\[data-density=["\']compact["\']\]'
    assert re.search(pattern, css), "Missing compact density variant"


def test_data_table_density_comfortable():
    css = CSS.read_text(encoding="utf-8")
    pattern = r'\.data-table\[data-density=["\']comfortable["\']\]'
    assert re.search(pattern, css), "Missing comfortable density variant"


def test_data_table_sortable_indicator():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r'\.data-table\s+th\[aria-sort', css) or re.search(
        r'\.data-table\s+th\.sortable', css
    ), "Missing sortable column indicator (th[aria-sort] or th.sortable)"


def test_styled_table_inline_count_decreased():
    # Baseline = 15; after migrating 5 in Task 6.B -> <=10
    assert count_inline_styled_tables() <= 10
