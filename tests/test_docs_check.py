"""Tests for scripts/docs_check.py audit tool."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "docs_check.py"


def run_check(*args: str, cwd: Path | None = None) -> tuple[int, str, str]:
    p = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=cwd or Path.cwd(),
    )
    return p.returncode, p.stdout, p.stderr


def test_bilingual_check_passes_when_paired(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "alpha.md").write_text("# Alpha\n")
    (docs / "alpha_zh.md").write_text("# Alpha\n")
    rc, out, _ = run_check("--bilingual", "--root", str(docs))
    assert rc == 0, out


def test_bilingual_check_no_longer_flags_orphaned_docs_dir_files(tmp_path: Path) -> None:
    # 2026-07 docs overhaul: docs/ is 繁中單語, so --bilingual no longer
    # checks per-file _zh.md pairing under --root; it only checks the
    # repo-root README.md/README_zh.md pair (both present in this repo), so
    # an orphaned file inside an arbitrary docs/ tree no longer fails.
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "alpha.md").write_text("# Alpha\n")
    # missing alpha_zh.md — no longer relevant to --bilingual
    rc, out, _ = run_check("--bilingual", "--root", str(docs))
    assert rc == 0, out


def test_freshness_check_flags_stale(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "alpha.md").write_text(
        "---\ntitle: Alpha\nlast_verified: 2020-01-01\n---\n# Alpha\n"
    )
    (docs / "alpha_zh.md").write_text(
        "---\ntitle: Alpha\nlast_verified: 2020-01-01\n---\n# Alpha\n"
    )
    rc, out, _ = run_check("--freshness", "30", "--root", str(docs))
    assert rc != 0
    assert "alpha.md" in out


def test_frontmatter_check_passes_on_clean(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "alpha.py").write_text("x = 1\n")
    body = (
        "---\n"
        "title: Alpha\n"
        "last_verified: 2026-05-15\n"
        "verified_against: src/alpha.py\n"
        "---\n"
        "# Alpha\n"
    )
    (docs / "alpha.md").write_text(body)
    (docs / "alpha_zh.md").write_text(body)
    rc, out, _ = run_check("--frontmatter", "--root", str(docs))
    assert rc == 0, out


def test_links_check_passes_on_clean_and_anchors(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "alpha.md").write_text(
        "# Alpha\n\nSee [beta](beta.md) and [self](#top) and [ext](https://example.com).\n"
    )
    (docs / "alpha_zh.md").write_text("# Alpha\n")
    (docs / "beta.md").write_text("# Beta\n")
    (docs / "beta_zh.md").write_text("# Beta\n")
    rc, out, _ = run_check("--links", "--root", str(docs))
    assert rc == 0, out


def test_exclude_skips_matching_paths(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    (docs / "superpowers" / "plans").mkdir(parents=True)
    (docs / "user-guide").mkdir(parents=True)
    # Orphan inside superpowers/ — should be skipped
    (docs / "superpowers" / "plans" / "plan.md").write_text("# Plan\n")
    # Paired in user-guide — should be unaffected
    (docs / "user-guide" / "doc.md").write_text("# Doc\n")
    (docs / "user-guide" / "doc_zh.md").write_text("# Doc\n")
    rc, out, _ = run_check(
        "--bilingual", "--exclude", "superpowers/**", "--root", str(docs)
    )
    assert rc == 0, out


def test_frontmatter_rejects_empty_verified_against(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    # verified_against present but value is an empty list (key only, no items)
    body = (
        "---\n"
        "title: Alpha\n"
        "last_verified: 2026-05-15\n"
        "verified_against:\n"
        "---\n"
        "# Alpha\n"
    )
    (docs / "alpha.md").write_text(body)
    (docs / "alpha_zh.md").write_text(body)
    rc, out, _ = run_check("--frontmatter", "--root", str(docs))
    assert rc != 0
    assert "verified_against" in out and "empty" in out


def test_frontmatter_accepts_list_verified_against(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "alpha.py").write_text("x = 1\n")
    (tmp_path / "src" / "beta.py").write_text("x = 1\n")
    body = (
        "---\n"
        "title: Alpha\n"
        "last_verified: 2026-05-15\n"
        "verified_against:\n"
        "  - src/alpha.py\n"
        "  - src/beta.py\n"
        "---\n"
        "# Alpha\n"
    )
    (docs / "alpha.md").write_text(body)
    (docs / "alpha_zh.md").write_text(body)
    rc, out, _ = run_check("--frontmatter", "--root", str(docs))
    assert rc == 0, out


def test_verified_against_dangling_path_flagged(tmp_path: Path) -> None:
    # 2026-07-17 事故防門：verified_against 指向已刪除檔案必須被抓出
    # （preview.py 懸空引用當時靠人工 review 才發現）。
    docs = tmp_path / "docs"
    docs.mkdir()
    body = (
        "---\n"
        "title: Alpha\n"
        "last_verified: 2026-05-15\n"
        "verified_against:\n"
        "  - src/definitely_missing_xyz.py\n"
        "---\n"
        "# Alpha\n"
    )
    (docs / "alpha.md").write_text(body)
    rc, out, _ = run_check("--frontmatter", "--root", str(docs))
    assert rc != 0
    assert "path not found" in out and "definitely_missing_xyz" in out


def test_verified_against_non_path_entries_skipped(tmp_path: Path) -> None:
    # 不含 '/' 的條目（版本字樣等）不做存在性檢查
    docs = tmp_path / "docs"
    docs.mkdir()
    body = (
        "---\n"
        "title: Alpha\n"
        "last_verified: 2026-05-15\n"
        "verified_against:\n"
        "  - PCE 25.2.40\n"
        "---\n"
        "# Alpha\n"
    )
    (docs / "alpha.md").write_text(body)
    rc, out, _ = run_check("--frontmatter", "--root", str(docs))
    assert rc == 0, out


def test_links_accepts_target_in_excluded_path(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    (docs / "superpowers").mkdir(parents=True)
    (docs / "user-guide").mkdir(parents=True)
    # Audited source links into the excluded subtree
    (docs / "user-guide" / "doc.md").write_text(
        "# Doc\n\nSee [spec](../superpowers/spec.md).\n"
    )
    (docs / "user-guide" / "doc_zh.md").write_text("# Doc\n")
    # Target exists on disk but is excluded from auditing
    (docs / "superpowers" / "spec.md").write_text("# Spec\n")
    rc, out, _ = run_check(
        "--links", "--exclude", "superpowers/**", "--root", str(docs)
    )
    # Link is valid (target file exists); --exclude only suppresses auditing
    # of the target file, not its existence as a link destination.
    assert rc == 0, out
