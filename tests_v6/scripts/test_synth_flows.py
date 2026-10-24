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


def _load_synth():
    import importlib.util
    spec = importlib.util.spec_from_file_location("synth_flows_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generated_store_leaves_no_rollup_to_rebuild(tmp_path, monkeypatch):
    # A pair across midnight dirties the day before after it was built; a store left like that makes
    # the first measured cycle rebuild those days (the 619 s run in the P2 re-measure).
    from datetime import UTC, datetime, timedelta
    synth = _load_synth()
    real = synth._connection

    def across_midnight(rng, tup, wls, day_start):
        recs = real(rng, tup, wls, day_start)
        for r in recs:
            a, b = ((timedelta(hours=23, minutes=55), timedelta(hours=23, minutes=59, seconds=59))
                    if r["flow_direction"] == "outbound" else (timedelta(minutes=1), timedelta(minutes=3)))
            r["timestamp_range"] = {"first_detected": (day_start + a).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "last_detected": (day_start + b).strftime("%Y-%m-%dT%H:%M:%SZ")}
        return recs

    monkeypatch.setattr(synth, "_connection", across_midnight)
    synth.generate(tmp_path, workloads=10, days=3, flows_per_day=300, seed=1,
                   end=datetime(2026, 10, 24, tzinfo=UTC), unmanaged=20)
    with sqlite3.connect(tmp_path / "data" / "flows.sqlite") as conn:
        multi_day = conn.execute("SELECT count(*) FROM (SELECT conn_key FROM flows GROUP BY conn_key "
                                 "HAVING count(DISTINCT substr(last_detected, 1, 10)) > 1)").fetchone()[0]
        dirty = conn.execute("SELECT count(*) FROM rollup_state WHERE dirty = 1").fetchone()[0]
    assert multi_day > 0  # the condition really occurred
    assert dirty == 0
