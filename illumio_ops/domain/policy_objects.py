"""What a flow condition reads from two PCE policy objects (5.x parity 2026-11-06): a service's ports and a label
group's member labels."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

PortEntry = tuple[int | None, int | None, int | None]  # (port, to_port, proto); None = any


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def service_port_entries(service: Mapping[str, Any]) -> tuple[PortEntry, ...]:
    """The ports of a service's service_ports and windows_services. A proto of -1 (All Services) is any protocol; an
    entry with neither a port nor a protocol (a Windows service by name alone) has no port to match a flow on."""
    out: list[PortEntry] = []
    for entry in [*(service.get("service_ports") or []), *(service.get("windows_services") or [])]:
        if not isinstance(entry, Mapping) or (entry.get("port") is None and entry.get("proto") is None):
            continue
        proto, port = _int(entry.get("proto")), _int(entry.get("port"))
        to_port = _int(entry.get("to_port")) if port is not None else None
        out.append((port, to_port if to_port is not None and to_port >= (port or 0) else None,
                    proto if proto is not None and proto >= 0 else None))
    return tuple(dict.fromkeys(out))


def label_group_values(group: Mapping[str, Any], groups: Mapping[str, Mapping[str, Any]],
                       labels: Mapping[str, tuple[str, str]]) -> tuple[str, ...]:
    """The values of the group's member labels, its sub-groups' included (a cycle stops). A member of another key
    (the PCE does not allow one) is left out: a group stands for values of its own key."""
    key = group.get("key")
    seen: set[str] = set()
    values: set[str] = set()
    todo: list[Mapping[str, Any]] = [group]
    while todo:
        g = todo.pop()
        href = str(g.get("href") or "")
        if href in seen:
            continue
        seen.add(href)
        for ref in _refs(g.get("labels")):
            if ref in labels and labels[ref][0] == key:
                values.add(labels[ref][1])
        todo.extend(groups[ref] for ref in _refs(g.get("sub_groups")) if ref in groups)
    return tuple(sorted(values))


def _refs(items: Any) -> Sequence[str]:
    return [str(i["href"]) for i in items or [] if isinstance(i, Mapping) and i.get("href")]
