"""Phase 1 migration script writes a deterministic manifest."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dry_run_emits_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "migrate_strings_to_json.py"),
            "--dry-run",
            "--manifest",
            str(manifest),
        ],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": f"{ROOT}:{ROOT}/venv/lib/python3.12/site-packages"},
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["only_in_strings"] >= 400, "expect ~467 only-STRINGS keys"
    assert data["overlap"] >= 100, "expect ~195 overlap keys"
    assert "samples" in data and len(data["samples"]) > 0
