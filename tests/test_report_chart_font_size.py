"""Chart tick fonts must be at least 12px (印刷可讀性)."""
from __future__ import annotations

import re
from pathlib import Path

CR = Path("src/report/exporters/chart_renderer.py").read_text()


def test_tickfont_sizes_at_least_12():
    sizes = [int(m.group(1)) for m in re.finditer(
        r"(?:tickfont|textfont)=dict\(\s*(?:family=[^,]+,\s*)?size=(\d+)", CR)]
    assert sizes, "no tickfont/textfont sizes found"
    assert all(s >= 12 for s in sizes), f"some chart fonts < 12px: {sizes}"


def test_chart_title_font_at_least_15():
    m = re.search(r"title_font=dict\(\s*size=(\d+)", CR)
    assert m, "title_font size not found"
    assert int(m.group(1)) >= 15
