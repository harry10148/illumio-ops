"""FlowSource's reads for the anomaly detectors (spec §6.5.8): the account, process and connection baselines and
each source's hourly activity. Every read is by the keys a run's candidates name, never a pass over a table, and
raises StaleGeneration when the PCE was switched while it read (nothing of the previous PCE reaches a detector)."""
from __future__ import annotations

from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Any, TypeVar

from illumio_ops.domain.values import DIRECTORY_PORTS, IngestSource
from illumio_ops.services.collect.guard import require_same_pce
from illumio_ops.services.context import AppContext
from illumio_ops.services.coverage import store_coverage
from illumio_ops.store.flowdb.db import StaleGeneration, db_time

CHUNK = 200
T = TypeVar("T")


@contextmanager
def _reading(ctx: AppContext) -> Iterator[Any]:
    fdb = ctx.flows()
    gen = fdb.generation  # noted before the settings it goes with (FlowDb.generation)
    settings = ctx.settings.current()
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        yield conn
    if fdb.generation != gen:
        raise StaleGeneration


def _chunks(items: Collection[T]) -> Iterator[list[T]]:
    ordered = sorted(set(items), key=str)
    for i in range(0, len(ordered), CHUNK):
        yield ordered[i:i + CHUNK]


def _by_pairs(ctx: AppContext, sql: str, pairs: Collection[tuple[str, str]],
              row: Callable[[Any], tuple[tuple[str, str], datetime]]) -> dict[tuple[str, str], datetime]:
    out: dict[tuple[str, str], datetime] = {}
    with _reading(ctx) as conn:
        for chunk in _chunks(pairs):
            marks = ",".join("(?, ?)" for _ in chunk)
            for r in conn.execute(sql.format(marks=marks), [v for p in chunk for v in p]):
                k, v = row(r)
                out[k] = v
    return out


def _min_by(ctx: AppContext, sql: str, keys: Collection[str]) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    with _reading(ctx) as conn:
        for chunk in _chunks(keys):
            for k, first in conn.execute(sql.format(marks=",".join("?" * len(chunk))), chunk):
                out[k] = datetime.fromisoformat(first)
    return out


def account_first_seen(ctx: AppContext, pairs: Collection[tuple[str, str]]) -> dict[tuple[str, str], datetime]:
    """(account, src_key) -> when the baseline first saw the account start a connection there."""
    return _by_pairs(ctx, "SELECT account, src_key, first_seen FROM account_source_baseline "
                          "WHERE (account, src_key) IN (VALUES {marks})", pairs,
                     lambda r: ((r[0], r[1]), datetime.fromisoformat(r[2])))


def account_since(ctx: AppContext, accounts: Collection[str]) -> dict[str, datetime]:
    """account -> its earliest first_seen on any source."""
    return _min_by(ctx, "SELECT account, MIN(first_seen) FROM account_source_baseline WHERE account IN ({marks}) "
                        "GROUP BY account", accounts)


def account_history(ctx: AppContext, accounts: Collection[str], *, before: datetime) -> dict[str, int]:
    """account -> how many sources it had started connections from before `before`."""
    out: dict[str, int] = {}
    with _reading(ctx) as conn:
        for chunk in _chunks(accounts):
            for k, n in conn.execute(
                    "SELECT account, COUNT(*) FROM account_source_baseline "
                    f"WHERE account IN ({','.join('?' * len(chunk))}) AND first_seen <= ? GROUP BY account",
                    [*chunk, db_time(before)]):
                out[k] = n
    return out


def process_first_seen(ctx: AppContext, pairs: Collection[tuple[str, str]]) -> dict[tuple[str, str], datetime]:
    """(src_key, process) -> when the baseline first saw the process start a connection on the host."""
    return _by_pairs(ctx, "SELECT src_key, process, first_seen FROM process_baseline "
                          "WHERE (src_key, process) IN (VALUES {marks})", pairs,
                     lambda r: ((r[0], r[1]), datetime.fromisoformat(r[2])))


def process_since(ctx: AppContext, srcs: Collection[str]) -> dict[str, datetime]:
    """src_key -> the earliest first_seen of any process on the host."""
    return _min_by(ctx, "SELECT src_key, MIN(first_seen) FROM process_baseline WHERE src_key IN ({marks}) "
                        "GROUP BY src_key", srcs)


def peer_seen(ctx: AppContext, queries: Mapping[tuple[str, int, int], Collection[str]], *,
              before: datetime) -> dict[tuple[str, int, int], set[str]]:
    """(group, port, proto) -> the destinations any of the group's members had used on that port before `before`
    (ix_baseline_port_src). Every group is read on one connection."""
    out: dict[tuple[str, int, int], set[str]] = {}
    with _reading(ctx) as conn:
        for (group, port, proto), members in sorted(queries.items()):
            seen = out.setdefault((group, port, proto), set())
            for chunk in _chunks(members):
                seen |= {r[0] for r in conn.execute(
                    "SELECT DISTINCT dst_key FROM connection_baseline WHERE port = ? AND proto = ? "
                    f"AND src_key IN ({','.join('?' * len(chunk))}) AND first_seen <= ?",
                    [port, proto, *chunk, db_time(before)])}
    return out


