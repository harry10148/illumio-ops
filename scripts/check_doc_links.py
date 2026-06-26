#!/usr/bin/env python3
"""Walk every Markdown file at repo root and under docs/ and report broken local links.

Exits 0 on success, 1 on any broken link.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINK_RE = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<href>[^)]+)\)")

INCLUDE_DIRS = ["docs"]
INCLUDE_FILES = ["README.md", "README_zh.md", "Status.md", "Task.md"]
EXCLUDE_PARTS = {"_notebooklm_excerpts", "superpowers", "_archive"}


def iter_markdown() -> list[Path]:
    files: list[Path] = []
    for name in INCLUDE_FILES:
        p = ROOT / name
        if p.is_file():
            files.append(p)
    for d in INCLUDE_DIRS:
        for p in (ROOT / d).rglob("*.md"):
            if EXCLUDE_PARTS & set(p.parts):
                continue
            files.append(p)
    return files


def is_local(href: str) -> bool:
    return not (
        href.startswith(("http://", "https://", "mailto:", "#"))
        or href.startswith("data:")
    )


def check(file: Path) -> list[str]:
    text = file.read_text(encoding="utf-8")
    errors: list[str] = []
    for m in LINK_RE.finditer(text):
        href = m.group("href").split("#", 1)[0].strip()
        if not href or not is_local(href):
            continue
        target = (file.parent / href).resolve()
        if not target.exists():
            errors.append(f"{file.relative_to(ROOT)}: broken link → {href}")
    return errors


def main() -> int:
    errors: list[str] = []
    for f in iter_markdown():
        errors.extend(check(f))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print(f"\n{len(errors)} broken link(s)", file=sys.stderr)
        return 1
    print("OK — all local links resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
