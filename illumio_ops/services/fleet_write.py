"""VEN fleet traffic reporting rate writes, on the optional write key."""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from loguru import logger
from pydantic import BaseModel

from illumio_ops.pce.client import PceBudgetExhausted, PceTransportError
from illumio_ops.services.collect.guard import require_same_pce
from illumio_ops.services.context import AppContext
from illumio_ops.services.fleet import OnlineState
from illumio_ops.services.hosts import parse_key
from illumio_ops.services.reports.ven_status import bucket
from illumio_ops.settings.schema import PceSettings
from illumio_ops.store import fleet_actions as actions
from illumio_ops.store.flowdb import workloads
from illumio_ops.store.flowdb.workloads import WorkloadRow

MAX_BATCH = 50
DETAIL_MAX = 300
RATE_MINUTES = 10
RATE_PATH = "/workloads/set_flow_reporting_frequency"
PCE_TRANSPORT = (PceTransportError, PceBudgetExhausted)
Reason = Literal["unmanaged", "not_in_inventory"]
Status = Literal["ok", "failed", "skipped", "unknown"]  # unknown: the write's answer never came


class NoWriteKey(Exception):
    """The write key is not set: nothing can be written."""


class FleetTarget(BaseModel):
    key: str
    name: str | None
    ok: bool
    reason: Reason | None
    current: str | None          # the enforcement mode the inventory holds
    online: OnlineState | None


class RateCheck(BaseModel):
    write_key: bool
    minutes: int
    targets: list[FleetTarget]


class FleetResult(BaseModel):
    key: str
    name: str | None
    status: Status
    detail: str | None           # a Reason, pce_changed, or the PCE's answer
    previous: str | None         # enforcement: the host's mode (read right before the write when one was sent)


class FleetOutcome(BaseModel):
    action: Literal["enforcement", "traffic_rate"]
    batch_id: str
    target: str | None
    results: list[FleetResult]
    until: datetime | None       # traffic_rate: when the VENs go back to every 10 minutes


class FleetAction(BaseModel):
    id: int
    at: datetime
    by: str
    action: str
    batch_id: str
    workload_href: str
    hostname: str | None
    previous_mode: str | None
    target_mode: str | None
    result: str
    detail: str | None


def _detail(status: int, body: bytes) -> str:
    return f"HTTP {status} {body[:DETAIL_MAX].decode('utf-8', 'replace')}".strip()


def _inventory(ctx: AppContext, cfg: PceSettings) -> dict[str, WorkloadRow]:
    with ctx.flows().connect() as conn:
        require_same_pce(conn, cfg)
        return {w.href: w for w in workloads.all_workloads(conn) if w.managed}


def _targets(ctx: AppContext, keys: Sequence[str], cfg: PceSettings, now: datetime) -> list[FleetTarget]:
    if len(keys) > MAX_BATCH:
        raise ValueError(f"at most {MAX_BATCH} hosts at a time")
    parsed = [(k, parse_key(k)[0]) for k in dict.fromkeys(keys)]  # ValueError on a malformed key
    inv = _inventory(ctx, cfg)
    out = []
    for key, href in parsed:
        w = inv.get(href) if href else None
        reason: Reason | None = "unmanaged" if href is None else "not_in_inventory" if w is None else None
        out.append(FleetTarget(key=key, name=(w.hostname or w.name) if w else None, ok=reason is None, reason=reason,
                               current=w.enforcement_mode if w else None,
                               online=bucket(w, now) if w else None))  # type: ignore[arg-type]
    return out


def _write_key(cfg: PceSettings) -> bool:
    return bool(cfg.write_api_key and cfg.write_api_secret)


