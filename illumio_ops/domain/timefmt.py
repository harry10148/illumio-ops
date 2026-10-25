"""The two timestamp formats v6 writes: what the PCE accepts in queries, and what the flow
database stores (fixed width, so text order is time order)."""
from __future__ import annotations

from datetime import UTC, datetime


def pce_time(value: datetime) -> str:
    """The PCE rejects a bare date or an offset-less time (HTTP 406)."""
    if value.tzinfo is None:
        raise ValueError("PCE timestamps need a time zone")
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def store_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("stored timestamps need a time zone")
    return value.astimezone(UTC).isoformat(timespec="milliseconds")
