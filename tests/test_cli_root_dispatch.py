"""Verify dispatcher routes click-global flags to click, not legacy argparse."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).parent.parent
ILLUMIO_OPS = REPO / "illumio-ops.py"
PY = sys.executable


def _run(argv: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, str(ILLUMIO_OPS), *argv],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_json_status_routes_to_click():
    """`illumio-ops --json status` must reach click, not bail with argparse error."""
    proc = _run(["--json", "status"])
    # argparse failure produces "unrecognized arguments"
    assert "unrecognized arguments" not in proc.stderr, (
        f"--json status routed to argparse:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    # success: returncode 0 and some output on stdout
    assert proc.returncode == 0, f"Non-zero exit:\n{proc.stderr}"


def test_quiet_flag_routes_to_click():
    proc = _run(["--quiet", "version"])
    assert "unrecognized arguments" not in proc.stderr
    assert proc.returncode == 0


def test_short_quiet_flag_routes_to_click():
    proc = _run(["-q", "version"])
    assert "unrecognized arguments" not in proc.stderr
    assert proc.returncode == 0


def test_legacy_monitor_flag_still_routes_to_argparse():
    """--monitor without subcommand should still hit legacy argparse path."""
    proc = _run(["--monitor", "--help"])
    # argparse help is fine; just must not crash with import error
    assert proc.returncode in (0, 2), f"Unexpected exit: {proc.returncode}\n{proc.stderr}"
