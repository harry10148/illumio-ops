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


_PRIVATE = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))
_SHARED = ipaddress.ip_network("100.64.0.0/10")


def address_scope(value: str | None) -> str:
    """Which space an address is numbered in: "public" (globally routed), "private" (RFC 1918, IPv6 ULA), "shared"
    (RFC 6598 carrier space, 100.64.0.0/10) or "other" (link-local, loopback, reserved, not an address)."""
    if is_public(value):
        return "public"
    try:
        addr = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return "other"
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if addr.version == 4 and addr in _SHARED:
        return "shared"
    return "private" if any(addr.version == n.version and addr in n for n in _PRIVATE) else "other"


def outside(ip: str | None, href: str | None) -> bool:
    """An end outside the estate: a public address no workload holds. Some organisations number their own hosts in
    public space; a workload the PCE knows is inside whatever its address."""
    return not href and is_public(ip)
