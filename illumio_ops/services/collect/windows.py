"""Splitting a time window when the PCE's row cap was reached (shared by traffic and events)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

MIN_WINDOW = timedelta(seconds=60)
MAX_DEPTH = 12
# The most one traffic query reads, written before the next is read: at 1,000 workloads a day is
# ~1M records, ~6 GB once parsed (P2 Task 15), an hour ~42k records, ~260 MB.
SLICE = timedelta(hours=1)


@dataclass
class WindowHarvest:
    rows: list[dict[str, Any]] = field(default_factory=list)
    windows: int = 0
    truncated: list[tuple[datetime, datetime, int]] = field(default_factory=list)


def harvest(fetch: Callable[[datetime, datetime], tuple[list[dict[str, Any]], bool]],
            start: datetime, end: datetime) -> WindowHarvest:
    """fetch(start, end) -> (rows, capped). A capped window is halved until it fits or reaches
    MIN_WINDOW / MAX_DEPTH; what still caps is kept and reported as truncated. Exceptions from
    fetch propagate: the caller records the whole window as failed."""
    out = WindowHarvest()

    def walk(a: datetime, b: datetime, depth: int) -> None:
        rows, capped = fetch(a, b)
        out.windows += 1
        if not capped:
            out.rows.extend(rows)
            return
        if depth >= MAX_DEPTH or (b - a) <= MIN_WINDOW:
            out.rows.extend(rows)
            out.truncated.append((a, b, len(rows)))
            return
        mid = a + (b - a) / 2
        walk(a, mid, depth + 1)
        walk(mid, b, depth + 1)

    walk(start, end, 0)
    return out


# The PCE keeps traffic by UTC day: one record per connection and day, and a query whose window touches a day
# answers with that whole day's count for the connections seen inside the window. A window touching two days comes
# back as one record per connection holding both days' counts (lab 26.2 and SaaS 26.30, 2026-11-14: a one-hour
# window and a twelve-hour window of the same day returned the same count, a window from 16:00 to 16:00 twice it;
# and the end is inclusive: a window ending at 00:00:00 brought the next day's records stamped 00:00:00). Read in
# windows of days that are not UTC days, a period counted its inner days twice. So no traffic window sent to the
# PCE crosses a UTC midnight (day_end), and one that ends at a midnight is asked to the second before (asked_end).


def day_end(at: datetime) -> datetime:
    """The UTC midnight after `at`."""
    return at.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


def asked_end(start: datetime, end: datetime) -> datetime:
    """The end a traffic query for [start, end) is sent with: the second before `end` when it is a UTC midnight,
    so the query does not touch the day that begins there."""
    e = end.astimezone(UTC)
    if (e.hour, e.minute, e.second, e.microsecond) == (0, 0, 0, 0) and end - start > timedelta(seconds=1):
        return end - timedelta(seconds=1)
    return end


def slices(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """[start, end] as consecutive pieces of at most SLICE, none crossing a UTC midnight (one piece when it is no
    longer and within one day)."""
    out = []
    cur = start
    while cur < end:
        nxt = min(cur + SLICE, day_end(cur), end)
        out.append((cur, nxt))
        cur = nxt
    return out
