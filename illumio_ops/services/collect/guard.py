"""The flow database belongs to one PCE; a collector never writes another PCE's data into it."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from urllib.parse import urlsplit

from illumio_ops.settings.schema import PceSettings
from illumio_ops.store.flowdb import binding


class BindingMismatch(Exception):
    """The flow database is bound to a different PCE than the one configured."""


def normalize_target(url: str, org_id: str) -> tuple[str, str]:
    """Compare PCE identities without being fooled by case or a trailing slash."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme.lower()}://{host}{port}", org_id.strip()


def ensure_binding(conn: sqlite3.Connection, pce: PceSettings, now: datetime) -> None:
    want = normalize_target(pce.url, pce.org_id)
    current = binding.current(conn)
    if current is None:
        binding.bind(conn, want[0], want[1], now)
        return
    if normalize_target(current.pce_url, current.org_id) != want:
        raise BindingMismatch("the flow database belongs to another PCE")
