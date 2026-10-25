"""Turn one PCE audit event into an EventRecord."""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from illumio_ops.domain.flows import FlowShapeError, parse_time
from illumio_ops.domain.values import PrecursorKind, TamperClassification

# created_by carries one of these; for agent events the PCE sends both agent and ven,
# and the VEN href is the one that leads to a workload.
_CREATOR_ORDER = ("ven", "agent", "user", "service_account", "system")


class EventShapeError(ValueError):
    pass


@dataclass(frozen=True)
class EventRecord:
    href: str
    event_type: str
    severity: str | None
    status: str | None
    timestamp: datetime
    created_by_kind: str | None
    created_by_name: str | None
    created_by_href: str | None
    workload_href: str | None
    tamper_classification: str | None  # TamperClassification value, or the PCE's text if new
    raw_json: str


def _classification(raw: Mapping[str, Any]) -> str | None:
    for n in raw.get("notifications") or []:
        info = n.get("info") if isinstance(n, Mapping) else None
        value = info.get("event_classification") if isinstance(info, Mapping) else None
        if isinstance(value, str) and value:
            try:
                return TamperClassification(value)
            except ValueError:
                return value
    return None


def normalize_event(raw: Mapping[str, Any]) -> EventRecord:
    href, event_type = raw.get("href"), raw.get("event_type")
    if not isinstance(href, str) or not href or not isinstance(event_type, str) or not event_type:
        raise EventShapeError("missing href or event_type")
    try:
        ts = parse_time(raw.get("timestamp"))
    except FlowShapeError as exc:
        raise EventShapeError(str(exc)) from None
    kind = name = creator_href = None
    created_by = raw.get("created_by")
    if isinstance(created_by, Mapping):
        for k in _CREATOR_ORDER:
            v = created_by.get(k)
            if isinstance(v, Mapping):
                kind = k
                name = v.get("hostname") or v.get("username") or v.get("name")
                creator_href = v.get("href")
                break
    return EventRecord(
        href=href, event_type=event_type,
        severity=raw.get("severity"), status=raw.get("status"), timestamp=ts,
        created_by_kind=kind, created_by_name=name, created_by_href=creator_href,
        workload_href=None,
        tamper_classification=_classification(raw) if event_type == "agent.tampering" else None,
        raw_json=json.dumps(raw, separators=(",", ":"), ensure_ascii=False),
    )


@dataclass(frozen=True)
class EventHosts:
    ven_hrefs: frozenset[str]
    workload_hrefs: frozenset[str]
    hostnames: frozenset[str]


def _hosts(cb: Mapping[str, Any], resource_changes: list[Any], *, online_lost_only: bool) -> EventHosts:
    vens, wls, names = set(), set(), set()
    for kind in ("ven", "agent"):
        entry = cb.get(kind) if isinstance(cb.get(kind), Mapping) else None
        if entry:
            if kind == "ven" and entry.get("href"):
                vens.add(str(entry["href"]))
            if entry.get("hostname"):
                names.add(str(entry["hostname"]))
    for change in resource_changes:
        if not isinstance(change, Mapping):
            continue
        wl = (change.get("resource") or {}).get("workload") if isinstance(change.get("resource"), Mapping) else None
        if not isinstance(wl, Mapping):
            continue
        online = ((change.get("changes") or {}).get("online") or {}) if isinstance(change.get("changes"), Mapping) else {}
        if online_lost_only and not (online.get("before") is True and online.get("after") is False):
            continue
        if wl.get("href"):
            wls.add(str(wl["href"]))
        if wl.get("hostname"):
            names.add(str(wl["hostname"]))
    return EventHosts(frozenset(vens), frozenset(wls), frozenset(names))


def event_hosts(raw: Mapping[str, Any]) -> EventHosts:
    """The hosts an event is about, in the three shapes events carry them: created_by.ven / created_by.agent
    (VEN-sent events) and resource_changes[].resource.workload (system tasks such as the offline check)."""
    cb = raw.get("created_by") if isinstance(raw.get("created_by"), Mapping) else {}
    changes = raw.get("resource_changes") if isinstance(raw.get("resource_changes"), list) else []
    return _hosts(cb or {}, changes or [], online_lost_only=False)


PRECURSOR_EVENT_TYPES: Mapping[str, PrecursorKind] = {
    "agent.tampering": PrecursorKind.TAMPER,
    "agent.suspend": PrecursorKind.SUSPEND,
    "system_task.agent_offline_check": PrecursorKind.OFFLINE,
}


def precursor_of(raw: Mapping[str, Any]) -> tuple[PrecursorKind, EventHosts, bool] | None:
    """(kind, hosts, signal-type) when the event is a lateral-movement precursor (spec §6.5.1 前兆): an offline
    check counts only for the workloads it took offline."""
    kind = PRECURSOR_EVENT_TYPES.get(str(raw.get("event_type")))
    if kind is None:
        return None
    cb = raw.get("created_by") if isinstance(raw.get("created_by"), Mapping) else {}
    changes = raw.get("resource_changes") if isinstance(raw.get("resource_changes"), list) else []
    hosts = _hosts(cb or {}, changes or [], online_lost_only=kind is PrecursorKind.OFFLINE)
    if kind is PrecursorKind.OFFLINE and not hosts.workload_hrefs:
        return None
    return kind, hosts, _classification(raw) == TamperClassification.SIGNAL
