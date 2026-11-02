"""What every page's frame shows (UI redesign spec §3, §5): the mode in the interface's words, how collection is
going, the alerts nobody has marked as known, and whether the optional write key is set."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from illumio_ops.domain.values import CollectionMode
from illumio_ops.jobs.health import list_health
from illumio_ops.services.context import AppContext
from illumio_ops.store import alerts as alert_store

UNPROCESSED_DAYS = 7  # the alerts page's default period
TRAFFIC_JOB = "collect_traffic"
COLLECT_JOBS = (TRAFFIC_JOB, "collect_events", "collect_inventory")

Collection = Literal["ok", "degraded", "failing", "not_started"]


class ShellStatus(BaseModel):
    mode: Literal["basic", "advanced"]  # basic: lightweight; advanced: alert or full (spec §5)
    collection_mode: CollectionMode
    collection: Collection
    unprocessed_alerts: int
    write_key: bool


def _collection(ctx: AppContext, mode: CollectionMode) -> Collection:
    """From each collector's last run: none ran yet, all fine, some failing, or all failing. Lightweight mode does not
    collect traffic, so a traffic run left from before a switch says nothing."""
    jobs = [j for j in COLLECT_JOBS if not (mode is CollectionMode.LIGHTWEIGHT and j == TRAFFIC_JOB)]
    with ctx.db() as conn:
        health = {h.job_id: h for h in list_health(conn) if h.job_id in jobs}
    finished = [h.last_ok for h in health.values() if h.last_ok is not None]
    if not finished:
        return "not_started"
    failed = finished.count(False)
    if failed == 0:
        return "ok"
    return "failing" if failed == len(jobs) else "degraded"


def status(ctx: AppContext, *, now: datetime | None = None) -> ShellStatus:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    s = ctx.settings.current()
    mode = s.collection.mode
    with ctx.db() as conn:
        unprocessed = alert_store.count_ungrouped(conn, pce_url=s.pce.url, org_id=s.pce.org_id,
                                                  since=at - timedelta(days=UNPROCESSED_DAYS))
    return ShellStatus(mode="basic" if mode is CollectionMode.LIGHTWEIGHT else "advanced", collection_mode=mode,
                       collection=_collection(ctx, mode), unprocessed_alerts=unprocessed,
                       write_key=bool(s.pce.write_api_key and s.pce.write_api_secret))
