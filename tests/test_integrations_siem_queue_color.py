"""SIEM Queue card: when totalFailed > 0 the 'failed' label & value MUST render
via var(--color-danger). The card-err / card-warn / card-ok border-left utility
classes MUST resolve through the semantic token layer."""
from __future__ import annotations

import re
from pathlib import Path


JS = Path(__file__).parent.parent / "src" / "static" / "js" / "integrations.js"
CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"


def test_buildovcards_failedcolor_uses_color_danger():
    js = JS.read_text(encoding="utf-8")
    m = re.search(r"var failedColor\s*=\s*([^;]+);", js)
    assert m, "`var failedColor = ...` not found in integrations.js"
    expr = m.group(1)
    assert "var(--color-danger)" in expr, (
        f"failedColor should reference var(--color-danger), got: {expr!r}"
    )


def test_card_err_border_uses_color_danger():
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"\.card\.card-err\s*\{([^}]*)\}", css)
    assert m, ".card.card-err rule not found"
    assert "var(--color-danger)" in m.group(1), (
        f"`.card.card-err` border-left should use var(--color-danger): {m.group(1)!r}"
    )


def test_card_warn_border_uses_color_warning():
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"\.card\.card-warn\s*\{([^}]*)\}", css)
    assert m, ".card.card-warn rule not found"
    assert "var(--color-warning)" in m.group(1)


def test_card_ok_border_uses_color_success():
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"\.card\.card-ok\s*\{([^}]*)\}", css)
    assert m, ".card.card-ok rule not found"
    assert "var(--color-success)" in m.group(1)
