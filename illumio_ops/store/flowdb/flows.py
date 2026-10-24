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
from datetime import datetime, timedelta

from illumio_ops.domain.flows import FlowRecord, ranges_within, record_key
from illumio_ops.domain.identity import endpoint_key
from illumio_ops.domain.values import DataOrigin, FlowDirection
from illumio_ops.store.flowdb.db import db_time
from illumio_ops.store.flowdb.labels import label_set_id

NO_PORT = -1  # rollup and baseline keys cannot be NULL


@dataclass(frozen=True)
class UpsertStats:
    inserted: int
    refreshed: int
    paired: int
    days_touched: frozenset[str]


def _max_bytes(column: str) -> str:
    # A NULL (no byte data) never replaces a known count; a smaller re-pull never shrinks it.
    return f"{column} = CASE WHEN ? IS NULL THEN {column} WHEN {column} IS NULL THEN ? ELSE MAX({column}, ?) END"


_REFRESH = (
    "UPDATE flows SET "
    "last_detected = MAX(last_detected, ?), "
    "num_connections = MAX(num_connections, ?), "
    f"{_max_bytes('bytes_in')}, {_max_bytes('bytes_out')}, "
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
    "bytes_in, bytes_out, state, transmission, network_href, origin, ingested_at) "
    "VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def _find_partner(conn: sqlite3.Connection, r: FlowRecord) -> str | None:
    rows = conn.execute(
        "SELECT conn_key, first_detected, last_detected FROM flows "
        "WHERE src_ip = ? AND dst_ip = ? AND proto = ? AND port IS ? AND direction != ? "
        "ORDER BY is_primary DESC, id",
        (r.src_ip, r.dst_ip, r.proto, r.port, r.direction.value),
    ).fetchall()
    for row in rows:
        if ranges_within(r.first_detected, r.last_detected,
                         datetime.fromisoformat(row["first_detected"]), datetime.fromisoformat(row["last_detected"])):
            return str(row["conn_key"])
    return None


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
        r.num_connections, r.bytes_in, r.bytes_out, r.state, r.transmission, r.network_href,
        origin.value, stamp,
    ))


def _refresh(conn: sqlite3.Connection, row_id: int, r: FlowRecord, origin: DataOrigin, stamp: str) -> None:
    last = db_time(r.last_detected)
    conn.execute(_REFRESH, (
        last, r.num_connections,
        r.bytes_in, r.bytes_in, r.bytes_in, r.bytes_out, r.bytes_out, r.bytes_out,
        last, r.state,
        r.own_process, r.own_user, r.own_process, r.own_user,
        origin.value, origin.value, stamp, row_id,
    ))


def _first(values: list[str | None]) -> str | None:
    return next((v for v in values if v), None)


def _merge_connection(conn: sqlite3.Connection, conn_key: str) -> set[str]:
    """Pick the primary row and complete each row with the other side's attributes.
    Returns the days (of last_detected) of every row in the connection."""
    rows = conn.execute(
        "SELECT id, direction, initiator_process, initiator_user, service_process, service_user, "
        "bytes_in, bytes_out, last_detected FROM flows WHERE conn_key = ? ORDER BY id", (conn_key,)).fetchall()
    days = {str(row["last_detected"])[:10] for row in rows}
    outs = [row for row in rows if row["direction"] == FlowDirection.OUTBOUND.value]
    ins = [row for row in rows if row["direction"] == FlowDirection.INBOUND.value]
    primary = (outs or ins)[0]
    conn.execute("UPDATE flows SET is_primary = CASE WHEN id = ? THEN 1 ELSE 0 END WHERE conn_key = ?",
                 (primary["id"], conn_key))
    if len(rows) == 1:
        return days
    conn.execute("UPDATE flows SET initiator_process = ?, initiator_user = ? WHERE conn_key = ? AND direction = ?",
                 (_first([o["initiator_process"] for o in outs]), _first([o["initiator_user"] for o in outs]),
                  conn_key, FlowDirection.INBOUND.value))
    conn.execute("UPDATE flows SET service_process = ?, service_user = ? WHERE conn_key = ? AND direction = ?",
                 (_first([i["service_process"] for i in ins]), _first([i["service_user"] for i in ins]),
                  conn_key, FlowDirection.OUTBOUND.value))
    known_in = [row["bytes_in"] for row in rows if row["bytes_in"] is not None]
    known_out = [row["bytes_out"] for row in rows if row["bytes_out"] is not None]
    conn.execute("UPDATE flows SET bytes_in = ?, bytes_out = ? WHERE id = ?",
                 (max(known_in) if known_in else None, max(known_out) if known_out else None, primary["id"]))
    return days


