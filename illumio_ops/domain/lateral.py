"""What every lateral-movement analysis shares (spec §6.5.1): the management port set, and which hosts are
critical assets or in an admin group. Pure: the service layer reads settings, inventory and labels."""
from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Literal

from illumio_ops.domain.filter import PortProto

Selector = tuple[str, str]  # (label key, label value)


@dataclass(frozen=True)
class AdminPort:
    port: int
    proto: int | None  # None = any protocol
    name: str | None
    source: Literal["builtin", "pce", "added"]


@dataclass(frozen=True)
class AdminPortSet:
    entries: tuple[AdminPort, ...]

    @cached_property
    def _lookup(self) -> frozenset[tuple[int, int | None]]:
        return frozenset((e.port, e.proto) for e in self.entries)

    def matches(self, port: int | None, proto: int) -> bool:
        # Read for every baseline row of the exposure graph: a set lookup, not a scan of the entries.
        return port is not None and ((port, None) in self._lookup or (port, proto) in self._lookup)

    @cached_property
    def _filters(self) -> tuple[PortProto, ...]:
        return tuple(dict.fromkeys(PortProto(port=e.port, proto=e.proto) for e in self.entries))

    def port_filters(self) -> tuple[PortProto, ...]:
        return self._filters  # every detection's evidence segment carries it


def effective_admin_ports(builtin: Sequence[tuple[int, str]], pce_admin: Sequence[tuple[int, int, str]],
                          extra: Sequence[tuple[int, int | None]], removed: Sequence[tuple[int, int | None]],
                          include_pce: bool) -> AdminPortSet:
    """Built-in list ∪ the PCE's high-risk services of category admin (when included) ∪ ports added, minus
    the ports removed; a removal without a protocol removes the port for every protocol."""
    candidates = [AdminPort(p, None, name, "builtin") for p, name in builtin]
    if include_pce:
        candidates += [AdminPort(p, proto, name, "pce") for p, proto, name in pce_admin]
    candidates += [AdminPort(p, proto, None, "added") for p, proto in extra]

    def gone(e: AdminPort) -> bool:
        return any(p == e.port and (proto is None or proto == e.proto) for p, proto in removed)

    return AdminPortSet(tuple(dict.fromkeys(e for e in candidates if not gone(e))))


@dataclass(frozen=True)
class HostInfo:
    key: str
    href: str | None
    hostname: str | None
    managed: bool
    labels: Mapping[str, str]
    enforcement_mode: str | None
    visibility_level: str | None
    os_id: str | None
    ven_href: str | None
    critical: bool
    admin_group: bool


def selector_matches(labels: Mapping[str, str], selectors: Sequence[Selector]) -> bool:
    """Any one key=value is enough (a union: spec examples app=Finance and role=DB each stand alone)."""
    return any(labels.get(k) == v for k, v in selectors)


def stale_selectors(selectors: Sequence[Selector], known: Collection[Selector]) -> list[Selector]:
    """Selectors naming a label the current inventory does not have (deleted or renamed in the PCE)."""
    return [s for s in selectors if s not in known]
