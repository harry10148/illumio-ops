"""Host profile (spec §6.5.3, P6b): what the store holds about one host — its inventory row and labels, its slice
of the hourly exposure result, the tamper investigation and the ransomware breakdown. Who connects to it, its
ports, what a mode switch would block and its events are workbench requests the page makes, so those numbers
are the workbench's and lightweight mode reads them from the PCE the same way."""
from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from illumio_ops.domain.exposure import AssetExposure
from illumio_ops.domain.focus import DETECTION_TITLE_KEYS
from illumio_ops.domain.values import (
    CapabilityState,
    CollectionMode,
    DetectorKind,
    Language,
    TamperPattern,
)
from illumio_ops.i18n import translate
from illumio_ops.services.analysis import ransomware, tamper
from illumio_ops.services.analysis.ransomware import HostRansomware
from illumio_ops.services.analysis.tamper import HostTamper
from illumio_ops.services.collect.guard import require_same_pce
from illumio_ops.services.context import AppContext
from illumio_ops.services.flowsource import host_addresses
from illumio_ops.services.reports.common import unnamed_host
from illumio_ops.store.flowdb import analysis, capabilities, labels, workloads
from illumio_ops.store.flowdb import flows as flows_store
from illumio_ops.store.flowdb import ransomware as ransomware_store
from illumio_ops.store.flowdb.db import db_day

WORKLOAD_HREF = re.compile(r"^/orgs/\d+/workloads/[A-Za-z0-9_.-]+$")
# every href a flow end is keyed by: a workload, a Kubernetes Workload, a container workload
HOST_HREF = re.compile(r"^/orgs/\d+/(?:workloads|kubernetes_workloads|container_workloads)/[A-Za-z0-9_.-]+$")


class HostIdentity(BaseModel):
    hostname: str | None
    name: str | None
    enforcement_mode: str | None
    visibility_level: str | None
    os_id: str | None
    ven_version: str | None
    online: bool | None
    agent_status: str | None
    last_heartbeat_at: str | None
    policy_sync_state: str | None
    policy_applied_at: str | None
    fetched_at: str


class HostExposureView(BaseModel):
    computed_at: datetime
    reach_now: int
    reach_enforced: int
    pivot_now: bool
    pivot_enforced: bool
    asset: AssetExposure | None  # set when the host is a critical asset


class QuarantineEligibility(BaseModel):
    """Who the quarantine button would act on: only a managed workload the inventory holds (spec §4.4)."""
    eligible: bool
    reason: Literal["unmanaged", "not_in_inventory", "no_subject"] | None
    no_enforcement: bool  # Idle or Visibility Only: the label would isolate nothing
    key: str | None
    name: str | None


class RankedValue(BaseModel):
    value: str
    connections: int


class HostUsual(BaseModel):
    """What the host usually does (spec §5.1): its top destinations, initiating processes and accounts by connections
    over the last USUAL_DAYS of daily rollups."""
    top_destinations: list[RankedValue]
    top_processes: list[RankedValue]
    top_accounts: list[RankedValue]
    days_covered: int


class HostDifference(BaseModel):
    detection_id: int
    detector: str
    first_seen: datetime
    severity: str
    text: str


class HostProfile(BaseModel):
    key: str
    managed: bool          # a workload href (False: an address the inventory does not hold)
    in_inventory: bool
    name: str              # what to call it: hostname, name, an address seen in the flows, or words (never the href)
    named: bool = True     # False: the store knew no name or address (the page asks the host's own traffic)
    address: str | None    # the address of an unmanaged key
    identity: HostIdentity | None
    labels: dict[str, str]
    exposure: HostExposureView | None
    tamper: HostTamper | None
    ransomware: HostRansomware | None
    ransomware_unsupported: bool
    # the host's details as read: ok, stale (the PCE's rating changed since), missing (never read, or the reads
    # failed), not_rated (the PCE gave the host no ransomware rating)
    ransomware_details: Literal["ok", "stale", "missing", "not_rated"] | None = None
    usual: HostUsual | None = None
    usual_state: Literal["ok", "basic_mode", "accumulating", "no_data"] = "no_data"
    different: list[HostDifference] = []
    quarantine: QuarantineEligibility | None = None


USUAL_DAYS = 30
USUAL_TOP = 5
USUAL_MIN_DAYS = 7     # fewer days of rollups: "accumulating", the ranking still shown
DIFFERENT_DAYS = 7
DIFFERENT_LIMIT = 20
NO_ENFORCEMENT = frozenset({"visibility_only", "idle"})


UsualState = Literal["ok", "basic_mode", "accumulating", "no_data"]


