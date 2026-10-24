"""What part of a requested window the store can answer, shared by FlowSource and EventSource.

A source's coverage is the union of the ranges it has read (live cycles and backfill days,
ingest_coverage), clipped at the retention floor. Every part of the request outside it is a gap:
before_retention below the floor, not_yet_collected above it — or collection_off when the source is
not being collected (collection switched off, or a mode that does not read it). Recorded failed /
truncated windows (ingest_gaps) are listed whether or not the window around them is covered.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from illumio_ops.store.flowdb import ingest_state

GapReason = Literal["before_retention", "not_yet_collected", "collection_off", "ingest_failed", "truncated"]
Window = tuple[datetime, datetime]


class Coverage(BaseModel):
    source: Literal["store", "pce", "mixed"]
    store_from: datetime | None
    store_to: datetime | None
    gaps: list[tuple[datetime, datetime, str]]
    filled_from_pce: list[tuple[datetime, datetime]]
    truncated: bool


@dataclass(frozen=True)
class StoreCoverage:
    gaps: list[tuple[datetime, datetime, str]]
    store_from: datetime | None
    store_to: datetime | None
    covers_any: bool  # some covered range meets the window


def subtract(window: Window, cuts: Sequence[Window]) -> list[Window]:
    parts = [window]
    for a, b in cuts:
        nxt = []
        for x, y in parts:
            if b <= x or a >= y:
                nxt.append((x, y))
                continue
            if x < a:
                nxt.append((x, a))
            if b < y:
                nxt.append((b, y))
        parts = nxt
    return parts


def merge_gaps(gaps: Sequence[tuple[datetime, datetime, str]]) -> list[tuple[datetime, datetime, str]]:
    """Join gaps of the same reason that overlap or touch (retries of one failed window)."""
    out: list[tuple[datetime, datetime, str]] = []
    for a, b, reason in sorted(gaps, key=lambda g: (g[2], g[0])):
        if out and out[-1][2] == reason and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b), reason)
        else:
            out.append((a, b, reason))
    return sorted(out)


def store_coverage(conn: Any, source: str, window: Window, *, floor: datetime,
                   collected: bool = True) -> StoreCoverage:
    start, end = window
    ranges = [(max(a, floor), b) for a, b in ingest_state.coverage(conn, source) if b > floor]
    recorded = [(max(g.window_start, start), min(g.window_end, end),
                 "truncated" if g.kind == "truncated" else "ingest_failed")
                for g in ingest_state.open_gaps(conn, source) if g.window_start < end and g.window_end > start]
    gaps = list(recorded)
    for a, b in subtract(window, ranges):
        for x, y in subtract((a, b), [(g[0], g[1]) for g in recorded]):
            if x < floor:
                gaps.append((x, min(y, floor), "before_retention"))
            if y > floor:
                gaps.append((max(x, floor), y, "not_yet_collected" if collected else "collection_off"))
    return StoreCoverage(
        gaps=merge_gaps(gaps),
        store_from=min((a for a, _ in ranges), default=None), store_to=max((b for _, b in ranges), default=None),
        covers_any=any(a < end and b > start for a, b in ranges))
