"""Copy a 5.x config.json with nothing that identifies a customer left in it.

    python3 -I redact_v5_config.py <in.json> <out.json>

Default deny: every string is replaced unless its key is on the SAFE_KEYS list of known
enumerations (language, transport, …). Replacements keep the shapes the migrator relies on:
argon2 hashes stay argon2-shaped, hex keys stay hex, URLs keep scheme and port (host aliased,
user info, path and query dropped), IP addresses and networks move into the documentation
ranges with their prefix length kept, org ids become "1". Numbers and booleans are kept.
Standard library only, so it runs with the 5.x interpreter on the machine that holds the real
file; only the redacted copy should leave that machine. Prints nothing.
"""
from __future__ import annotations

import ipaddress
import json
import re
import sys
from typing import Any
from urllib.parse import urlsplit

# Keys whose string values are product enumerations, never customer data.
SAFE_KEYS = frozenset({
    "language", "timezone", "theme", "deployment_type", "profile", "min_version", "key_algorithm",
    "level", "rotation", "format", "schedule", "day_of_week", "source", "transport", "type", "active",
    "protocol", "severity", "frequency", "report_type", "ciphers", "direction", "policy_decision",
    "policy_decisions", "mode", "output_format", "compression", "strategy", "unit",
})
FAKE_ARGON2 = "$argon2id$v=19$m=131072,t=4,p=4$cmVkYWN0ZWRzYWx0$cmVkYWN0ZWRyZWRhY3RlZHJlZGFjdGVkcmVkYWN0ZWQ"
HEX = re.compile(r"[0-9a-fA-F]{32,}")


class Aliases:
    def __init__(self) -> None:
        self.hosts: dict[str, str] = {}
        self.v4: dict[str, str] = {}
        self.v6: dict[str, str] = {}
        self.other = 0

    def host(self, name: str) -> str:
        return self.hosts.setdefault(name.lower(), f"host-{len(self.hosts) + 1}.example.invalid")

    def ip(self, addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
        if addr.version == 4:
            return self.v4.setdefault(str(addr), f"192.0.2.{len(self.v4) + 1}")
        return self.v6.setdefault(str(addr), f"2001:db8::{len(self.v6) + 1:x}")

    def opaque(self) -> str:
        self.other += 1
        return f"redacted-{self.other}"


def _as_ip(value: str, al: Aliases) -> str | None:
    try:
        if "/" in value:
            net = ipaddress.ip_network(value, strict=False)
            return f"{al.ip(net.network_address)}/{net.prefixlen}"
        return al.ip(ipaddress.ip_address(value))
    except ValueError:
        return None


def _as_url(value: str, al: Aliases) -> str | None:
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        return None
    try:
        parts = urlsplit(value)
        host, port = parts.hostname, parts.port
    except ValueError:
        return f"https://{al.host(value)}"
    if not host:
        return None
    ip = _as_ip(host, al)
    new_host = ip if ip else al.host(host)
    if ip and ":" in ip:
        new_host = f"[{ip}]"
    return f"{parts.scheme}://{new_host}" + (f":{port}" if port else "")


def redact_string(key: str, value: str, al: Aliases) -> str:
    if value == "" or key in SAFE_KEYS:
        return value
    if key == "org_id":
        return "1"
    if value.startswith("$argon2"):
        return FAKE_ARGON2
    if HEX.fullmatch(value):
        return "f" * len(value)
    for convert in (_as_url, _as_ip):
        out = convert(value, al)
        if out is not None:
            return out
    return al.opaque()


def redact(node: Any, key: str, al: Aliases) -> Any:
    if isinstance(node, dict):
        return {k: redact(v, k, al) for k, v in node.items()}
    if isinstance(node, list):
        return [redact(v, key, al) for v in node]
    if isinstance(node, str):
        return redact_string(key, node, al)
    if key == "org_id" and isinstance(node, int) and not isinstance(node, bool):
        return 1
    return node


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write("usage: redact_v5_config.py <in.json> <out.json>\n")
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
    with open(argv[2], "w", encoding="utf-8") as fh:
        json.dump(redact(data, "", Aliases()), fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
