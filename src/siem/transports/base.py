from __future__ import annotations
from abc import ABC, abstractmethod


class Transport(ABC):
    @abstractmethod
    def send(self, payload: str) -> None:
        """Send payload string. Raises on unrecoverable error."""

    def send_record(self, payload: str, event_time: float | None = None) -> None:
        """Send one record. event_time = 記錄本身的 epoch 秒（事件／flow 時間）。

        預設忽略 event_time（syslog 的時間已寫在 payload 的 header／CEF rt 裡）；
        需要另外帶時間的 transport（Splunk HEC 的 `time`）覆寫此方法。
        """
        self.send(payload)

    def close(self) -> None:
        """Optional teardown."""
