"""SIEM forwarding state in data/app.sqlite (owner of siem_cursor, siem_dlq and siem_stats): where each destination got
to in each source, what it would not take, and what it sent and failed over time. The services decide; this module only
stores."""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
    floor_time: datetime | None = None  # a destination carried over from 5.x: what 5.x already sent is at or before


def _cursor(row: sqlite3.Row) -> Cursor:
    return Cursor(destination_id=row["destination_id"], source=row["source"], pce_url=row["pce_url"],
                  org_id=row["org_id"], last_id=int(row["last_id"]), head_id=row["head_id"],
                  head_attempts=int(row["head_attempts"]), sent=int(row["sent"]), dropped=int(row["dropped"]),
                  last_sent_at=datetime.fromisoformat(row["last_sent_at"]) if row["last_sent_at"] else None,
                  last_error=row["last_error"],
                  last_error_at=datetime.fromisoformat(row["last_error_at"]) if row["last_error_at"] else None,
                  floor_time=datetime.fromisoformat(row["floor_time"]) if row["floor_time"] else None)


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


def set_floor(conn: sqlite3.Connection, destination_id: str, source: str, floor: datetime | None) -> None:
    """P8 handover: records at or before floor are passed over without sending (None: the floor goes)."""
    with conn:
        conn.execute("UPDATE siem_cursor SET floor_time = ? WHERE destination_id = ? AND source = ?",
                     (_t(floor), destination_id, source))


def advance(conn: sqlite3.Connection, destination_id: str, source: str, *, pce_url: str, org_id: str, last_id: int,
            sent: int, at: datetime) -> bool:
    """Move the cursor to last_id after sending `sent` records, counted in the same transaction; False (nothing
    written) when the cursor now belongs to another PCE — a switch landed while the batch was out."""
    with conn:
        moved = conn.execute(
            "UPDATE siem_cursor SET last_id = MAX(last_id, :last), sent = sent + :sent, "
            "last_sent_at = COALESCE(:at, last_sent_at), "
            # the failing record's count is kept until the cursor is past it (a batch that sent nothing moves nothing)
            "head_attempts = CASE WHEN head_id IS NULL OR :last >= head_id THEN 0 ELSE head_attempts END, "
            "head_id = CASE WHEN head_id IS NULL OR :last >= head_id THEN NULL ELSE head_id END "
            "WHERE destination_id = :dest AND source = :source AND pce_url = :pce AND org_id = :org",
            {"last": last_id, "sent": sent, "at": _t(at) if sent else None, "dest": destination_id, "source": source,
             "pce": pce_url, "org": org_id}).rowcount > 0
        if moved and sent:
            _count(conn, destination_id, at, sent=sent, failed=0)
    return moved


def record_failure(conn: sqlite3.Connection, destination_id: str, source: str, *, head_id: int | None, error: str,
                   at: datetime) -> int:
    """A failed send of the batch starting at head_id (one failed attempt in the counts); returns how many times that
    record has now failed."""
    with conn:
        conn.execute(
            "UPDATE siem_cursor SET head_attempts = CASE WHEN head_id IS ? THEN head_attempts + 1 ELSE 1 END, "
            "head_id = ?, last_error = ?, last_error_at = ? WHERE destination_id = ? AND source = ?",
            (head_id, head_id, error[:2000], _t(at), destination_id, source))
        _count(conn, destination_id, at, sent=0, failed=1)
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


def restart_flow_cursors(conn: sqlite3.Connection, *, pce_url: str, org_id: str) -> None:
    """A PCE switch recreates the flow store: its sources start again at its beginning, for the new PCE — what is
    collected for it before the next SIEM run is sent (a backfill's history is not: audit sends live events only)."""
    with conn:
        conn.execute(f"UPDATE siem_cursor SET last_id = 0, pce_url = ?, org_id = ?, head_id = NULL, head_attempts = 0 "
                     f"WHERE source IN ({','.join('?' * len(FLOW_SOURCES))})", (pce_url, org_id, *FLOW_SOURCES))


