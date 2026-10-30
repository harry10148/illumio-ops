"""Quarantine (spec §6.5.1 防堵, P6d): put a workload's `Quarantine` label on or take it off — one of the two writes
v6.0 makes to the PCE, with the optional write key only.

Before: which policy refers to each level (read on the main key; the label changes nothing unless an enabled rule in
the active policy names it), and what traffic the hosts had in the last PREVIEW — the connections into and out of
them that the quarantine policy could cut (an approximation: the rules' IP lists and services are listed, not
applied). The level is checked again on the server when applied: a level no policy refers to needs the person's
acknowledgement in the request. Each workload is read again right before its write, only its Quarantine label is
changed (the PCE replaces the whole set), and every attempt is recorded — a refused one too, with the PCE's answer."""
from __future__ import annotations

import json
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel

from illumio_ops.domain import quarantine as dq
from illumio_ops.domain.deny import DenyProposal, proposal_filter
from illumio_ops.domain.filter import EndpointFilter
from illumio_ops.domain.quarantine import KEY, LEVELS, LevelState, QuarantineRuleRef
from illumio_ops.domain.values import CollectionMode
from illumio_ops.pce.client import PceBudgetExhausted, PceClient, PceTransportError
from illumio_ops.pce.collections import get_all
from illumio_ops.pce.policy import fetch_rule_sets
from illumio_ops.services.analysis.deny_sim import DenySimulation, simulate_deny
from illumio_ops.services.collect.guard import require_same_pce
from illumio_ops.services.context import AppContext
from illumio_ops.services.hosts import display_names, parse_key
from illumio_ops.services.lateral_view import DenySimulationView
from illumio_ops.services.ondemand import INTERACTIVE_PULL, pull_period
from illumio_ops.services.workbench_store import PullInfo
from illumio_ops.settings.schema import PceSettings
from illumio_ops.store import quarantine_actions as actions
from illumio_ops.store.flowdb import labels as label_store
from illumio_ops.store.flowdb import workloads

MAX_BATCH = 50
PREVIEW = timedelta(days=7)
DEADLINE_S = 120
DETAIL_MAX = 300
NAMES_MAX = 50  # actors and services named per check: one GET each
NO_ENFORCEMENT = frozenset({"visibility_only", "idle"})
PCE_TRANSPORT = (PceTransportError, PceBudgetExhausted)


class NoWriteKey(Exception):
    """The write key is not set: nothing can be written."""


class NoPolicy(Exception):
    """No enabled rule in the active policy refers to the level, and the person did not acknowledge it."""


class QuarantineLevelPolicy(BaseModel):
    state: LevelState
    rules: list[QuarantineRuleRef]  # the active policy's references (the draft's when draft_only)


class QuarantineCheck(BaseModel):
    write_key: bool
    labels: dict[str, str | None]       # level -> its label's href; None: not on the PCE yet (created when applied)
    all_labels: dict[str, str]          # every Quarantine label on the PCE: href -> value
    levels: dict[str, QuarantineLevelPolicy]
    names: dict[str, str]               # actor and service hrefs -> how they read


class QuarantineTarget(BaseModel):
    key: str
    name: str
    ok: bool
    reason: Literal["unmanaged", "not_in_inventory"] | None
    no_enforcement: bool                # Visibility Only or Idle: no rule is enforced, the label isolates nothing
    enforcement_mode: str | None
    current: str | None                 # the Quarantine level the inventory holds


class QuarantinePreview(BaseModel):
    check: QuarantineCheck
    targets: list[QuarantineTarget]
    inbound: DenySimulationView | None  # the targets' connections in, and out, over the last PREVIEW
    outbound: DenySimulationView | None


class QuarantineResult(BaseModel):
    key: str
    name: str
    status: Literal["ok", "failed", "skipped", "not_quarantined", "unknown"]  # unknown: the write's answer never came
    detail: str | None
    previous: str | None


class QuarantineOutcome(BaseModel):
    action: Literal["apply", "remove"]
    level: str | None
    label_created: bool
    label_error: str | None
    results: list[QuarantineResult]


class QuarantineAction(BaseModel):
    id: int
    at: datetime
    by: str
    action: str
    workload_href: str
    hostname: str | None
    level: str | None
    previous_level: str | None
    original_labels: list[dict[str, Any]]
    result: str
    detail: str | None



def _detail(status: int, body: bytes) -> str:
    return f"HTTP {status} {body[:DETAIL_MAX].decode('utf-8', 'replace')}".strip()


