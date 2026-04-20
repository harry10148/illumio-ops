from __future__ import annotations
from abc import ABC, abstractmethod


class Formatter(ABC):
    @abstractmethod
    def format_event(self, event: dict) -> str:
        """Format a PCE audit event dict into a log line."""

    @abstractmethod
    def format_flow(self, flow: dict) -> str:
        """Format a PCE traffic flow dict into a log line."""
