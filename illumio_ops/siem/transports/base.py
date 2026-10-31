from __future__ import annotations

from abc import ABC, abstractmethod


class Transport(ABC):
    @abstractmethod
    def send(self, payload: str) -> None:
        """Send payload string. Raises on unrecoverable error."""

    def send_record(self, payload: str, event_time: float | None = None) -> None:
        """Send one record. event_time: the record's own time, epoch seconds.

        Ignored by default (syslog carries the time in the header / CEF rt); a transport that sends the time
        separately (Splunk HEC's `time`) overrides this."""
        self.send(payload)

    def finish_batch(self) -> None:
        """Confirm the batch reached the peer (stream transports: graceful close, raising OSError on a reset)."""

    def close(self) -> None:
        """Optional teardown."""
