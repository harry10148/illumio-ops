"""What the data collection page shows: each source's health, open gaps, capacity, the VEN
visibility levels and what this PCE / VEN version supports. P4's watchdog alerts read the same."""
from __future__ import annotations

import re
import shutil
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel

from illumio_ops.domain.values import IngestSource
from illumio_ops.services.collect.inventory import visibility_summary
from illumio_ops.services.collect.mode import in_mode
from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb import binding, capabilities, ingest_state

GAP_WINDOW = timedelta(hours=24)
GAP_LIST_LIMIT = 50
_GIB = 1024**3
_TRANSPORT = re.compile(r"(?:failed: |interrupted \()(dns|refused|timeout|tls|ca_bundle|other)\b")
_HTTP = re.compile(r"HTTP (\d{3})")
_TRANSPORT_REASONS = {"dns": "unreachable", "refused": "unreachable", "timeout": "timeout", "tls": "tls",
                      "ca_bundle": "tls", "other": "unreachable"}


def error_reason(detail: str | None) -> str | None:
    """The recorded error in one of a few words the page can say: another_pce, rate_limit, timeout,
    unreachable, tls, auth, pce_error or other. The raw detail stays available next to it."""
    if not detail:
        return None
    if detail.startswith("binding:"):
        return "another_pce"
    if "PceBudgetExhausted" in detail or "rate budget" in detail:
        return "rate_limit"
    if m := _TRANSPORT.search(detail):
        return _TRANSPORT_REASONS[m.group(1)]
    if m := _HTTP.search(detail):
        code = int(m.group(1))
        return "auth" if code in (401, 403) else "rate_limit" if code == 429 else "pce_error"
    if "timeout" in detail or "in time" in detail:
        return "timeout"
    return "other"


class SourceStatus(BaseModel):
    source: str
    collected: bool                   # the collection mode reads this source
    interval_seconds: int | None
    last_started_at: datetime | None
    last_ok_at: datetime | None
    last_error: str | None
    last_error_reason: str | None     # error_reason(last_error); None when the last cycle succeeded
    consecutive_failures: int
    last_rows: int | None
    lag_seconds: int | None
    stale: bool
    progress: dict[str, Any] | None


class GapView(BaseModel):
    source: str
    kind: str
    window_start: datetime
    window_end: datetime
    detail: str | None


class CollectionStatus(BaseModel):
    enabled: bool
    mode: str
    pce_configured: bool
    binding_host: str | None
    sources: list[SourceStatus]
    open_gaps: list[GapView]          # recorded in the last 24 hours, newest first
    open_gaps_truncated: bool         # more than GAP_LIST_LIMIT of them
    open_gap_counts: dict[str, int]   # all open gaps by kind
    db_bytes: int
    disk_free_bytes: int
    disk_low: bool
    visibility: dict[str, int]
    capabilities: dict[str, str]


def _intervals(ctx: AppContext) -> dict[str, int | None]:
    c = ctx.settings.current().collection
    return {IngestSource.TRAFFIC: c.traffic_interval_seconds, IngestSource.EVENTS: c.events_interval_seconds,
            IngestSource.INVENTORY: c.inventory_interval_seconds, IngestSource.RANSOMWARE: c.inventory_interval_seconds,
            IngestSource.BACKFILL: None}


def _merged(gaps: list[Any]) -> list[GapView]:
    """One line per stretch of missing data: windows of the same source and kind that overlap or
    touch are joined (retries of a failed cold start all start at the same moment). The detail of
    the most recently recorded gap is kept. Newest first."""
    out: list[GapView] = []
    latest: dict[int, datetime] = {}
    for g in sorted(gaps, key=lambda g: (g.source, g.kind, g.window_start)):
        last = out[-1] if out else None
        if last and (last.source, last.kind) == (g.source, g.kind) and g.window_start <= last.window_end:
            last.window_end = max(last.window_end, g.window_end)
            if g.recorded_at >= latest[id(last)]:
                last.detail, latest[id(last)] = g.detail, g.recorded_at
            continue
        view = GapView(source=g.source, kind=g.kind, window_start=g.window_start, window_end=g.window_end,
                       detail=g.detail)
        latest[id(view)] = g.recorded_at
        out.append(view)
    return sorted(out, key=lambda v: v.window_start, reverse=True)


def collection_status(ctx: AppContext, *, now: datetime | None = None) -> CollectionStatus:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    s = ctx.settings.current()
    fdb = ctx.flows()
    with fdb.connect() as conn:
        states = ingest_state.all_states(conn)
        gaps = ingest_state.open_gaps(conn)
        bound = binding.current(conn)
        caps = {name: row.state for name, row in capabilities.all(conn).items()}
        visibility = visibility_summary(conn)
    sources = []
    for source, interval in _intervals(ctx).items():
        st = states.get(source)
        last_ok = st.last_ok_at if st else None
        reference = last_ok or (st.last_started_at if st else None)
        lag = int((at - last_ok).total_seconds()) if last_ok else None
        collected = in_mode(s, source)
        stale = bool(collected and interval and reference and (at - reference).total_seconds() > 2 * interval)
        sources.append(SourceStatus(
            source=source, collected=collected, interval_seconds=interval, last_started_at=st.last_started_at if st else None,
            last_ok_at=last_ok, last_error=st.last_error if st else None,
            last_error_reason=error_reason(st.last_error) if st and st.consecutive_failures else None,
            consecutive_failures=st.consecutive_failures if st else 0, last_rows=st.last_rows if st else None,
            lag_seconds=lag, stale=stale, progress=st.progress if st else None))
    recent = _merged([g for g in gaps if g.recorded_at >= at - GAP_WINDOW])
    db_bytes = sum(p.stat().st_size for p in (fdb.path, fdb.path.with_name(fdb.path.name + "-wal")) if p.exists())
    free = shutil.disk_usage(ctx.paths.data_dir).free
    return CollectionStatus(
        enabled=s.collection.enabled, mode=s.collection.mode.value, pce_configured=bool(s.pce.url and s.pce.org_id and s.pce.api_key),
        binding_host=urlsplit(bound.pce_url).hostname if bound else None,
        sources=sources,
        open_gaps=recent[:GAP_LIST_LIMIT],
        open_gaps_truncated=len(recent) > GAP_LIST_LIMIT,
        open_gap_counts=dict(Counter(g.kind for g in gaps)),
        db_bytes=db_bytes, disk_free_bytes=free, disk_low=free < s.collection.disk_free_warn_gb * _GIB,
        visibility=visibility, capabilities=caps,
    )
