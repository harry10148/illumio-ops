"""CI gate: ensure all production dependencies are installed and importable.

Runs scripts/verify_deps.py as a subprocess and asserts exit code 0.
Failure means requirements.txt is out of sync with reality.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify_deps.py"


def test_verify_deps_script_exists():
    """Phase 0 deliverable: scripts/verify_deps.py must exist."""
    assert VERIFY_SCRIPT.is_file(), f"missing {VERIFY_SCRIPT}"


def test_all_production_packages_importable():
    """All packages in requirements.txt must import in the current environment.

    This is the CI gate — if a developer adds a package to requirements.txt
    but forgets to add it to verify_deps.PRODUCTION, this test still catches
    runtime-missing packages because verify_deps tries to import each one.
    """
    result = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        msg = (
            f"verify_deps.py exited {result.returncode}\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
        raise AssertionError(msg)


def test_requirements_txt_has_no_unpinned_packages():
    """Every line in requirements.txt that names a package must have a version constraint."""
    req_file = REPO_ROOT / "requirements.txt"
    assert req_file.is_file()
    offenders: list[str] = []
    for raw in req_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not any(op in line for op in ("==", ">=", "<=", "~=", ">", "<", "!=")):
            offenders.append(line)
    assert not offenders, f"unpinned packages: {offenders}"


def test_offline_runtime_uses_cheroot_not_waitress():
    offline = (REPO_ROOT / "requirements-offline.txt").read_text(encoding="utf-8").lower()
    assert "cheroot" in offline
    assert "waitress" not in offline
