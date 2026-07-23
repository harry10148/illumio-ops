#!/usr/bin/env python3
"""docs_check.py — illumio-ops documentation audit.

Modes (compose freely):
  --bilingual           every EN .md has a sibling _zh.md (and vice-versa)
  --freshness N         flag .md files with last_verified older than N days
                        (default when triggered via --all: 30)
  --links               flag broken relative links in .md files
  --frontmatter         flag missing/invalid/empty frontmatter keys
  --all                 enable all checks (uses freshness threshold of 30 days
                        unless --freshness is also given)
  --exclude GLOB        path-relative glob to skip (repeatable)
  --root PATH           docs root (default: ./docs)

Exit 0 on clean, non-zero on issues found.
"""
from __future__ import annotations
import argparse
import fnmatch
import re
import sys
from datetime import date, datetime
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^---\n(.*?\n)---\n", re.DOTALL)
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
DEFAULT_FRESHNESS_DAYS = 30


def parse_frontmatter(text: str) -> dict[str, str | list[str]] | None:
    """Parse a ``---\\n…\\n---\\n`` YAML-lite block.

    Returns ``None`` if no block; otherwise a dict whose values are either
    scalar strings or lists of strings (for ``key:`` followed by indented
    ``  - item`` lines). Returns ``None`` for missing/malformed block only.
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    out: dict[str, str | list[str]] = {}
    current_list_key: str | None = None
    for line in m.group(1).splitlines():
        if current_list_key and line.startswith("  - "):
            bucket = out[current_list_key]
            if isinstance(bucket, list):
                bucket.append(line[4:].strip())
            continue
        if line and not line.startswith(" "):
            current_list_key = None
            if ":" in line:
                k, _, v = line.partition(":")
                k = k.strip()
                v = v.strip()
                if v == "":
                    out[k] = []
                    current_list_key = k
                else:
                    out[k] = v
    return out


def iter_md(root: Path, exclude: list[str] | None = None) -> list[Path]:
    """`.md` files under root that we want to *audit* (honors --exclude)."""
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


def all_md_targets(root: Path) -> list[Path]:
    """All `.md` files under root that are valid *link targets*.

    Ignores `_meta/` but does NOT honor --exclude — a link from an audited
    file to an excluded file is still a valid link.
    """
    return sorted(p for p in root.rglob("*.md") if "_meta" not in p.parts)


def check_bilingual(md: list[Path], issues: list[tuple[str, str, str]]) -> None:
    """2026-07 docs overhaul 後 docs/ 為繁中單語；僅倉庫根 README.md 與
    README_zh.md 仍要求成對（md 清單掃的是 docs/，故直接檢查 repo 根）。"""
    repo_root = Path(__file__).resolve().parent.parent
    readme = repo_root / "README.md"
    readme_zh = repo_root / "README_zh.md"
    if readme.is_file() != readme_zh.is_file():
        missing = "README_zh.md" if readme.is_file() else "README.md"
        present = "README.md" if readme.is_file() else "README_zh.md"
        issues.append((present, "bilingual", f"missing counterpart: {missing}"))


def check_freshness(md: list[Path], days: int, issues: list[tuple[str, str, str]]) -> None:
    cutoff = date.today().toordinal() - days
    for path in md:
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        if not fm or "last_verified" not in fm:
            continue
        lv = fm["last_verified"]
        if not isinstance(lv, str):
            issues.append((str(path), "freshness", f"last_verified is not a scalar: {lv!r}"))
            continue
        try:
            d = datetime.strptime(lv, "%Y-%m-%d").date()
        except ValueError:
            issues.append((str(path), "freshness", f"invalid last_verified: {lv}"))
            continue
        if d.toordinal() < cutoff:
            issues.append((str(path), "freshness", f"last_verified {d} older than {days}d"))


def check_frontmatter(md: list[Path], issues: list[tuple[str, str, str]]) -> None:
    required = {"title", "last_verified", "verified_against"}
    for path in md:
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        if fm is None:
            issues.append((str(path), "frontmatter", "missing or malformed frontmatter block"))
            continue
        for key in required:
            if key not in fm:
                issues.append((str(path), "frontmatter", f"missing key: {key}"))
                continue
            v = fm[key]
            if isinstance(v, list) and len(v) == 0:
                issues.append((str(path), "frontmatter", f"{key} is an empty list"))
            elif isinstance(v, str) and v == "":
                issues.append((str(path), "frontmatter", f"{key} is empty"))


def check_verified_against_paths(
    md: list[Path], issues: list[tuple[str, str, str]], repo_root: Path,
) -> None:
    """verified_against 裡「長得像 repo 路徑」的條目必須存在。

    只檢查含 '/' 的條目（如 src/foo.py）；不含 '/' 的版本字樣
    （如 "PCE 25.2.40"）跳過。2026-07-17 preview.py 懸空引用事故的防門。
    """
    for path in md:
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        if not fm:
            continue
        va = fm.get("verified_against")
        entries = va if isinstance(va, list) else ([va] if isinstance(va, str) else [])
        for item in entries:
            item = (item or "").strip()
            if not item or "/" not in item or item.startswith(("http://", "https://")):
                continue
            if not (repo_root / item).exists():
                issues.append((str(path), "verified_against", f"path not found: {item}"))


def check_links(md: list[Path], md_targets: list[Path], issues: list[tuple[str, str, str]]) -> None:
    target_set = {p.resolve() for p in md_targets}
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
                if resolved not in target_set:
                    issues.append((str(path), "links", f"broken: {target}"))


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
    args = p.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"error: root not found: {root}", file=sys.stderr)
        return 2

    md = iter_md(root, args.exclude)
    md_targets = all_md_targets(root)
    issues: list[tuple[str, str, str]] = []
    if args.all or args.bilingual:
        check_bilingual(md, issues)
    if args.all or args.freshness is not None:
        check_freshness(md, args.freshness if args.freshness is not None else DEFAULT_FRESHNESS_DAYS, issues)
    if args.all or args.frontmatter:
        check_frontmatter(md, issues)
        check_verified_against_paths(md, issues, root.parent)
    if args.all or args.links:
        check_links(md, md_targets, issues)

    for f, r, d in issues:
        print(f"[{r}] {f}: {d}")
    if not issues:
        print("OK — no issues")

    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
