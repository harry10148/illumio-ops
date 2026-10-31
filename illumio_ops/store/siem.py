"""SIEM forwarding state in data/app.sqlite (owner of siem_cursor and siem_dlq): where each destination got to in
each source, and what it would not take. The services decide; this module only stores."""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

FLOW_SOURCES = ("audit", "detections", "new_connections")  # their ids live in the flow store a PCE switch recreates


def _t(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass(frozen=True)
class Cursor:
    destination_id: str
    source: str
    pce_url: str
    org_id: str
    last_id: int
    head_id: int | None
    head_attempts: int
    sent: int
    dropped: int
    last_sent_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None


def _cursor(row: sqlite3.Row) -> Cursor:
    return Cursor(destination_id=row["destination_id"], source=row["source"], pce_url=row["pce_url"],
                  org_id=row["org_id"], last_id=int(row["last_id"]), head_id=row["head_id"],
                  head_attempts=int(row["head_attempts"]), sent=int(row["sent"]), dropped=int(row["dropped"]),
                  last_sent_at=datetime.fromisoformat(row["last_sent_at"]) if row["last_sent_at"] else None,
                  last_error=row["last_error"],
                  last_error_at=datetime.fromisoformat(row["last_error_at"]) if row["last_error_at"] else None)


def cursors(conn: sqlite3.Connection) -> dict[tuple[str, str], Cursor]:
    return {(r["destination_id"], r["source"]): _cursor(r) for r in conn.execute("SELECT * FROM siem_cursor")}


def get_cursor(conn: sqlite3.Connection, destination_id: str, source: str) -> Cursor | None:
    row = conn.execute("SELECT * FROM siem_cursor WHERE destination_id = ? AND source = ?",
                       (destination_id, source)).fetchone()
    return _cursor(row) if row else None


def start_cursor(conn: sqlite3.Connection, destination_id: str, source: str, *, pce_url: str, org_id: str,
                 last_id: int) -> None:
    """A new cursor (or one of another PCE) at last_id: what is already stored is not sent."""
    with conn:
        conn.execute(
            "INSERT INTO siem_cursor (destination_id, source, pce_url, org_id, last_id) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(destination_id, source) DO UPDATE SET pce_url = excluded.pce_url, org_id = excluded.org_id, "
            "last_id = excluded.last_id, head_id = NULL, head_attempts = 0",
            (destination_id, source, pce_url, org_id, last_id))


def advance(conn: sqlite3.Connection, destination_id: str, source: str, *, pce_url: str, org_id: str, last_id: int,
            sent: int, at: datetime) -> bool:
    """Move the cursor to last_id after sending `sent` records; False (nothing written) when the cursor now belongs to
    another PCE — a switch landed while the batch was out."""
    with conn:
        return conn.execute(
            "UPDATE siem_cursor SET last_id = MAX(last_id, :last), sent = sent + :sent, "
            "last_sent_at = COALESCE(:at, last_sent_at), "
            # the failing record's count is kept until the cursor is past it (a batch that sent nothing moves nothing)
            "head_attempts = CASE WHEN head_id IS NULL OR :last >= head_id THEN 0 ELSE head_attempts END, "
            "head_id = CASE WHEN head_id IS NULL OR :last >= head_id THEN NULL ELSE head_id END "
            "WHERE destination_id = :dest AND source = :source AND pce_url = :pce AND org_id = :org",
            {"last": last_id, "sent": sent, "at": _t(at) if sent else None, "dest": destination_id, "source": source,
             "pce": pce_url, "org": org_id}).rowcount > 0


def record_failure(conn: sqlite3.Connection, destination_id: str, source: str, *, head_id: int | None, error: str,
                   at: datetime) -> int:
    """A failed send of the batch starting at head_id; returns how many times that record has now failed."""
    with conn:
        conn.execute(
            "UPDATE siem_cursor SET head_attempts = CASE WHEN head_id IS ? THEN head_attempts + 1 ELSE 1 END, "
            "head_id = ?, last_error = ?, last_error_at = ? WHERE destination_id = ? AND source = ?",
            (head_id, head_id, error[:2000], _t(at), destination_id, source))
        row = conn.execute("SELECT head_attempts FROM siem_cursor WHERE destination_id = ? AND source = ?",
                           (destination_id, source)).fetchone()
    return int(row[0]) if row else 0


def note_error(conn: sqlite3.Connection, destination_id: str, source: str, error: str, at: datetime) -> None:
    with conn:
        conn.execute("UPDATE siem_cursor SET last_error = ?, last_error_at = ? WHERE destination_id = ? AND source = ?",
                     (error[:2000], _t(at), destination_id, source))


def add_dropped(conn: sqlite3.Connection, counts: dict[tuple[str, str], int]) -> None:
    with conn:
        conn.executemany("UPDATE siem_cursor SET dropped = dropped + ? WHERE destination_id = ? AND source = ?",
                         [(n, d, s) for (d, s), n in counts.items() if n])


def forget_flow_cursors(conn: sqlite3.Connection) -> None:
    """A PCE switch recreates the flow store: its sources start over from the new store's newest id."""
    with conn:
        conn.execute(f"DELETE FROM siem_cursor WHERE source IN ({','.join('?' * len(FLOW_SOURCES))})", FLOW_SOURCES)


def forget_destination(conn: sqlite3.Connection, destination_id: str, keep_sources: Sequence[str]) -> None:
    """Cursors of a removed destination, or of sources a destination no longer takes (taking one again starts over
    from the newest record, like a new destination)."""
    with conn:
        conn.execute(f"DELETE FROM siem_cursor WHERE destination_id = ? AND source NOT IN "
                     f"({','.join('?' * len(keep_sources)) or 'NULL'})", (destination_id, *keep_sources))


# ── DLQ ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DeadLetter:
    id: int
    destination_id: str
    source: str
    record_id: int
    external_id: str
    event_time: datetime | None
    payload: str
    error: str
    attempts: int
    quarantined_at: datetime


def _dead(row: sqlite3.Row) -> DeadLetter:
    return DeadLetter(id=row["id"], destination_id=row["destination_id"], source=row["source"],
                      record_id=row["record_id"], external_id=row["external_id"],
                      event_time=datetime.fromisoformat(row["event_time"]) if row["event_time"] else None,
                      payload=row["payload"], error=row["error"], attempts=int(row["attempts"]),
                      quarantined_at=datetime.fromisoformat(row["quarantined_at"]))


def dlq_count(conn: sqlite3.Connection, destination_id: str | None = None) -> int:
    if destination_id is None:
        return int(conn.execute("SELECT COUNT(*) FROM siem_dlq").fetchone()[0])
    return int(conn.execute("SELECT COUNT(*) FROM siem_dlq WHERE destination_id = ?", (destination_id,)).fetchone()[0])


def dlq_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {r[0]: int(r[1]) for r in conn.execute("SELECT destination_id, COUNT(*) FROM siem_dlq GROUP BY 1")}


def quarantine(conn: sqlite3.Connection, *, destination_id: str, source: str, record_id: int, external_id: str,
               event_time: datetime | None, payload: str, error: str, attempts: int, at: datetime) -> None:
    with conn:
        conn.execute(
            "INSERT INTO siem_dlq (destination_id, source, record_id, external_id, event_time, payload, error, "
            "attempts, quarantined_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (destination_id, source, record_id, external_id, _t(event_time), payload, error[:2000], attempts, _t(at)))


def dlq_page(conn: sqlite3.Connection, *, destination_id: str | None, limit: int, offset: int) -> list[DeadLetter]:
    if destination_id is None:
        rows = conn.execute("SELECT * FROM siem_dlq ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM siem_dlq WHERE destination_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                            (destination_id, limit, offset)).fetchall()
    return [_dead(r) for r in rows]


def dlq_by_ids(conn: sqlite3.Connection, ids: Sequence[int]) -> list[DeadLetter]:
    out: list[DeadLetter] = []
    for i in range(0, len(ids), 500):
        chunk = list(ids[i:i + 500])
        out += [_dead(r) for r in conn.execute(
            f"SELECT * FROM siem_dlq WHERE id IN ({','.join('?' * len(chunk))}) ORDER BY id", chunk)]
    return out


def dlq_after(conn: sqlite3.Connection, *, destination_id: str | None, after_id: int, limit: int) -> list[DeadLetter]:
    """Oldest first, after an id: export and resend-all page through the whole DLQ with this."""
    if destination_id is None:
        rows = conn.execute("SELECT * FROM siem_dlq WHERE id > ? ORDER BY id LIMIT ?", (after_id, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM siem_dlq WHERE destination_id = ? AND id > ? ORDER BY id LIMIT ?",
                            (destination_id, after_id, limit)).fetchall()
    return [_dead(r) for r in rows]


def dlq_delete(conn: sqlite3.Connection, ids: Sequence[int]) -> int:
    n = 0
    with conn:
        for i in range(0, len(ids), 500):
            chunk = list(ids[i:i + 500])
            n += conn.execute(f"DELETE FROM siem_dlq WHERE id IN ({','.join('?' * len(chunk))})", chunk).rowcount
    return n


def dlq_purge(conn: sqlite3.Connection, destination_id: str | None) -> int:
    with conn:
        if destination_id is None:
            return conn.execute("DELETE FROM siem_dlq").rowcount
        return conn.execute("DELETE FROM siem_dlq WHERE destination_id = ?", (destination_id,)).rowcount


def dlq_failed_again(conn: sqlite3.Connection, dead_id: int, error: str) -> None:
    with conn:
        conn.execute("UPDATE siem_dlq SET attempts = attempts + 1, error = ? WHERE id = ?", (error[:2000], dead_id))
