"""Phase 3: report_generator must not mutate global lang during render."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_report_generator_has_no_set_language_calls() -> None:
    """Static check: report_generator.py should not call set_language anywhere."""
    text = (ROOT / "src" / "report" / "report_generator.py").read_text(encoding="utf-8")
    matches = re.findall(r"\bset_language\s*\(", text)
    assert not matches, (
        f"set_language() calls remain in report_generator.py: {len(matches)} occurrences. "
        "Use t(key, lang=lang) instead."
    )


def test_report_generator_does_not_import_set_language() -> None:
    """Once all callers are migrated, the import should be dropped."""
    text = (ROOT / "src" / "report" / "report_generator.py").read_text(encoding="utf-8")
    assert "set_language" not in text, "set_language reference (import or call) lingers"
