"""The v2 design-token scales must exist, with the values the stylesheets and
components assume, and the consumers must actually reference them.

Phase 2A Task 11 retargeted this file, and folded four sibling files into it
when the LEGACY src/static/css/app.css was deleted:

  test_css_space_type_tokens.py       (this file)  --space-*/--text-*/--radius-*/--shadow-*
  test_radius_shadow_tokens_available.py           --radius-sm/md/lg, --shadow-1/2/3
  test_css_font_size_migration.py                  font-size must be var(--text-*)
  test_css_grid_gap_consistency.py                 gap must be var(--space-*)
  test_css_spacing_migration.py                    margin/padding must be var(--space-*)

The other four are deleted: every one of them asserted the legacy scale's
literal values (--space-1: 4px, --text-base: 14px, --radius-md: 10px), and
the v2 scale is a different, denser one (--space-1: 2px, --fs-ui: 13px,
--radius-m: 3px) with different names. Repointing them one by one would have
produced four files asserting four slices of the same table; folding them
into one keeps every question they asked:

  "the scales exist with the right values"  -> the four test_*_scale tests
  "consumers reference the scale"           -> test_consumers_use_the_scales
  "magic numbers stay near zero"            -> tests/test_css_spacing_lint.py
"""
from __future__ import annotations

import re
from pathlib import Path


CSS_DIR = Path(__file__).parent.parent / "src" / "static" / "css" / "v2"
TOKENS = CSS_DIR / "tokens.css"

EXPECTED_SPACE = {
    "--space-1": "2px", "--space-2": "4px", "--space-3": "6px", "--space-4": "8px",
    "--space-5": "12px", "--space-6": "16px", "--space-7": "24px", "--space-8": "32px",
}
EXPECTED_FS = {
    "--fs-micro": "9.5px", "--fs-mini": "10.5px", "--fs-body": "11.5px",
    "--fs-ui": "13px", "--fs-lead": "15px", "--fs-num": "19px",
    "--fs-display": "30px",
}
EXPECTED_RADIUS = {"--radius-s": "2px", "--radius-m": "3px", "--radius-l": "6px"}
EXPECTED_SHADOW = ["--shadow-1", "--shadow-2"]


def _tokens_text() -> str:
    """Comments stripped: the header documents the families in brace shorthand
    (`--space-{1..8}`), which would confuse any brace-based parsing."""
    return re.sub(r"/\*.*?\*/", "", TOKENS.read_text(encoding="utf-8"), flags=re.DOTALL)


def _assert_scale(expected: dict[str, str]) -> None:
    text = _tokens_text()
    for tok, val in expected.items():
        pat = re.compile(re.escape(tok) + r"\s*:\s*" + re.escape(val) + r"\s*;")
        assert pat.search(text), f"Token {tok!r} should be {val}"


def test_space_scale():
    _assert_scale(EXPECTED_SPACE)


def test_font_size_scale():
    _assert_scale(EXPECTED_FS)


def test_radius_scale():
    _assert_scale(EXPECTED_RADIUS)


def test_shadow_scale():
    text = _tokens_text()
    for tok in EXPECTED_SHADOW:
        assert re.search(re.escape(tok) + r"\s*:\s*[^;]+;", text), (
            f"Token {tok!r} should be defined"
        )


def test_consumers_use_the_scales():
    """Every font-size / gap / margin / padding / border-radius / box-shadow
    declaration in the consumer stylesheets should read a token.

    Not "all of them": tests/test_css_spacing_lint.py owns the small allowance
    for component-internal values that do not land on a step. This asserts the
    other direction — that the scales are the norm, not decoration nobody uses.
    """
    consumers = "".join(
        p.read_text(encoding="utf-8")
        for p in sorted(CSS_DIR.glob("*.css")) if p != TOKENS
    )
    assert consumers.count("var(--fs-") >= 40, consumers.count("var(--fs-")
    assert consumers.count("var(--space-") >= 100, consumers.count("var(--space-")
    assert consumers.count("var(--radius-") >= 10, consumers.count("var(--radius-")
    assert consumers.count("var(--shadow-") >= 3, consumers.count("var(--shadow-")


# The one literal font-size in the product, allowed by name so a SECOND one
# cannot slip in beside it: the posture gauge's hero numeral (.gauge .num,
# components.css) is deliberately larger than --fs-display's 30px top step and
# has no other consumer, so promoting it to a token would add a scale step
# nothing else could use. Every other declaration must read the scale.
_ALLOWED_LITERAL_FONT_SIZES = {"components.css: 44px"}


def test_no_font_size_declaration_bypasses_the_scale():
    """The one rule test_css_font_size_migration.py enforced, kept whole:
    a literal font-size is a size nobody can rescale with the density switch."""
    offenders = []
    for path in sorted(CSS_DIR.glob("*.css")):
        if path == TOKENS:
            continue
        for m in re.finditer(r"font-size\s*:\s*([^;]+);", path.read_text(encoding="utf-8")):
            value = m.group(1).strip()
            if not value.startswith("var(--"):
                offenders.append(f"{path.name}: {value}")
    assert set(offenders) == _ALLOWED_LITERAL_FONT_SIZES, (
        f"literal font-size declarations changed: {sorted(offenders)} != "
        f"{sorted(_ALLOWED_LITERAL_FONT_SIZES)}"
    )
