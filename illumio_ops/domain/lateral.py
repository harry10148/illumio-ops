"""What every lateral-movement analysis shares (spec §6.5.1): the management port set, and which hosts are
critical assets or in an admin group. Pure: the service layer reads settings, inventory and labels."""
from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Literal

from illumio_ops.domain.filter import PortProto
from illumio_ops.domain.values import PortClass, builtin_protocols

Selector = tuple[str, str]  # (label key, label value)


@dataclass(frozen=True)
class AdminPort:
    port: int
    proto: int | None  # None = any protocol
    name: str | None
    source: Literal["builtin", "pce", "added"]
    category: PortClass = PortClass.REMOTE


# Which classes each kind of reader takes (spec §6.5.8).
EXECUTION: frozenset[PortClass] = frozenset({PortClass.REMOTE})
EXECUTION_OR_DATA: frozenset[PortClass] = frozenset({PortClass.REMOTE, PortClass.DATABASE})
GRAPH_CLASSES = EXECUTION_OR_DATA  # the exposure graph: directory edges would make every member reach the DCs


@dataclass(frozen=True)
class AdminPortSet:
    entries: tuple[AdminPort, ...]

    @cached_property
    def _lookup(self) -> dict[tuple[int, int | None], PortClass]:
        out: dict[tuple[int, int | None], PortClass] = {}
        for e in self.entries:
            out.setdefault((e.port, e.proto), e.category)
        return out

    def class_of(self, port: int | None, proto: int) -> PortClass | None:
        # Read for every baseline row of the exposure graph: a dict lookup, not a scan of the entries.
        if port is None:
            return None
        found = self._lookup.get((port, proto))
        return found if found is not None else self._lookup.get((port, None))

    def matches(self, port: int | None, proto: int, classes: Collection[PortClass] | None = None) -> bool:
        found = self.class_of(port, proto)
        return found is not None and (classes is None or found in classes)

    @cached_property
    def _filters(self) -> dict[frozenset[PortClass] | None, tuple[PortProto, ...]]:
        return {}

    def port_filters(self, classes: Collection[PortClass] | None = None) -> tuple[PortProto, ...]:
        """Every detection's evidence segment carries the ports of the classes its detector reads."""
        key = None if classes is None else frozenset(classes)
        if key not in self._filters:
            self._filters[key] = tuple(dict.fromkeys(PortProto(port=e.port, proto=e.proto) for e in self.entries
                                                     if key is None or e.category in key))
        return self._filters[key]


def effective_admin_ports(builtin: Sequence[tuple[int, str, PortClass]], pce_admin: Sequence[tuple[int, int, str]],
                          extra: Sequence[tuple[int, int | None, PortClass]],
                          removed: Sequence[tuple[int, int | None]], include_pce: bool) -> AdminPortSet:
    """Built-in list (each port on its own protocols, values.builtin_protocols) ∪ the PCE's high-risk services of category admin (when included; remote execution) ∪ ports
    added, minus the ports removed; a removal without a protocol removes the port for every protocol."""
    candidates = [AdminPort(p, proto, name, "builtin", cls) for p, name, cls in builtin for proto in builtin_protocols(p)]
    if include_pce:
        candidates += [AdminPort(p, proto, name, "pce", PortClass.REMOTE) for p, proto, name in pce_admin]
    candidates += [AdminPort(p, proto, None, "added", cls) for p, proto, cls in extra]

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
