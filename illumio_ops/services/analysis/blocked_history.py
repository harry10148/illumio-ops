"""The blocked-surge detector's 7-day history, cached hourly (P3 Task 15: re-reading 7 days of blocked traffic
was 40 s of an 85 s detection run at 1,000 workloads, and detection delays the alerts).

The hourly step stores, per source, the most distinct targets it was blocked from in any window of the
detector's length during the 7 days up to the traffic watermark ("through"). A detection run then reads only
the tail after that — from one window before "through", so a window straddling it is still counted. A cache
that is missing, older than two hours, made for another window length, or reaching past the history the run
needs is not used: the run reads all 7 days, and its status says which it did.
"""
from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from illumio_ops.domain.detectors import Obs, max_window_targets
from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.values import IngestSource, PolicyDecision
from illumio_ops.services.context import AppContext
from illumio_ops.services.flowsource import observations
from illumio_ops.store.flowdb import analysis, ingest_state

KIND = "blocked_history"
HISTORY = timedelta(days=7)
MAX_AGE = timedelta(hours=2)

HistoryMode = Literal["cached", "live"]


@dataclass(frozen=True)
class CachedHistory:
    through: datetime
    max_targets: Mapping[str, int]


def _window(ctx: AppContext) -> timedelta:
    return timedelta(minutes=ctx.settings.current().lateral.detectors.blocked_window_minutes)


def _max_per_source(rows: list[Obs], window: timedelta, *, until: datetime,
                    only: Collection[str] | None = None) -> dict[str, int]:
    by_src: dict[str, list[Obs]] = {}
    for o in rows:  # one pass: a scan per source was the slowest part of a busy run (P3 Task 15 scale)
        if o.last <= until and (only is None or o.src_key in only):
            by_src.setdefault(o.src_key, []).append(o)
    return {src: max_window_targets(found, window) for src, found in by_src.items()}


def build_blocked_history(ctx: AppContext, now: datetime) -> None:
    """The hourly step: the history up to the traffic watermark, for every source."""
    fdb = ctx.flows()
    gen = fdb.generation
    with fdb.connect() as conn:
        state = ingest_state.get(conn, IngestSource.TRAFFIC)
    through = state.watermark if state is not None else None
    if through is None:
        return
    window = _window(ctx)
    rows = observations(ctx, FilterSpec(start=through - HISTORY, end=through, decisions=(PolicyDecision.BLOCKED,)),
                        now=now).rows
    found = _max_per_source(rows, window, until=through)
    with fdb.writing(gen) as conn:
        analysis.write_result(conn, KIND, params={"blocked_window_minutes": int(window.total_seconds() // 60),
                                                  "through": through.isoformat()},
                              result={"max_targets": found}, at=now)


def cached_history(ctx: AppContext, *, window: timedelta, before: datetime, now: datetime) -> CachedHistory | None:
    with ctx.flows().connect() as conn:
        row = analysis.read_result(conn, KIND)
    if row is None:
        return None
    params = json.loads(row["params_json"])
    through = datetime.fromisoformat(params["through"])
    if (params.get("blocked_window_minutes") != int(window.total_seconds() // 60)
            or datetime.fromisoformat(row["computed_at"]).astimezone(UTC) < now - MAX_AGE or through > before):
        return None
    return CachedHistory(through=through, max_targets=json.loads(row["result_json"])["max_targets"])


def history_for(ctx: AppContext, sources: Collection[str], *, window: timedelta, lo: datetime,
                now: datetime) -> tuple[dict[str, int], HistoryMode]:
    """For these sources: their most distinct blocked targets in any window of the 7 days before lo."""
    blocked = (PolicyDecision.BLOCKED,)
    cache = cached_history(ctx, window=window, before=lo, now=now)
    if cache is None:
        rows = observations(ctx, FilterSpec(start=lo - HISTORY, end=lo, decisions=blocked), now=now).rows
        found = _max_per_source(rows, window, until=lo, only=set(sources))
        return {src: found.get(src, 0) for src in sources}, "live"
    tail_start = cache.through - window
    tail = (observations(ctx, FilterSpec(start=tail_start, end=lo, decisions=blocked), now=now).rows
            if lo > tail_start else [])
    found = _max_per_source(tail, window, until=lo, only=set(sources))
    return {src: max(cache.max_targets.get(src, 0), found.get(src, 0)) for src in sources}, "cached"
