"""The flow database belongs to one PCE; a collector never writes another PCE's data into it."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from urllib.parse import urlsplit

from illumio_ops.settings.schema import PceSettings
from illumio_ops.store.flowdb import binding


class BindingMismatch(Exception):
    """The flow database is bound to a different PCE than the one configured."""


_DEFAULT_PORTS = {"https": 443, "http": 80}


def normalize_target(url: str, org_id: str) -> tuple[str, str]:
    """A PCE's identity: scheme, host, port (default folded), base path, and org — compared without
    being fooled by case, a trailing slash, an explicit default port or a zero-padded org ID.
    The result parses back to itself (IPv6 hosts keep their brackets)."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    authority = host if port is None or _DEFAULT_PORTS.get(scheme) == port else f"{host}:{port}"
    org = org_id.strip()
    return f"{scheme}://{authority}{parts.path.rstrip('/')}", str(int(org)) if org.isdigit() else org


def ensure_binding(conn: sqlite3.Connection, pce: PceSettings, now: datetime) -> None:
    want = normalize_target(pce.url, pce.org_id)
    current = binding.current(conn)
    if current is None:
        binding.bind(conn, want[0], want[1], now)
        return
    if normalize_target(current.pce_url, current.org_id) != want:
        raise BindingMismatch("the flow database belongs to another PCE")


def require_same_pce(conn: sqlite3.Connection, pce: PceSettings) -> None:
    """For readers: refuse to answer from another PCE's data (a switch whose clearing has not finished)."""
    current = binding.current(conn)
    if current is not None and normalize_target(current.pce_url, current.org_id) != normalize_target(pce.url, pce.org_id):
        raise BindingMismatch("the flow database still holds another PCE's data; the next collector run clears it")
