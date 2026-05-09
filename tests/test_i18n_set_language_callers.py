"""Phase 3 policy: set_language() is bootstrap-only.

Lint test that scans src/ for set_language() callers and rejects any
that aren't in the explicit allowlist. New callers must justify their
addition by editing this file.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# Files allowed to call set_language(). Keep this list short and add
# justification when extending it.
ALLOWED_CALLERS: set[Path] = {
    # Function definition + module re-export.
    SRC / "i18n" / "engine.py",
    SRC / "i18n" / "__init__.py",
    # Bootstrap from persisted config.json — sets process language at
    # ConfigManager load time so CLI entrypoints reflect user preference.
    SRC / "config.py",
}


def test_no_new_set_language_callers() -> None:
    pattern = re.compile(r"\bset_language\s*\(")
    new_violators: list[str] = []
    for py in SRC.rglob("*.py"):
        if py in ALLOWED_CALLERS:
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        # Skip files that only mention set_language in comments/docstrings.
        # The pattern matches actual call syntax.
        if pattern.search(text):
            new_violators.append(str(py.relative_to(ROOT)))
    assert not new_violators, (
        f"set_language() called from non-allowed file(s): {new_violators}. "
        "Use t(key, lang=...) instead, or add the file to ALLOWED_CALLERS "
        "in tests/test_i18n_set_language_callers.py with justification."
    )
