"""The facts the system checks read: the PCE probe, each collector's failures, data-loss gaps, job health and
disk space — the state P1 and P2 already keep, never re-derived here."""
from __future__ import annotations

from datetime import datetime, timedelta

from illumio_ops.domain.alerting import (
    GapFact,
    JobFact,
    ProbeFact,
    SourceFact,
    SystemFacts,
)
from illumio_ops.jobs.health import list_health
from illumio_ops.services import pce_health
from illumio_ops.services.collect.status import collection_status
from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb import ingest_state

# A probe older than this is not news: the probe job runs every 5 minutes.
PROBE_FRESH = timedelta(minutes=15)
_GIB = 1024 ** 3


def system_facts(ctx: AppContext, *, since_gap_id: int, now: datetime) -> tuple[SystemFacts, int]:
    """(the facts, the newest gap id seen)."""
    status = collection_status(ctx, now=now)
    probe = None
    found = pce_health.latest(ctx)
    if found is not None and found[0] >= now - PROBE_FRESH:
        probe = ProbeFact(found[0], tuple(r.name.value for r in found[1] if not r.ok))
    with ctx.flows().connect() as conn:
        gaps = ingest_state.gaps_after(conn, since_gap_id)
        newest = max([since_gap_id, *(g.id for g in gaps)])
    with ctx.db() as conn:
        jobs = list_health(conn)
    warn = ctx.settings.current().collection.disk_free_warn_gb * _GIB
    return SystemFacts(
        probe=probe,
        sources=tuple(SourceFact(s.source, s.consecutive_failures, s.last_error, s.last_ok_at)
                      for s in status.sources if s.collected),
        new_gaps=tuple(GapFact(g.id, g.source, g.kind, g.window_start, g.window_end) for g in gaps),
        jobs=tuple(JobFact(j.job_id, j.consecutive_failures, j.last_error) for j in jobs),
        disk_free_bytes=status.disk_free_bytes, disk_warn_bytes=warn,
    ), newest


def max_gap_id(ctx: AppContext) -> int:
    with ctx.flows().connect() as conn:
        return ingest_state.max_gap_id(conn)
