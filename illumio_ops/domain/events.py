"""Turn one PCE audit event into an EventRecord."""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from illumio_ops.domain.flows import FlowShapeError, parse_time
from illumio_ops.domain.values import TamperClassification

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