def _label_hrefs(rows: Sequence[dict[str, Any]]) -> tuple[dict[str, str | None], bool, dict[str, str]]:
    """(each level's label href, whether any rule set or boundary names one, every Quarantine label href -> its value:
    a value other than the three levels is still a quarantine, recognised and removed by href)."""
    hrefs: dict[str, str | None] = {level: None for level in LEVELS}
    every: dict[str, str] = {}
    used = False
    for lb in rows:
        if lb.get("key") != KEY or lb.get("deleted") or not lb.get("href"):
            continue
        every[str(lb["href"])] = str(lb.get("value") or "")
        if lb.get("value") in hrefs:
            hrefs[str(lb["value"])] = str(lb["href"])
            usage = lb.get("usage") or {}
            used = used or bool(usage.get("ruleset") or usage.get("enforcement_boundary"))
    return hrefs, used, every


def _names(client: PceClient, refs: dict[str, list[QuarantineRuleRef]], deadline: float) -> dict[str, str]:
    wanted = sorted({h for rs in refs.values() for r in rs for h in (*r.consumers, *r.providers, *r.services)
                     if h.startswith("/orgs/")})[:NAMES_MAX]
    out: dict[str, str] = {}
    for href in wanted:
        try:
            r = client.request("GET", href, org_scoped=False, timeout=30, deadline=deadline)
            body = r.json() if r.status == 200 else None
        except Exception as exc:  # noqa: BLE001 - a name not read is shown as its href's last part, said nowhere else
            logger.warning("quarantine: could not name {}: {}", href, exc)
            continue
        if isinstance(body, dict):
            name = f"{body['key']}={body['value']}" if body.get("key") and body.get("value") else body.get("name")
            if name:
                out[href] = str(name)
    return out


def check(ctx: AppContext, cfg: PceSettings | None = None) -> QuarantineCheck:
    """Which policy refers to each level, read on the main key. The labels' usage flags say first whether any rule set
    names them at all; only then are the rule sets read."""
    deadline = time.monotonic() + DEADLINE_S
    cfg = cfg or ctx.settings.current().pce
    with ctx.pce_client(cfg) as client:
        hrefs, used, every = _label_hrefs(get_all(client, "/labels", params={"key": KEY, "usage": "true"}, deadline=deadline))
        empty: dict[str, list[QuarantineRuleRef]] = {level: [] for level in LEVELS}
        active, draft = empty, empty
        if used:
            active = dq.policy_refs(fetch_rule_sets(client, "active", deadline=deadline), hrefs)
            if any(not active[level] and hrefs[level] for level in LEVELS):
                draft = dq.policy_refs(fetch_rule_sets(client, "draft", deadline=deadline), hrefs)
        states = dq.level_states(active=active, draft=draft)
        shown = {level: active[level] or (draft[level] if states[level] == "draft_only" else []) for level in LEVELS}
        names = _names(client, shown, deadline) if any(shown.values()) else {}
    return QuarantineCheck(write_key=bool(cfg.write_api_key and cfg.write_api_secret), labels=hrefs, all_labels=every,
                           names=names,
                           levels={level: QuarantineLevelPolicy(state=states[level], rules=shown[level])
                                   for level in LEVELS})


def _targets(ctx: AppContext, keys: Sequence[str], cfg: PceSettings | None = None) -> list[QuarantineTarget]:
    if len(keys) > MAX_BATCH:
        raise ValueError(f"at most {MAX_BATCH} hosts at a time")
    parsed = [(k, *parse_key(k)) for k in dict.fromkeys(keys)]  # ValueError on a malformed key
    with ctx.flows().connect() as conn:
        require_same_pce(conn, cfg or ctx.settings.current().pce)
        inventory = {w.href: w for w in workloads.all_workloads(conn)}
        sets = label_store.label_sets(conn, {w.label_set for w in inventory.values() if w.label_set is not None})
    names = display_names(ctx, [k for k, _, _ in parsed])
    out = []
    for key, href, _ in parsed:
        wl = inventory.get(href) if href else None
        reason: Literal["unmanaged", "not_in_inventory"] | None = (
            "unmanaged" if href is None else "not_in_inventory" if wl is None else None)
        mode = wl.enforcement_mode if wl else None
        current = sets.get(wl.label_set, {}).get(KEY) if wl and wl.label_set is not None else None
        out.append(QuarantineTarget(key=key, name=names.get(key, key), ok=reason is None, reason=reason,
                          no_enforcement=mode in NO_ENFORCEMENT, enforcement_mode=mode, current=current))
    return out


def _named(ctx: AppContext, sim: DenySimulation, pull: PullInfo | None) -> DenySimulationView:
    keys = {k for r in (*sim.sources, *sim.destinations) for k in r.keys if isinstance(k, str)}
    keys |= {k for f in sim.sample for k in (f.src_key, f.dst_key)}
    return DenySimulationView(simulation=sim, names=display_names(ctx, keys), pull=pull)


