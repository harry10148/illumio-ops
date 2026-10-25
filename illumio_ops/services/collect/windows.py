"""Splitting a time window when the PCE's row cap was reached (shared by traffic and events)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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


def slices(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """[start, end] as consecutive pieces of at most SLICE (one piece when it is no longer)."""
    out = []
    cur = start
    while cur < end:
        out.append((cur, min(cur + SLICE, end)))
        cur += SLICE
    return out
