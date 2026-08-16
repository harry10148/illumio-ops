"""Colour semantic token system: the five tone families must exist in the
dark palette and be re-declared for the light theme.

Phase 2A Task 11 retargeted this file from the LEGACY src/static/css/app.css
(`--color-success` / `--color-danger` / ... with the palette hexes asserted
literally) to src/static/css/v2/tokens.css, which is the only stylesheet the
product still has that names a colour. The invariant is the same one, in the
v2 vocabulary: every semantic tone has a bg/fg pair, and a light-theme
reader gets a light-theme value rather than inheriting a dark one.

The literal hex values are deliberately NOT asserted any more. In the legacy
file they encoded an external reference palette that could drift silently; in
v2 the palette is this file, so asserting its own values against itself
proves nothing (an "assertion that cannot fail" — Phase 2A findings B1).
What can fail, and is what this checks, is a MISSING or unthemed token.
"""
from __future__ import annotations

import re
from pathlib import Path


CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "v2" / "tokens.css"

TONES = ["ok", "warn", "crit", "info", "neutral"]
# Every tone needs a fill and a text colour; `border` exists for the four
# non-neutral tones in the dark palette and is not required per-theme.
REQUIRED_SUFFIXES = ["bg", "fg"]


def _read_css() -> str:
    """tokens.css's header comment documents the token families in shorthand
    (`--tone-{ok,warn,...}-{bg,fg}`), i.e. it contains braces. Strip comments
    before any brace-matching or the very first block boundary is wrong."""
    return re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.DOTALL)


def _block(css: str, selector: str) -> str:
    """Return every CSS rule body whose selector list contains `selector`,
    concatenated.

    ALL of them, not the first: tokens.css opens with a `:root` block of
    typography/spacing and declares the palette in a SECOND, grouped
    `:root, [data-theme="dark"]` block. Taking only the first would have this
    file assert the palette against the type scale.
    """
    bodies = []
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css, flags=re.DOTALL):
        selectors = [s.strip() for s in m.group(1).split(",")]
        if selector in selectors:
            bodies.append(m.group(2))
    assert bodies, f"Could not find any CSS block for {selector!r}"
    return "\n".join(bodies)


def test_tone_tokens_defined_in_the_dark_palette():
    body = _block(_read_css(), '[data-theme="dark"]')
    missing = [
        f"--tone-{tone}-{suffix}"
        for tone in TONES for suffix in REQUIRED_SUFFIXES
        if f"--tone-{tone}-{suffix}" not in body
    ]
    assert not missing, f"missing tone tokens in the dark palette: {missing}"


def test_tone_tokens_overridden_in_light_theme():
    """A tone that keeps its dark value under [data-theme="light"] is
    unreadable there — that is the defect this guards."""
    dark = _block(_read_css(), '[data-theme="dark"]')
    light = _block(_read_css(), '[data-theme="light"]')

    def value(body: str, token: str) -> str | None:
        m = re.search(re.escape(token) + r"\s*:\s*([^;]+);", body)
        return m.group(1).strip().lower() if m else None

    for tone in TONES:
        for suffix in REQUIRED_SUFFIXES:
            token = f"--tone-{tone}-{suffix}"
            light_value = value(light, token)
            assert light_value, f"{token} is not re-declared in [data-theme='light']"
            assert light_value != value(dark, token), (
                f"{token} has the same value in both themes — one of them is wrong"
            )


def test_root_carries_the_default_palette():
    """`:root` alone (no data-theme attribute set) must still be painted:
    the shell's pre-paint bootstrap writes data-theme, but a page rendered
    before it runs, or with JS off, must not fall back to unstyled."""
    css = _read_css()
    body = _block(css, ":root")
    for tone in TONES:
        assert f"--tone-{tone}-bg" in body, tone
