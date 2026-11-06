"""VEN fleet overview (spec §6.5 「VEN 車隊總覽」, deferred to v6.1 and built now): the managed-workload inventory the
store holds, counted by enforcement mode, VEN version, operating system, online state and policy sync, and a host
list filtered by mode, environment label and online state. Online and sync use the VEN status report's own
definitions (services.reports.ven_status), so the page and the report give the same numbers. Read-only: the
inventory collector is its only source, nothing is read from the PCE here."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from illumio_ops.domain.fleet import MODES
from illumio_ops.services.collect.guard import require_same_pce
from illumio_ops.services.context import AppContext
from illumio_ops.services.reports.ven_status import bucket, problems
from illumio_ops.store.flowdb import labels, workloads
from illumio_ops.store.flowdb.workloads import WorkloadRow

LIST_MAX = 500
OnlineState = Literal["online", "lost_24h", "lost_48h", "long_offline", "unknown"]
ONLINE_STATES: tuple[OnlineState, ...] = ("online", "lost_24h", "lost_48h", "long_offline", "unknown")


class Tally(BaseModel):
    value: str | None  # None: the PCE did not report it
    hosts: int


class FleetOverview(BaseModel):
    total: int                      # managed workloads in the inventory
    fetched_at: str | None          # when the inventory was last read from the PCE; None: never
    env_key: str                    # the environment label key (lateral-movement settings)
    modes: list[Tally]
    versions: list[Tally]
    systems: list[Tally]
    online: dict[str, int]          # ONLINE_STATES -> hosts
    sync_states: list[Tally]        # the PCE's policy sync state as reported
    sync_problems: int              # online VENs with a policy sync problem (the VEN status report's definition)
    environments: list[str]         # the environment label values the inventory holds


class FleetHost(BaseModel):
    key: str                        # the workload href: the host page's key
    name: str | None                # hostname, else name; None: the PCE sent neither (the page says so in words)
    mode: str | None
    ven_version: str | None
    os_id: str | None
    online: OnlineState
    last_heartbeat_at: str | None
    policy_sync_state: str | None
    problems: list[str]             # sync problems of an online VEN (ven_status.problems)
    env: str | None
    app: str | None


class FleetHostList(BaseModel):
    total: int                      # hosts matching the filter
    hosts: list[FleetHost]          # the first LIST_MAX of them, by name
    limit_hit: bool


class FleetFilter(BaseModel):
    mode: str | None = None         # a mode, or "unknown" (none reported)
    env: str | None = None          # an environment label value
    no_env: bool = False            # only hosts without an environment label
    online: OnlineState | None = None
    q: str | None = None            # part of the host name


def _tally(values: Iterable[str | None]) -> list[Tally]:
    c = Counter(values)
    return [Tally(value=v, hosts=n) for v, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0] or "￿"))]


def _read(ctx: AppContext) -> tuple[list[WorkloadRow], dict[int, dict[str, str]]]:
    with ctx.flows().connect() as conn:
        require_same_pce(conn, ctx.settings.current().pce)
        fleet = [w for w in workloads.all_workloads(conn) if w.managed]
        sets = labels.label_sets(conn, {w.label_set for w in fleet if w.label_set is not None})
    return fleet, sets


def _labels(w: WorkloadRow, sets: dict[int, dict[str, str]]) -> dict[str, str]:
    return sets.get(w.label_set, {}) if w.label_set is not None else {}


def overview(ctx: AppContext, *, now: datetime | None = None) -> FleetOverview:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    fleet, sets = _read(ctx)
    env_key = ctx.settings.current().lateral.environment_label_key
    states = Counter(bucket(w, at) for w in fleet)
    online = [w for w in fleet if bucket(w, at) == "online"]
    return FleetOverview(
        total=len(fleet), fetched_at=max((w.fetched_at for w in fleet), default=None), env_key=env_key,
        modes=sorted(_tally(w.enforcement_mode for w in fleet),
                     key=lambda x: MODES.index(x.value) if x.value in MODES else len(MODES)),
        versions=_tally(w.ven_version for w in fleet), systems=_tally(w.os_id for w in fleet),
        online={s: states[s] for s in ONLINE_STATES},
        sync_states=_tally(w.policy_sync_state for w in fleet),
        sync_problems=sum(1 for w in online if problems(w)),
        environments=sorted({v for w in fleet if (v := _labels(w, sets).get(env_key))}))


def _matches(h: FleetHost, f: FleetFilter) -> bool:
    if f.mode is not None and (h.mode or "unknown") != f.mode:
        return False
    if f.env is not None and h.env != f.env:
        return False
    if f.no_env and h.env is not None:
        return False
    if f.online is not None and h.online != f.online:
        return False
    return not f.q or f.q.casefold() in (h.name or "").casefold()


def host_list(ctx: AppContext, f: FleetFilter, *, now: datetime | None = None) -> FleetHostList:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    fleet, sets = _read(ctx)
    env_key = ctx.settings.current().lateral.environment_label_key
    rows = []
    for w in fleet:
        lab = _labels(w, sets)
        state = bucket(w, at)
        rows.append(FleetHost(key=w.href, name=w.hostname or w.name,
                              mode=w.enforcement_mode, ven_version=w.ven_version, os_id=w.os_id, online=state,  # type: ignore[arg-type]
                              last_heartbeat_at=w.last_heartbeat_at, policy_sync_state=w.policy_sync_state,
                              problems=problems(w) if state == "online" else [], env=lab.get(env_key),
                              app=lab.get("app")))
    matched = sorted((h for h in rows if _matches(h, f)), key=lambda h: ((h.name or "\uffff").casefold(), h.key))
    return FleetHostList(total=len(matched), hosts=matched[:LIST_MAX], limit_hit=len(matched) > LIST_MAX)
