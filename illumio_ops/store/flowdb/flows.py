"""Writes to flows, flow_rollup_daily, connection_baseline and user_baseline.

One PCE record is one row. When both ends of a connection report it (spec §6.6 F11), the two
rows share conn_key, exactly one is primary (the outbound one when present), and each row is
completed with the other side's process / user; the primary also carries the larger byte counts.
Counting connections means counting primary rows, so a two-sided connection counts once.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from illumio_ops.domain.flows import FlowRecord, ranges_within, record_key
from illumio_ops.domain.identity import endpoint_key
from illumio_ops.domain.values import DataOrigin, FlowDirection
from illumio_ops.store.flowdb import archive
from illumio_ops.store.flowdb.db import db_day, db_time, transaction
from illumio_ops.store.flowdb.labels import label_set_id

NO_PORT = -1  # rollup and baseline keys cannot be NULL


@dataclass(frozen=True)
class UpsertStats:
    inserted: int
    refreshed: int
    paired: int
    days_touched: frozenset[str]
    unchanged: int = 0  # re-pulled exactly as stored: nothing written


def _max_bytes(column: str) -> str:
    # A NULL (no byte data) never replaces a known count; a smaller re-pull never shrinks it.
    return f"{column} = CASE WHEN ? IS NULL THEN {column} WHEN {column} IS NULL THEN ? ELSE MAX({column}, ?) END"


_REFRESH = (
    "UPDATE flows SET "
    "last_detected = MAX(last_detected, ?), "
    "num_connections = MAX(num_connections, ?), "
    f"{_max_bytes('bytes_in')}, {_max_bytes('bytes_out')}, "
    f"{_max_bytes('own_bytes_in')}, {_max_bytes('own_bytes_out')}, "
    "state = CASE WHEN ? > last_detected THEN ? ELSE state END, "
    "initiator_process = CASE WHEN direction = 'outbound' THEN COALESCE(initiator_process, ?) "
    "ELSE initiator_process END, "
    "initiator_user = CASE WHEN direction = 'outbound' THEN COALESCE(initiator_user, ?) ELSE initiator_user END, "
    "service_process = CASE WHEN direction = 'inbound' THEN COALESCE(service_process, ?) ELSE service_process END, "
    "service_user = CASE WHEN direction = 'inbound' THEN COALESCE(service_user, ?) ELSE service_user END, "
    "origin = CASE WHEN origin = 'ingest' THEN 'ingest' ELSE ? END, "
    "ingested_at = CASE WHEN ? = 'ingest' THEN ? ELSE ingested_at END "
    "WHERE id = ?"
)

_INSERT = (
    "INSERT INTO flows (record_key, conn_key, is_primary, direction, src_ip, dst_ip, src_key, dst_key, "
    "src_href, dst_href, src_hostname, dst_hostname, src_managed, dst_managed, src_mode, dst_mode, "
    "src_label_set, dst_label_set, port, proto, initiator_process, initiator_user, service_process, "
    "service_user, windows_service, policy_decision, first_detected, last_detected, num_connections, "
    "bytes_in, bytes_out, own_bytes_in, own_bytes_out, state, transmission, network_href, origin, ingested_at) "
    "VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def _insert(conn: sqlite3.Connection, r: FlowRecord, key: str, conn_key: str, origin: DataOrigin, stamp: str) -> None:
    outbound = r.direction is FlowDirection.OUTBOUND
    conn.execute(_INSERT, (
        key, conn_key, r.direction.value, r.src_ip, r.dst_ip,
        endpoint_key(r.src_href, r.src_ip), endpoint_key(r.dst_href, r.dst_ip),
        r.src_href, r.dst_href, r.src_hostname, r.dst_hostname, int(r.src_managed), int(r.dst_managed),
        r.src_mode, r.dst_mode, label_set_id(conn, r.src_labels), label_set_id(conn, r.dst_labels),
        r.port, r.proto,
        r.own_process if outbound else None, r.own_user if outbound else None,
        None if outbound else r.own_process, None if outbound else r.own_user,
        r.windows_service, r.policy_decision, db_time(r.first_detected), db_time(r.last_detected),
        r.num_connections, r.bytes_in, r.bytes_out, r.bytes_in, r.bytes_out, r.state, r.transmission, r.network_href,
        origin.value, stamp,
    ))


def _refresh(conn: sqlite3.Connection, row_id: int, r: FlowRecord, origin: DataOrigin, stamp: str) -> None:
    last = db_time(r.last_detected)
    conn.execute(_REFRESH, (
        last, r.num_connections,
        r.bytes_in, r.bytes_in, r.bytes_in, r.bytes_out, r.bytes_out, r.bytes_out,
        r.bytes_in, r.bytes_in, r.bytes_in, r.bytes_out, r.bytes_out, r.bytes_out,
        last, r.state,
        r.own_process, r.own_user, r.own_process, r.own_user,
        origin.value, origin.value, stamp, row_id,
    ))


# The record's own counts (a primary row's bytes_* are its connection's); rows written before flow db
# 0002 that were part of a pair have no own count and fall back to bytes_*.
_STORED = ("SELECT id, direction, last_detected, num_connections, COALESCE(own_bytes_in, bytes_in) AS bytes_in, "
           "COALESCE(own_bytes_out, bytes_out) AS bytes_out, initiator_process, "
           "initiator_user, service_process, service_user, origin FROM flows WHERE record_key = ?")


def _adds_nothing(old: sqlite3.Row, r: FlowRecord, origin: DataOrigin) -> bool:
    """Whether _refresh would leave the stored row as it is (ingested_at aside, which nothing reads)."""
    def more_bytes(new: int | None, have: int | None) -> bool:
        return new is not None and (have is None or new > have)
    side = "initiator" if old["direction"] == FlowDirection.OUTBOUND.value else "service"
    return (db_time(r.last_detected) <= old["last_detected"]
            and r.num_connections <= old["num_connections"]
            and not more_bytes(r.bytes_in, old["bytes_in"]) and not more_bytes(r.bytes_out, old["bytes_out"])
            and not (r.own_process and old[f"{side}_process"] is None)
            and not (r.own_user and old[f"{side}_user"] is None)
            and (old["origin"] == DataOrigin.INGEST.value or old["origin"] == origin.value))


def _first(values: list[str | None]) -> str | None:
    return next((v for v in values if v), None)


def _merge_connection(conn: sqlite3.Connection, conn_key: str) -> None:
    """Pick the primary row of one connection and complete each row with the other side's
    attributes (a lone row has nothing from the other side). The primary row's bytes are the largest
    own count among the connection's records, recomputed every time: a record re-paired into another
    connection takes its bytes along (F10). Every other row shows its own count."""
    rows = conn.execute(
        "SELECT id, direction, initiator_process, initiator_user, service_process, service_user, "
        "bytes_in, bytes_out, own_bytes_in, own_bytes_out FROM flows WHERE conn_key = ? ORDER BY id",
        (conn_key,)).fetchall()
    if not rows:
        return
    outs = [row for row in rows if row["direction"] == FlowDirection.OUTBOUND.value]
    ins = [row for row in rows if row["direction"] == FlowDirection.INBOUND.value]
    primary = (outs or ins)[0]
    conn.execute("UPDATE flows SET is_primary = CASE WHEN id = ? THEN 1 ELSE 0 END WHERE conn_key = ?",
                 (primary["id"], conn_key))
    conn.execute("UPDATE flows SET initiator_process = ?, initiator_user = ? WHERE conn_key = ? AND direction = ?",
                 (_first([o["initiator_process"] for o in outs]), _first([o["initiator_user"] for o in outs]),
                  conn_key, FlowDirection.INBOUND.value))
    conn.execute("UPDATE flows SET service_process = ?, service_user = ? WHERE conn_key = ? AND direction = ?",
                 (_first([i["service_process"] for i in ins]), _first([i["service_user"] for i in ins]),
                  conn_key, FlowDirection.OUTBOUND.value))
    own = {row["id"]: (_own(row, "in"), _own(row, "out")) for row in rows}
    known_in = [v[0] for v in own.values() if v[0] is not None]
    known_out = [v[1] for v in own.values() if v[1] is not None]
    total = (max(known_in) if known_in else None, max(known_out) if known_out else None)
    for row in rows:
        want = total if row["id"] == primary["id"] else own[row["id"]]
        if (row["bytes_in"], row["bytes_out"]) != want:
            conn.execute("UPDATE flows SET bytes_in = ?, bytes_out = ? WHERE id = ?", (*want, row["id"]))


def _own(row: sqlite3.Row, side: str) -> int | None:
    """A row's own byte count; rows written before flow db 0002 as part of a pair have none recorded and
    keep what they show."""
    value: int | None = row[f"own_bytes_{side}"]
    if value is None:
        value = row[f"bytes_{side}"]
    return value


def _repair_tuple(conn: sqlite3.Connection, tup: tuple[str, str, int | None, int],
                  written: set[str]) -> tuple[set[str], int]:
    """Re-decide which records of one (src, dst, port, proto) are the same connection.

    Deterministic whatever order the records arrived in: outbound and inbound records are each
    taken in (first_detected, record_key) order, and every outbound record is matched with the
    first unmatched inbound record whose time range is within the pairing gap. Everything else
    stands alone — when it is unclear, count separately (spec §6.5.7).
    Returns (the connections that changed — those holding a record written in this batch, and
    both sides of every record that moved — and the pairs formed). Connections of the tuple that
    did not change are left alone: the tuple recurs daily, and touching them would mark every past
    day's rollup and archive as changed."""
    rows = conn.execute(
        "SELECT id, record_key, conn_key, direction, first_detected, last_detected FROM flows "
        "WHERE src_ip = ? AND dst_ip = ? AND port IS ? AND proto = ? ORDER BY first_detected, record_key", tup,
    ).fetchall()
    outs = [r for r in rows if r["direction"] == FlowDirection.OUTBOUND.value]
    ins = [r for r in rows if r["direction"] == FlowDirection.INBOUND.value]
    want = {r["id"]: str(r["record_key"]) for r in rows}
    used: set[int] = set()
    pairs = 0
    for o in outs:
        o_first, o_last = datetime.fromisoformat(o["first_detected"]), datetime.fromisoformat(o["last_detected"])
        for i in ins:
            if i["id"] in used:
                continue
            if ranges_within(o_first, o_last, datetime.fromisoformat(i["first_detected"]),
                             datetime.fromisoformat(i["last_detected"])):
                used.add(i["id"])
                want[i["id"]] = str(o["record_key"])
                pairs += 1
                break
    keys: set[str] = set()
    for r in rows:
        if r["conn_key"] != want[r["id"]]:
            conn.execute("UPDATE flows SET conn_key = ? WHERE id = ?", (want[r["id"]], r["id"]))
            keys |= {str(r["conn_key"]), want[r["id"]]}
        elif r["record_key"] in written:
            keys.add(want[r["id"]])
    return keys, pairs


