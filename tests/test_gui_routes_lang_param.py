"""Phase 3: gui routes must not call set_language() in request handlers."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_events_route_no_set_language() -> None:
    text = (ROOT / "src" / "gui" / "routes" / "events.py").read_text(encoding="utf-8")
    matches = re.findall(r"\bset_language\s*\(", text)
    assert not matches, (
        f"set_language() in src/gui/routes/events.py: {len(matches)} occurrences. "
        "Use t(key, lang=lang) with a request-scoped local variable instead."
    )


def test_events_route_no_set_language_import() -> None:
    text = (ROOT / "src" / "gui" / "routes" / "events.py").read_text(encoding="utf-8")
    # Match `from src.i18n import ... set_language ...`
    bad = re.search(r"from\s+src\.i18n\s+import[^;\n]*\bset_language\b", text)
    assert bad is None, "set_language import lingers in events.py"
