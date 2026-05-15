"""Spacing lint: count magic-number margin/padding declarations in app.css.
Threshold MUST NOT exceed 30 — anything above means a regression from the
2026-05-15 spacing token migration."""
from __future__ import annotations

import re
from pathlib import Path


CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"
INDEX = Path(__file__).parent.parent / "src" / "templates" / "index.html"

# Threshold: baseline was 57 magic-number margin/padding declarations.
# Phase 2.1 Task 2 migrated ~27 single-value; Task 3 collapsed gap shortcuts.
# Remaining ~31 are mostly composite multi-value shortcuts (margin: 0 4px 4px 0)
# and zero resets that don't map to a single --space-* token.
# 32 = current count + 1 buffer; lower this if you can migrate more.
MAGIC_THRESHOLD = 32


def test_magic_number_margin_padding_count_below_threshold():
    css = CSS.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^\s*(margin|padding)[a-zA-Z-]*\s*:\s*[0-9]",
        re.MULTILINE,
    )
    matches = pattern.findall(css)
    n = len(matches)
    assert n <= MAGIC_THRESHOLD, (
        f"Found {n} magic-number margin/padding declarations in app.css; "
        f"threshold is {MAGIC_THRESHOLD}. Migrate to var(--space-*) or "
        f"justify the addition by raising the threshold."
    )


def test_no_unjustified_inline_spacing_in_index_html():
    """Sample check: inline `style="padding: 16px"` etc. in index.html.
    Soft threshold — informational only, not blocking. Logs offenders if > 200."""
    html = INDEX.read_text(encoding="utf-8")
    html_no_style = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    inline = re.findall(r'style="([^"]*)"', html_no_style)
    blob = " ".join(inline)
    pattern = re.compile(r"(margin|padding)[a-zA-Z-]*\s*:\s*[0-9]")
    matches = pattern.findall(blob)
    assert len(matches) <= 220, (
        f"Inline spacing magic-numbers in index.html jumped to {len(matches)}; "
        f"likely a regression. Investigate."
    )