def forget_destination(conn: sqlite3.Connection, destination_id: str, keep_sources: Sequence[str]) -> None:
    """Cursors of a removed destination, or of sources a destination no longer takes (taking one again starts over
    from the newest record, like a new destination)."""
    with conn:
        if not keep_sources:  # NOT IN (NULL) would match nothing: a removed destination keeps no cursor
            conn.execute("DELETE FROM siem_cursor WHERE destination_id = ?", (destination_id,))
            return
        conn.execute(f"DELETE FROM siem_cursor WHERE destination_id = ? AND source NOT IN "
                     f"({','.join('?' * len(keep_sources))})", (destination_id, *keep_sources))


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
    sent_as: str
    error: str
    attempts: int
    quarantined_at: datetime


def _dead(row: sqlite3.Row) -> DeadLetter:
    return DeadLetter(id=row["id"], destination_id=row["destination_id"], source=row["source"],
                      record_id=row["record_id"], external_id=row["external_id"],
                      event_time=datetime.fromisoformat(row["event_time"]) if row["event_time"] else None,
                      payload=row["payload"], sent_as=row["sent_as"], error=row["error"], attempts=int(row["attempts"]),
                      quarantined_at=datetime.fromisoformat(row["quarantined_at"]))


def _where(destination_id: str | None, error: str | None) -> tuple[str, list[object]]:
    """The DLQ filter: a destination, and lines whose error contains a text as written (no wildcards)."""
    parts: list[str] = ["1 = 1"]
    args: list[object] = []
    if destination_id is not None:
        parts.append("destination_id = ?")
        args.append(destination_id)
    if error:
        parts.append("instr(error, ?) > 0")
        args.append(error)
    return " AND ".join(parts), args


def dlq_count(conn: sqlite3.Connection, destination_id: str | None = None, *, error: str | None = None) -> int:
    where, args = _where(destination_id, error)
    return int(conn.execute(f"SELECT COUNT(*) FROM siem_dlq WHERE {where}", args).fetchone()[0])


def dlq_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {r[0]: int(r[1]) for r in conn.execute("SELECT destination_id, COUNT(*) FROM siem_dlq GROUP BY 1")}


def quarantine(conn: sqlite3.Connection, *, destination_id: str, source: str, record_id: int, external_id: str,
               event_time: datetime | None, payload: str, sent_as: str, error: str, attempts: int,
               at: datetime) -> None:
    with conn:
        conn.execute(
            "INSERT INTO siem_dlq (destination_id, source, record_id, external_id, event_time, payload, sent_as, error, "
            "attempts, quarantined_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (destination_id, source, record_id, external_id, _t(event_time), payload, sent_as, error[:2000], attempts,
             _t(at)))