def _simulate(ctx: AppContext, proposal: DenyProposal, at: datetime) -> DenySimulationView:
    window = (at - PREVIEW, at)
    if ctx.settings.current().collection.mode is not CollectionMode.LIGHTWEIGHT:
        return _named(ctx, simulate_deny(ctx, proposal, now=at, window=window, edges=[]), None)
    start, end = window
    with INTERACTIVE_PULL, pull_period(ctx, start=start, end=end, spec=proposal_filter(proposal, start=start, end=end),
                                       now=at) as res:
        sim = simulate_deny(res.ctx, proposal, now=at, window=window, edges=[])
        return _named(res.ctx, sim, PullInfo(start=start, end=end, rows=res.rows, capped=res.capped_total,
                                             unread_from=res.unread_from, truncated_windows=len(res.truncated),
                                             read_at=at))


def preview(ctx: AppContext, keys: Sequence[str], level: str, *, now: datetime | None = None) -> QuarantinePreview:
    if level not in LEVELS:
        raise ValueError("unknown quarantine level")
    at = (now or datetime.now(UTC)).astimezone(UTC)
    targets = _targets(ctx, keys)
    hrefs = tuple(t.key for t in targets if t.ok)
    chk = check(ctx)
    if not hrefs:
        return QuarantinePreview(check=chk, targets=targets, inbound=None, outbound=None)
    hosts = EndpointFilter(hrefs=hrefs)
    return QuarantinePreview(check=chk, targets=targets,
                             inbound=_simulate(ctx, DenyProposal(src=EndpointFilter(), dst=hosts), at),
                             outbound=_simulate(ctx, DenyProposal(src=hosts, dst=EndpointFilter()), at))


Ident = tuple[str, str, int]


def _ident(ctx: AppContext, cfg: PceSettings) -> Ident:
    return (cfg.url, cfg.org_id, ctx.flows().generation)


def _record(ctx: AppContext, cfg: PceSettings, *, at: datetime, by: str, action: str, target: QuarantineTarget,
            level: str | None, previous: str | None, original: Sequence[dict[str, Any]], result: str,
            detail: str | None) -> int:
    """One row per host and attempt, under the PCE written to (not whatever is configured by now)."""
    kept = [{k: lb.get(k) for k in ("href", "key", "value")} for lb in original]  # labels only, never more
    with ctx.db() as conn:
        return actions.add(conn, pce_url=cfg.url, org_id=cfg.org_id, at=at, by=by, action=action,
                           workload_href=target.key, hostname=target.name, level=level, previous_level=previous,
                           original_labels=kept, result=result, detail=detail)


def _previous(labels: Sequence[dict[str, Any]], every: dict[str, str]) -> str | None:
    for lb in labels:
        if lb.get("key") == KEY:
            return str(lb.get("value") or every.get(str(lb.get("href")), "?"))
        if lb.get("href") in every:
            return every[str(lb["href"])] or "?"
    return None


def _refused(ctx: AppContext, cfg: PceSettings, targets: Sequence[QuarantineTarget], *, action: str,
             level: str | None, by: str, at: datetime, why: str) -> None:
    for t in targets:
        if t.ok:
            _record(ctx, cfg, at=at, by=by, action=action, target=t, level=level, previous=None, original=[],
                    result="refused", detail=why)


