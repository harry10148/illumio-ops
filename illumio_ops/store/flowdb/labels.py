"""Label combinations, stored once and referenced by id from flows and workloads."""
from __future__ import annotations

import sqlite3
from collections.abc import Collection


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


def label_sets(conn: sqlite3.Connection, ids: Collection[int] | None = None) -> dict[int, dict[str, str]]:
    """Label set id -> {key: value}; every set when ids is None."""
    if ids is not None and not ids:
        return {}
    sql = "SELECT set_id, key, value FROM label_set_members"
    params: list[int] = []
    if ids is not None:
        sql += f" WHERE set_id IN ({','.join('?' * len(ids))})"
        params = sorted(ids)
    out: dict[int, dict[str, str]] = {}
    for set_id, key, value in conn.execute(sql, params):
        out.setdefault(set_id, {})[key] = value
    return out


def known_labels(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    """The labels the current inventory carries. label_set_members also keeps every combination ever seen
    on a flow, including labels deleted from the PCE long ago."""
    return {(k, v) for k, v in conn.execute(
        "SELECT DISTINCT m.key, m.value FROM label_set_members m JOIN workloads w ON w.label_set = m.set_id")}
