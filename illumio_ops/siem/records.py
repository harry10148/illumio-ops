"""What one forwarded line says, whatever its format (spec §6.5 SIEM 轉送, P7): an audit event as the PCE gave it,
or one of this product's own events — a detection, an alert, a new connection — with its text already in the display
language and both ends named. A new connection carries no connection or byte counts: the PCE's API totals are
daily running sums (spec §6.6 F12) a SIEM would add up as if they were per-event."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from illumio_ops.domain.values import Severity

RecordKind = Literal["audit", "detection", "alert", "new_connection", "test"]


@dataclass(frozen=True)
class Endpoint:
    ip: str | None = None
    host: str | None = None
    href: str | None = None
    labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SiemRecord:
    kind: RecordKind
    record_id: int
    time: datetime                      # when it happened: the SIEM's timeline, not when it was sent
    event: Mapping[str, Any] | None = None   # audit: the PCE event
    signature: str = ""                 # detection.fanout, alert.lateral, new_connection.blocked
    name: str = ""                      # its title, in the display language
    severity: Severity | None = None
    summary: str = ""                   # its one sentence, in the display language
    src: Endpoint | None = None
    dst: Endpoint | None = None
    port: int | None = None
    proto: int | None = None
    decision: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    facts: Mapping[str, Any] = field(default_factory=dict)
    pce_fqdn: str = ""                  # the PCE it is about

    @property
    def external_id(self) -> str:
        """Joins a line to its record (and a resend to the first send): kind and id."""
        return f"{self.kind}:{self.record_id}"