def dlq_page(conn: sqlite3.Connection, *, destination_id: str | None, limit: int, offset: int,
             error: str | None = None) -> list[DeadLetter]:
    where, args = _where(destination_id, error)
    rows = conn.execute(f"SELECT * FROM siem_dlq WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                        [*args, limit, offset]).fetchall()
    return [_dead(r) for r in rows]


def dlq_get(conn: sqlite3.Connection, dead_id: int) -> DeadLetter | None:
    row = conn.execute("SELECT * FROM siem_dlq WHERE id = ?", (dead_id,)).fetchone()
    return _dead(row) if row else None


def dlq_by_ids(conn: sqlite3.Connection, ids: Sequence[int]) -> list[DeadLetter]:
    out: list[DeadLetter] = []
    for i in range(0, len(ids), 500):
        chunk = list(ids[i:i + 500])
        out += [_dead(r) for r in conn.execute(
            f"SELECT * FROM siem_dlq WHERE id IN ({','.join('?' * len(chunk))}) ORDER BY id", chunk)]
    return out


def dlq_after(conn: sqlite3.Connection, *, destination_id: str | None, after_id: int, limit: int,
              error: str | None = None) -> list[DeadLetter]:
    """Oldest first, after an id: export and resend-all page through the whole DLQ with this."""
    where, args = _where(destination_id, error)
    rows = conn.execute(f"SELECT * FROM siem_dlq WHERE {where} AND id > ? ORDER BY id LIMIT ?",
                        [*args, after_id, limit]).fetchall()
    return [_dead(r) for r in rows]


def dlq_delete(conn: sqlite3.Connection, ids: Sequence[int]) -> int:
    n = 0
    with conn:
        for i in range(0, len(ids), 500):
            chunk = list(ids[i:i + 500])
            n += conn.execute(f"DELETE FROM siem_dlq WHERE id IN ({','.join('?' * len(chunk))})", chunk).rowcount
    return n


def dlq_purge(conn: sqlite3.Connection, destination_id: str | None, *, error: str | None = None) -> int:
    """Every line of a destination (or of every destination), narrowed to an error text when given."""
    where, args = _where(destination_id, error)
    with conn:
        return conn.execute(f"DELETE FROM siem_dlq WHERE {where}", args).rowcount


def dlq_purge_before(conn: sqlite3.Connection, destination_id: str | None, before: datetime, *,
                     error: str | None = None) -> int:
    """Lines moved to the DLQ before a time (of a destination, or of every destination; of an error text)."""
    where, args = _where(destination_id, error)
    with conn:
        return conn.execute(f"DELETE FROM siem_dlq WHERE {where} AND quarantined_at < ?", [*args, _t(before)]).rowcount


def dlq_failed_again(conn: sqlite3.Connection, dead_id: int, error: str) -> None:
    with conn:
        conn.execute("UPDATE siem_dlq SET attempts = attempts + 1, error = ? WHERE id = ?", (error[:2000], dead_id))


# ── sends over time ──────────────────────────────────────────────────────────

BUCKET = timedelta(minutes=10)
STATS_KEEP = timedelta(days=8)  # the longest window shown is 7 days


@dataclass(frozen=True)
class Sends:
    sent: int
    failed: int


def _bucket(at: datetime) -> str:
    at = at.astimezone(UTC)
    return at.replace(minute=at.minute - at.minute % 10, second=0, microsecond=0).isoformat()


def _count(conn: sqlite3.Connection, destination_id: str, at: datetime, *, sent: int, failed: int) -> None:
    conn.execute(
        "INSERT INTO siem_stats (destination_id, bucket, sent, failed) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(destination_id, bucket) DO UPDATE SET sent = sent + excluded.sent, failed = failed + excluded.failed",
        (destination_id, _bucket(at), sent, failed))


def record_sends(conn: sqlite3.Connection, destination_id: str, at: datetime, *, sent: int = 0, failed: int = 0) -> None:
    """Lines sent and failed attempts outside a cursor's move: a refused or unformattable record, a DLQ resend."""
    if sent or failed:
        with conn:
            _count(conn, destination_id, at, sent=sent, failed=failed)


def sends_since(conn: sqlite3.Connection, since: datetime) -> dict[str, Sends]:
    """Per destination, the sends of every bucket from the one holding `since`: a window reaches back up to one
    bucket (10 minutes) further than asked."""
    return {r[0]: Sends(int(r[1]), int(r[2])) for r in conn.execute(
        "SELECT destination_id, SUM(sent), SUM(failed) FROM siem_stats WHERE bucket >= ? GROUP BY 1",
        (_bucket(since),))}


def delete_sends_before(conn: sqlite3.Connection, before: datetime) -> int:
    with conn:
        return conn.execute("DELETE FROM siem_stats WHERE bucket < ?", (_bucket(before),)).rowcount


def move_pce(conn: sqlite3.Connection, *, old_url: str, new_url: str, org_id: str) -> int:
    """The same PCE moved to a new address (System › PCE connection, decision D3): its rows follow it."""
    # The flow store is kept, so the cursors into it stay valid.
    return int(conn.execute("UPDATE siem_cursor SET pce_url = ? WHERE pce_url = ? AND org_id = ?",
                            (new_url, old_url, org_id)).rowcount)