def _usual(ctx: AppContext, key: str, at: datetime) -> tuple[HostUsual | None, UsualState]:
    if ctx.settings.current().collection.mode is CollectionMode.LIGHTWEIGHT:
        return None, "basic_mode"
    since = at - timedelta(days=USUAL_DAYS)
    with ctx.flows().connect() as conn:
        first = flows_store.rollup_first_day(conn)
        tops = {c: flows_store.rollup_top(conn, key, since_day=db_day(since), column=c, limit=USUAL_TOP)
                for c in flows_store.ROLLUP_RANKED}
    if first is None:
        return None, "no_data"
    covered = min(USUAL_DAYS, (at.date() - date.fromisoformat(first)).days)
    names = display_names(ctx, {k for k, _ in tops["dst_key"]})
    usual = HostUsual(
        top_destinations=[RankedValue(value=names.get(k, k), connections=n) for k, n in tops["dst_key"]],
        top_processes=[RankedValue(value=v, connections=n) for v, n in tops["initiator_process"]],
        top_accounts=[RankedValue(value=v, connections=n) for v, n in tops["initiator_user"]],
        days_covered=covered)
    return usual, "ok" if covered >= USUAL_MIN_DAYS else "accumulating"


def _different(ctx: AppContext, key: str, name: str, at: datetime) -> list[HostDifference]:
    lang = ctx.settings.current().display.language
    with ctx.flows().connect() as conn:
        rows = analysis.detections_of_subject(conn, key, start=at - timedelta(days=DIFFERENT_DAYS), end=at,
                                              limit=DIFFERENT_LIMIT)
    out = []
    for r in rows:
        summary = json.loads(r["summary_json"] or "{}")
        params = {k: str(v).removeprefix("ip:") for k, v in summary.items() if v is not None and not isinstance(v, dict | list)}
        params |= {"host": name, "account": key, "minutes": str(summary.get("window_minutes", ""))}
        out.append(HostDifference(detection_id=int(r["id"]), detector=str(r["detector"]),
                                  first_seen=datetime.fromisoformat(r["first_seen"]), severity=str(r["severity"]),
                                  text=translate(lang, DETECTION_TITLE_KEYS[DetectorKind(r["detector"])], params)))
    return sorted(out, key=lambda d: d.first_seen, reverse=True)


def _eligibility(key: str, name: str, *, managed: bool, in_inventory: bool, mode: str | None) -> QuarantineEligibility:
    reason: Literal["unmanaged", "not_in_inventory"] | None = (
        "unmanaged" if not managed else "not_in_inventory" if not in_inventory else None)
    return QuarantineEligibility(eligible=reason is None, reason=reason, no_enforcement=mode in NO_ENFORCEMENT,
                                 key=key, name=name)


def parse_key(key: str) -> tuple[str | None, str | None]:
    """(href, address) of a host key; ValueError when it is neither a workload href nor ip:<address>."""
    if key.startswith("ip:"):
        return None, str(ipaddress.ip_address(key[3:]))
    if WORKLOAD_HREF.match(key):
        return key, None
    raise ValueError("a host is a workload href or ip:<address>")


def display_names(ctx: AppContext, keys: Iterable[str], *, lang: Language | None = None) -> dict[str, str]:
    """How each host key is shown — never an href: the inventory's hostname or name, else what the flows called it
    or an address it was seen with (the PCE sends no hostname for some workloads, lab 2026-10-30; the inventory
    holds no Kubernetes Workload, lab 2026-10-31), an unmanaged key as its address; a workload known nowhere is
    said in words (`lang`, else the display language)."""
    keys = set(keys)
    hrefs = {k for k in keys if HOST_HREF.match(k)}
    names: dict[str, str] = {}
    if hrefs:
        with ctx.flows().connect() as conn:
            names = {w.href: n for w in workloads.all_workloads(conn) if w.href in hrefs and (n := w.hostname or w.name)}
        names |= host_addresses(ctx, hrefs - set(names))
    said = lang or ctx.settings.current().display.language
    return {k: names.get(k) or (unnamed_host(k, said) or k if k in hrefs else k.removeprefix("ip:")) for k in keys}


def _exposure(ctx: AppContext, key: str) -> HostExposureView | None:
    with ctx.flows().connect() as conn:
        row = analysis.read_result(conn, "exposure")
    if row is None:
        return None
    result = json.loads(row["result_json"])
    host = next((h for h in result.get("hosts") or () if h.get("key") == key), None)
    asset = next((a for a in result.get("assets") or () if a.get("key") == key), None)
    if host is None and asset is None:
        return None
    h = host or {}
    return HostExposureView(computed_at=datetime.fromisoformat(row["computed_at"]),
                            reach_now=int(h.get("reach_now") or 0), reach_enforced=int(h.get("reach_enforced") or 0),
                            pivot_now=bool(h.get("pivot_now")), pivot_enforced=bool(h.get("pivot_enforced")),
                            asset=AssetExposure.model_validate(asset) if asset else None)


