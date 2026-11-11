"""The hosts an alert is about (purpose-led UI spec §8): a detection's from its fingerprint, an event rule's from the
events that fired it. A host is named by its key — a workload href or ip:<address>, as every page names hosts. A part
of a fingerprint that is not such a key (an account, a process, a signature, a port) is left out: nothing is guessed."""
from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

Role = Literal["source", "destination", "subject"]

MAX_DEVICES = 20  # the most an alert lists; the rest are a count

_HREF = re.compile(r"^/orgs/\d+/(?:workloads|kubernetes_workloads|container_workloads)/[A-Za-z0-9_.-]+$")

# detector prefix -> the role of each part after it (None: not a host)
_PARTS: dict[str, tuple[Role | None, ...]] = {
    "xenv": ("source", "destination"), "nag": ("source", "destination"), "new": ("source", "destination"),
    "authdst": ("source", "destination"), "reverse": ("source", "destination"), "pairport": ("source", "destination"),
    "chain": ("source", "destination", "destination"), "staging": ("destination",),
    "acct": (None,), "acctsrc": (None, "source"),
}


@dataclass(frozen=True)
class Device:
    key: str
    role: Role


def is_host_key(value: str) -> bool:
    if value.startswith("ip:"):
        try:
            ipaddress.ip_address(value[3:])
        except ValueError:
            return False
        return True
    return bool(_HREF.match(value))


def devices_of_detection(fingerprint: str) -> tuple[Device, ...]:
    """The hosts in a detection's fingerprint (`<detector>|<part>|…`). Detectors not listed above are about their
    first part, the source — when that part is a host."""
    prefix, _, rest = fingerprint.partition("|")
    parts = rest.split("|") if rest else []
    roles = _PARTS.get(prefix, ("source",))
    out: list[Device] = []
    for part, role in zip(parts, roles, strict=False):
        if role is not None and is_host_key(part) and Device(part, role) not in out:
            out.append(Device(part, role))
    return tuple(out)


def devices_of_events(hosts: Iterable[str | None]) -> tuple[Device, ...]:
    """The hosts of the events that fired a rule: once each, in the order met."""
    seen: dict[str, None] = {}
    for host in hosts:
        if host and is_host_key(host):
            seen.setdefault(host)
    return tuple(Device(key, "subject") for key in seen)


def capped(devices: tuple[Device, ...]) -> tuple[tuple[Device, ...], int]:
    """(the devices an alert lists, how many more there were)."""
    return devices[:MAX_DEVICES], max(0, len(devices) - MAX_DEVICES)
