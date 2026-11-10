"""The docs point only at things that exist, and the REST reference is the contract's own output."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.gen_api_reference import OUT, render
from tests.gates._scan import REPO_ROOT

DOCS = REPO_ROOT / "docs"
# docs/superpowers holds dated working papers (plans, specs); they are records, not the manual.
PAGES = sorted([p for p in DOCS.rglob("*.md") if "superpowers" not in p.relative_to(DOCS).parts]
               + [REPO_ROOT / "README.md", REPO_ROOT / "README_zh.md"])
CURRENT = [p for p in PAGES if "legacy-5.x" not in p.parts]
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_FENCE = re.compile(r"```.*?```", re.DOTALL)


def broken_links(page: Path) -> list[str]:
    out = []
    for target in _LINK.findall(_FENCE.sub("", page.read_text(encoding="utf-8"))):
        if re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        if not (page.parent / target.split("#", 1)[0]).exists():
            out.append(target)
    return out


def verified_against(page: Path) -> list[str]:
    text = page.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return []
    head = text.split("\n---\n", 1)[0]
    block = head.split("verified_against:\n", 1)
    return re.findall(r"^\s+-\s+(\S+)\s*$", block[1], re.MULTILINE) if len(block) == 2 else []


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_relative_links_resolve(page: Path) -> None:
    assert broken_links(page) == []


@pytest.mark.parametrize("page", CURRENT, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_current_pages_name_files_that_exist(page: Path) -> None:
    assert [f for f in verified_against(page) if not (REPO_ROOT / f).exists()] == []


def test_index_lists_every_current_page() -> None:
    index = (DOCS / "INDEX.md").read_text(encoding="utf-8")
    pages = [p for p in CURRENT if p.is_relative_to(DOCS) and p.name != "INDEX.md"]
    assert [str(p.relative_to(DOCS)) for p in pages if f"({p.relative_to(DOCS)})" not in index] == []


def test_rest_api_reference_is_the_generators_output() -> None:
    assert OUT.read_text(encoding="utf-8") == render(), "run: python scripts/gen_api_reference.py"
