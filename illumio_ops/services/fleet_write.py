"""VEN fleet writes (spec §6.5 「VEN enforcement 推進」「心跳加速」, deferred to v6.1 and built now), on the optional
write key only, as quarantine does (services/quarantine.py).

Enforcement progression: chosen hosts move forward to a target mode (domain.fleet: a white-list, never back). The
preview says, per host, its mode now and what the target would block — from the connections reported into it over the
last PREVIEW (the host page's own definition: Full blocks what was reported Potentially Blocked). Apply takes only
the hosts the preview showed, each with the mode it showed: a host whose mode is no longer that one is not written.
Each host is read again right before its write, only `enforcement_mode` is sent (PUT on the workload: one answer per
host, unlike bulk_update whose answer the REST guide does not describe), and every attempt is recorded.

Traffic update rate (5.x 「加速流量回報」): the PCE console's "Increase Traffic Update Rate" — the VEN reports traffic
once a minute for RATE_MINUTES, then goes back to every 10 minutes by itself (Visualization guide 26.1). The REST
guide lists only its audit event (workloads.set_flow_reporting_frequency); the call is the one 5.x made."""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from loguru import logger
from pydantic import BaseModel, Field

from illumio_ops.domain import fleet as df
from illumio_ops.domain.filter import EndpointFilter, FlowCondition
from illumio_ops.domain.segment import GroupBy
from illumio_ops.domain.values import (
    PolicyDecision,
    SegmentDimension,
    SegmentMetric,
    SegmentView,
)
from illumio_ops.pce.client import PceBudgetExhausted, PceTransportError
from illumio_ops.services import workbench
from illumio_ops.services.collect.guard import require_same_pce
from illumio_ops.services.context import AppContext
from illumio_ops.services.fleet import OnlineState
from illumio_ops.services.hosts import parse_key
from illumio_ops.services.reports.ven_status import bucket
from illumio_ops.services.workbench_store import PullInfo
from illumio_ops.settings.schema import PceSettings
from illumio_ops.store import fleet_actions as actions
from illumio_ops.store.flowdb import labels as label_store
from illumio_ops.store.flowdb import workloads
from illumio_ops.store.flowdb.db import StaleGeneration
from illumio_ops.store.flowdb.workloads import WorkloadRow

MAX_BATCH = 50
PREVIEW = timedelta(days=7)
TOP = 5
RANK_LIMIT = 1000
DETAIL_MAX = 300
RATE_MINUTES = 10
RATE_PATH = "/workloads/set_flow_reporting_frequency"
PCE_TRANSPORT = (PceTransportError, PceBudgetExhausted)
Reason = Literal["unmanaged", "not_in_inventory", "same_mode", "not_forward", "mode_changed"]
Status = Literal["ok", "failed", "skipped", "unknown"]  # unknown: the write's answer never came


class NoWriteKey(Exception):
    """The write key is not set: nothing can be written."""


class SelectionTooLarge(ValueError):
    def __init__(self, n: int) -> None:
        super().__init__(f"{n} hosts match; at most {MAX_BATCH} at a time")
        self.n = n


class LabelPick(BaseModel):
    key: str = Field(min_length=1, max_length=255)
    value: str = Field(min_length=1, max_length=255)


class FleetTarget(BaseModel):
    key: str
    name: str | None
    ok: bool
    reason: Reason | None
    current: str | None          # the enforcement mode the inventory holds
    online: OnlineState | None


class RankedSource(BaseModel):
    key: str
    name: str
    connections: int


class HostBlocks(BaseModel):
    key: str
    inbound: int                 # connections into the host over the window, any decision
    would_block: int | None      # of them, what the target blocks; None: not computable (basis deny_rules)
    top_sources: list[RankedSource]


class EnforcementPreview(BaseModel):
    target: str
    write_key: bool
    basis: df.BlockBasis
    targets: list[FleetTarget]
    blocks: list[HostBlocks]     # one per target that can move, when basis is "connections"
    window_start: datetime
    window_end: datetime
    pulled: PullInfo | None      # read from the PCE for this preview (lightweight mode)
    gaps: int                    # parts of the window the store does not cover
    truncated: bool              # a ranking stopped at its row limit: counts are lower bounds


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


class EnforcementHost(BaseModel):
    key: str
    from_mode: str               # the mode the preview showed


def _detail(status: int, body: bytes) -> str:
    return f"HTTP {status} {body[:DETAIL_MAX].decode('utf-8', 'replace')}".strip()


def _inventory(ctx: AppContext, cfg: PceSettings) -> tuple[dict[str, WorkloadRow], dict[int, dict[str, str]]]:
    with ctx.flows().connect() as conn:
        require_same_pce(conn, cfg)
        inv = {w.href: w for w in workloads.all_workloads(conn) if w.managed}
        sets = label_store.label_sets(conn, {w.label_set for w in inv.values() if w.label_set is not None})
    return inv, sets


