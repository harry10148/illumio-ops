"""Protocol names and display labels shared by domain display surfaces."""
from __future__ import annotations

PROTOCOLS = {6: "TCP", 17: "UDP", 1: "ICMP", 58: "ICMPv6", 47: "GRE", 50: "ESP"}


def service_label(port: int | None, proto: int | None, to_port: int | None = None) -> str:
    """A service label. Missing/-1 protocol means any protocol, shown as the port alone."""
    if proto is None or proto == -1:
        if port is None or port < 0:
            return "*"  # every port of every protocol (a quarantine rule's "all services")
        return f"{port}-{to_port}" if to_port is not None else str(port)
    name = PROTOCOLS.get(proto, str(proto))
    if port is None or port < 0:
        return name
    span = f"{port}-{to_port}" if to_port is not None else str(port)
    return f"{span}/{name}"