class _Batch:
    """One traffic-rate request: its id, who and when, and one record per host."""

    def __init__(self, ctx: AppContext, cfg: PceSettings, *, action: str, target: str | None, by: str,
                 at: datetime) -> None:
        self.ctx, self.cfg, self.action, self.target, self.by, self.at = ctx, cfg, action, target, by, at
        self.id = uuid.uuid4().hex
        self.results: list[FleetResult] = []

    def record(self, t: FleetTarget, result: str, detail: str | None, previous: str | None) -> int:
        with self.ctx.db() as conn:
            return actions.add(conn, pce_url=self.cfg.url, org_id=self.cfg.org_id, batch_id=self.id, at=self.at,
                               by=self.by, action=self.action, workload_href=t.key, hostname=t.name,
                               previous_mode=previous, target_mode=self.target, result=result, detail=detail)

    def done(self, t: FleetTarget, status: Status, detail: str | None, previous: str | None = None,
             row: int | None = None) -> None:
        self.results.append(FleetResult(key=t.key, name=t.name, status=status, detail=detail, previous=previous))
        if row is None:
            self.record(t, status, detail, previous)
        else:
            with self.ctx.db() as conn:
                actions.finish(conn, row, result=status, detail=detail, previous_mode=previous)

    def refuse(self, targets: Sequence[FleetTarget], why: str) -> None:
        for t in targets:
            if t.ok:
                self.record(t, "refused", why, None)


def rate_check(ctx: AppContext, keys: Sequence[str], *, now: datetime | None = None) -> RateCheck:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    cfg = ctx.settings.current().pce
    return RateCheck(write_key=_write_key(cfg), minutes=RATE_MINUTES, targets=_targets(ctx, keys, cfg, at))


def increase_rate(ctx: AppContext, keys: Sequence[str], *, by: str, now: datetime | None = None) -> FleetOutcome:
    """Ask the PCE to have each host's VEN report traffic more often for RATE_MINUTES (one request for the batch:
    MAX_BATCH is the call's own limit of 50). Raises NoWriteKey, ValueError."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    cfg = ctx.settings.current().pce
    targets = _targets(ctx, keys, cfg, at)
    batch = _Batch(ctx, cfg, action="traffic_rate", target=None, by=by, at=at)
    if not _write_key(cfg):
        batch.refuse(targets, "no_write_key")
        raise NoWriteKey
    for t in targets:
        if not t.ok:
            batch.done(t, "skipped", t.reason)
    ready = [t for t in targets if t.ok]
    if ready:
        rows = {t.key: batch.record(t, "pending", None, None) for t in ready}
        status: Status
        detail: str | None
        try:
            with ctx.pce_write_client(cfg) as client:
                r = client.request("POST", RATE_PATH, json={"workloads": [{"href": t.key} for t in ready]},
                                   timeout=30, bounded=True)
        except PCE_TRANSPORT as exc:
            status, detail = "unknown", str(exc)[:DETAIL_MAX]
        else:
            ok = r.status in (200, 201, 204)
            status, detail = ("ok", None) if ok else ("failed", _detail(r.status, r.body))
        for t in ready:  # the PCE answers for the request, not per host
            batch.done(t, status, detail, row=rows[t.key])
    logger.info("traffic update rate by {}: {}", by,
                {s: sum(1 for r in batch.results if r.status == s) for s in {r.status for r in batch.results}})
    until = at + timedelta(minutes=RATE_MINUTES) if any(r.status == "ok" for r in batch.results) else None
    return FleetOutcome(action="traffic_rate", batch_id=batch.id, target=None, results=batch.results, until=until)


def history(ctx: AppContext, *, limit: int = 200) -> list[FleetAction]:
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        rows = actions.recent(conn, pce_url=pce.url, org_id=pce.org_id, limit=limit)
    return [FleetAction(id=r["id"], at=datetime.fromisoformat(r["at"]), by=r["by_user"], action=r["action"],
                        batch_id=r["batch_id"], workload_href=r["workload_href"], hostname=r["hostname"],
                        previous_mode=r["previous_mode"], target_mode=r["target_mode"], result=r["result"],
                        detail=r["detail"]) for r in rows]