# "+is_primary" keeps the planner on ix_flows_conn: left to itself it picks ix_flows_primary_last
# and walks every primary row, making each cycle slower as the store grows (test_query_plans).
PRIMARY_OF_CONNECTION = ("SELECT src_key, dst_key, port, proto, first_detected, last_detected, initiator_user, "
                         "policy_decision FROM flows WHERE conn_key = ? AND +is_primary = 1")


def _update_baselines(conn: sqlite3.Connection, conn_key: str) -> None:
    row = conn.execute(PRIMARY_OF_CONNECTION, (conn_key,)).fetchone()
    if row is None:
        return
    port = row["port"] if row["port"] is not None else NO_PORT
    # The newest observation's decision wins (SET expressions all read the row as it was before).
    conn.execute(
        "INSERT INTO connection_baseline (src_key, dst_key, port, proto, first_seen, last_seen, last_decision) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(src_key, dst_key, port, proto) DO UPDATE SET "
        "first_seen = MIN(first_seen, excluded.first_seen), last_seen = MAX(last_seen, excluded.last_seen), "
        "last_decision = CASE WHEN excluded.last_seen >= last_seen THEN excluded.last_decision ELSE last_decision END",
        (row["src_key"], row["dst_key"], port, row["proto"], row["first_detected"], row["last_detected"],
         row["policy_decision"]))
    if row["initiator_user"]:
        conn.execute(
            "INSERT INTO user_baseline (initiator_user, dst_key, port, proto, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(initiator_user, dst_key, port, proto) DO UPDATE SET "
            "first_seen = MIN(first_seen, excluded.first_seen), last_seen = MAX(last_seen, excluded.last_seen)",
            (row["initiator_user"], row["dst_key"], port, row["proto"], row["first_detected"], row["last_detected"]))