def select(ctx: AppContext, picks: Sequence[LabelPick]) -> list[str]:
    """The managed hosts carrying every chosen label, by href: resolved for the preview only; apply takes hrefs."""
    if not picks:
        raise ValueError("choose at least one label")
    inv, sets = _inventory(ctx, ctx.settings.current().pce)
    want = {(p.key, p.value) for p in picks}
    keys = sorted(h for h, w in inv.items()
                  if w.label_set is not None and want <= set(sets.get(w.label_set, {}).items()))
    if len(keys) > MAX_BATCH:
        raise SelectionTooLarge(len(keys))
    return keys


def _targets(ctx: AppContext, keys: Sequence[str], cfg: PceSettings, target: str | None,
             now: datetime) -> list[FleetTarget]:
    if len(keys) > MAX_BATCH:
        raise ValueError(f"at most {MAX_BATCH} hosts at a time")
    parsed = [(k, parse_key(k)[0]) for k in dict.fromkeys(keys)]  # ValueError on a malformed key
    inv, _ = _inventory(ctx, cfg)
    out = []
    for key, href in parsed:
        w = inv.get(href) if href else None
        reason: Reason | None = "unmanaged" if href is None else "not_in_inventory" if w is None else None
        if w is not None and target is not None:
            reason = df.refusal(w.enforcement_mode, target)
        out.append(FleetTarget(key=key, name=(w.hostname or w.name) if w else None, ok=reason is None, reason=reason,
                               current=w.enforcement_mode if w else None,
                               online=bucket(w, now) if w else None))  # type: ignore[arg-type]
    return out


def _write_key(cfg: PceSettings) -> bool:
    return bool(cfg.write_api_key and cfg.write_api_secret)


def _blocks(ctx: AppContext, hrefs: tuple[str, ...], start: datetime, end: datetime,
            now: datetime) -> tuple[list[HostBlocks], PullInfo | None, int, bool]:
    """Per host: connections into it over the window, those reported Potentially Blocked, and their top sources —
    through the workbench, so lightweight mode reads the PCE as the host page does."""
    into = EndpointFilter(hrefs=hrefs)

    def rank(condition: FlowCondition, second: SegmentDimension) -> workbench.WorkbenchResult:
        req = workbench.FlowRequest(mode="flows", view=SegmentView.RANKING, condition=condition, start=start, end=end,
                                    metric=SegmentMetric.CONNECTIONS, limit=RANK_LIMIT,
                                    group_by=(GroupBy(dimension=SegmentDimension.DST_HOST), GroupBy(dimension=second)))
        return workbench.run(ctx, req, now=now)

    by_decision = rank(FlowCondition(dst=into), SegmentDimension.DECISION)
    sources = rank(FlowCondition(dst=into, decisions=(PolicyDecision.POTENTIALLY_BLOCKED,)), SegmentDimension.SRC_HOST)
    inbound = dict.fromkeys(hrefs, 0)
    blocked = dict.fromkeys(hrefs, 0)
    top: dict[str, list[RankedSource]] = {h: [] for h in hrefs}
    for r in by_decision.result.ranking or []:
        dst = str(r.keys[0])
        if dst in inbound:
            inbound[dst] += r.value
            if r.keys[1] == PolicyDecision.POTENTIALLY_BLOCKED.value:
                blocked[dst] += r.value
    for r in sources.result.ranking or []:  # most connections first
        dst = str(r.keys[0])
        if dst in top and len(top[dst]) < TOP:
            src = str(r.keys[1])
            top[dst].append(RankedSource(key=src, name=r.display[1] or src, connections=r.value))
    results = (by_decision.result, sources.result)
    gaps = max(len(x.coverage.gaps) for x in results)
    truncated = any(x.limit_hit or x.coverage.truncated for x in results)
    pulled = by_decision.pulled or sources.pulled
    return ([HostBlocks(key=h, inbound=inbound[h], would_block=blocked[h], top_sources=top[h]) for h in hrefs],
            pulled, gaps, truncated)


def preview(ctx: AppContext, keys: Sequence[str], target: str, *, now: datetime | None = None) -> EnforcementPreview:
    if target not in df.TARGETS:
        raise ValueError("unknown target mode")
    at = (now or datetime.now(UTC)).astimezone(UTC)
    cfg = ctx.settings.current().pce
    targets = _targets(ctx, keys, cfg, target, at)
    basis = df.block_basis(target)
    hrefs = tuple(t.key for t in targets if t.ok)
    start, end = at - PREVIEW, at
    blocks: list[HostBlocks] = []
    pulled, gaps, truncated = None, 0, False
    if hrefs and basis == "connections":
        blocks, pulled, gaps, truncated = _blocks(ctx, hrefs, start, end, at)
    return EnforcementPreview(target=target, write_key=_write_key(cfg), basis=basis, targets=targets, blocks=blocks,
                              window_start=start, window_end=end, pulled=pulled, gaps=gaps, truncated=truncated)


