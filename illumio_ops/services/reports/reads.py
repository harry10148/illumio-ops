"""The store reads report builders share. Every read checks the flow database still belongs to the configured
PCE and raises StaleGeneration when the PCE was switched while it read (the report then fails, spec §6.4)."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta

from illumio_ops.services.collect.guard import require_same_pce
from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb.db import StaleGeneration, db_day

PortSpec = tuple[int, int | None]  # (port, protocol or None for any)


@contextmanager
def reading(ctx: AppContext) -> Iterator[sqlite3.Connection]:
    fdb = ctx.flows()
    gen = fdb.generation  # noted before the settings it goes with (FlowDb.generation)
    settings = ctx.settings.current()
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        yield conn
    if fdb.generation != gen:
        raise StaleGeneration


def utc_days(start: datetime, end: datetime) -> tuple[str, str]:
    """The UTC days the daily rollups hold for [start, end): rollups are per UTC day, so a period that starts
    or ends inside a UTC day takes that whole day (the report says so)."""
    return db_day(start), db_day(end - timedelta(microseconds=1))


def port_clause(ports: Sequence[PortSpec], *, column: str = "port", proto_column: str = "proto") -> tuple[str, list[int]]:
    parts, params = [], []
    for port, proto in ports:
        if proto is None:
            parts.append(f"{column} = ?")
            params.append(port)
        else:
            parts.append(f"({column} = ? AND {proto_column} = ?)")
            params += [port, proto]
    return ("(" + " OR ".join(parts) + ")" if parts else "0"), params


def rollup_sources_on_ports(conn: sqlite3.Connection, days: tuple[str, str], ports: Sequence[PortSpec], *,
                            limit: int) -> list[tuple[str, int]]:
    """(source, connections) on these ports over the rollup days, not blocked, busiest first."""
    clause, params = port_clause(ports)
    return [(r[0], int(r[1])) for r in conn.execute(
        f"SELECT src_key, SUM(connections) AS n FROM flow_rollup_daily WHERE day >= ? AND day <= ? AND {clause} "
        "AND policy_decision NOT LIKE 'blocked%' GROUP BY src_key ORDER BY n DESC, src_key LIMIT ?",
        [*days, *params, limit])]


def rollup_connections_of(conn: sqlite3.Connection, days: tuple[str, str], ports: Sequence[PortSpec],
                          sources: Sequence[str]) -> dict[str, int]:
    """source -> connections on these ports over the rollup days, not blocked, for the given sources only."""
    if not sources:
        return {}
    clause, params = port_clause(ports)
    out: dict[str, int] = {}
    ordered = sorted(set(sources))
    for i in range(0, len(ordered), 500):
        chunk = ordered[i:i + 500]
        for src, n in conn.execute(
                f"SELECT src_key, SUM(connections) FROM flow_rollup_daily WHERE day >= ? AND day <= ? AND {clause} "
                f"AND policy_decision NOT LIKE 'blocked%' AND src_key IN ({','.join('?' * len(chunk))}) "
                "GROUP BY src_key", [*days, *params, *chunk]):
            out[src] = int(n)
    return out
