"""VEN compatibility as the PCE's compatibility report gives it (owner of ven_compat): its qualify status, the checks
that did not pass and when the PCE wrote it, one row per VEN."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from illumio_ops.store.flowdb.db import db_time, transaction


@dataclass(frozen=True)
class VenCompat:
    ven_href: str
    qualify_status: str | None  # green, yellow or red as the PCE says; None: the PCE has no report for this VEN
    issues: tuple[str, ...]     # the checks the PCE did not mark green, in its order
    report_at: str | None       # when the PCE wrote the report
    fetched_at: str


def record(conn: sqlite3.Connection, ven_href: str, *, qualify_status: str | None, issues: Sequence[str],
           report_at: str | None, at: datetime) -> None:
    with transaction(conn):
        conn.execute("INSERT OR REPLACE INTO ven_compat (ven_href, qualify_status, issues_json, report_at, fetched_at) "
                     "VALUES (?, ?, ?, ?, ?)", (ven_href, qualify_status, json.dumps(list(issues)), report_at,
                                                db_time(at)))


def fetched(conn: sqlite3.Connection) -> dict[str, str]:
    """VEN href -> when its report was last read."""
    return {r[0]: r[1] for r in conn.execute("SELECT ven_href, fetched_at FROM ven_compat")}


def by_ven(conn: sqlite3.Connection) -> dict[str, VenCompat]:
    return {r[0]: VenCompat(r[0], r[1], tuple(json.loads(r[2])), r[3], r[4]) for r in conn.execute(
        "SELECT ven_href, qualify_status, issues_json, report_at, fetched_at FROM ven_compat")}


def prune_missing(conn: sqlite3.Connection, keep: Iterable[str]) -> int:
    keep_set = set(keep)
    gone = [h for h in fetched(conn) if h not in keep_set]
    with transaction(conn):
        conn.executemany("DELETE FROM ven_compat WHERE ven_href = ?", [(h,) for h in gone])
    return len(gone)
