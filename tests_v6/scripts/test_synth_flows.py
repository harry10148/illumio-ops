"""The synthetic flow generator used for the 1,000-workload load measurement (P2 Task 14)."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "v6" / "synth_flows.py"
ARGS = ["--workloads", "10", "--days", "2", "--flows-per-day", "500", "--seed", "1", "--end", "2026-10-24"]


def _run(root: Path) -> dict:
    out = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), *ARGS], cwd=REPO,
                         capture_output=True, text=True, timeout=120, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def _counts(root: Path) -> tuple[int, int, int]:
    with sqlite3.connect(root / "data" / "flows.sqlite") as conn:
        return conn.execute("SELECT count(*), count(DISTINCT conn_key), sum(is_primary) FROM flows").fetchone()


def test_synth_small_is_deterministic(tmp_path):
    a, b = _run(tmp_path / "a"), _run(tmp_path / "b")
    assert _counts(tmp_path / "a") == _counts(tmp_path / "b")
    rows, conns, primary = _counts(tmp_path / "a")
    assert (a["rows"], a["connections"]) == (b["rows"], b["connections"]) == (rows, conns)
    assert primary == conns == 2 * 500 and rows > conns  # some connections are reported by both ends
