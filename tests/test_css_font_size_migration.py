"""Font-size declarations in core rules MUST reference --text-* tokens."""
from __future__ import annotations

import re
from pathlib import Path


CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"


def _rule_body(css: str, selector_pattern: str) -> str | None:
    m = re.search(selector_pattern + r"\s*\{([^}]*)\}", css, flags=re.DOTALL)
    return m.group(1) if m else None


def test_card_label_font_size_uses_text_token():
    body = _rule_body(CSS.read_text(encoding="utf-8"), r"\n\s*\.card\s+\.label")
    assert body is not None, ".card .label rule not found"
    m = re.search(r"font-size\s*:\s*([^;]+);", body)
    if m:
        val = m.group(1).strip()
        assert val.startswith("var(--text"), (
            f".card .label font-size should use var(--text-*), got: {val!r}"
        )


def test_minimum_text_token_usage_count():
    """At least 10 font-size declarations should reference var(--text-*)."""
    css = CSS.read_text(encoding="utf-8")
    matches_var = len(re.findall(r"font-size\s*:\s*var\(--text-", css))
    assert matches_var >= 10, (
        f"Only {matches_var} font-size declarations use --text-* token; "
        f"expected >= 10 after Phase 2.1 Task 6 migration."
    )
