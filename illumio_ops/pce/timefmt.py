"""The only timestamp format the PCE accepts in queries (a bare date or an offset-less time is 406)."""
from __future__ import annotations

from datetime import UTC, datetime


def pce_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("PCE timestamps need a time zone")
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
