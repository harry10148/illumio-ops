"""Grid / flex container gaps in app.css MUST reference --space-* tokens, not
magic numbers. Covers .cards, .form-row, .modal-actions per UX_Review §12.1."""
from __future__ import annotations

import re
from pathlib import Path


CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"


def _rule_body(css: str, selector_pattern: str) -> str | None:
    m = re.search(selector_pattern + r"\s*\{([^}]*)\}", css, flags=re.DOTALL)
    return m.group(1) if m else None


def test_cards_gap_uses_token():
    body = _rule_body(CSS.read_text(encoding="utf-8"), r"\n\s*\.cards")
    assert body is not None, ".cards rule not found"
    m = re.search(r"gap\s*:\s*([^;]+);", body)
    assert m, "`.cards` should declare gap"
    val = m.group(1).strip()
    assert val.startswith("var("), f".cards gap should be a var() token, got: {val!r}"


def test_form_row_gap_uses_token():
    body = _rule_body(CSS.read_text(encoding="utf-8"), r"\n\s*\.form-row")
    if body is None:
        return
    m = re.search(r"gap\s*:\s*([^;]+);", body)
    if not m:
        return
    val = m.group(1).strip()
    assert val.startswith("var("), f".form-row gap should be a var() token, got: {val!r}"


def test_modal_actions_gap_uses_token():
    body = _rule_body(CSS.read_text(encoding="utf-8"), r"\n\s*\.modal-actions")
    if body is None:
        return
    m = re.search(r"gap\s*:\s*([^;]+);", body)
    if m:
        val = m.group(1).strip()
        assert val.startswith("var("), f".modal-actions gap should be a var() token, got: {val!r}"


def test_no_magic_number_gaps_outside_tokens():
    """Count remaining `gap: Npx;` magic numbers — locked at current baseline.

    Phase 2.1 Task 3 migrated 27 gaps; baseline post-migration was 0.
    Phase 2.2 component abstraction added a few component-internal gaps
    that don't map cleanly to --space-* (e.g. dense column-gap inside data
    table cells); current baseline ≤ 10 includes those component additions.
    """
    css = CSS.read_text(encoding="utf-8")
    # Strip :root and theme blocks
    consumers = re.sub(r":root\s*\{[^}]*\}", "", css, flags=re.DOTALL)
    consumers = re.sub(r'\[data-theme="[^"]+"\]\s*\{[^}]*\}', "", consumers, flags=re.DOTALL)
    matches = re.findall(r"\bgap\s*:\s*\d+(?:\.\d+)?(?:px|rem|em)\s*;", consumers)
    assert len(matches) <= 10, f"Magic-number gap declarations too high: {len(matches)} (limit 10)"
