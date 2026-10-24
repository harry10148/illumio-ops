"""The one flow filter, executed three ways (spec §6.3 point 2):

- to_pce_payload: what the PCE can filter goes into the async-query payload; what it cannot
  (process / user / text matching, CIDRs, labels without a known href) comes back as a residual
  spec that the caller applies record by record.
- to_sql: a WHERE clause over the flow store's primary rows (alias f).
- matches: the same test on one record.

to_sql and matches must agree on every spec (tests_v6/domain/test_filter.py checks 20 of them).

Endpoint semantics: an EndpointFilter is a union — the endpoint has all the listed label keys
(each key: any of its values), OR is one of the hrefs, OR is in one of the IPs / networks.
"""
from __future__ import annotations

import ipaddress
import itertools
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from illumio_ops.domain.flows import FlowRecord
from illumio_ops.domain.identity import is_system_account
from illumio_ops.domain.netaddr import parse_ip_token
from illumio_ops.domain.timefmt import pce_time, store_time
from illumio_ops.domain.values import FlowDirection, PolicyDecision


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LabelCond(_Model):
    key: str = Field(min_length=1)
    values: tuple[str, ...] = Field(min_length=1)


class PortProto(_Model):
    port: int | None = Field(default=None, ge=0, le=65535)
    to_port: int | None = Field(default=None, ge=0, le=65535)
    proto: int | None = Field(default=None, ge=0, le=255)

    @model_validator(mode="after")
    def _shape(self) -> PortProto:
        if self.port is None and self.proto is None:
            raise ValueError("a port or a protocol is required")
        if self.to_port is not None and (self.port is None or self.to_port < self.port):
            raise ValueError("to_port needs a port no larger than it")
        return self


class EndpointFilter(_Model):
    labels: tuple[LabelCond, ...] = ()
    hrefs: tuple[str, ...] = ()
    ips: tuple[str, ...] = ()

    @field_validator("ips")
    @classmethod
    def _ips(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for token in v:
            parse_ip_token(token)  # ValueError -> validation error
        return v

    def is_empty(self) -> bool:
        return not (self.labels or self.hrefs or self.ips)


class FilterSpec(_Model):
    start: AwareDatetime
    end: AwareDatetime
    src: EndpointFilter | None = None
    dst: EndpointFilter | None = None
    src_exclude: EndpointFilter | None = None
    dst_exclude: EndpointFilter | None = None
    ports: tuple[PortProto, ...] = ()
    exclude_ports: tuple[PortProto, ...] = ()
    decisions: tuple[PolicyDecision, ...] = ()
    initiator_process: str | None = None
    initiator_user: str | None = None
    service_process: str | None = None
    service_user: str | None = None
    text: str | None = None
    exclude_system_accounts: bool = False

    @model_validator(mode="after")
    def _window(self) -> FilterSpec:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


# ── shared helpers ───────────────────────────────────────────────────────────

_TEXT_COLUMNS = ("src_hostname", "dst_hostname", "src_ip", "dst_ip", "initiator_process", "initiator_user",
                 "service_process", "service_user")


def like_pattern(term: str) -> str:
    """Partial match by default; '*' anchors and stands for any run of characters."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped.replace("*", "%") if "*" in term else f"%{escaped}%"


def _like_regex(pattern: str) -> re.Pattern[str]:
    """SQLite's LIKE with ESCAPE '\\': % any run, _ one character, ASCII-only case folding."""
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if ch == "%" else "." if ch == "_" else re.escape(ch))
        i += 1
    return re.compile("".join(out), re.IGNORECASE | re.ASCII | re.DOTALL)


def _like(value: Any, term: str) -> bool:
    return value is not None and _like_regex(like_pattern(term)).fullmatch(str(value)) is not None


def _split_ips(ips: tuple[str, ...]) -> tuple[list[str], list[str]]:
    exact: list[str] = []
    nets: list[str] = []
    for token in ips:
        (nets if "/" in token else exact).append(token)
    return exact, nets


def ip_in_net(ip: Any, net: Any) -> int:
    try:
        return int(parse_ip_token(str(ip)) in ipaddress.ip_network(str(net), strict=False))
    except (ValueError, TypeError):
        return 0


def _is_system(user: Any) -> int:
    return int(is_system_account(user if isinstance(user, str) else None))


def sql_functions() -> dict[str, Callable[..., int]]:
    """Functions to_sql's clauses call; register them on the connection before running them."""
    return {"ip_in_net": ip_in_net, "is_system_account": _is_system}


# ── to_pce_payload ───────────────────────────────────────────────────────────