PortSpec = tuple[int, int | None]  # (port, protocol or None for any)


def _port_clause(ports: Sequence[PortSpec]) -> tuple[str, list[int]]:
    """Each directory port with its own protocol (TCP 8443 added as directory does not make UDP 8443 one)."""
    parts, params = [], []
    for port, proto in ports:
        if proto is None:
            parts.append("port = ?")
            params.append(port)
        else:
            parts.append("(port = ? AND proto = ?)")
            params += [port, proto]
    return "(" + " OR ".join(parts) + ")", params


def directory_sources(ctx: AppContext, ports: Collection[PortSpec], *, since: datetime) -> dict[str, int]:
    """Destination -> how many distinct sources connected to it on these ports and were still seen since `since`."""
    specs = sorted(set(ports), key=str)
    with _reading(ctx) as conn:
        if not specs:
            return {}
        clause, params = _port_clause(specs)
        return {k: n for k, n in conn.execute(
            f"SELECT dst_key, COUNT(DISTINCT src_key) FROM connection_baseline WHERE {clause} AND last_seen >= ? "
            "GROUP BY dst_key", [*params, db_time(since)])}


def directory_clients_before(ctx: AppContext, srcs: Collection[str], servers: Collection[str],
                             ports: Collection[PortSpec], *, before: datetime) -> set[str]:
    """Of these sources, those that had connected to any of the servers on these ports before `before`."""
    out: set[str] = set()
    specs = sorted(set(ports), key=str)
    server_list = sorted(set(servers))
    with _reading(ctx) as conn:
        if not specs or not server_list:
            return out
        clause, params = _port_clause(specs)
        for chunk in _chunks(srcs):
            out |= {r[0] for r in conn.execute(
                "SELECT DISTINCT src_key FROM connection_baseline "
                f"WHERE src_key IN ({','.join('?' * len(chunk))}) "
                f"AND dst_key IN ({','.join('?' * len(server_list))}) AND {clause} AND first_seen <= ?",
                [*chunk, *server_list, *params, db_time(before)])}
    return out


Activity = tuple[int, int | None]


def activity_now(ctx: AppContext, *, since: datetime, until: datetime) -> dict[tuple[str, str], Activity]:
    """(src_key, 'all' | 'directory') -> (connections, bytes or None when no growth carried bytes) that collection
    cycles saw grow in (since, until], not blocked and not late."""
    out: dict[tuple[str, str], list[Any]] = {}
    with _reading(ctx) as conn:
        for src, port, connections, grown_bytes in conn.execute(
                "SELECT f.src_key, f.port, i.connections, i.bytes FROM flow_increments i "
                "JOIN flows r ON r.record_key = i.record_key JOIN flows f ON f.conn_key = r.conn_key AND f.is_primary = 1 "
                "WHERE i.late = 0 AND i.observed_at > ? AND i.observed_at <= ? "
                "AND f.policy_decision NOT LIKE 'blocked%'", (db_time(since), db_time(until))):
            for cls in (("all", "directory") if port in DIRECTORY_PORTS else ("all",)):
                slot = out.setdefault((src, cls), [0, None])
                slot[0] += connections
                if grown_bytes is not None:
                    slot[1] = (slot[1] or 0) + grown_bytes
    return {k: (v[0], v[1]) for k, v in out.items()}


def activity_history(ctx: AppContext, srcs: Sequence[str] | Collection[str], *, start: datetime,
                     end: datetime) -> dict[tuple[str, str], tuple[int, int | None]]:
    """(src_key, class) -> the most connections in any hour of [start, end), and the most bytes in any hour that
    carried byte counts (None when none did: unknown, not zero)."""
    out: dict[tuple[str, str], tuple[int, int | None]] = {}
    with _reading(ctx) as conn:
        for chunk in _chunks(srcs):
            for src, cls, connections, grown_bytes in conn.execute(
                    "SELECT src_key, port_class, MAX(connections), MAX(CASE WHEN bytes_known > 0 THEN bytes END) "
                    "FROM source_activity_hourly "
                    f"WHERE src_key IN ({','.join('?' * len(chunk))}) AND hour >= ? AND hour < ? "
                    "GROUP BY src_key, port_class", [*chunk, db_time(start), db_time(end)]):
                out[(src, cls)] = (connections, grown_bytes)
    return out


def activity_gaps(ctx: AppContext, *, start: datetime, end: datetime) -> list[tuple[datetime, datetime, str]]:
    """Traffic collection gaps in [start, end): hours with less activity than there was, behind a surge's history."""
    with _reading(ctx) as conn:
        cov = store_coverage(conn, IngestSource.TRAFFIC, (start, end), floor=start)
    return [g for g in cov.gaps if g[2] in ("truncated", "ingest_failed", "not_yet_collected")]


def activity_coverage(ctx: AppContext) -> datetime | None:
    """The earliest hour the activity table holds (how long the history behind a surge is)."""
    with _reading(ctx) as conn:
        row = conn.execute("SELECT MIN(hour) FROM source_activity_hourly").fetchone()
    return datetime.fromisoformat(row[0]) if row and row[0] else None