def split_unseen(conn: sqlite3.Connection, records: Sequence[FlowRecord]) -> tuple[list[FlowRecord], list[FlowRecord]]:
    """(records not stored yet, stored records with something to add). Read-only, so a caller can
    leave the unchanged ones out before it takes the write lock."""
    new: list[FlowRecord] = []
    grown: list[FlowRecord] = []
    for r in records:
        old = conn.execute(_STORED, (record_key(r),)).fetchone()
        if old is None:
            new.append(r)
        elif not _adds_nothing(old, r, DataOrigin.BACKFILL):  # backfill: an ingest row stays ingest
            grown.append(r)
    return new, grown


def upsert_flows(conn: sqlite3.Connection, records: Sequence[FlowRecord], *, origin: DataOrigin,
                 now: datetime) -> UpsertStats:
    """Write a batch in one transaction (nested in the caller's, if any). The caller holds
    FlowDb.write_lock."""
    stamp = db_time(now)
    inserted = refreshed = paired = unchanged = 0
    days: set[str] = set()
    tuples: set[tuple[str, str, int | None, int]] = set()
    written: set[str] = set()
    with transaction(conn):
        for r in records:
            key = record_key(r)
            old = conn.execute(_STORED, (key,)).fetchone()
            if old is not None and _adds_nothing(old, r, origin):
                unchanged += 1
                continue
            written.add(key)
            if old is not None:
                days.add(str(old["last_detected"])[:10])
                _refresh(conn, int(old["id"]), r, origin, stamp)
                refreshed += 1
            else:
                _insert(conn, r, key, key, origin, stamp)
                inserted += 1
            tuples.add((r.src_ip, r.dst_ip, r.port, r.proto))
        keys: set[str] = set()
        for tup in sorted(tuples, key=str):
            tup_keys, tup_pairs = _repair_tuple(conn, tup, written)
            keys |= tup_keys
            paired += tup_pairs
        ordered = sorted(keys)
        for conn_key in ordered:
            _merge_connection(conn, conn_key)
            _update_baselines(conn, conn_key)
        for i in range(0, len(ordered), 500):  # every row of a changed connection may have changed
            chunk = ordered[i:i + 500]
            days |= {d for (d,) in conn.execute(
                f"SELECT DISTINCT substr(last_detected, 1, 10) FROM flows WHERE conn_key IN ({','.join('?' * len(chunk))})",
                chunk)}
        archive.mark_stale(conn, "flows", days)
        conn.executemany("INSERT INTO rollup_state (day, dirty) VALUES (?, 1) "
                         "ON CONFLICT(day) DO UPDATE SET dirty = 1", [(d,) for d in sorted(days)])
    return UpsertStats(inserted=inserted, refreshed=refreshed, paired=paired, days_touched=frozenset(days),
                       unchanged=unchanged)