def _pce_side(ep: EndpointFilter | None, label_hrefs: Mapping[tuple[str, str], str]) -> list[list[dict[str, Any]]] | None:
    """The include list for one side, or None when part of the union cannot go to the PCE."""
    if ep is None or ep.is_empty():
        return [[]]
    exact, nets = _split_ips(ep.ips)
    if nets:
        return None
    groups: list[list[dict[str, Any]]] = []
    if ep.labels:
        per_key = []
        for cond in ep.labels:
            hrefs = [label_hrefs.get((cond.key, v)) for v in cond.values]
            if any(h is None for h in hrefs):
                return None
            per_key.append([{"label": {"href": h}} for h in hrefs])
        groups.extend(list(combo) for combo in itertools.product(*per_key))
    groups.extend([{"workload": {"href": h}}] for h in ep.hrefs)
    groups.extend([{"ip_address": ip}] for ip in exact)  # plain string only (406 otherwise, 5.x)
    return groups


def _pce_exclude(ep: EndpointFilter | None, label_hrefs: Mapping[tuple[str, str], str]) -> list[dict[str, Any]]:
    """Excluding part of the set at the PCE is safe; the residual excludes the rest."""
    if ep is None:
        return []
    out: list[dict[str, Any]] = []
    if len(ep.labels) == 1:
        for v in ep.labels[0].values:
            href = label_hrefs.get((ep.labels[0].key, v))
            if href:
                out.append({"label": {"href": href}})
    out.extend({"workload": {"href": h}} for h in ep.hrefs)
    out.extend({"ip_address": ip} for ip in _split_ips(ep.ips)[0])
    return out


def _pce_port(p: PortProto) -> dict[str, int]:
    out: dict[str, int] = {}
    if p.port is not None:
        out["port"] = p.port
    if p.to_port is not None:
        out["to_port"] = p.to_port
    if p.proto is not None:
        out["proto"] = p.proto
    return out


def to_pce_payload(spec: FilterSpec, *, max_results: int, query_name: str,
                   label_hrefs: Mapping[tuple[str, str], str]) -> tuple[dict[str, Any], FilterSpec]:
    src_inc = _pce_side(spec.src, label_hrefs)
    dst_inc = _pce_side(spec.dst, label_hrefs)
    payload = {
        "query_name": query_name,
        "start_date": pce_time(spec.start),
        "end_date": pce_time(spec.end),
        "policy_decisions": [d.value for d in spec.decisions],
        "max_results": max_results,
        "sources": {"include": src_inc if src_inc is not None else [[]],
                    "exclude": _pce_exclude(spec.src_exclude, label_hrefs)},
        "destinations": {"include": dst_inc if dst_inc is not None else [[]],
                         "exclude": _pce_exclude(spec.dst_exclude, label_hrefs)},
        "services": {"include": [_pce_port(p) for p in spec.ports],
                     "exclude": [_pce_port(p) for p in spec.exclude_ports]},
        "sources_destinations_query_op": "and",
    }
    residual = spec.model_copy(update={
        "src": spec.src if src_inc is None else None,
        "dst": spec.dst if dst_inc is None else None,
        "ports": (), "exclude_ports": (), "decisions": (),
    })
    return payload, residual


# ── to_sql ───────────────────────────────────────────────────────────────────

def _sql_side(ep: EndpointFilter, side: str, a: str, params: list[Any]) -> str:
    parts: list[str] = []
    if ep.labels:
        keys = []
        for cond in ep.labels:
            marks = ",".join("?" * len(cond.values))
            keys.append(f"COALESCE({a}.{side}_label_set, -1) IN (SELECT set_id FROM label_set_members "
                        f"WHERE key = ? AND value IN ({marks}))")
            params.extend([cond.key, *cond.values])
        parts.append("(" + " AND ".join(keys) + ")")
    if ep.hrefs:
        parts.append(f"COALESCE({a}.{side}_href, '') IN ({','.join('?' * len(ep.hrefs))})")
        params.extend(ep.hrefs)
    exact, nets = _split_ips(ep.ips)
    if exact:
        parts.append(f"{a}.{side}_ip IN ({','.join('?' * len(exact))})")
        params.extend(exact)
    for net in nets:
        parts.append(f"ip_in_net({a}.{side}_ip, ?) = 1")
        params.append(net)
    return "(" + " OR ".join(parts) + ")" if parts else "1"


def _sql_port(p: PortProto, a: str, params: list[Any]) -> str:
    parts = []
    if p.proto is not None:
        parts.append(f"{a}.proto = ?")
        params.append(p.proto)
    if p.to_port is not None:
        parts.append(f"COALESCE({a}.port, -1) BETWEEN ? AND ?")
        params.extend([p.port, p.to_port])
    elif p.port is not None:
        parts.append(f"COALESCE({a}.port, -1) = ?")
        params.append(p.port)
    return "(" + " AND ".join(parts) + ")"


