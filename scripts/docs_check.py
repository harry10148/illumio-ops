#!/usr/bin/env python3
"""docs_check.py — illumio-ops documentation audit.

Modes (compose freely):
  --bilingual           every EN .md has a sibling _zh.md (and vice-versa)
  --freshness N         flag .md files with last_verified older than N days
                        (default when triggered via --all: 30)
  --links               flag broken relative links in .md files
  --frontmatter         flag missing/invalid frontmatter keys
  --all                 enable all checks (uses freshness threshold of 30 days
                        unless --freshness is also given)
  --exclude GLOB        path-relative glob to skip (repeatable)
  --root PATH           docs root (default: ./docs)
  --json                emit JSON instead of human text

Exit 0 on clean, non-zero on issues found.
"""
from __future__ import annotations
import argparse
import fnmatch
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^---\n(.*?\n)---\n", re.DOTALL)
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

DEFAULT_FRESHNESS_DAYS = 30


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


def iter_md(root: Path, exclude: list[str] | None = None) -> list[Path]:
    exclude = exclude or []
    out: list[Path] = []
    for p in sorted(root.rglob("*.md")):
        if "_meta" in p.parts:
            continue
        rel = p.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, pat) for pat in exclude):
            continue
        out.append(p)
    return out


def check_bilingual(md: list[Path], report: Report) -> None:
    by_dir: dict[Path, set[str]] = {}
    for p in md:
        by_dir.setdefault(p.parent, set()).add(p.name)
    for parent, names in by_dir.items():
        for name in names:
            if name.endswith("_zh.md"):
                counterpart = name[: -len("_zh.md")] + ".md"
            else:
                counterpart = name[: -len(".md")] + "_zh.md"
            if counterpart not in names:
                report.add(str(parent / name), "bilingual", f"missing counterpart: {counterpart}")


def check_freshness(md: list[Path], days: int, report: Report) -> None:
    cutoff = date.today().toordinal() - days
    for path in md:
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


def check_frontmatter(md: list[Path], report: Report) -> None:
    required = {"title", "last_verified", "verified_against"}
    for path in md:
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        if fm is None:
            report.add(str(path), "frontmatter", "missing or malformed frontmatter block")
            continue
        for key in required:
            if key not in fm:
                report.add(str(path), "frontmatter", f"missing key: {key}")


def check_links(md: list[Path], report: Report) -> None:
    md_set = {p.resolve() for p in md}
    for path in md:
        text = path.read_text(encoding="utf-8")
        for link in LINK_RE.findall(text):
            target = link.split("#", 1)[0].split(" ", 1)[0]
            if not target:
                continue  # anchor-only link
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if target.endswith(".md"):
                resolved = (path.parent / target).resolve()
                if resolved not in md_set:
                    report.add(str(path), "links", f"broken: {target}")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--bilingual", action="store_true")
    p.add_argument(
        "--freshness", type=int, default=None,
        help=f"flag .md files with last_verified older than N days (default with --all: {DEFAULT_FRESHNESS_DAYS})",
    )
    p.add_argument("--links", action="store_true")
    p.add_argument("--frontmatter", action="store_true")
    p.add_argument(
        "--all", action="store_true",
        help=f"enable all checks (freshness defaults to {DEFAULT_FRESHNESS_DAYS} days)",
    )
    p.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="path-relative glob to skip (repeatable). Example: --exclude superpowers/** --exclude ux-review-*/**",
    )
    p.add_argument("--root", default="docs")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"error: root not found: {root}", file=sys.stderr)
        return 2

    md = iter_md(root, args.exclude)
    report = Report()
    if args.all or args.bilingual:
        check_bilingual(md, report)
    if args.all or args.freshness is not None:
        check_freshness(md, args.freshness if args.freshness is not None else DEFAULT_FRESHNESS_DAYS, report)
    if args.all or args.frontmatter:
        check_frontmatter(md, report)
    if args.all or args.links:
        check_links(md, report)

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
