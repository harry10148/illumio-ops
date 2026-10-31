"""Where a stopped 5.x got to (P8, spec §7 "切換時的連續性"), read only — never written:

- per SIEM destination (by its 5.x name), the audit events already sent: the floor is just before the oldest event
  still pending, or else the newest sent. 5.x sends in queue order, not event order, so an older event can still be
  pending behind newer sent ones; resending from it is at least once, which SIEM delivery already is (externalId
  dedups). Events 5.x gave up on (its DLQ, status 'failed') are counted, not resent.
- for event alerts, the events evaluated: with the cache on, the analyzer's cursor in ingestion_cursors, ordered by
  (ingested_at, id); otherwise logs/state.json's event_watermark.

5.x stores naive UTC datetimes ("2026-10-31 17:29:47.779000"). Nothing found means no floor: v6 starts at the upgrade
and the report says so.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_MS = timedelta(milliseconds=1)


@dataclass(frozen=True)
class Handover:
    audit_floors: dict[str, datetime | None]  # 5.x destination name -> sent through (None: nothing recorded)
    dlq_counts: dict[str, int]                # 5.x destination name -> audit events 5.x gave up on
    event_alert_floor: datetime | None


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    t = datetime.fromisoformat(str(value))  # 3.11+ reads a trailing Z
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def cache_store(v5_root: Path, raw: dict[str, Any]) -> Path:
    cache = raw.get("pce_cache") if isinstance(raw.get("pce_cache"), dict) else {}
    assert isinstance(cache, dict)
    path = Path(str(cache.get("db_path") or "data/pce_cache.sqlite"))
    return path if path.is_absolute() else v5_root / path  # 5.x opened it relative to its install root


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _destination(db: sqlite3.Connection, name: str) -> tuple[datetime | None, int]:
    pending =db.execute("SELECT MIN(e.timestamp) FROM siem_dispatch d JOIN pce_events e ON e.id = d.source_id "
                         "WHERE d.source_table = 'pce_events' AND d.destination = ? AND d.status = 'pending'",
                         (name,)).fetchone()[0]
    sent = db.execute("SELECT MAX(e.timestamp) FROM siem_dispatch d JOIN pce_events e ON e.id = d.source_id "
                      "WHERE d.source_table = 'pce_events' AND d.destination = ? AND d.status = 'sent'",
                      (name,)).fetchone()[0]
    failed = db.execute("SELECT COUNT(*) FROM siem_dispatch WHERE source_table = 'pce_events' AND destination = ? "
                        "AND status = 'failed'", (name,)).fetchone()[0]
    oldest_unsent = _time(pending)
    return (oldest_unsent - _MS if oldest_unsent else _time(sent)), int(failed)


def _analyzer(db: sqlite3.Connection) -> datetime | None:
    row = db.execute("SELECT last_ingested_at, last_row_id FROM ingestion_cursors WHERE consumer = 'analyzer' "
                     "AND source_table = 'pce_events'").fetchone()
    if row is None or row[0] is None:
        return None
    at, last = row[0], row[1] or 0
    after = db.execute("SELECT MIN(timestamp) FROM pce_events WHERE ingested_at > ? OR (ingested_at = ? AND id > ?)",
                       (at, at, last)).fetchone()[0]
    if after:
        first = _time(after)
        return first - _MS if first else None
    return _time(db.execute("SELECT MAX(timestamp) FROM pce_events WHERE ingested_at < ? "
                            "OR (ingested_at = ? AND id <= ?)", (at, at, last)).fetchone()[0])


def _state_json(v5_root: Path) -> datetime | None:
    try:
        state = json.loads((v5_root / "logs" / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict):
        return None
    try:
        return _time(state.get("event_watermark") or state.get("last_check"))
    except ValueError:
        return None


def read_handover(v5_root: Path, raw: dict[str, Any]) -> Handover:
    siem = raw.get("siem") if isinstance(raw.get("siem"), dict) else {}
    assert isinstance(siem, dict)
    names = [str(d.get("name") or "").strip() for d in siem.get("destinations") or [] if isinstance(d, dict)]
    floors: dict[str, datetime | None] = dict.fromkeys(names)
    dlq: dict[str, int] = dict.fromkeys(names, 0)
    cache_on = isinstance(raw.get("pce_cache"), dict) and raw["pce_cache"].get("enabled") is True
    alert_floor = None
    path = cache_store(v5_root, raw)
    if path.is_file():
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)  # never written, never a WAL checkpoint
        try:
            tables = _tables(db)
            if {"siem_dispatch", "pce_events"} <= tables:
                for name in names:
                    floors[name], dlq[name] = _destination(db, name)
            if cache_on and {"ingestion_cursors", "pce_events"} <= tables:
                alert_floor = _analyzer(db)
        finally:
            db.close()
    if alert_floor is None and not cache_on:
        alert_floor = _state_json(v5_root)
    return Handover(audit_floors=floors, dlq_counts=dlq, event_alert_floor=alert_floor)
