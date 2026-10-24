"""Fill a flow database with synthetic traffic at customer scale, through the real write path.

    python3 scripts/v6/synth_flows.py --root <dir> --workloads 1000 --days 35 --flows-per-day 260000 --seed 1

Writes <dir>/data/flows.sqlite with upsert_flows in collector-sized batches (pairing, baselines)
and rebuild_rollup per day, so the time it takes and the size it reaches are what collection
would cost. The mix follows the lab (spec §6.6): about 4% of connections reported by both ends,
12% with a user, 4% with a process, 5% with byte counts, four label keys, and twice as many
unmanaged addresses as workloads. Connections recur from day to day the way real ones do. The
same seed and --end give the same database. Prints one JSON line of totals at the end.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.store.flowdb.db import FlowDb, db_day
from illumio_ops.store.flowdb.flows import rebuild_rollup, upsert_flows

BATCH = 2000  # about one collector cycle's worth of records
PORTS = [(445, 6, 20), (3389, 6, 8), (22, 6, 10), (443, 6, 25), (80, 6, 8), (135, 6, 6), (5985, 6, 3),
         (1433, 6, 3), (3306, 6, 3), (53, 17, 10), (123, 17, 3), (389, 6, 4), (88, 6, 4), (8080, 6, 3)]
DECISIONS = [("allowed", 70), ("potentially_blocked", 22), ("blocked", 6), ("unknown", 2)]
LABELS = {"app": [f"app{i:02d}" for i in range(40)], "env": ["Prod", "Dev", "Test", "Staging"],
          "loc": ["TPE", "HSC", "TXG", "KHH"], "role": ["Web", "App", "DB", "AD", "File", "Jump"]}
PROCESSES = ["sqlservr.exe", "w3wp.exe", "java", "sshd", "lsass.exe", "svchost.exe", "nginx", "postgres"]


def _workloads(rng: random.Random, n: int) -> list[dict[str, Any]]:
    out = []
    for i in range(n):
        labels = [{"key": k, "value": rng.choice(v)} for k, v in LABELS.items()]
        out.append({"ip": f"10.{i // 250}.{i % 250}.10", "workload": {
            "href": f"/orgs/1/workloads/synth-{i}", "hostname": f"host-{i:04d}", "managed": True,
            "enforcement_mode": rng.choice(["visibility_only", "selective", "full"]), "labels": labels}})
    return out


def _pool(rng: random.Random, size: int, workloads: list[dict[str, Any]], unmanaged: int) -> list[tuple[Any, ...]]:
    """Distinct (src, dst, port, proto) tuples; a few hosts talk much more than the rest."""
    weights = [1.0 / (1 + i) ** 0.6 for i in range(len(workloads))]
    seen: set[tuple[Any, ...]] = set()
    pool: list[tuple[Any, ...]] = []
    ports = [(p, pr) for p, pr, _ in PORTS]
    port_w = [w for _, _, w in PORTS]
    while len(pool) < size:
        src = rng.choices(range(len(workloads)), weights)[0]
        u = rng.randrange(unmanaged)
        dst: int | str = rng.randrange(len(workloads)) if rng.random() < 0.4 else f"192.168.{u // 250}.{u % 250 + 1}"
        port, proto = rng.choices(ports, port_w)[0] if rng.random() < 0.8 else (rng.randrange(1024, 65535), 6)
        key = (src, dst, port, proto)
        if key in seen or dst == src:
            continue
        seen.add(key)
        pool.append(key)
    return pool


def _raw(src: dict[str, Any], dst: dict[str, Any], port: int, proto: int, first: datetime, last: datetime,
         direction: str, decision: str, *, user: str | None, process: str | None,
         byte_counts: tuple[int, int] | None) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "src": src, "dst": dst, "service": {"port": port, "proto": proto},
        "policy_decision": decision, "flow_direction": direction, "num_connections": 1,
        "timestamp_range": {"first_detected": first.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "last_detected": last.strftime("%Y-%m-%dT%H:%M:%SZ")},
    }
    if user:
        raw["service"]["user_name"] = user
    if process:
        raw["service"]["process_name"] = process
    if byte_counts:
        raw["dst_bi"], raw["dst_bo"] = byte_counts
    return raw


def _connection(rng: random.Random, tup: tuple[Any, ...], wls: list[dict[str, Any]],
                day_start: datetime) -> list[dict[str, Any]]:
    """One connection's records for the day: the initiator's, and sometimes the destination's too."""
    s, t, port, proto = tup
    src = wls[s]
    dst = wls[t] if isinstance(t, int) else {"ip": t}
    first = day_start + timedelta(seconds=rng.randrange(0, 86400 - 600))
    last = min(first + timedelta(seconds=rng.randrange(0, 3600)), day_start + timedelta(seconds=86399))
    decision = rng.choices([x for x, _ in DECISIONS], [w for _, w in DECISIONS])[0]
    user = f"CORP\\user{rng.randrange(200):03d}" if rng.random() < 0.12 else None
    process = rng.choice(PROCESSES) if rng.random() < 0.04 else None
    byte_counts = (rng.randrange(1, 10**7), rng.randrange(1, 10**7)) if rng.random() < 0.05 else None
    out = [_raw(src, dst, port, proto, first, last, "outbound", decision, user=user, process=process,
                byte_counts=byte_counts)]
    if isinstance(t, int) and rng.random() < 0.10:  # ~4% of all: managed destinations reporting too
        service = rng.choice(PROCESSES) if rng.random() < 0.5 else None
        out.append(_raw(src, dst, port, proto, first + timedelta(seconds=rng.randrange(0, 30)), last, "inbound",
                        decision, user=None, process=service, byte_counts=None))
    return out


