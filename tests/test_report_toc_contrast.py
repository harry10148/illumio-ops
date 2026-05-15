"""TOC sidebar must use high-contrast text on dark cyan background."""
from __future__ import annotations

import re

from src.report.exporters.report_css import build_css


def test_nav_link_color_is_high_contrast():
    css = build_css("traffic")
    # nav a should target white or near-white; --slate-20 was insufficient
    m = re.search(r"^\s*nav a \{[^}]*\}", css, re.MULTILINE)
    assert m, "nav a base rule not found"
    rule = m.group(0)
    color_m = re.search(r"color:\s*(#[0-9A-Fa-f]+|var\(--[\w-]+\))", rule)
    assert color_m, f"nav a color not found: {rule!r}"
    color = color_m.group(1).lower()
    assert color in {"#fff", "#ffffff", "var(--slate-00)", "var(--white)"} or color.startswith("#fff"), (
        f"nav a color must be white-ish for contrast; got: {color!r}"
    )


def test_nav_brand_class_styled():
    css = build_css("traffic")
    assert ".nav-brand" in css, ".nav-brand rule must exist"
    nav_brand_idx = css.find(".nav-brand")
    block = css[nav_brand_idx:nav_brand_idx + 400]
    assert "font-weight" in block
    assert "border-bottom" in block or "padding" in block


def test_nav_a_font_size_is_at_least_13px():
    css = build_css("traffic")
    m = re.search(r"^\s*nav a \{[^}]*\}", css, re.MULTILINE)
    assert m, "nav a rule not found"
    size_m = re.search(r"font-size:\s*(\d+)px", m.group(0))
    assert size_m, f"nav a font-size not found: {m.group(0)!r}"
    assert int(size_m.group(1)) >= 13, f"nav a font-size {size_m.group(1)}px < 13px"
