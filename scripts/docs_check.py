#!/usr/bin/env python3
"""docs_check.py — illumio-ops documentation audit.

Modes (compose freely):
  --bilingual           every EN .md has a sibling _zh.md (and vice-versa)
  --freshness N         flag .md files with last_verified older than N days
  --links               flag broken relative links in .md files
  --frontmatter         flag missing/invalid frontmatter keys
  --all                 enable all checks
  --root PATH           docs root (default: ./docs)
  --files FILE [FILE]   only check these files
  --json                emit JSON instead of human text

Exit 0 on clean, non-zero on issues found.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^---\n(.*?\n)---\n", re.DOTALL)
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


@dataclass
class Issue:
    file: str
    rule: str
    detail: str


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)

    def add(self, file: str, rule: str, detail: str) -> None:
        self.issues.append(Issue(file, rule, detail))

    @property
    def ok(self) -> bool:
        return not self.issues


def parse_frontmatter(text: str) -> dict[str, str] | None:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def iter_md(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.md") if "_meta" not in p.parts)


def check_bilingual(root: Path, report: Report) -> None:
    files = {p.name: p for p in iter_md(root)}
    for name, path in files.items():
        if name.endswith("_zh.md"):
            counterpart = name[: -len("_zh.md")] + ".md"
        else:
            counterpart = name[: -len(".md")] + "_zh.md"
        if counterpart not in files:
            report.add(str(path), "bilingual", f"missing counterpart: {counterpart}")


def check_freshness(root: Path, days: int, report: Report) -> None:
    cutoff = date.today().toordinal() - days
    for path in iter_md(root):
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        if not fm or "last_verified" not in fm:
            continue
        try:
            d = datetime.strptime(fm["last_verified"], "%Y-%m-%d").date()
        except ValueError:
            report.add(str(path), "freshness", f"invalid last_verified: {fm['last_verified']}")
            continue
        if d.toordinal() < cutoff:
            report.add(str(path), "freshness", f"last_verified {d} older than {days}d")


def check_frontmatter(root: Path, report: Report) -> None:
    required = {"title", "last_verified", "verified_against"}
    for path in iter_md(root):
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        if fm is None:
            report.add(str(path), "frontmatter", "missing or malformed frontmatter block")
            continue
        for key in required:
            if key not in fm:
                report.add(str(path), "frontmatter", f"missing key: {key}")


def check_links(root: Path, report: Report) -> None:
    md_files = {p.resolve() for p in iter_md(root)}
    for path in iter_md(root):
        text = path.read_text(encoding="utf-8")
        for link in LINK_RE.findall(text):
            target = link.split("#", 1)[0].split(" ", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if target.endswith(".md"):
                resolved = (path.parent / target).resolve()
                if resolved not in md_files:
                    report.add(str(path), "links", f"broken: {target}")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--bilingual", action="store_true")
    p.add_argument("--freshness", type=int, default=None)
    p.add_argument("--links", action="store_true")
    p.add_argument("--frontmatter", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--root", default="docs")
    p.add_argument("--files", nargs="*", default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"error: root not found: {root}", file=sys.stderr)
        return 2

    report = Report()
    if args.all or args.bilingual:
        check_bilingual(root, report)
    if args.all or args.freshness is not None:
        check_freshness(root, args.freshness if args.freshness is not None else 30, report)
    if args.all or args.frontmatter:
        check_frontmatter(root, report)
    if args.all or args.links:
        check_links(root, report)

    if args.json:
        print(json.dumps([i.__dict__ for i in report.issues], indent=2, ensure_ascii=False))
    else:
        for i in report.issues:
            print(f"[{i.rule}] {i.file}: {i.detail}")
        if report.ok:
            print("OK — no issues")

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
