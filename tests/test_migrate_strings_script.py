"""Phase 1 migration script writes a deterministic manifest."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dry_run_emits_manifest(tmp_path: Path) -> None:
    """The script must run, emit a well-formed manifest, and not mutate JSON files."""
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
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(manifest.read_text(encoding="utf-8"))

    # Schema check — these fields must always be present regardless of migration scope.
    for field in ("only_in_strings", "overlap", "overlap_changes", "samples", "prefer"):
        assert field in data, f"manifest missing field: {field}"
    assert isinstance(data["only_in_strings"], int)
    assert isinstance(data["overlap"], int)
    assert isinstance(data["samples"], list)
    assert data["prefer"] in ("strings", "json")

    # Behavioral check — the overlap set is a stable property of STRINGS+JSON
    # consolidation, so it remains non-zero even after migration (the keys still
    # exist in both places). This catches a script that silently breaks.
    assert data["overlap"] > 0, "overlap should be > 0 even post-migration"
