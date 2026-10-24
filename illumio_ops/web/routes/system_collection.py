"""System › Data collection (settings, status, backfill) and System › Logs."""
from __future__ import annotations

import threading
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from flask import Blueprint
from pydantic import BaseModel, Field

from illumio_ops.domain.values import IngestSource
from illumio_ops.jobs.scheduler import apply_schedule, instrument
from illumio_ops.services import logs
from illumio_ops.services.collect import backfill
from illumio_ops.services.collect.mode import backfill_sources
from illumio_ops.services.collect.status import CollectionStatus, collection_status
from illumio_ops.settings.schema import CollectionSettings
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation


class CollectionView(BaseModel):
    revision: int
    settings: CollectionSettings


class CollectionUpdate(BaseModel):
    revision: int
    settings: CollectionSettings


class BackfillRequest(BaseModel):
    start: date
    end: date  # inclusive


class BackfillAccepted(BaseModel):
    start: datetime
    end: datetime


class LogQuery(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = None
    module: str | None = Field(default=None, max_length=200)
    contains: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=200, ge=1, le=1000)


class LogLine(BaseModel):
    ts: str
    level: str
    module: str
    message: str


class LogLines(BaseModel):
    lines: list[LogLine]
    truncated: bool


OP_GET = operation("system.collection.get", "GET", "/api/system/collection", None, CollectionView)
OP_UPDATE = operation("system.collection.update", "PUT", "/api/system/collection", CollectionUpdate, CollectionView)
OP_STATUS = operation("system.collection.status", "GET", "/api/system/collection/status", None, CollectionStatus)
OP_BACKFILL = operation("system.collection.backfill", "POST", "/api/system/collection/backfill", BackfillRequest,
                        BackfillAccepted)
OP_LOGS = operation("system.logs.query", "POST", "/api/system/logs/query", LogQuery, LogLines)

bp = Blueprint("system_collection", __name__)


def _view() -> CollectionView:
    s = get_ctx().settings.current()
    return CollectionView(revision=s.revision, settings=s.collection)


@api_route(bp, OP_GET)
def get_collection() -> CollectionView:
    return _view()


@api_route(bp, OP_UPDATE)
def update_collection(body: CollectionUpdate) -> CollectionView:
    ctx = get_ctx()
    new = ctx.settings.update(body.revision, lambda d: d.__setitem__("collection", body.settings.model_dump(mode="json")))
    if ctx.scheduler is not None:
        apply_schedule(ctx.scheduler, new)
    if ctx.rate_limiter is not None:
        ctx.rate_limiter.set_rate(new.collection.rate_limit_per_minute)
    return _view()


@api_route(bp, OP_STATUS)
def status() -> CollectionStatus:
    return collection_status(get_ctx())


@api_route(bp, OP_BACKFILL)
def start_backfill(body: BackfillRequest) -> BackfillAccepted:
    ctx = get_ctx()
    now = datetime.now(UTC).replace(microsecond=0)
    today = now.date()
    if body.start > body.end or body.end > today:
        raise ApiFailure(400, "backfill_range_invalid", "err_backfill_range_invalid", field="start")
    settings = ctx.settings.current()
    keep = settings.collection.retention
    days = keep.flow_days if IngestSource.TRAFFIC in backfill_sources(settings, manual=True) else keep.event_days
    if body.start < today - timedelta(days=days):
        raise ApiFailure(400, "backfill_beyond_retention", "err_backfill_beyond_retention", field="start")
    if backfill.BACKFILL_LOCK.locked():
        raise ApiFailure(409, "backfill_running", "err_backfill_running")
    start = datetime.combine(body.start, time.min, tzinfo=UTC)
    end = min(datetime.combine(body.end + timedelta(days=1), time.min, tzinfo=UTC), now)

    def job() -> None:
        backfill.run_backfill(ctx, start=start, end=end)

    if ctx.scheduler is not None:
        ctx.scheduler.add_job(instrument("collect_backfill_manual", job, ctx), "date", run_date=now,
                              id="collect_backfill_manual", replace_existing=True)
    else:  # not serving (tests, tools): run beside the request
        threading.Thread(target=job, daemon=True, name="backfill").start()
    return BackfillAccepted(start=start, end=end)


@api_route(bp, OP_LOGS)
def query_logs(body: LogQuery) -> LogLines:
    entries, truncated = logs.tail(get_ctx().paths.logs_dir, level=body.level, module=body.module,
                                   contains=body.contains, limit=body.limit)
    return LogLines(lines=[LogLine(ts=e.ts, level=e.level, module=e.module, message=e.message) for e in entries],
                    truncated=truncated)