def to_sql(spec: FilterSpec, *, table_alias: str = "f") -> tuple[str, list[Any]]:
    a = table_alias
    params: list[Any] = [store_time(spec.start), store_time(spec.end)]
    clauses = [f"{a}.is_primary = 1", f"{a}.last_detected >= ?", f"{a}.first_detected <= ?"]
    for side, ep, negate in (("src", spec.src, False), ("dst", spec.dst, False),
                             ("src", spec.src_exclude, True), ("dst", spec.dst_exclude, True)):
        if ep is not None and not ep.is_empty():
            clause = _sql_side(ep, side, a, params)
            clauses.append(f"NOT {clause}" if negate else clause)
    if spec.ports:
        clauses.append("(" + " OR ".join(_sql_port(p, a, params) for p in spec.ports) + ")")
    if spec.exclude_ports:
        clauses.append("NOT (" + " OR ".join(_sql_port(p, a, params) for p in spec.exclude_ports) + ")")
    if spec.decisions:
        clauses.append(f"{a}.policy_decision IN ({','.join('?' * len(spec.decisions))})")
        params.extend(d.value for d in spec.decisions)
    for column in ("initiator_process", "initiator_user", "service_process", "service_user"):
        term = getattr(spec, column)
        if term:
            clauses.append(f"{a}.{column} LIKE ? ESCAPE '\\'")
            params.append(like_pattern(term))
    if spec.text:
        pattern = like_pattern(spec.text)
        clauses.append("(" + " OR ".join(f"{a}.{c} LIKE ? ESCAPE '\\'" for c in _TEXT_COLUMNS) + ")")
        params.extend([pattern] * len(_TEXT_COLUMNS))
    if spec.exclude_system_accounts:
        clauses.append(f"is_system_account({a}.initiator_user) = 0")
    return " AND ".join(clauses), params


# ── matches ──────────────────────────────────────────────────────────────────

def _view(record: FlowRecord | Mapping[str, Any]) -> dict[str, Any]:
    """The fields the filter reads, from a stored row (FlowRow / dict) or a live FlowRecord."""
    if isinstance(record, FlowRecord):
        outbound = record.direction is FlowDirection.OUTBOUND
        return {
            "src_ip": record.src_ip, "dst_ip": record.dst_ip, "src_href": record.src_href,
            "dst_href": record.dst_href, "src_hostname": record.src_hostname, "dst_hostname": record.dst_hostname,
            "src_labels": dict(record.src_labels), "dst_labels": dict(record.dst_labels),
            "port": record.port, "proto": record.proto, "policy_decision": record.policy_decision,
            "initiator_process": record.own_process if outbound else None,
            "initiator_user": record.own_user if outbound else None,
            "service_process": None if outbound else record.own_process,
            "service_user": None if outbound else record.own_user,
            "first_detected": record.first_detected, "last_detected": record.last_detected,
        }
    return dict(record)


def _when(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _side_matches(ep: EndpointFilter, v: Mapping[str, Any], side: str) -> bool:
    labels = v.get(f"{side}_labels") or {}
    if ep.labels and all(labels.get(c.key) in c.values for c in ep.labels):
        return True
    if (v.get(f"{side}_href") or "") in ep.hrefs:
        return True
    exact, nets = _split_ips(ep.ips)
    ip = v.get(f"{side}_ip")
    return ip in exact or any(ip_in_net(ip, n) for n in nets)


def _port_matches(p: PortProto, v: Mapping[str, Any]) -> bool:
    if p.proto is not None and v.get("proto") != p.proto:
        return False
    port = v.get("port")
    port = -1 if port is None else port
    if p.to_port is not None:
        return p.port is not None and p.port <= port <= p.to_port
    return p.port is None or port == p.port


def matches(spec: FilterSpec, record: FlowRecord | Mapping[str, Any]) -> bool:
    v = _view(record)
    if v.get("is_primary", 1) != 1:
        return False
    if _when(v["last_detected"]) < spec.start or _when(v["first_detected"]) > spec.end:
        return False
    for side, ep, negate in (("src", spec.src, False), ("dst", spec.dst, False),
                             ("src", spec.src_exclude, True), ("dst", spec.dst_exclude, True)):
        if ep is not None and not ep.is_empty() and _side_matches(ep, v, side) == negate:
            return False
    if spec.ports and not any(_port_matches(p, v) for p in spec.ports):
        return False
    if spec.exclude_ports and any(_port_matches(p, v) for p in spec.exclude_ports):
        return False
    if spec.decisions and v.get("policy_decision") not in {d.value for d in spec.decisions}:
        return False
    for column in ("initiator_process", "initiator_user", "service_process", "service_user"):
        term = getattr(spec, column)
        if term and not _like(v.get(column), term):
            return False
    if spec.text and not any(_like(v.get(c), spec.text) for c in _TEXT_COLUMNS):
        return False
    return not (spec.exclude_system_accounts and is_system_account(v.get("initiator_user")))
