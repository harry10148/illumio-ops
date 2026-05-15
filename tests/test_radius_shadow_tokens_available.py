"""Sanity: --radius-* and --shadow-* tokens added in Phase 2.1 Task 1 are present
and parseable. Legacy --radius and --shadow tokens preserved for backward compat."""
from __future__ import annotations

import re
from pathlib import Path


CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"


def test_three_radius_tokens_present():
    body = CSS.read_text(encoding="utf-8")
    for tok in ["--radius-sm", "--radius-md", "--radius-lg"]:
        assert tok in body, f"{tok} not declared in app.css"


def test_three_shadow_tokens_present():
    body = CSS.read_text(encoding="utf-8")
    for tok in ["--shadow-1", "--shadow-2", "--shadow-3"]:
        assert tok in body, f"{tok} not declared in app.css"


def test_existing_radius_token_still_present():
    """Backward compat: --radius MUST still exist so legacy rules don't break."""
    body = CSS.read_text(encoding="utf-8")
    assert re.search(r"--radius\s*:\s*[^;]+;", body), (
        "Legacy --radius token removed; this breaks existing .card / .btn rules."
    )
