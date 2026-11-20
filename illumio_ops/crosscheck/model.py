"""What every check returns, and what every check is given."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, get_args

from illumio_ops.paths import InstallPaths
from illumio_ops.pce.client import PceClient
from illumio_ops.settings.schema import Settings

Status = Literal["consistent", "inconsistent", "unchecked"]
STATUSES: tuple[Status, ...] = get_args(Status)


@dataclass(frozen=True)
class Finding:
    """One compared item. `unchecked` is never a pass: `detail` says why it could not be compared.

    `sample` holds identifiers only (field names, event_type, timestamp, href), never content values or credentials.
    """
    area: str
    item: str
    status: Status
    detail: str
    sample: Any = field(default=None)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}, not {self.status!r}")


@dataclass(frozen=True)
class Run:
    """One invocation: where the install is, its settings, a PCE client, the period [start, end) and the moment the
    run began (`now`: retention and collection lag are measured from it, not from `end`), all UTC."""
    paths: InstallPaths
    settings: Settings
    pce: PceClient
    start: datetime
    end: datetime
    now: datetime
