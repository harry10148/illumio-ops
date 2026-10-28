"""On-demand traffic (spec §6.4, 2026-10-29): a period read from the PCE into a throwaway flow store when the
install keeps no traffic for it (lightweight mode, or a period past the local retention).

The store has the same schema as the install's own, so a report is built from it with the same SQL. It is
read a day at a time (lab: one download of 150k rows peaked at 1.4 GB), each window written before the next
is read; a window at the per-query cap is halved like a collection cycle's, and what still caps is kept and
recorded as a truncated gap. The file lives under the install's data directory and goes when the pull ends,
however it ends; the service sweeps leftovers at start."""
from __future__ import annotations

import dataclasses
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from illumio_ops.domain.filter import FilterSpec, to_pce_payload
from illumio_ops.domain.values import DataOrigin, IngestSource
from illumio_ops.paths import InstallPaths
from illumio_ops.pce.async_query import run_traffic_query, traffic_payload
from illumio_ops.services.collect.guard import ensure_binding
from illumio_ops.services.collect.traffic import (
    PCE_FAILURES,
    QUERY_DEADLINE_SECONDS,
    normalize_all,
)
from illumio_ops.services.collect.windows import MAX_DEPTH, MIN_WINDOW
from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.db import FlowDb, transaction
from illumio_ops.store.flowdb.flows import refresh_rollups, upsert_flows

PER_QUERY = 50_000  # rows one query may return: about 400 MB held while it is parsed
ONDEMAND_MAX_ROWS = 1_000_000  # rows one pull may read in all; the rest of the period is a recorded gap
WINDOW = timedelta(days=1)
QUERY_NAME = "illumio-ops on-demand"


class OnDemandFailed(Exception):
    """The PCE could not answer part of the period; nothing was built from a partial read."""


@dataclass(frozen=True)
class OnDemandResult:
    ctx: AppContext  # the caller's context with the throwaway store in place of the install's
    rows: int
    windows: int
    truncated: list[tuple[datetime, datetime, int]]
    earliest: datetime | None  # the first record the PCE returned: how far back it still keeps traffic
    capped_total: bool
    unread_from: datetime | None  # where reading stopped at ONDEMAND_MAX_ROWS


@dataclass
class _Pull:
    rows: int = 0
    windows: int = 0
    truncated: list[tuple[datetime, datetime, int]] = field(default_factory=list)
    earliest: datetime | None = None
    unread_from: datetime | None = None


def ondemand_dir(paths: InstallPaths) -> Path:
    return paths.data_dir / "ondemand"


def sweep_leftovers(paths: InstallPaths) -> int:
    """Delete the files a pull interrupted by a crash or a stop left behind; returns how many."""
    d = ondemand_dir(paths)
    if not d.is_dir():
        return 0
    n = 0
    for p in d.iterdir():
        if p.is_file():
            p.unlink(missing_ok=True)
            n += 1
    return n


def _payload(spec: FilterSpec | None, a: datetime, b: datetime) -> dict[str, object]:
    if spec is None:
        return traffic_payload(a, b, max_results=PER_QUERY, query_name=QUERY_NAME)
    # Ports and decisions go to the PCE; label conditions stay with the report's own SQL (no label hrefs here).
    payload, _ = to_pce_payload(spec.model_copy(update={"start": a, "end": b}), max_results=PER_QUERY,
                                query_name=QUERY_NAME, label_hrefs={})
    return payload


def _walk(ctx: AppContext, fdb: FlowDb, client: object, spec: FilterSpec | None, a: datetime, b: datetime,
          depth: int, state: _Pull, at: datetime) -> None:
    if state.unread_from is not None:
        return
    if state.rows >= ONDEMAND_MAX_ROWS:
        state.unread_from = a
        return
    result = run_traffic_query(client, _payload(spec, a, b),  # type: ignore[arg-type]
                               deadline=time.monotonic() + QUERY_DEADLINE_SECONDS)
    state.windows += 1
    if result.capped and depth < MAX_DEPTH and (b - a) > MIN_WINDOW:
        mid = a + (b - a) / 2
        _walk(ctx, fdb, client, spec, a, mid, depth + 1, state, at)
        _walk(ctx, fdb, client, spec, mid, b, depth + 1, state, at)
        return
    capped = result.capped
    records, _skipped = normalize_all(result.rows)
    del result
    if records:
        first = min(r.first_detected for r in records)
        state.earliest = first if state.earliest is None else min(state.earliest, first)
    with fdb.writing(fdb.generation) as conn, transaction(conn):
        upsert_flows(conn, records, origin=DataOrigin.INGEST, now=at)
        if capped:
            ingest_state.record_gap(conn, IngestSource.TRAFFIC, a, b, "truncated",
                                    f"{len(records)} rows returned at the per-query limit", at)
            state.truncated.append((a, b, len(records)))
    state.rows += len(records)


@contextmanager
def pull_period(ctx: AppContext, *, start: datetime, end: datetime, spec: FilterSpec | None = None,
                now: datetime | None = None) -> Iterator[OnDemandResult]:
    """Read [start, end) from the PCE into a throwaway store and yield a context that reads it.
    Raises OnDemandFailed when the PCE could not answer a window."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    settings = ctx.settings.current()
    d = ondemand_dir(ctx.paths)
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = d / f"{uuid.uuid4().hex}.sqlite"
    fdb = FlowDb(path)
    try:
        state = _Pull()
        with fdb.writing(fdb.generation) as conn:
            ensure_binding(conn, settings.pce, at)
        cur = start
        try:
            with ctx.pce_client(settings.pce) as client:
                while cur < end and state.unread_from is None:
                    nxt = min(cur + WINDOW, end)
                    _walk(ctx, fdb, client, spec, cur, nxt, 0, state, at)
                    cur = nxt
        except PCE_FAILURES as exc:
            raise OnDemandFailed(f"the PCE could not answer {cur.date().isoformat()}: {exc}") from exc
        read_to = state.unread_from or end
        with fdb.writing(fdb.generation) as conn, transaction(conn):
            ingest_state.add_coverage(conn, IngestSource.TRAFFIC, start, read_to)
            if state.unread_from is not None:
                ingest_state.record_gap(conn, IngestSource.TRAFFIC, state.unread_from, end, "truncated",
                                        f"stopped at {ONDEMAND_MAX_ROWS} rows", at)
            refresh_rollups(conn, at, today_every=timedelta(0))
        yield OnDemandResult(ctx=dataclasses.replace(ctx, flowdb=fdb), rows=state.rows, windows=state.windows,
                             truncated=state.truncated, earliest=state.earliest,
                             capped_total=state.unread_from is not None, unread_from=state.unread_from)
    finally:
        fdb.close()
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