def profile(ctx: AppContext, key: str, *, now: datetime | None = None) -> HostProfile:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    href, address = parse_key(key)
    with ctx.flows().connect() as conn:
        require_same_pce(conn, ctx.settings.current().pce)  # a switch not yet cleared: not the previous PCE's host
    usual, usual_state = _usual(ctx, key, at)
    if href is None:
        shown = address or key
        return HostProfile(key=key, managed=False, in_inventory=False, name=shown, address=address,
                           identity=None, labels={}, exposure=_exposure(ctx, key), tamper=None, ransomware=None,
                           ransomware_unsupported=False, usual=usual, usual_state=usual_state,
                           different=_different(ctx, key, shown, at),
                           quarantine=_eligibility(key, shown, managed=False, in_inventory=False, mode=None))
    with ctx.flows().connect() as conn:
        wl = next((w for w in workloads.all_workloads(conn) if w.href == href), None)
        host_labels = dict(labels.label_sets(conn, {wl.label_set}).get(wl.label_set, {})) \
            if wl is not None and wl.label_set is not None else {}
        cap = capabilities.all(conn).get("ransomware_risk")
        held = ransomware_store.source_updated(conn)
    unsupported = cap is not None and cap.state == CapabilityState.UNSUPPORTED
    identity = None if wl is None else HostIdentity(
        hostname=wl.hostname, name=wl.name, enforcement_mode=wl.enforcement_mode, visibility_level=wl.visibility_level,
        os_id=wl.os_id, ven_version=wl.ven_version, online=None if wl.online is None else bool(wl.online),
        agent_status=wl.agent_status, last_heartbeat_at=wl.last_heartbeat_at, policy_sync_state=wl.policy_sync_state,
        policy_applied_at=wl.policy_applied_at, fetched_at=wl.fetched_at)
    details: Literal["ok", "stale", "missing", "not_rated"] | None = None
    if wl is not None:
        if wl.risk_percent is None and wl.risk_updated_at is None:
            details = "not_rated"
        elif href not in held:
            details = "missing"
        else:
            details = "stale" if wl.risk_updated_at and held[href] != wl.risk_updated_at else "ok"
    name = (wl.hostname or wl.name) if wl is not None else None
    named = bool(name) or bool(name := host_addresses(ctx, {href}).get(href))
    if not name:
        name = display_names(ctx, {href})[href]
    return HostProfile(
        key=key, managed=True, in_inventory=wl is not None, name=name, named=named, address=None, identity=identity,
        labels=host_labels, exposure=_exposure(ctx, key), tamper=tamper.host_tamper(ctx, href, now=at),
        ransomware=ransomware.host_ransomware(ctx, href, now=at, explain_allows=False)
        if wl is not None and not unsupported else None,
        ransomware_unsupported=unsupported, ransomware_details=details, usual=usual,
        usual_state=usual_state, different=_different(ctx, key, name, at),
        quarantine=_eligibility(key, name, managed=True, in_inventory=wl is not None,
                                mode=wl.enforcement_mode if wl is not None else None))


SEARCH_LIMIT = 50


class HostHit(BaseModel):
    key: str
    name: str
    managed: bool


class HostSearch(BaseModel):
    items: list[HostHit]


def search(ctx: AppContext, q: str) -> HostSearch:
    """Inventory workloads whose hostname or name contains `q` (any case), at most SEARCH_LIMIT; an address the
    inventory does not name is offered as an unmanaged host."""
    text = q.strip()
    if not text:
        return HostSearch(items=[])
    try:
        ip = str(ipaddress.ip_address(text))
    except ValueError:
        ip = None
    with ctx.flows().connect() as conn:
        require_same_pce(conn, ctx.settings.current().pce)
        rows = workloads.all_workloads(conn)
    low = text.lower()
    hits = [HostHit(key=w.href, name=n, managed=bool(w.managed)) for w in rows
            if (n := w.hostname or w.name) and low in n.lower()]
    hits.sort(key=lambda h: h.name.lower())
    if ip is not None and not hits:
        hits = [HostHit(key=f"ip:{ip}", name=ip, managed=False)]
    return HostSearch(items=hits[:SEARCH_LIMIT])


def ransomware_allows(ctx: AppContext, key: str) -> HostRansomware:
    """The breakdown with the allow rules behind each allowed service: one PCE Rule Search per such service."""
    href, _ = parse_key(key)
    if href is None:
        raise ValueError("an unmanaged address has no ransomware breakdown")
    return ransomware.host_ransomware(ctx, href, explain_allows=True)


def add_tamper_note(ctx: AppContext, key: str, *, pattern: TamperPattern | None, process: str | None, reason: str,
                    by: str) -> int:
    href, _ = parse_key(key)
    if href is None:
        raise ValueError("tampering is reported for workloads")
    return tamper.add_annotation(ctx, host_href=href, pattern=pattern, process=process, reason=reason, by=by)


def remove_tamper_note(ctx: AppContext, note_id: int) -> None:
    tamper.remove_annotation(ctx, note_id)
