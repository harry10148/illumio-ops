#!/usr/bin/env python3
"""Codemod: stdlib logging → loguru across src/.

Usage:
  python scripts/migrate_to_loguru.py           # execute migration
  python scripts/migrate_to_loguru.py --dry-run  # preview without touching files
"""
import re
import sys
from pathlib import Path

_IMPORT_PATTERN = re.compile(r"^import logging(\s*#[^\n]*)?\n", re.MULTILINE)
_LOGGER_ASSIGN_PATTERN = re.compile(
    r"^logger\s*=\s*logging\.getLogger\([^)]*\)\s*\n",
    re.MULTILINE,
)
_FORMAT_SPEC_IN_CALL = re.compile(
    r"""(logger\.(?:debug|info|warning|error|critical|exception)\()"""
    r"""(['"])"""
    r"""((?:[^'"\\]|\\.)*)"""
    r"""\2""",
    re.DOTALL,
)
_PERCENT_SPEC = re.compile(r"%[sdifr]")


def _convert_format_specs(src: str) -> str:
    """Convert %s/%d/... → {} inside logger call string literals."""
    def _repl(m: re.Match) -> str:
        prefix, quote, content = m.group(1), m.group(2), m.group(3)
        new_content = _PERCENT_SPEC.sub("{}", content)
        return f"{prefix}{quote}{new_content}{quote}"
    return _FORMAT_SPEC_IN_CALL.sub(_repl, src)


def migrate_file(path: Path, dry_run: bool = False) -> bool:
    """Migrate one file. Return True if file was (or would be) changed."""
    original = path.read_text(encoding="utf-8")
    text = original

    has_import = bool(_IMPORT_PATTERN.search(text))
    has_getlogger = "logging.getLogger" in text

    if has_import or has_getlogger:
        # Replace `import logging` with loguru import (first occurrence only)
        if has_import:
            # Replace only the standalone `import logging` line
            text = _IMPORT_PATTERN.sub("from loguru import logger\n", text, count=1)
            # If there were multiple `import logging` lines (rare), remove the rest
            text = _IMPORT_PATTERN.sub("", text)
        elif has_getlogger and "from loguru import logger" not in text:
            # Has getLogger but no `import logging` line — add loguru import at top
            text = "from loguru import logger\n" + text

        # Remove `logger = logging.getLogger(...)` lines
        text = _LOGGER_ASSIGN_PATTERN.sub("", text)

    # Convert %s/%d/... format specifiers inside logger calls
    text = _convert_format_specs(text)

    # Collapse 3+ consecutive blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    if text == original:
        return False

    if dry_run:
        print(f"[dry-run] would modify {path}")
    else:
        path.write_text(text, encoding="utf-8")
        print(f"migrated {path}")
    return True


def main() -> int:
    src = Path(__file__).resolve().parent.parent / "src"
    dry = "--dry-run" in sys.argv
    exclude = {"module_log.py", "loguru_config.py", "utils.py"}
    changed = 0
    for py in sorted(src.rglob("*.py")):
        if py.name in exclude:
            continue
        if migrate_file(py, dry_run=dry):
            changed += 1
    print(f"\n{'Would migrate' if dry else 'Migrated'} {changed} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
