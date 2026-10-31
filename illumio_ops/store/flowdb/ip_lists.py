"""The PCE's active IP lists (owner of ip_lists and ip_list_nets): a name to pick and the networks a filter's
ip_lists part matches (filter.to_sql reads ip_list_nets directly)."""
from __future__ import annotations

import sqlite3
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime

from illumio_ops.store.flowdb.db import db_time


@dataclass(frozen=True)
class IpListRow:
    href: str
    name: str
    nets: tuple[str, ...]


def replace_all(conn: sqlite3.Connection, rows: Sequence[IpListRow], *, at: datetime) -> None:
    """The caller holds the transaction."""
    conn.execute("DELETE FROM ip_list_nets")
    conn.execute("DELETE FROM ip_lists")
    stamp = db_time(at)
    conn.executemany("INSERT INTO ip_lists (href, name, fetched_at) VALUES (?, ?, ?)",
                     [(r.href, r.name, stamp) for r in rows])
    conn.executemany("INSERT INTO ip_list_nets (href, net) VALUES (?, ?)",
                     [(r.href, n) for r in rows for n in r.nets])


def names(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """(href, name) of every list, by name."""
    return [(r[0], r[1]) for r in conn.execute("SELECT href, name FROM ip_lists ORDER BY name, href")]


def networks(conn: sqlite3.Connection, hrefs: Collection[str] | None = None) -> dict[str, tuple[str, ...]]:
    """href -> its networks; every list when hrefs is None. A list the PCE no longer has is absent: it matches nothing."""
    sql, params = "SELECT href, net FROM ip_list_nets", list(hrefs or ())
    if hrefs is not None:
        if not hrefs:
            return {}
        sql += f" WHERE href IN ({','.join('?' * len(params))})"
    out: dict[str, list[str]] = {}
    for href, net in conn.execute(sql, params):
        out.setdefault(href, []).append(net)
    return {h: tuple(v) for h, v in out.items()}


def copy_from(conn: sqlite3.Connection, schema: str) -> None:
    """Copy the lists from an attached store (an on-demand store starts from the install's, ondemand.py)."""
    conn.execute(f"INSERT INTO ip_lists SELECT * FROM {schema}.ip_lists")
    conn.execute(f"INSERT INTO ip_list_nets SELECT * FROM {schema}.ip_list_nets")
