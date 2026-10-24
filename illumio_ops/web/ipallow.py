"""IP allowlist and the RST drop, ported from 5.x src/gui/_helpers.py.

A refused client gets no HTTP response at all: the socket is closed with RST so
a scanner cannot tell an HTTP service is listening.
"""
from __future__ import annotations

import ipaddress
import socket
import struct
from collections.abc import Iterable

from flask import request

from illumio_ops.domain.netaddr import IpToken, parse_ip_token


class RstDrop(Exception):
    """The request was dropped with a TCP RST; nothing must be written back."""


class InvalidIpEntries(ValueError):
    def __init__(self, invalid: list[str]) -> None:
        self.invalid = invalid
        super().__init__(f"{len(invalid)} invalid IP allowlist entries")


def normalize_ip_token(value: str) -> IpToken:
    return parse_ip_token(value)


def is_allowed(allowed_ips: Iterable[str], remote_addr: str | None) -> bool:
    allowed = list(allowed_ips)
    if not allowed:
        return True
    try:
        remote = normalize_ip_token(remote_addr or "")
    except ValueError:
        return False
    if isinstance(remote, (ipaddress.IPv4Network, ipaddress.IPv6Network)):
        return False
    for entry in allowed:
        try:
            tok = normalize_ip_token(entry)
        except ValueError:
            continue
        if isinstance(tok, (ipaddress.IPv4Network, ipaddress.IPv6Network)):
            if remote.version == tok.version and remote in tok:
                return True
        elif remote == tok or (remote.is_loopback and tok.is_loopback):
            return True
    return False


def validate_allowed_ips(items: Iterable[str]) -> list[str]:
    """Canonical strings for the non-blank entries; InvalidIpEntries lists the bad ones."""
    out, invalid = [], []
    for raw in items:
        item = str(raw or "").strip()
        if not item:
            continue
        try:
            out.append(str(normalize_ip_token(item)))
        except ValueError:
            invalid.append(item)
    if invalid:
        raise InvalidIpEntries(invalid)
    return out


def _request_socket() -> socket.socket | None:
    env = request.environ
    sock = env.get("werkzeug.socket")
    if isinstance(sock, socket.socket):
        return sock
    obj = env.get("wsgi.input")
    for path in (("raw",), ("_sock",), ("raw", "_sock")):
        cur = obj
        for attr in path:
            cur = getattr(cur, attr, None)
        if isinstance(cur, socket.socket):
            return cur
    return None


def rst_drop() -> None:
    """Close the client socket with RST (SO_LINGER 0) and abort the request."""
    sock = _request_socket()
    if sock is not None:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # already closed: the RST is best-effort, the abort below is not
    raise RstDrop()