def _change(ctx: AppContext, cfg: PceSettings, ident: Ident, targets: Sequence[QuarantineTarget], level: str | None,
            *, by: str, at: datetime, chk: QuarantineCheck, create: bool) -> QuarantineOutcome:
    action: Literal["apply", "remove"] = "remove" if level is None else "apply"
    results: list[QuarantineResult] = []
    label_created, label_error = False, None
    every = dict(chk.all_labels)

    def done(t: QuarantineTarget, status: str, detail: str | None, previous: str | None,
             original: Sequence[dict[str, Any]] = (), row: int | None = None) -> None:
        results.append(QuarantineResult(key=t.key, name=t.name, status=status, detail=detail,  # type: ignore[arg-type]
                                        previous=previous))
        if row is None:
            _record(ctx, cfg, at=at, by=by, action=action, target=t, level=level, previous=previous,
                    original=original, result=status, detail=detail)
        else:
            with ctx.db() as conn:
                actions.finish(conn, row, result=status, detail=detail)

    with ctx.pce_write_client(cfg) as client:
        target_href = chk.labels.get(level) if level else None
        if level and target_href is None and create:
            r = client.request("POST", "/labels", json={"key": KEY, "value": level}, timeout=30)
            body = r.json() if r.status == 201 else None
            if isinstance(body, dict) and body.get("href"):
                target_href, label_created = str(body["href"]), True
                every[target_href] = level
            else:
                label_error = _detail(r.status, r.body)
        for t in targets:
            if _ident(ctx, ctx.settings.current().pce) != ident:
                # the PCE changed mid-batch: these hrefs are the previous PCE's; nothing more is written
                done(t, "failed", "pce_changed", None)
                continue
            if not t.ok:
                done(t, "skipped", t.reason, None)
                continue
            if level and target_href is None:
                done(t, "failed", label_error, None)
                continue
            try:
                got = client.request("GET", t.key, org_scoped=False, timeout=30)  # as it is now, right before the write
            except PCE_TRANSPORT as exc:
                done(t, "failed", str(exc)[:DETAIL_MAX], None)
                continue
            body = got.json() if got.status == 200 else None
            if not isinstance(body, dict) or not isinstance(body.get("labels"), list):
                done(t, "failed", _detail(got.status, got.body), None)
                continue
            original = [lb for lb in body["labels"] if isinstance(lb, dict)]
            previous = _previous(original, every)
            if level is None and previous is None:
                done(t, "not_quarantined", None, None, original)
                continue
            labels = dq.relabel(original, target_href, set(every))
            # the intent first: a write whose answer never comes is still on record
            row = _record(ctx, cfg, at=at, by=by, action=action, target=t, level=level, previous=previous,
                          original=original, result="pending", detail=None)
            try:
                # sent once (no transparent retry): a retry would resend labels read before someone else's change
                put = client.request("PUT", t.key, org_scoped=False, json={"labels": labels}, timeout=30, bounded=True)
            except PCE_TRANSPORT as exc:
                done(t, "unknown", str(exc)[:DETAIL_MAX], previous, row=row)
                continue
            ok = put.status in (200, 204)
            done(t, "ok" if ok else "failed", None if ok else _detail(put.status, put.body), previous, row=row)
    logger.info("quarantine {} {} by {}: {}", action, level, by,
                {r.status: sum(1 for x in results if x.status == r.status) for r in results})
    return QuarantineOutcome(action=action, level=level, label_created=label_created, label_error=label_error,
                             results=results)


def apply(ctx: AppContext, keys: Sequence[str], level: str, *, by: str, acknowledge_no_policy: bool,
          now: datetime | None = None) -> QuarantineOutcome:
    """Put `level` on each workload (replacing another level). Raises NoWriteKey, NoPolicy (no enabled rule in the
    active policy refers to the level and the person did not acknowledge it), ValueError. One PCE throughout: the
    one configured when it starts."""
    if level not in LEVELS:
        raise ValueError("unknown quarantine level")
    at = (now or datetime.now(UTC)).astimezone(UTC)
    cfg = ctx.settings.current().pce
    ident = _ident(ctx, cfg)
    targets = _targets(ctx, keys, cfg)
    if not (cfg.write_api_key and cfg.write_api_secret):
        _refused(ctx, cfg, targets, action="apply", level=level, by=by, at=at, why="no_write_key")
        raise NoWriteKey
    chk = check(ctx, cfg)  # again here: the page's answer may be old, and the request is not trusted to have asked
    if chk.levels[level].state != "active" and not acknowledge_no_policy:
        _refused(ctx, cfg, targets, action="apply", level=level, by=by, at=at, why="no_policy")
        raise NoPolicy
    return _change(ctx, cfg, ident, targets, level, by=by, at=at, chk=chk, create=True)


def remove(ctx: AppContext, keys: Sequence[str], *, by: str, now: datetime | None = None) -> QuarantineOutcome:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    cfg = ctx.settings.current().pce
    ident = _ident(ctx, cfg)
    targets = _targets(ctx, keys, cfg)
    if not (cfg.write_api_key and cfg.write_api_secret):
        _refused(ctx, cfg, targets, action="remove", level=None, by=by, at=at, why="no_write_key")
        raise NoWriteKey
    deadline = time.monotonic() + DEADLINE_S
    with ctx.pce_client(cfg) as client:
        hrefs, _, every = _label_hrefs(get_all(client, "/labels", params={"key": KEY}, deadline=deadline))
    chk = QuarantineCheck(write_key=True, labels=hrefs, all_labels=every, levels={}, names={})
    return _change(ctx, cfg, ident, targets, None, by=by, at=at, chk=chk, create=False)


def history(ctx: AppContext, key: str | None = None, *, limit: int = 50) -> list[QuarantineAction]:
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        rows = actions.recent(conn, pce_url=pce.url, org_id=pce.org_id, workload_href=key, limit=limit)
    return [QuarantineAction(id=r["id"], at=datetime.fromisoformat(r["at"]), by=r["by_user"], action=r["action"],
                      workload_href=r["workload_href"], hostname=r["hostname"], level=r["level"],
                      previous_level=r["previous_level"], original_labels=json.loads(r["original_labels_json"]),
                      result=r["result"], detail=r["detail"]) for r in rows]
