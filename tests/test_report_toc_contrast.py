"""The table of contents must stay readable — restated for the v2 shell.

The old shell put the navigation in a dark cyan sidebar, so the guard asked for
white-ish ``nav a`` text on ``build_css()``'s output. The v2 shell prints the
TOC on the white sheet, so "white text" is now exactly the wrong answer; the
requirement that survives is the one underneath it — **enough contrast between
the link ink and the paper it sits on, at a size that is still legible**.

So this resolves ``.toc a``'s declared colour through ``:root`` and computes the
WCAG 2.1 contrast ratio rather than pattern-matching a hex value. That keeps the
guard able to fail: ``--text-2`` (the shipped value) measures 8.84:1 on
``--paper``, while dropping the link to the muted ``--text-3`` measures 4.36:1
and goes red on the 4.5 floor.
"""
from __future__ import annotations

import re

from src.report.exporters.report_shell import SHELL_CSS

# The screen half; the print block redeclares the size tokens in pt.
SCREEN_CSS = SHELL_CSS.split("@media print")[0]

MIN_CONTRAST = 4.5      # WCAG 2.1 AA, normal-size text
MIN_TOC_PX = 11.0       # see test_toc_link_size_is_still_legible


def _rule(css: str, selector: str, must_contain: str = "") -> str:
    """The rule block for ``selector``.

    A selector can be declared more than once (``.toc`` carries its grid column
    in one place and its own typography in another), so ``must_contain`` picks
    the one being asked about instead of silently taking the first.
    """
    rules = [m.group(0) for m in
             re.finditer(r"^" + re.escape(selector) + r"\s*\{[^}]*\}", css, re.MULTILINE)
             if must_contain in m.group(0)]
    assert rules, f"{selector} rule not found (must contain {must_contain!r})"
    assert len(rules) == 1, f"{selector} matched {len(rules)} rules: {rules!r}"
    return rules[0]


def _root_tokens() -> dict[str, str]:
    block = _rule(SCREEN_CSS, ":root")
    return {k: v.strip() for k, v in re.findall(r"(--[\w-]+):\s*([^;]+);", block)}


def _resolve(value: str) -> str:
    """Resolve one level of ``var(--token)`` against ``:root``."""
    tokens = _root_tokens()
    m = re.fullmatch(r"var\((--[\w-]+)\)", value.strip())
    if m:
        assert m.group(1) in tokens, f"{m.group(1)} is not declared on :root"
        return tokens[m.group(1)].strip()
    return value.strip()


def _declared(rule: str, prop: str) -> str:
    m = re.search(rf"(?<![\w-]){re.escape(prop)}:\s*([^;]+);", rule)
    assert m, f"{prop} not declared in: {rule!r}"
    return m.group(1).strip()


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    assert len(h) == 6, f"expected a 6-digit hex colour, got {hex_colour!r}"
    channels = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_toc_link_ink_has_enough_contrast_on_the_sheet():
    paper = _resolve("var(--paper)")
    ink = _resolve(_declared(_rule(SCREEN_CSS, ".toc a"), "color"))
    ratio = _contrast(ink, paper)
    assert ratio >= MIN_CONTRAST, (
        f".toc a colour {ink} on {paper} is {ratio:.2f}:1, below {MIN_CONTRAST}:1")


def test_toc_hover_ink_has_enough_contrast_on_the_sheet():
    """Hover is not decoration here — it is the only affordance telling the
    reader an entry is a link, so it has to clear the same floor."""
    paper = _resolve("var(--paper)")
    ink = _resolve(_declared(_rule(SCREEN_CSS, r".toc a:hover"), "color"))
    ratio = _contrast(ink, paper)
    assert ratio >= MIN_CONTRAST, (
        f".toc a:hover colour {ink} on {paper} is {ratio:.2f}:1, "
        f"below {MIN_CONTRAST}:1")


def test_toc_heading_is_visually_distinguished_from_its_entries():
    """Was ``.nav-brand``: the TOC needs a heading that does not read as another
    entry, or the first chapter looks like it is called "CONTENTS"."""
    rule = _rule(SCREEN_CSS, r".toc h2")
    assert "font-weight" in rule
    assert "text-transform: uppercase" in rule
    assert "letter-spacing" in rule
    assert _declared(rule, "font-family") == "var(--font-mono)"


def test_toc_link_size_is_still_legible():
    """The old floor was 13px on the dark sidebar. The v2 shell deliberately
    sets the whole TOC one step down from body copy (``.toc`` declares
    ``font-size: var(--fs-body)``), so the shipped size is 11.5px, not 13px —
    recorded as a design decision, not a regression, and the floor is set below
    it rather than the test being deleted. It still discriminates: the next
    token down, ``--fs-mini`` (10.5px), fails.
    """
    size = _resolve(_declared(_rule(SCREEN_CSS, ".toc", "font-size"), "font-size"))
    px = float(re.fullmatch(r"([\d.]+)px", size).group(1))
    assert px >= MIN_TOC_PX, f".toc font-size {px}px < {MIN_TOC_PX}px"
    # And nothing shrinks it again further down the cascade.
    link_rule = _rule(SCREEN_CSS, ".toc a")
    assert "font-size" not in link_rule, (
        "`.toc a` now overrides the TOC font size; this guard only measures "
        f"`.toc`: {link_rule!r}")
