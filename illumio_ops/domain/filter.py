"""The one flow filter, executed three ways (spec §6.3 point 2):

- to_pce_payload: what the PCE can filter goes into the async-query payload; what it cannot
  (process / user / text matching, CIDRs, labels without a known href) comes back as a residual
  spec that the caller applies record by record.
- to_sql: a WHERE clause over the flow store's primary rows (alias f).
- matches: the same test on one record.

to_sql and matches must agree on every spec (tests/domain/test_filter.py checks 20 of them).

Endpoint semantics: an EndpointFilter is a union by default — the endpoint has all the listed label keys
(each key: any of its values), OR is one of the hrefs, OR is in one of the IPs / networks. With match="all" the
labels and the hosts (hrefs or addresses, together one part) must both hold when both are set (the workbench's
"env=Prod and this host", P6a). public is one more host part: a public address no Workload holds (netaddr.outside,
user 2026-10-31: alert rules leave the internet side of a connection out); so is ip_lists, PCE IP lists by href, whose
networks the flow store keeps (to_sql reads them there; matches is given them). A list the PCE no longer has matches
nothing. label_groups are PCE label groups by href, part of the labels: a group's member values join the values of its
key, and every key must hold (the PCE's own reading of labels and label groups); a group the PCE no longer has matches
nothing. A port of -1 is "no port" (a protocol
alone is any port). The *_processes / *_users sets are exact values (domain accounts case-insensitive), the single
fields are partial matches.

5.x parity (2026-11-06): either / either_exclude are one endpoint condition on either end (5.x any_* / ex_any_*);
services are PCE services by href, their ports from the flow store, one set with the listed ports; Windows service
names compare case-insensitively (ASCII, as SQLite's lower()); transmissions are the PCE's unicast / broadcast /
multicast; exclude_processes leaves out a connection whose process at either end is one of them. An exclusion never
leaves out a connection that lacks the value.
"""
from __future__ import annotations

import ipaddress
import itertools
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from illumio_ops.domain.flows import FlowRecord
from illumio_ops.domain.identity import is_system_account, normalize_process
from illumio_ops.domain.netaddr import outside, parse_ip_token
from illumio_ops.domain.timefmt import pce_time, store_time
from illumio_ops.domain.values import FlowDirection, PolicyDecision