def generate(root: Path, *, workloads: int, days: int, flows_per_day: int, seed: int, end: datetime,
             unmanaged: int) -> dict[str, Any]:
    rng = random.Random(seed)
    wls = _workloads(rng, workloads)
    pool = _pool(rng, int(flows_per_day * 1.5), wls, unmanaged)
    fdb = FlowDb(root / "data" / "flows.sqlite")
    fdb.path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    write_seconds = 0.0
    for d in range(days):
        day_start = end - timedelta(days=days - d)
        at = day_start + timedelta(days=1)
        picked = rng.sample(range(len(pool)), flows_per_day)
        written = 0
        t0 = time.monotonic()
        for i in range(0, len(picked), BATCH):  # one batch at a time: small machines have little memory
            records = []
            for idx in picked[i:i + BATCH]:
                records.extend(_connection(rng, pool[idx], wls, day_start))
            with fdb.write_lock, fdb.connect() as conn:
                upsert_flows(conn, [normalize_flow(r) for r in records], origin=DataOrigin.BACKFILL, now=at)
            written += len(records)
        with fdb.write_lock, fdb.connect() as conn:
            rebuild_rollup(conn, db_day(day_start))
        write_seconds += time.monotonic() - t0
        print(f"day {d + 1}/{days}: {written} records, {time.monotonic() - started:.0f} s", file=sys.stderr)
    with fdb.connect() as conn:
        rows, conns = conn.execute("SELECT count(*), count(DISTINCT conn_key) FROM flows").fetchone()
    size = sum(p.stat().st_size for p in fdb.path.parent.glob("flows.sqlite*"))
    return {"rows": rows, "connections": conns, "db_bytes": size, "write_seconds": round(write_seconds, 1),
            "total_seconds": round(time.monotonic() - started, 1)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--workloads", type=int, default=1000)
    p.add_argument("--unmanaged", type=int, default=None, help="unmanaged addresses (default 2 per workload)")
    p.add_argument("--days", type=int, default=35)
    p.add_argument("--flows-per-day", type=int, default=260_000)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--end", default=None, help="UTC day after the last generated one (default: today)")
    a = p.parse_args(argv)
    end = (datetime.fromisoformat(a.end).replace(tzinfo=UTC) if a.end
           else datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0))
    totals = generate(a.root, workloads=a.workloads, days=a.days, flows_per_day=a.flows_per_day, seed=a.seed,
                      end=end, unmanaged=a.unmanaged or 2 * a.workloads)
    print(json.dumps(totals))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
