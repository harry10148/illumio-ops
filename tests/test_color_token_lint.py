"""Lint: semantic-meaning hex colors MUST live inside :root / [data-theme=...]
token blocks of app.css and MUST NOT leak into inline styles of index.html.

Allowed exceptions:
 - .rs-badge-* legacy badges in index.html (will be migrated separately)
 - login.html (standalone styling — separate token scope)
 - dashboard.js inline badge rendering (Phase 2 component extraction)
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).parent.parent
CSS = ROOT / "src" / "static" / "css" / "app.css"
INDEX = ROOT / "src" / "templates" / "index.html"

# Hex values that carry semantic meaning under the new token system.
SEMANTIC_HEX = {
    "#16A34A": "--color-success",
    "#DCFCE7": "--color-success-bg",
    "#F59E0B": "--color-warning",
    "#FEF3C7": "--color-warning-bg",
    "#BE122F": "--color-danger",
    "#FEE2E2": "--color-danger-bg",
    "#2563EB": "--color-info",
    "#DBEAFE": "--color-info-bg",
}


def _strip_token_blocks(css: str) -> str:
    """Remove :root { ... } and [data-theme="..."] { ... } blocks; what remains
    is 'consumer' CSS where semantic hex MUST NOT appear (use var() instead)."""
    css = re.sub(r":root\s*\{[^}]*\}", "", css, flags=re.DOTALL)
    css = re.sub(r'\[data-theme="[^"]+"\]\s*\{[^}]*\}', "", css, flags=re.DOTALL)
    return css


def test_no_semantic_hex_in_css_consumers():
    css = CSS.read_text(encoding="utf-8")
    consumers = _strip_token_blocks(css)
    for hex_val, token in SEMANTIC_HEX.items():
        # case-insensitive search
        if re.search(re.escape(hex_val), consumers, re.IGNORECASE):
            raise AssertionError(
                f"Hard-coded semantic hex {hex_val!r} found in app.css outside "
                f"token blocks — use var({token}) instead."
            )


def test_no_semantic_hex_in_index_html_inline():
    """Inline style attrs in index.html MUST NOT contain semantic hex values.
    Only check style="..." occurrences; <style> tags handled by app.css test."""
    html = INDEX.read_text(encoding="utf-8")
    # Strip <style>...</style> blocks
    html_no_style = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    inline_styles = re.findall(r'style="([^"]*)"', html_no_style)
    blob = " ".join(inline_styles)
    for hex_val, token in SEMANTIC_HEX.items():
        if re.search(re.escape(hex_val), blob, re.IGNORECASE):
            raise AssertionError(
                f"Hard-coded {hex_val!r} found in inline style of index.html — "
                f"use var({token}) instead."
            )
