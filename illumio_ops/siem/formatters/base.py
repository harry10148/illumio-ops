from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Formatter(ABC):
    @abstractmethod
    def format_event(self, event: dict[str, Any]) -> str:
        """Format a PCE audit event dict into a log line."""
