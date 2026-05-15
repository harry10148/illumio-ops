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


def test_bilingual_check_fails_on_orphan(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "alpha.md").write_text("# Alpha\n")
    # missing alpha_zh.md
    rc, out, _ = run_check("--bilingual", "--root", str(docs))
    assert rc != 0
    assert "alpha_zh.md" in out


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
