from __future__ import annotations

import orjson

from src.siem.formatters.base import Formatter


class JSONLineFormatter(Formatter):
    """Formats events/flows as JSON Lines (one JSON object per line, no trailing newline)."""

    def format_event(self, event: dict) -> str:
        return orjson.dumps(event).decode("utf-8")

    def format_flow(self, flow: dict) -> str:
        return orjson.dumps(flow).decode("utf-8")
