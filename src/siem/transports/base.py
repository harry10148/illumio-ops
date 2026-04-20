from __future__ import annotations
from abc import ABC, abstractmethod


class Transport(ABC):
    @abstractmethod
    def send(self, payload: str) -> None:
        """Send payload string. Raises on unrecoverable error."""

    def close(self) -> None:
        """Optional teardown."""
