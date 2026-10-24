"""Collectors: bring PCE data into the flow database on the schedule set in settings."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CycleResult:
    rows: int       # records written (new or refreshed)
    windows: int    # PCE queries that answered
    gaps: int       # windows recorded as failed or truncated
    skipped: int = 0  # records the PCE sent in a shape we could not read