IpLists = Mapping[str, Sequence[str]]  # IP list href -> its networks
LabelGroups = Mapping[str, tuple[str, Collection[str]]]  # label group href -> (key, member values)
ServicePorts = Mapping[str, Sequence[tuple[int | None, int | None, int | None]]]  # service href -> (port, to_port, proto)
Href = Annotated[str, Field(min_length=1, max_length=255)]
Transmission = Literal["unicast", "broadcast", "multicast"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LabelCond(_Model):
    key: str = Field(min_length=1)
    values: tuple[str, ...] = Field(min_length=1)


class PortProto(_Model):
    port: int | None = Field(default=None, ge=-1, le=65535)  # -1: the service has no port (ICMP...), P6a
    to_port: int | None = Field(default=None, ge=0, le=65535)
    proto: int | None = Field(default=None, ge=0, le=255)

    @model_validator(mode="after")
    def _shape(self) -> PortProto:
        if self.port is None and self.proto is None:
            raise ValueError("a port or a protocol is required")
        if self.to_port is not None and (self.port is None or self.port < 0 or self.to_port < self.port):
            raise ValueError("to_port needs a port no larger than it")
        return self


class EndpointFilter(_Model):
    labels: tuple[LabelCond, ...] = ()
    hrefs: tuple[str, ...] = ()
    ips: tuple[str, ...] = ()
    ip_lists: tuple[Href, ...] = ()
    public: bool = False
    match: Literal["any", "all"] = "any"  # any: one of the parts (the union); all: the labels and the hosts
    label_groups: tuple[Href, ...] = ()  # part of the labels (module docstring)

    def has_labels(self) -> bool:
        return bool(self.labels or self.label_groups)

    def has_hosts(self) -> bool:
        return bool(self.hrefs or self.ips or self.ip_lists or self.public)

    def intersects(self) -> bool:
        """Labels and hosts both set under match="all": an intersection, not the union."""
        return self.match == "all" and self.has_labels() and self.has_hosts()

    @field_validator("ips")
    @classmethod
    def _ips(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for token in v:
            parse_ip_token(token)  # ValueError -> validation error
        return v

    def is_empty(self) -> bool:
        return not (self.has_labels() or self.has_hosts())


class FlowCondition(_Model):
    """A flow filter without its time window: what an alert rule (and later a saved report section) stores.
    within() gives the FilterSpec for a window; every field, default and check is FilterSpec's."""
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
    # exact values, any of them (the workbench's dimension clicks, P6a): unlike the partial fields above
    initiator_processes: tuple[str, ...] = ()
    initiator_users: tuple[str, ...] = ()
    service_processes: tuple[str, ...] = ()
    service_users: tuple[str, ...] = ()
    text: str | None = None
    exclude_system_accounts: bool = False
    # 5.x parity (module docstring)
    either: EndpointFilter | None = None
    either_exclude: EndpointFilter | None = None
    services: tuple[Href, ...] = ()
    exclude_services: tuple[Href, ...] = ()
    windows_services: tuple[Annotated[str, Field(min_length=1, max_length=255)], ...] = ()
    exclude_windows_services: tuple[Annotated[str, Field(min_length=1, max_length=255)], ...] = ()
    transmissions: tuple[Transmission, ...] = ()
    exclude_transmissions: tuple[Transmission, ...] = ()
    exclude_processes: tuple[Annotated[str, Field(min_length=1, max_length=255)], ...] = ()

    @field_validator("exclude_processes")
    @classmethod
    def _processes(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        """As the store keeps them (identity.normalize_process): a path or a Windows name typed is still found."""
        out = []
        for name in v:
            n = normalize_process(name.strip())
            if n is None:
                raise ValueError("a process name cannot be empty")
            out.append(n)
        return tuple(out)

    def within(self, start: datetime, end: datetime) -> FilterSpec:
        return FilterSpec(start=start, end=end, **dict(self))


class FilterSpec(FlowCondition):
    start: AwareDatetime
    end: AwareDatetime

    # The store keeps milliseconds: a bound finer than that is moved inward to the next whole
    # millisecond, so the SQL bound and the per-record predicate see the same window.
    @field_validator("start")
    @classmethod
    def _start_ms(cls, v: datetime) -> datetime:
        extra = v.microsecond % 1000
        return v + timedelta(microseconds=1000 - extra) if extra else v

    @field_validator("end")
    @classmethod
    def _end_ms(cls, v: datetime) -> datetime:
        return v - timedelta(microseconds=v.microsecond % 1000)

    @model_validator(mode="after")
    def _window(self) -> FilterSpec:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self

    def condition(self) -> FlowCondition:
        return FlowCondition(**{k: v for k, v in self if k not in ("start", "end")})


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


def user_key(name: str) -> str:
    """Domain accounts (DOMAIN\\acct, acct@domain) are case-insensitive, local accounts are not: the key a
    ranking groups users by (segment._user) and the exact user sets compare with."""
    return name.lower() if ("\\" in name or "@" in name) else name


def _sql_user(column: str) -> str:
    return (f"CASE WHEN instr({column}, '\\') > 0 OR instr({column}, '@') > 0 "
            f"THEN lower({column}) ELSE {column} END")


def ascii_lower(value: str) -> str:
    """Lower-case ASCII letters only, as SQLite's lower() does."""
    return "".join(c.lower() if c.isascii() else c for c in value)


def _is_outside(ip: Any, href: Any) -> int:
    return int(outside(ip if isinstance(ip, str) else None, href if isinstance(href, str) else None))


def sql_functions() -> dict[str, Callable[..., int]]:
    """Functions to_sql's clauses call; register them on the connection before running them."""
    return {"ip_in_net": ip_in_net, "is_system_account": _is_system, "is_outside": _is_outside}


# ── to_pce_payload ───────────────────────────────────────────────────────────

def _pce_side(ep: EndpointFilter | None, label_hrefs: Mapping[tuple[str, str], str]) -> list[list[dict[str, Any]]] | None:
    """The include list for one side, or None when part of the union cannot go to the PCE."""
    if ep is None or ep.is_empty():
        return [[]]
    if ep.intersects():
        return None  # the PCE's include list is a union of groups: the intersection is checked locally
    exact, nets = _split_ips(ep.ips)
    if nets or ep.public or ep.ip_lists or ep.label_groups:
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
    if ep is None or ep.intersects():
        return []  # excluding a part of an intersection would exclude too much: the residual excludes it
    out: list[dict[str, Any]] = []
    if len(ep.labels) == 1 and not ep.label_groups:  # with a group, the label alone is not the labels part
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
    # "no port" (-1) has no PCE form: those service lists are checked locally
    # nor do named services: the listed ports and the services are one set, so neither half is pushed alone
    noport_in = any(p.port == -1 for p in spec.ports) or bool(spec.services)
    noport_ex = any(p.port == -1 for p in spec.exclude_ports)
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
        "services": {"include": [] if noport_in else [_pce_port(p) for p in spec.ports],
                     "exclude": [] if noport_ex else [_pce_port(p) for p in spec.exclude_ports]},
        "sources_destinations_query_op": "and",
    }
    residual = spec.model_copy(update={
        "src": spec.src if src_inc is None else None,
        "dst": spec.dst if dst_inc is None else None,
        "ports": spec.ports if noport_in else (), "exclude_ports": spec.exclude_ports if noport_ex else (),
        "decisions": (),
    })
    return payload, residual


# ── to_sql ───────────────────────────────────────────────────────────────────

def _sql_side(ep: EndpointFilter, side: str, a: str, params: list[Any]) -> str:
    """The parts of one endpoint (labels, hrefs, addresses), ORed — or labels AND hosts for match="all"."""
    parts: list[str] = []
    if ep.label_groups:
        parts.append(_sql_labels_with_groups(ep, side, a, params))
    elif ep.labels:
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
    addresses: list[str] = []
    if exact:
        addresses.append(f"{a}.{side}_ip IN ({','.join('?' * len(exact))})")
        params.extend(exact)
    for net in nets:
        addresses.append(f"ip_in_net({a}.{side}_ip, ?) = 1")
        params.append(net)
    if ep.ip_lists:
        addresses.append(f"EXISTS (SELECT 1 FROM ip_list_nets n WHERE n.href IN ({','.join('?' * len(ep.ip_lists))}) "
                         f"AND ip_in_net({a}.{side}_ip, n.net) = 1)")
        params.extend(ep.ip_lists)
    if ep.public:
        addresses.append(f"is_outside({a}.{side}_ip, {a}.{side}_href) = 1")
    if ep.hrefs:
        addresses.insert(0, parts.pop())
    if addresses:
        parts.append("(" + " OR ".join(addresses) + ")")
    if not parts:
        return "1"
    return "(" + (" AND " if ep.match == "all" else " OR ").join(parts) + ")"


def _sql_labels_with_groups(ep: EndpointFilter, side: str, a: str, params: list[Any]) -> str:
    """The labels part when it names label groups: every named group exists, and the end's label set holds, for each
    key the part names, one of that key's allowed values (the key's listed values and its groups' members). A label
    set has one value per key, so counting the keys it matches among the allowed pairs counts the keys it satisfies."""
    groups = sorted(set(ep.label_groups))
    gm = ",".join("?" * len(groups))
    pairs = [(c.key, v) for c in ep.labels for v in c.values]
    cond_keys = sorted({c.key for c in ep.labels})
    allowed = f"SELECT key, value FROM label_group_members WHERE href IN ({gm})" + " UNION ALL SELECT ?, ?" * len(pairs)
    keys = f"SELECT key FROM label_groups WHERE href IN ({gm})" + " UNION SELECT ?" * len(cond_keys)
    params.extend(groups)
    params.extend(groups)
    params.extend(x for pair in pairs for x in pair)
    params.extend(groups)
    params.extend(cond_keys)
    return (f"((SELECT COUNT(*) FROM label_groups WHERE href IN ({gm})) = {len(groups)} "
            f"AND COALESCE({a}.{side}_label_set, -1) IN (SELECT m.set_id FROM label_set_members m "
            f"WHERE (m.key, m.value) IN ({allowed}) GROUP BY m.set_id "
            f"HAVING COUNT(DISTINCT m.key) = (SELECT COUNT(DISTINCT key) FROM ({keys}))))")


def _sql_services(hrefs: tuple[str, ...], a: str, params: list[Any]) -> str:
    params.extend(hrefs)
    return (f"EXISTS (SELECT 1 FROM pce_service_ports s WHERE s.href IN ({','.join('?' * len(hrefs))}) "
            f"AND (s.proto IS NULL OR s.proto = {a}.proto) "
            f"AND (s.port IS NULL OR COALESCE({a}.port, -1) BETWEEN s.port AND COALESCE(s.to_port, s.port)))")


def _sql_in(expr: str, values: Sequence[Any], params: list[Any], *, negate: bool) -> str:
    """expr IN values; negated, a NULL expr is not left out (an exclusion never drops a missing value)."""
    params.extend(values)
    inside = f"{expr} IN ({','.join('?' * len(values))})"
    return f"NOT COALESCE({inside}, 0)" if negate else inside


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


def to_sql(spec: FilterSpec, *, table_alias: str = "f", wide: bool = False) -> tuple[str, list[Any]]:
    """wide: the window holds most of the stored rows, so the time bound must not pick the last_detected index
    (walking it for most of the table is several times slower than a scan; flowsource.wide_window decides)."""
    a = table_alias
    params: list[Any] = [store_time(spec.start), store_time(spec.end)]
    clauses = [f"{a}.is_primary = 1", f"{'+' if wide else ''}{a}.last_detected >= ?", f"{a}.first_detected <= ?"]
    for side, ep, negate in (("src", spec.src, False), ("dst", spec.dst, False),
                             ("src", spec.src_exclude, True), ("dst", spec.dst_exclude, True)):
        if ep is not None and not ep.is_empty():
            clause = _sql_side(ep, side, a, params)
            clauses.append(f"NOT {clause}" if negate else clause)
    for ep, negate in ((spec.either, False), (spec.either_exclude, True)):
        if ep is not None and not ep.is_empty():
            clause = f"({_sql_side(ep, 'src', a, params)} OR {_sql_side(ep, 'dst', a, params)})"
            clauses.append(f"NOT {clause}" if negate else clause)
    for ports, services, negate in ((spec.ports, spec.services, False), (spec.exclude_ports, spec.exclude_services, True)):
        terms = [_sql_port(p, a, params) for p in ports] + ([_sql_services(services, a, params)] if services else [])
        if terms:
            clauses.append(("NOT (" if negate else "(") + " OR ".join(terms) + ")")
    if spec.windows_services:
        clauses.append(_sql_in(f"lower({a}.windows_service)", [ascii_lower(x) for x in spec.windows_services], params,
                               negate=False))
    if spec.exclude_windows_services:
        clauses.append(_sql_in(f"lower({a}.windows_service)", [ascii_lower(x) for x in spec.exclude_windows_services],
                               params, negate=True))
    if spec.transmissions:
        clauses.append(_sql_in(f"lower({a}.transmission)", list(spec.transmissions), params, negate=False))
    if spec.exclude_transmissions:
        clauses.append(_sql_in(f"lower({a}.transmission)", list(spec.exclude_transmissions), params, negate=True))
    if spec.exclude_processes:
        clauses.append(_sql_in(f"{a}.initiator_process", spec.exclude_processes, params, negate=True))
        clauses.append(_sql_in(f"{a}.service_process", spec.exclude_processes, params, negate=True))
    if spec.decisions:
        clauses.append(f"{a}.policy_decision IN ({','.join('?' * len(spec.decisions))})")
        params.extend(d.value for d in spec.decisions)
    for column in ("initiator_process", "initiator_user", "service_process", "service_user"):
        term = getattr(spec, column)
        if term:
            clauses.append(f"{a}.{column} LIKE ? ESCAPE '\\'")
            params.append(like_pattern(term))
        values = getattr(spec, f"{column}es" if column.endswith("process") else f"{column}s")
        if values:
            expr = _sql_user(f"{a}.{column}") if column.endswith("user") else f"{a}.{column}"
            clauses.append(f"{expr} IN ({','.join('?' * len(values))})")
            params.extend(user_key(x) if column.endswith("user") else x for x in values)
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
            "windows_service": record.windows_service, "transmission": record.transmission,
            "first_detected": record.first_detected, "last_detected": record.last_detected,
        }
    return dict(record)


def _when(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _labels_hold(ep: EndpointFilter, labels: Mapping[str, str], groups: LabelGroups) -> bool:
    allowed: dict[str, set[str]] = {}
    for c in ep.labels:
        allowed.setdefault(c.key, set()).update(c.values)
    for h in ep.label_groups:
        if h not in groups:
            return False  # a group the PCE no longer has matches nothing
        key, members = groups[h]
        allowed.setdefault(key, set()).update(members)
    return all(labels.get(k) in vs for k, vs in allowed.items())


def _side_matches(ep: EndpointFilter, v: Mapping[str, Any], side: str, ip_lists: IpLists,
                  label_groups: LabelGroups) -> bool:
    labels = v.get(f"{side}_labels") or {}
    exact, nets = _split_ips(ep.ips)
    ip = v.get(f"{side}_ip")
    held = []  # (the part is set, the end satisfies it)
    held.append((ep.has_labels(), ep.has_labels() and _labels_hold(ep, labels, label_groups)))
    href = v.get(f"{side}_href")
    listed = (n for h in ep.ip_lists for n in ip_lists.get(h, ()))
    held.append((ep.has_hosts(), (href or "") in ep.hrefs
                 or ip in exact or any(ip_in_net(ip, n) for n in nets) or (ep.public and outside(ip, href))
                 or any(ip_in_net(ip, n) for n in listed)))
    if ep.match == "all":
        return all(ok for is_set, ok in held if is_set)
    return any(ok for is_set, ok in held if is_set)


def _port_matches(p: PortProto, v: Mapping[str, Any]) -> bool:
    if p.proto is not None and v.get("proto") != p.proto:
        return False
    port = v.get("port")
    port = -1 if port is None else port
    if p.to_port is not None:
        return p.port is not None and p.port <= port <= p.to_port
    return p.port is None or port == p.port


def _service_matches(entries: Sequence[tuple[int | None, int | None, int | None]], v: Mapping[str, Any]) -> bool:
    port = v.get("port")
    port = -1 if port is None else port
    return any((proto is None or v.get("proto") == proto)
               and (lo is None or lo <= port <= (hi if hi is not None else lo)) for lo, hi, proto in entries)


def _in_ci(value: Any, values: Sequence[str]) -> bool:
    return isinstance(value, str) and ascii_lower(value) in {ascii_lower(x) for x in values}


def port_matches(p: PortProto, port: int | None, proto: int) -> bool:
    """One port condition on a (port, proto) pair, as matches and to_sql apply it."""
    return _port_matches(p, {"port": port, "proto": proto})


def _endpoints(spec: FlowCondition) -> tuple[EndpointFilter, ...]:
    return tuple(ep for ep in (spec.src, spec.dst, spec.src_exclude, spec.dst_exclude, spec.either,
                               spec.either_exclude) if ep is not None)


def ip_list_hrefs(spec: FlowCondition) -> set[str]:
    """The IP lists a spec names on any side (what matches needs the networks of)."""
    return {h for ep in _endpoints(spec) for h in ep.ip_lists}


def label_group_hrefs(spec: FlowCondition) -> set[str]:
    """The label groups a spec names on any side (what matches needs the members of)."""
    return {h for ep in _endpoints(spec) for h in ep.label_groups}


def service_hrefs(spec: FlowCondition) -> set[str]:
    """The services a spec names (what matches needs the ports of)."""
    return set(spec.services) | set(spec.exclude_services)


def endpoint_matches(ep: EndpointFilter, *, href: str | None, ip: str, labels: Mapping[str, str],
                     ip_lists: IpLists | None = None, label_groups: LabelGroups | None = None) -> bool:
    """One endpoint condition on one end (a host's href, address and labels), as matches applies it."""
    return _side_matches(ep, {"x_href": href, "x_ip": ip, "x_labels": labels}, "x", ip_lists or {}, label_groups or {})


def _service_set(ports: tuple[PortProto, ...], services: tuple[str, ...], v: Mapping[str, Any],
                 known: ServicePorts) -> bool:
    return (any(_port_matches(p, v) for p in ports)
            or any(_service_matches(known.get(h, ()), v) for h in services))


def matches(spec: FilterSpec, record: FlowRecord | Mapping[str, Any], *, ip_lists: IpLists | None = None,
            label_groups: LabelGroups | None = None, services: ServicePorts | None = None) -> bool:
    """ip_lists, label_groups, services: what the spec's IP lists, label groups and services stand for (the flow
    store's ip_lists.networks, policy_objects.label_groups and policy_objects.service_ports)."""
    v = _view(record)
    if v.get("is_primary", 1) != 1:
        return False
    if _when(v["last_detected"]) < spec.start or _when(v["first_detected"]) > spec.end:
        return False
    nets, groups, known = ip_lists or {}, label_groups or {}, services or {}
    for side, ep, negate in (("src", spec.src, False), ("dst", spec.dst, False),
                             ("src", spec.src_exclude, True), ("dst", spec.dst_exclude, True)):
        if ep is not None and not ep.is_empty() and _side_matches(ep, v, side, nets, groups) == negate:
            return False
    for ep, negate in ((spec.either, False), (spec.either_exclude, True)):
        if ep is not None and not ep.is_empty() and (
                _side_matches(ep, v, "src", nets, groups) or _side_matches(ep, v, "dst", nets, groups)) == negate:
            return False
    if (spec.ports or spec.services) and not _service_set(spec.ports, spec.services, v, known):
        return False
    if (spec.exclude_ports or spec.exclude_services) and _service_set(spec.exclude_ports, spec.exclude_services, v,
                                                                      known):
        return False
    if spec.windows_services and not _in_ci(v.get("windows_service"), spec.windows_services):
        return False
    if spec.exclude_windows_services and _in_ci(v.get("windows_service"), spec.exclude_windows_services):
        return False
    if spec.transmissions and not _in_ci(v.get("transmission"), spec.transmissions):
        return False
    if spec.exclude_transmissions and _in_ci(v.get("transmission"), spec.exclude_transmissions):
        return False
    if spec.exclude_processes and (v.get("initiator_process") in spec.exclude_processes
                                   or v.get("service_process") in spec.exclude_processes):
        return False
    if spec.decisions and v.get("policy_decision") not in {d.value for d in spec.decisions}:
        return False
    for column in ("initiator_process", "initiator_user", "service_process", "service_user"):
        term = getattr(spec, column)
        if term and not _like(v.get(column), term):
            return False
        values = getattr(spec, f"{column}es" if column.endswith("process") else f"{column}s")
        if values:
            got = v.get(column)
            if column.endswith("user"):
                if got is None or user_key(got) not in {user_key(x) for x in values}:
                    return False
            elif got not in values:
                return False
    if spec.text and not any(_like(v.get(c), spec.text) for c in _TEXT_COLUMNS):
        return False
    return not (spec.exclude_system_accounts and is_system_account(v.get("initiator_user")))
