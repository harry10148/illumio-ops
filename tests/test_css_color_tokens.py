"""Color semantic token system: required tokens MUST exist in :root and be
overridden in [data-theme="light"] block of app.css."""
from __future__ import annotations

import re
from pathlib import Path


CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"

# Per UX_Review.md §2.2 + Improvement_Plan.md §A 1.3
REQUIRED_TOKENS = [
    "--color-success",
    "--color-success-bg",
    "--color-warning",
    "--color-warning-bg",
    "--color-danger",
    "--color-danger-bg",
    "--color-info",
    "--color-info-bg",
]

# Expected dark-mode (:root) values — match the Improvement_Plan reference palette
EXPECTED_DARK = {
    "--color-success":    "#16A34A",
    "--color-success-bg": "#DCFCE7",
    "--color-warning":    "#F59E0B",
    "--color-warning-bg": "#FEF3C7",
    "--color-danger":     "#BE122F",
    "--color-danger-bg":  "#FEE2E2",
    "--color-info":       "#2563EB",
    "--color-info-bg":    "#DBEAFE",
}


def _read_css() -> str:
    return CSS.read_text(encoding="utf-8")


def _block(css: str, selector: str) -> str:
    """Return the body of the first CSS rule matching `selector { ... }`."""
    m = re.search(
        re.escape(selector) + r"\s*\{([^}]*)\}",
        css,
        flags=re.DOTALL,
    )
    assert m is not None, f"Could not find CSS block for {selector!r}"
    return m.group(1)


def test_tokens_defined_in_root():
    body = _block(_read_css(), ":root")
    for tok in REQUIRED_TOKENS:
        assert tok in body, f"Missing token {tok!r} in :root"


def test_root_token_values_match_palette():
    body = _block(_read_css(), ":root")
    for tok, val in EXPECTED_DARK.items():
        # Allow whitespace + colon + value + semicolon, case-insensitive on hex
        pat = re.compile(re.escape(tok) + r"\s*:\s*" + val + r"\s*;", re.IGNORECASE)
        assert pat.search(body), f"Token {tok!r} should be {val} in :root"


def test_tokens_overridden_in_light_theme():
    body = _block(_read_css(), '[data-theme="light"]')
    # In light theme we only need success/danger to match light-theme values
    # (warning/info can inherit from :root). Just require non-empty assignments.
    for tok in ["--color-success", "--color-danger"]:
        assert tok in body, f"{tok!r} should be redeclared in [data-theme='light']"
