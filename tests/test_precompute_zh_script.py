"""Pre-compute script must produce a zh_TW value for every en key."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_precompute_dry_run() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "precompute_zh_translations.py"), "--dry-run"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert result.returncode == 0, result.stderr
    assert "would update" in result.stdout
