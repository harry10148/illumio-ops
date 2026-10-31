from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from illumio_ops.siem.records import SiemRecord


class Formatter(ABC):
    @abstractmethod
    def format_event(self, event: dict[str, Any]) -> str:
        """Format a PCE audit event dict into a log line."""

    @abstractmethod
    def format_ops(self, rec: SiemRecord) -> str:
        """Format one of this product's own events (detection, alert, new connection, test)."""

    def format_record(self, rec: SiemRecord) -> str:
        if rec.kind == "audit":
            return self.format_event(dict(rec.event or {}))
        return self.format_ops(rec)
