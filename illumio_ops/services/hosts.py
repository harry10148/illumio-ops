"""Host profile (spec §6.5.3, P6b): what the store holds about one host — its inventory row and labels, its slice
of the hourly exposure result, the tamper investigation and the ransomware breakdown. Who connects to it, its
ports, what a mode switch would block and its events are workbench requests the page makes, so those numbers
are the workbench's and lightweight mode reads them from the PCE the same way."""
from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from illumio_ops.domain.exposure import AssetExposure
from illumio_ops.domain.values import CapabilityState, Language, TamperPattern
from illumio_ops.services.analysis import ransomware, tamper
from illumio_ops.services.analysis.ransomware import HostRansomware
from illumio_ops.services.analysis.tamper import HostTamper
from illumio_ops.services.collect.guard import require_same_pce
from illumio_ops.services.context import AppContext
from illumio_ops.services.flowsource import host_addresses
from illumio_ops.services.reports.common import unnamed_host
from illumio_ops.store.flowdb import analysis, capabilities, labels, workloads
from illumio_ops.store.flowdb import ransomware as ransomware_store

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


class HostProfile(BaseModel):
    key: str
    managed: bool          # a workload href (False: an address the inventory does not hold)
    in_inventory: bool
    name: str              # what to call it: hostname, name, an address seen in the flows, or the href
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
    if href is None:
        return HostProfile(key=key, managed=False, in_inventory=False, name=address or key, address=address,
                           identity=None, labels={}, exposure=_exposure(ctx, key), tamper=None, ransomware=None,
                           ransomware_unsupported=False)
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
    if not name:
        name = display_names(ctx, {href})[href]
    return HostProfile(
        key=key, managed=True, in_inventory=wl is not None, name=name, address=None, identity=identity,
        labels=host_labels, exposure=_exposure(ctx, key), tamper=tamper.host_tamper(ctx, href, now=at),
        ransomware=ransomware.host_ransomware(ctx, href, now=at, explain_allows=False)
        if wl is not None and not unsupported else None,
        ransomware_unsupported=unsupported, ransomware_details=details)


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
