"""The blocked-surge detector's 7-day history, cached hourly (P3 Task 15: re-reading 7 days of blocked traffic
was 40 s of an 85 s detection run at 1,000 workloads, and detection delays the alerts).

The hourly step stores, per source and per UTC hour, the most distinct targets it was blocked from in any
window of the detector's length ending in that hour, over the 7 days up to the traffic watermark ("through").
A detection run needs the windows ending in [lo - 7 days, lo]: it takes the whole hours of that range the cache
holds exactly — those whose windows lie inside both the cache's 7 days and its own — and reads the two edges
live: the head (from lo - 7 days to the first such hour) and the tail (from one window before the last such
hour to lo). The result equals reading all 7 days. A cache that is missing, older than two hours, made for
another window length, or too old for the range a run asks (a late pass over an old day) is not used: the run
reads all 7 days, and its status says which it did.
"""
from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from illumio_ops.domain.detectors import Obs, max_window_targets, window_targets_by_hour
from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.values import IngestSource, PolicyDecision
from illumio_ops.services.context import AppContext
from illumio_ops.services.flowsource import observations
from illumio_ops.store.flowdb import analysis, ingest_state

KIND = "blocked_history"
HISTORY = timedelta(days=7)
MAX_AGE = timedelta(hours=2)
HOUR = timedelta(hours=1)
# Hours older than this before "through" keep only what a later hour does not exceed (a run's range always
# reaches past them); a run whose range ends earlier than this reads live.
EXACT_RECENT = timedelta(hours=3)

HistoryMode = Literal["cached", "live"]


@dataclass(frozen=True)
class CachedHistory:
    through: datetime
    by_hour: Mapping[str, Mapping[datetime, int]]


def _window(ctx: AppContext) -> timedelta:
    return timedelta(minutes=ctx.settings.current().lateral.detectors.blocked_window_minutes)


def _hour(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def _ceil_hour(t: datetime) -> datetime:
    return _hour(t) if _hour(t) == t else _hour(t) + HOUR


def _max_per_source(rows: list[Obs], window: timedelta, *, until: datetime,
                    only: Collection[str] | None = None) -> dict[str, int]:
    by_src: dict[str, list[Obs]] = {}
    for o in rows:  # one pass: a scan per source was the slowest part of a busy run (P3 Task 15 scale)
        if o.last <= until and (only is None or o.src_key in only):
            by_src.setdefault(o.src_key, []).append(o)
    return {src: max_window_targets(found, window) for src, found in by_src.items()}


def _thin(by_hour: Mapping[datetime, int], through: datetime) -> dict[datetime, int]:
    """Keep the recent hours as they are; of the older ones, only those no later hour (also older) exceeds."""
    keep: dict[datetime, int] = {}
    best = 0
    for hour in sorted(by_hour, reverse=True):
        n = by_hour[hour]
        if hour >= _hour(through) - EXACT_RECENT:
            keep[hour] = n
        elif n > best:
            keep[hour] = n
            best = n
    return keep


def build_blocked_history(ctx: AppContext, now: datetime) -> None:
    """The hourly step: per source, per hour, up to the traffic watermark."""
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
    by_src: dict[str, list[Obs]] = {}
    for o in rows:
        if o.last <= through:
            by_src.setdefault(o.src_key, []).append(o)
    found = {src: [[h.isoformat(), n] for h, n in sorted(_thin(window_targets_by_hour(obs, window), through).items())]
             for src, obs in by_src.items()}
    with fdb.writing(gen) as conn:
        analysis.write_result(conn, KIND, params={"blocked_window_minutes": int(window.total_seconds() // 60),
                                                  "through": through.isoformat()},
                              result={"by_hour": found}, at=now)


def cached_history(ctx: AppContext, *, window: timedelta, now: datetime) -> CachedHistory | None:
    """The hourly cache, if it is recent and made for this window length."""
    with ctx.flows().connect() as conn:
        row = analysis.read_result(conn, KIND)
    if row is None:
        return None
    params = json.loads(row["params_json"])
    result = json.loads(row["result_json"])
    if (params.get("blocked_window_minutes") != int(window.total_seconds() // 60) or "by_hour" not in result
            or datetime.fromisoformat(row["computed_at"]).astimezone(UTC) < now - MAX_AGE):
        return None
    return CachedHistory(through=datetime.fromisoformat(params["through"]),
                         by_hour={src: {datetime.fromisoformat(h): int(n) for h, n in hours}
                                  for src, hours in result["by_hour"].items()})


def _cached_hours(cache: CachedHistory, *, window: timedelta, lo: datetime) -> tuple[datetime, datetime] | None:
    """[first, end) of the whole hours the cache holds exactly for a run starting at lo, or None."""
    floor = lo - HISTORY
    # A window ending at t holds rows back to t - window: inside both 7-day ranges only from max(...) + window.
    first = _ceil_hour(max(floor, cache.through - HISTORY) + window)
    end = _hour(min(lo, cache.through))
    if end <= first or end < _hour(cache.through) - EXACT_RECENT:
        return None
    return first, end


def history_for(ctx: AppContext, sources: Collection[str], *, window: timedelta, lo: datetime,
                now: datetime) -> tuple[dict[str, int], HistoryMode]:
    """For these sources: their most distinct blocked targets in any window of the 7 days before lo."""
    blocked = (PolicyDecision.BLOCKED,)
    only = set(sources)
    floor = lo - HISTORY
    cache = cached_history(ctx, window=window, now=now)
    hours = _cached_hours(cache, window=window, lo=lo) if cache is not None else None
    if cache is None or hours is None:
        rows = observations(ctx, FilterSpec(start=floor, end=lo, decisions=blocked), now=now).rows
        found = _max_per_source(rows, window, until=lo, only=only)
        return {src: found.get(src, 0) for src in sources}, "live"
    first, end = hours
    head = _max_per_source(observations(ctx, FilterSpec(start=floor, end=first, decisions=blocked), now=now).rows,
                           window, until=first, only=only)
    tail = _max_per_source(observations(ctx, FilterSpec(start=end - window, end=lo, decisions=blocked), now=now).rows,
                           window, until=lo, only=only)
    out = {}
    for src in sources:
        mid = max((n for h, n in cache.by_hour.get(src, {}).items() if first <= h < end), default=0)
        out[src] = max(mid, head.get(src, 0), tail.get(src, 0))
    return out, "cached"
