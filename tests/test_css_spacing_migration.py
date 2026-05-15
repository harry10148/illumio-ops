"""Spacing migration: previously magic-number declarations MUST now reference
var(--space-*). Tests check both individual hot-spot rules and the overall
magic-number count threshold."""
from __future__ import annotations

import re
from pathlib import Path


CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"


def _rule_body(css: str, selector_regex: str) -> str:
    m = re.search(selector_regex + r"([^}]*)\}", css, flags=re.DOTALL)
    return m.group(1) if m else ""


def test_card_label_margin_uses_space_token():
    body = _rule_body(CSS.read_text(encoding="utf-8"), r"\.card\s+\.label\s*\{")
    assert "var(--space-" in body, (
        f".card .label should use a --space-* token for margin-bottom, got: {body!r}"
    )


def test_modal_content_padding_uses_space_token():
    """`.modal-content` padding should use a --space-* token."""
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"\.modal-content\s*\{([^}]*)\}", css, flags=re.DOTALL)
    if m:
        body = m.group(1)
        assert "var(--space-" in body, (
            f".modal-content padding should use a --space-* token, got: {body!r}"
        )


def test_section_card_margin_uses_space_token():
    """`.section` margin-bottom should use a --space-* token."""
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"\n\s*\.section\s*\{([^}]*)\}", css, flags=re.DOTALL)
    if m:
        body = m.group(1)
        assert "var(--space-" in body, (
            f".section margin should use --space-* token, got: {body!r}"
        )


def test_magic_number_spacing_count_reduced():
    """Count single-value numeric margin/padding declarations. After Task 2,
    this count should be substantially lower (we're migrating ~20+ instances)."""
    css = CSS.read_text(encoding="utf-8")
    # Pattern: `margin-anything: 4px;` or `padding-anything: 16px;` — single value
    pat = re.compile(
        r"^\s*(margin|padding)(-[a-zA-Z]+)?:\s*[0-9]+(\.[0-9]+)?(px|rem|em)\s*;",
        re.MULTILINE,
    )
    count = len(pat.findall(css))
    # Pre-Task-2 baseline: ~50+ such declarations. After migration: should be < 35.
    # (Compound multi-value declarations are excluded by the regex; only single-value
    # are counted.)
    assert count < 35, (
        f"Single-value magic-number spacing count too high: {count} "
        f"(expected < 35 after Task 2 migration)"
    )