ROLLUP_INSERT = (
    "INSERT INTO flow_rollup_daily (day, src_key, dst_key, port, proto, policy_decision, initiator_user, "
    "initiator_process, connections, flow_records, bytes_in, bytes_out, bytes_known_records) "
    "SELECT ?, src_key, dst_key, COALESCE(port, ?), proto, policy_decision, COALESCE(initiator_user, ''), "
    "COALESCE(initiator_process, ''), SUM(num_connections), COUNT(*), COALESCE(SUM(bytes_in), 0), "
    "COALESCE(SUM(bytes_out), 0), COUNT(bytes_in) FROM flows "
    "WHERE is_primary = 1 AND last_detected >= ? AND last_detected < ? "
    "GROUP BY src_key, dst_key, COALESCE(port, ?), proto, policy_decision, COALESCE(initiator_user, ''), "
    "COALESCE(initiator_process, '')")


def rebuild_rollup(conn: sqlite3.Connection, day: str, *, at: datetime | None = None) -> int:
    """Recompute one UTC day from the primary rows whose last_detected falls in it."""
    start = datetime.fromisoformat(f"{day}T00:00:00+00:00")
    lo, hi = db_time(start), db_time(start + timedelta(days=1))
    with transaction(conn):
        conn.execute("DELETE FROM flow_rollup_daily WHERE day = ?", (day,))
        cur = conn.execute(ROLLUP_INSERT, (day, NO_PORT, lo, hi, NO_PORT))
        conn.execute("INSERT INTO rollup_state (day, dirty, built_at) VALUES (?, 0, ?) "
                     "ON CONFLICT(day) DO UPDATE SET dirty = 0, built_at = excluded.built_at",
                     (day, db_time(at or datetime.now(UTC))))
        return cur.rowcount


