"""Spacing & typography token system: required tokens MUST exist in :root.
Per Improvement_Plan §A 2.1 — 4px grid spacing, 7-step type scale, 3-step radius,
3-step shadow."""
from __future__ import annotations

import re
from pathlib import Path


CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"

EXPECTED_SPACE = {
    "--space-1":  "4px",
    "--space-2":  "8px",
    "--space-3":  "12px",
    "--space-4":  "16px",
    "--space-5":  "20px",
    "--space-6":  "24px",
    "--space-8":  "32px",
    "--space-10": "40px",
    "--space-12": "48px",
}

EXPECTED_TEXT = {
    # font-size only; line-height handled separately if needed
    "--text-xs":   "12px",
    "--text-sm":   "13px",
    "--text-base": "14px",
    "--text-md":   "16px",
    "--text-lg":   "18px",
    "--text-xl":   "22px",
    "--text-2xl":  "28px",
}

EXPECTED_RADIUS = {
    "--radius-sm": "6px",
    "--radius-md": "10px",
    "--radius-lg": "14px",
}

EXPECTED_SHADOW = ["--shadow-1", "--shadow-2", "--shadow-3"]


def _root_body() -> str:
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r":root\s*\{([^}]*)\}", css, flags=re.DOTALL)
    assert m, ":root block not found in app.css"
    return m.group(1)


def test_space_tokens_defined_with_correct_values():
    body = _root_body()
    for tok, val in EXPECTED_SPACE.items():
        pat = re.compile(re.escape(tok) + r"\s*:\s*" + re.escape(val) + r"\s*;")
        assert pat.search(body), f"Token {tok!r} should be {val} in :root"


def test_text_tokens_defined_with_correct_values():
    body = _root_body()
    for tok, val in EXPECTED_TEXT.items():
        # The text-* tokens may optionally include line-height as `12px / 16px`
        # — we only require the font-size prefix to match.
        pat = re.compile(re.escape(tok) + r"\s*:\s*" + re.escape(val))
        assert pat.search(body), f"Token {tok!r} should start with {val}"


def test_radius_tokens_defined():
    body = _root_body()
    for tok, val in EXPECTED_RADIUS.items():
        pat = re.compile(re.escape(tok) + r"\s*:\s*" + re.escape(val) + r"\s*;")
        assert pat.search(body), f"Token {tok!r} should be {val}"


def test_shadow_tokens_defined():
    body = _root_body()
    for tok in EXPECTED_SHADOW:
        assert tok in body, f"Token {tok!r} should be defined in :root"