Ident = tuple[str, str, int]


def _ident(ctx: AppContext, cfg: PceSettings) -> Ident:
    return (cfg.url, cfg.org_id, ctx.flows().generation)


class _Batch:
    """One confirmation: its id, who and when, and one record per host under the PCE written to."""

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


def apply(ctx: AppContext, hosts: Sequence[EnforcementHost], target: str, *, by: str,
          now: datetime | None = None) -> FleetOutcome:
    """Move each host from the mode the preview showed to `target`. Raises NoWriteKey, ValueError. One PCE
    throughout: the one configured when it starts."""
    if target not in df.TARGETS:
        raise ValueError("unknown target mode")
    at = (now or datetime.now(UTC)).astimezone(UTC)
    cfg = ctx.settings.current().pce
    ident = _ident(ctx, cfg)
    shown = {h.key: h.from_mode for h in hosts}
    targets = _targets(ctx, list(shown), cfg, target, at)
    for i, t in enumerate(targets):  # the inventory moved on since the preview: not what was confirmed
        if t.ok and t.current != shown[t.key]:
            targets[i] = t.model_copy(update={"ok": False, "reason": "mode_changed"})
    batch = _Batch(ctx, cfg, action="enforcement", target=target, by=by, at=at)
    if not _write_key(cfg):
        batch.refuse(targets, "no_write_key")
        raise NoWriteKey
    gen = ctx.flows().generation
    with ctx.pce_write_client(cfg) as client:
        for t in targets:
            if _ident(ctx, ctx.settings.current().pce) != ident:
                batch.done(t, "failed", "pce_changed")  # these hrefs are the previous PCE's: nothing more is written
                continue
            if not t.ok:
                batch.done(t, "skipped", t.reason, t.current)
                continue
            try:
                got = client.request("GET", t.key, org_scoped=False, timeout=30)  # as it is now, right before the write
            except PCE_TRANSPORT as exc:
                batch.done(t, "failed", str(exc)[:DETAIL_MAX])
                continue
            body = got.json() if got.status == 200 else None
            if not isinstance(body, dict):
                batch.done(t, "failed", _detail(got.status, got.body))
                continue
            live = body.get("enforcement_mode")
            previous = str(live) if live is not None else None
            if body.get("managed") is False:
                batch.done(t, "skipped", "unmanaged", previous)
                continue
            if live != shown[t.key]:
                batch.done(t, "skipped", "mode_changed", previous)
                continue
            row = batch.record(t, "pending", None, previous)  # the intent first: an unanswered write is on record
            try:
                # sent once (no transparent retry), one field only: a PUT changes every property it carries
                put = client.request("PUT", t.key, org_scoped=False, json={"enforcement_mode": target}, timeout=30,
                                     bounded=True)
            except PCE_TRANSPORT as exc:
                batch.done(t, "unknown", str(exc)[:DETAIL_MAX], previous, row=row)
                continue
            ok = put.status in (200, 204)
            batch.done(t, "ok" if ok else "failed", None if ok else _detail(put.status, put.body), previous, row=row)
            if ok:  # the inventory says what the PCE now holds, until the next inventory read replaces it
                try:
                    with ctx.flows().writing(gen) as conn:
                        workloads.set_enforcement_mode(conn, t.key, target)
                except StaleGeneration:
                    pass  # the store was switched to another PCE meanwhile: this row is gone with it
    logger.info("enforcement to {} by {}: {}", target, by,
                {s: sum(1 for r in batch.results if r.status == s) for s in {r.status for r in batch.results}})
    return FleetOutcome(action="enforcement", batch_id=batch.id, target=target, results=batch.results, until=None)


def rate_check(ctx: AppContext, keys: Sequence[str], *, now: datetime | None = None) -> RateCheck:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    cfg = ctx.settings.current().pce
    return RateCheck(write_key=_write_key(cfg), minutes=RATE_MINUTES, targets=_targets(ctx, keys, cfg, None, at))


def increase_rate(ctx: AppContext, keys: Sequence[str], *, by: str, now: datetime | None = None) -> FleetOutcome:
    """Ask the PCE to have each host's VEN report traffic once a minute for RATE_MINUTES (one request for the batch:
    MAX_BATCH is the call's own limit of 50). Raises NoWriteKey, ValueError."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    cfg = ctx.settings.current().pce
    targets = _targets(ctx, keys, cfg, None, at)
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
