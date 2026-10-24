"""Turn one PCE traffic-flow record into a FlowRecord, and decide when two records are the
same connection reported by both ends.

Field mapping measured on LAB-PCE 26.2.20 (spec §6.6). process_name / user_name belong to the
reporting side (F10): outbound = the initiator, inbound = the serving process.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from illumio_ops.domain.identity import normalize_process
from illumio_ops.domain.values import FlowDirection

# Two records of one connection: same 4-tuple, opposite direction, and time ranges that overlap
# or sit at most this far apart (F11: 150 of 154 pairs overlapped; first_detected rarely matches).
PAIRING_MAX_GAP_SECONDS = 600


class FlowShapeError(ValueError):
    """A record without the fields every flow has; it is skipped and counted, never guessed."""


@dataclass(frozen=True)
class FlowRecord:
    direction: FlowDirection
    src_ip: str
    dst_ip: str
    src_href: str | None
    dst_href: str | None
    src_hostname: str | None
    dst_hostname: str | None
    src_managed: bool
    dst_managed: bool
    src_mode: str | None
    dst_mode: str | None
    src_labels: tuple[tuple[str, str], ...]
    dst_labels: tuple[tuple[str, str], ...]
    port: int | None
    proto: int
    own_process: str | None
    own_user: str | None
    windows_service: str | None
    policy_decision: str
    first_detected: datetime
    last_detected: datetime
    num_connections: int
    bytes_in: int | None
    bytes_out: int | None
    state: str | None
    transmission: str | None
    network_href: str | None


def parse_time(value: Any) -> datetime:
    """PCE timestamps are ISO 8601 with Z; the result is always aware UTC."""
    if not isinstance(value, str) or not value:
        raise FlowShapeError("missing timestamp")
    try:
        dt = datetime.fromisoformat(value)  # 3.11+ reads the trailing Z
    except ValueError:
        raise FlowShapeError("unreadable timestamp") from None
    if dt.tzinfo is None:
        raise FlowShapeError("timestamp without a time zone")
    return dt.astimezone(UTC)


def _side(raw: Mapping[str, Any], name: str) -> tuple[str, Mapping[str, Any]]:
    side = raw.get(name)
    if not isinstance(side, Mapping) or not isinstance(side.get("ip"), str) or not side["ip"]:
        raise FlowShapeError(f"missing {name}.ip")
    wl = side.get("workload")
    empty: Mapping[str, Any] = {}
    return side["ip"], wl if isinstance(wl, Mapping) else empty


def _labels(wl: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    out = {(str(lb["key"]), str(lb["value"])) for lb in wl.get("labels") or []
           if isinstance(lb, Mapping) and lb.get("key") is not None and lb.get("value") is not None}
    return tuple(sorted(out))


def _bytes(raw: Mapping[str, Any]) -> tuple[int | None, int | None]:
    bi, bo = raw.get("dst_bi"), raw.get("dst_bo")
    bi = bi if isinstance(bi, int) and not isinstance(bi, bool) else None
    bo = bo if isinstance(bo, int) and not isinstance(bo, bool) else None
    # The PCE reports 0/0 on records that carry no byte data (the other end of the same
    # connection shows the real numbers); a connection that happened moved some bytes.
    if not bi and not bo:
        return None, None
    return bi, bo


def normalize_flow(raw: Mapping[str, Any]) -> FlowRecord:
    src_ip, src_wl = _side(raw, "src")
    dst_ip, dst_wl = _side(raw, "dst")
    try:
        direction = FlowDirection(raw["flow_direction"])
    except (KeyError, ValueError):
        raise FlowShapeError("missing or unknown flow_direction") from None
    decision = raw.get("policy_decision")
    if not isinstance(decision, str) or not decision:
        raise FlowShapeError("missing policy_decision")
    tr = raw.get("timestamp_range")
    if not isinstance(tr, Mapping):
        raise FlowShapeError("missing timestamp_range")
    first, last = parse_time(tr.get("first_detected")), parse_time(tr.get("last_detected"))
    svc_raw = raw.get("service")
    svc: Mapping[str, Any] = svc_raw if isinstance(svc_raw, Mapping) else {}
    proto = svc.get("proto")
    if not isinstance(proto, int) or isinstance(proto, bool):
        raise FlowShapeError("missing service.proto")
    port = svc.get("port")
    bytes_in, bytes_out = _bytes(raw)
    conns = raw.get("num_connections")
    net_raw = raw.get("network")
    network: Mapping[str, Any] = net_raw if isinstance(net_raw, Mapping) else {}
    return FlowRecord(
        direction=direction,
        src_ip=src_ip, dst_ip=dst_ip,
        src_href=src_wl.get("href") or None, dst_href=dst_wl.get("href") or None,
        src_hostname=src_wl.get("hostname") or None, dst_hostname=dst_wl.get("hostname") or None,
        src_managed=bool(src_wl.get("managed")), dst_managed=bool(dst_wl.get("managed")),
        src_mode=src_wl.get("enforcement_mode") or None, dst_mode=dst_wl.get("enforcement_mode") or None,
        src_labels=_labels(src_wl), dst_labels=_labels(dst_wl),
        port=port if isinstance(port, int) and not isinstance(port, bool) else None,
        proto=proto,
        own_process=normalize_process(svc.get("process_name")),
        own_user=svc.get("user_name") or None,
        windows_service=svc.get("windows_service_name") or None,
        policy_decision=decision.strip().lower(),
        first_detected=first, last_detected=last,
        num_connections=conns if isinstance(conns, int) and conns >= 0 else 0,
        bytes_in=bytes_in, bytes_out=bytes_out,
        state=raw.get("state") or None,
        transmission=raw.get("transmission") or None,
        network_href=network.get("href") or None,
    )


def record_key(r: FlowRecord) -> str:
    """Identity of one PCE record: the same record re-pulled later maps to the same key."""
    parts = [r.direction.value, r.src_ip, r.dst_ip, str(r.port), str(r.proto),
             r.first_detected.isoformat()]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def ranges_within(a_first: datetime, a_last: datetime, b_first: datetime, b_last: datetime,
                  max_gap_seconds: int = PAIRING_MAX_GAP_SECONDS) -> bool:
    """True when two [first, last] ranges overlap or lie at most max_gap_seconds apart."""
    gap = max(a_first, b_first) - min(a_last, b_last)
    return gap.total_seconds() <= max_gap_seconds


def same_connection(a: FlowRecord, b: FlowRecord, *, max_gap_seconds: int = PAIRING_MAX_GAP_SECONDS) -> bool:
    if a.direction == b.direction:
        return False
    if (a.src_ip, a.dst_ip, a.port, a.proto) != (b.src_ip, b.dst_ip, b.port, b.proto):
        return False
    return ranges_within(a.first_detected, a.last_detected, b.first_detected, b.last_detected, max_gap_seconds)
