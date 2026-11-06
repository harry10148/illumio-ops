"""The PCE's active services and label groups (owner of pce_services, pce_service_ports, label_groups and
label_group_members): a name to pick, and what a flow condition naming one matches — a service's ports, a group's
labels (filter.to_sql reads the member tables directly). Like the IP lists, a failed read keeps the names and drops
what they match, so a condition naming one matches nothing until the next read."""
from __future__ import annotations

import sqlite3
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime

from illumio_ops.domain.policy_objects import PortEntry
from illumio_ops.store.flowdb.db import db_time


@dataclass(frozen=True)
class ServiceRow:
    href: str
    name: str
    ports: tuple[PortEntry, ...]


@dataclass(frozen=True)
class LabelGroupRow:
    href: str
    name: str
    key: str
    values: tuple[str, ...]  # the member labels' values (all of the group's key), sub-groups included


def replace_services(conn: sqlite3.Connection, rows: Sequence[ServiceRow], *, at: datetime) -> None:
    """The caller holds the transaction."""
    conn.execute("DELETE FROM pce_service_ports")
    conn.execute("DELETE FROM pce_services")
    stamp = db_time(at)
    conn.executemany("INSERT INTO pce_services (href, name, fetched_at) VALUES (?, ?, ?)",
                     [(r.href, r.name, stamp) for r in rows])
    conn.executemany("INSERT INTO pce_service_ports (href, port, to_port, proto) VALUES (?, ?, ?, ?)",
                     [(r.href, *p) for r in rows for p in r.ports])


def forget_service_ports(conn: sqlite3.Connection) -> None:
    """A failed read: the names stay, the ports go. The caller holds the transaction."""
    conn.execute("DELETE FROM pce_service_ports")


def replace_label_groups(conn: sqlite3.Connection, rows: Sequence[LabelGroupRow], *, at: datetime) -> None:
    """The caller holds the transaction."""
    conn.execute("DELETE FROM label_group_members")
    conn.execute("DELETE FROM label_groups")
    stamp = db_time(at)
    conn.executemany("INSERT INTO label_groups (href, name, key, fetched_at) VALUES (?, ?, ?, ?)",
                     [(r.href, r.name, r.key, stamp) for r in rows])
    conn.executemany("INSERT INTO label_group_members (href, key, value) VALUES (?, ?, ?)",
                     [(r.href, r.key, v) for r in rows for v in sorted(set(r.values))])


def forget_label_group_members(conn: sqlite3.Connection) -> None:
    """A failed read: the groups and their keys stay, the members go. The caller holds the transaction."""
    conn.execute("DELETE FROM label_group_members")


def service_names(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """(href, name) of every service, by name."""
    return [(r[0], r[1]) for r in conn.execute("SELECT href, name FROM pce_services ORDER BY name, href")]


def label_group_names(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """(href, name, key) of every label group, by key and name."""
    return [(r[0], r[1], r[2]) for r in conn.execute("SELECT href, name, key FROM label_groups ORDER BY key, name, href")]


def service_ports(conn: sqlite3.Connection, hrefs: Collection[str]) -> dict[str, tuple[PortEntry, ...]]:
    """href -> its ports. A service the PCE no longer has (or whose ports a failed read dropped) is absent."""
    if not hrefs:
        return {}
    out: dict[str, list[PortEntry]] = {}
    for href, port, to_port, proto in conn.execute(
            f"SELECT href, port, to_port, proto FROM pce_service_ports WHERE href IN ({','.join('?' * len(hrefs))})",
            sorted(hrefs)):
        out.setdefault(href, []).append((port, to_port, proto))
    return {h: tuple(v) for h, v in out.items()}


def label_groups(conn: sqlite3.Connection, hrefs: Collection[str]) -> dict[str, tuple[str, frozenset[str]]]:
    """href -> (key, member values). A group the PCE no longer has is absent (it matches nothing)."""
    if not hrefs:
        return {}
    marks = ",".join("?" * len(hrefs))
    out: dict[str, tuple[str, set[str]]] = {r[0]: (r[1], set()) for r in conn.execute(
        f"SELECT href, key FROM label_groups WHERE href IN ({marks})", sorted(hrefs))}
    for href, value in conn.execute(f"SELECT href, value FROM label_group_members WHERE href IN ({marks})",
                                    sorted(hrefs)):
        if href in out:
            out[href][1].add(value)
    return {h: (k, frozenset(v)) for h, (k, v) in out.items()}


def copy_from(conn: sqlite3.Connection, schema: str) -> None:
    """Copy the services and groups from an attached store (an on-demand store starts from the install's)."""
    conn.execute(f"INSERT INTO pce_services SELECT * FROM {schema}.pce_services")
    conn.execute(f"INSERT INTO pce_service_ports SELECT * FROM {schema}.pce_service_ports")
    conn.execute(f"INSERT INTO label_groups SELECT * FROM {schema}.label_groups")
    conn.execute(f"INSERT INTO label_group_members SELECT * FROM {schema}.label_group_members")
