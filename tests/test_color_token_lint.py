"""Lint: colour literals MUST live in css/v2/tokens.css and nowhere else.

Phase 2A Task 11 retargeted this file. It used to police the LEGACY
src/static/css/app.css + src/templates/index.html, allowing a list of
exceptions ("dashboard.js inline badge rendering", ".rs-badge-* legacy
badges", ...). Both of those files are gone, and the v2 frontend's rule is
stricter with no exceptions: `tokens.css` is the only file in the product
that may name a colour, every other stylesheet and every .mjs uses
`var(--token)`. Measured against the tree at the time of writing, that rule
already held everywhere — this file is what stops it drifting back.
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).parent.parent
CSS_DIR = ROOT / "src" / "static" / "css" / "v2"
JS_DIR = ROOT / "src" / "static" / "js" / "v2"
TOKENS = CSS_DIR / "tokens.css"

# #abc, #aabbcc, #aabbccdd — and the functional colour notations, which are
# the obvious way to smuggle a literal past a hex-only check.
_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_FUNC_RE = re.compile(r"\b(?:rgba?|hsla?|color|lab|lch|oklab|oklch)\s*\(")


def _consumer_css() -> list[tuple[Path, str]]:
    return [(p, p.read_text(encoding="utf-8"))
            for p in sorted(CSS_DIR.glob("*.css")) if p != TOKENS]


def test_tokens_file_is_the_one_that_names_colours():
    """Sanity: the file this lint exempts must actually hold the palette.

    Without this, deleting every colour from tokens.css would leave the
    assertions below trivially satisfied.
    """
    assert TOKENS.exists(), TOKENS
    assert len(_HEX_RE.findall(TOKENS.read_text(encoding="utf-8"))) >= 40


def test_no_colour_literals_in_consumer_stylesheets():
    offenders = []
    for path, css in _consumer_css():
        for m in _HEX_RE.finditer(css):
            offenders.append(f"{path.name}: {m.group(0)}")
        for m in _FUNC_RE.finditer(css):
            offenders.append(f"{path.name}: {m.group(0)}...")
    assert not offenders, (
        "colour literals outside css/v2/tokens.css — use var(--token):\n  "
        + "\n  ".join(offenders)
    )


def test_no_colour_literals_in_v2_javascript():
    """The same rule for JS: no component may hardcode a colour.

    charts and tone chips read their colours from CSS custom properties, so
    a literal here is always a bug (and always invisible in the other theme).
    """
    offenders = []
    for path in sorted(JS_DIR.rglob("*.mjs")) + sorted(JS_DIR.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        # Strip // and /* */ comments — several modules quote the legacy
        # palette in their porting notes, which is documentation, not style.
        stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        stripped = re.sub(r"^\s*//.*$", "", stripped, flags=re.MULTILINE)
        for m in _HEX_RE.finditer(stripped):
            offenders.append(f"{path.relative_to(JS_DIR)}: {m.group(0)}")
    assert not offenders, (
        "colour literals in v2 JavaScript — read the token instead:\n  "
        + "\n  ".join(offenders)
    )
