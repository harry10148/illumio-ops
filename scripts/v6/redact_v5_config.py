"""Copy a 5.x config.json with every secret, host name, address, e-mail and org id replaced.

    python3 -I redact_v5_config.py <in.json> <out.json>

Standard library only, so it runs with the 5.x interpreter on the machine that holds the
real file; only the redacted copy should ever leave that machine. Prints nothing.
Shapes the migrator relies on are kept: an argon2 hash stays an argon2-shaped string,
a hex key stays hex of the same length, URLs keep their scheme and port.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

SECRET_KEY = re.compile(r"(secret|passw|token|credential|private|webhook|api_?key|^key$)", re.IGNORECASE)
HOST_KEY = re.compile(r"(host|hostname|server|fqdn|address)$", re.IGNORECASE)
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_HOST = re.compile(r"(https?://)([^/:\s]+)")
OPAQUE = re.compile(r"^[A-Za-z0-9+/=_:.\-]{24,}$")
HEX = re.compile(r"^[0-9a-fA-F]{32,}$")
FAKE_ARGON2 = "$argon2id$v=19$m=131072,t=4,p=4$cmVkYWN0ZWRzYWx0$cmVkYWN0ZWRyZWRhY3RlZHJlZGFjdGVkcmVkYWN0ZWQ"


class Aliases:
    def __init__(self) -> None:
        self.hosts: dict[str, str] = {}
        self.ips: dict[str, str] = {}

    def host(self, name: str) -> str:
        return self.hosts.setdefault(name.lower(), f"host-{len(self.hosts) + 1}.example.invalid")

    def ip(self, addr: str) -> str:
        return self.ips.setdefault(addr, f"192.0.2.{len(self.ips) + 1}")


def redact_secret(value: str) -> str:
    if value == "":
        return ""
    if value.startswith("$argon2"):
        return FAKE_ARGON2
    if HEX.match(value):
        return "f" * len(value)
    return "REDACTED"


def redact_string(key: str, value: str, al: Aliases) -> str:
    if SECRET_KEY.search(key):
        return redact_secret(value)
    if key == "org_id":
        return "1" if value else value
    out = URL_HOST.sub(lambda m: m.group(1) + (al.ip(m.group(2)) if IPV4.fullmatch(m.group(2))
                                               else al.host(m.group(2))), value)
    out = IPV4.sub(lambda m: al.ip(m.group(0)), out)
    out = EMAIL.sub("user@example.invalid", out)
    if out == value and HOST_KEY.search(key) and value and not value.isdigit():
        out = al.host(value)
    if OPAQUE.match(out) and not out.isdigit() and "example.invalid" not in out and not out.startswith("192.0.2."):
        out = "REDACTED"
    return out


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
