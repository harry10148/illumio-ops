"""Label combinations, stored once and referenced by id from flows and workloads."""
from __future__ import annotations

import sqlite3


def label_set_id(conn: sqlite3.Connection, labels: tuple[tuple[str, str], ...]) -> int | None:
    if not labels:
        return None
    pairs = sorted(set(labels))
    signature = "\n".join(f"{k}={v}" for k, v in pairs)
    row = conn.execute("SELECT id FROM label_sets WHERE signature = ?", (signature,)).fetchone()
    if row is not None:
        return int(row[0])
    cur = conn.execute("INSERT INTO label_sets (signature) VALUES (?)", (signature,))
    set_id = int(cur.lastrowid or 0)
    conn.executemany("INSERT INTO label_set_members (set_id, key, value) VALUES (?, ?, ?)",
                     [(set_id, k, v) for k, v in dict(pairs).items()])
    return set_id
