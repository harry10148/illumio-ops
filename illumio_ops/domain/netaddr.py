"""IP addresses and networks as the allowlist accepts them (shared by the settings schema
and the web layer). An IPv4-mapped IPv6 address is treated as the IPv4 address it maps."""
from __future__ import annotations

import ipaddress

IpToken = ipaddress.IPv4Address | ipaddress.IPv6Address | ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_ip_token(value: str) -> IpToken:
    """An address or a network; ValueError for anything else."""
    token = str(value or "").strip()
    if not token:
        raise ValueError("empty address")
    if "/" in token:
        net = ipaddress.ip_network(token, strict=False)
        if isinstance(net, ipaddress.IPv6Network) and net.network_address.ipv4_mapped:
            mapped = net.network_address.ipv4_mapped
            return ipaddress.ip_network(f"{mapped}/{max(0, net.prefixlen - 96)}", strict=False)
        return net
    addr = ipaddress.ip_address(token)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        return addr.ipv4_mapped
    return addr


def is_public(value: str | None) -> bool:
    """A globally routed address (not RFC 1918, CGNAT, link-local, loopback, IPv6 ULA...); anything that is not an
    address — empty, the PCE's FILTERED — is not public."""
    try:
        addr = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global