TODAY_ROLLUP_EVERY = timedelta(hours=1)


def refresh_rollups(conn: sqlite3.Connection, at: datetime, *, today_every: timedelta = TODAY_ROLLUP_EVERY,
                    frozen_through: str | None = None) -> list[str]:
    """Rebuild the rollups that changed: a past day at once (a backfill, a late record, or the day that
    just closed), today only if its last rebuild is at least today_every old. Returns the days rebuilt.
    A day up to frozen_through (the raw-flow retention cutoff's day) that was built before is left as
    it is: retention may have dropped some of its rows, so they no longer add up to its rollup."""
    today = db_day(at)
    due, frozen = [], []
    for day, built_at in conn.execute("SELECT day, built_at FROM rollup_state WHERE dirty = 1 ORDER BY day"):
        if frozen_through is not None and day <= frozen_through and built_at is not None:
            frozen.append((day,))
        elif day < today or built_at is None or at - datetime.fromisoformat(built_at) >= today_every:
            due.append(day)
    if frozen:
        with transaction(conn):
            conn.executemany("UPDATE rollup_state SET dirty = 0 WHERE day = ?", frozen)
    for day in due:
        rebuild_rollup(conn, day, at=at)
    return due



def expired_page(conn: sqlite3.Connection, cutoff: datetime, after: tuple[str, int], limit: int) -> list[sqlite3.Row]:
    """The next `limit` rows last seen before cutoff, in (last_detected, id) order after `after`;
    ix_flows_last serves it, so a page costs its own rows, not a pass over the table."""
    return conn.execute(
        "SELECT last_detected, id, conn_key FROM flows WHERE last_detected < ? AND (last_detected, id) > (?, ?) "
        "ORDER BY last_detected, id LIMIT ?", (db_time(cutoff), after[0], after[1], limit)).fetchall()


def delete_connections_before(conn: sqlite3.Connection, cutoff: datetime, *, conn_keys: Sequence[str],
                              archived_days: set[str] | None) -> int:
    """Of these connections, delete those whose newest record is older than cutoff; with
    archived_days, only those every row of which lies on an archived day (the two halves of a
    pair can fall on different days). Returns the connections deleted."""
    rows: dict[str, list[tuple[int, str]]] = {}
    for i in range(0, len(conn_keys), 500):
        chunk = list(conn_keys[i:i + 500])
        for rid, key, last in conn.execute(
                f"SELECT id, conn_key, last_detected FROM flows WHERE conn_key IN ({','.join('?' * len(chunk))})",
                chunk):
            rows.setdefault(key, []).append((rid, last))
    c = db_time(cutoff)
    doomed = [found for found in rows.values()
              if max(last for _, last in found) < c
              and (archived_days is None or {last[:10] for _, last in found} <= archived_days)]
    with transaction(conn):
        # in table order: rows of one day sit together, so this walks the table instead of jumping
        conn.executemany("DELETE FROM flows WHERE id = ?", sorted((rid,) for found in doomed for rid, _ in found))
    return len(doomed)


def delete_rollups_before(conn: sqlite3.Connection, day: str) -> int:
    with transaction(conn):
        conn.execute("DELETE FROM rollup_state WHERE day < ?", (day,))
        return conn.execute("DELETE FROM flow_rollup_daily WHERE day < ?", (day,)).rowcount


def delete_baselines_before(conn: sqlite3.Connection, cutoff: datetime) -> int:
    """A connection not seen within the baseline window is 'new' again when it reappears."""
    with transaction(conn):
        n = conn.execute("DELETE FROM connection_baseline WHERE last_seen < ?", (db_time(cutoff),)).rowcount
        return n + conn.execute("DELETE FROM user_baseline WHERE last_seen < ?", (db_time(cutoff),)).rowcount