def _update_baselines(conn: sqlite3.Connection, conn_key: str) -> None:
    row = conn.execute(
        "SELECT src_key, dst_key, port, proto, first_detected, last_detected, initiator_user FROM flows "
        "WHERE conn_key = ? AND is_primary = 1", (conn_key,)).fetchone()
    if row is None:
        return
    port = row["port"] if row["port"] is not None else NO_PORT
    conn.execute(
        "INSERT INTO connection_baseline (src_key, dst_key, port, proto, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(src_key, dst_key, port, proto) DO UPDATE SET "
        "first_seen = MIN(first_seen, excluded.first_seen), last_seen = MAX(last_seen, excluded.last_seen)",
        (row["src_key"], row["dst_key"], port, row["proto"], row["first_detected"], row["last_detected"]))
    if row["initiator_user"]:
        conn.execute(
            "INSERT INTO user_baseline (initiator_user, dst_key, port, proto, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(initiator_user, dst_key, port, proto) DO UPDATE SET "
            "first_seen = MIN(first_seen, excluded.first_seen), last_seen = MAX(last_seen, excluded.last_seen)",
            (row["initiator_user"], row["dst_key"], port, row["proto"], row["first_detected"], row["last_detected"]))


def upsert_flows(conn: sqlite3.Connection, records: Sequence[FlowRecord], *, origin: DataOrigin,
                 now: datetime) -> UpsertStats:
    """Write a batch in one transaction. The caller holds FlowDb.write_lock."""
    stamp = db_time(now)
    inserted = refreshed = paired = 0
    days: set[str] = set()
    touched: set[str] = set()
    with conn:
        for r in records:
            key = record_key(r)
            old = conn.execute("SELECT id, conn_key, last_detected FROM flows WHERE record_key = ?", (key,)).fetchone()
            if old is not None:
                days.add(str(old["last_detected"])[:10])
                _refresh(conn, int(old["id"]), r, origin, stamp)
                touched.add(str(old["conn_key"]))
                refreshed += 1
                continue
            partner = _find_partner(conn, r)
            conn_key = partner or key
            paired += partner is not None
            _insert(conn, r, key, conn_key, origin, stamp)
            touched.add(conn_key)
            inserted += 1
        for conn_key in touched:
            days |= _merge_connection(conn, conn_key)
            _update_baselines(conn, conn_key)
    return UpsertStats(inserted=inserted, refreshed=refreshed, paired=paired, days_touched=frozenset(days))


def rebuild_rollup(conn: sqlite3.Connection, day: str) -> int:
    """Recompute one UTC day from the primary rows whose last_detected falls in it."""
    start = datetime.fromisoformat(f"{day}T00:00:00+00:00")
    lo, hi = db_time(start), db_time(start + timedelta(days=1))
    with conn:
        conn.execute("DELETE FROM flow_rollup_daily WHERE day = ?", (day,))
        cur = conn.execute(
            "INSERT INTO flow_rollup_daily (day, src_key, dst_key, port, proto, policy_decision, initiator_user, "
            "initiator_process, connections, flow_records, bytes_in, bytes_out, bytes_known_records) "
            "SELECT ?, src_key, dst_key, COALESCE(port, ?), proto, policy_decision, COALESCE(initiator_user, ''), "
            "COALESCE(initiator_process, ''), SUM(num_connections), COUNT(*), COALESCE(SUM(bytes_in), 0), "
            "COALESCE(SUM(bytes_out), 0), COUNT(bytes_in) FROM flows "
            "WHERE is_primary = 1 AND last_detected >= ? AND last_detected < ? "
            "GROUP BY src_key, dst_key, COALESCE(port, ?), proto, policy_decision, COALESCE(initiator_user, ''), "
            "COALESCE(initiator_process, '')",
            (day, NO_PORT, lo, hi, NO_PORT))
        return cur.rowcount

