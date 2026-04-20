from __future__ import annotations

import re
from datetime import datetime, timezone

from src.siem.formatters.base import Formatter

_SEVERITY_MAP = {
    "info": 3,
    "warning": 6,
    "warn": 6,
    "error": 8,
    "err": 8,
    "critical": 10,
    "crit": 10,
}
_PCE_VERSION = "3.11"


def _cef_escape(value: str) -> str:
    """Escape CEF extension field values: backslash, pipe, equals, newline."""
    value = value.replace("\\", "\\\\")
    value = value.replace("|", "\\|")
    value = value.replace("=", "\\=")
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    return value


def _ts_to_epoch_ms(ts_str: str) -> int:
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class CEFFormatter(Formatter):
    def format_event(self, event: dict) -> str:
        sev_str = str(event.get("severity", "info")).lower()
        sev_num = _SEVERITY_MAP.get(sev_str, 3)
        event_type = _cef_escape(str(event.get("event_type", "unknown")))

        header = (
            f"CEF:0|Illumio|PCE|{_PCE_VERSION}"
            f"|{event_type}|{event_type}|{sev_num}"
        )

        ts = event.get("timestamp", "")
        ext_parts = []
        if ts:
            ext_parts.append(f"rt={_ts_to_epoch_ms(ts)}")
        ext_parts.append(f"dvchost={_cef_escape(str(event.get('pce_fqdn', '')))}")
        ext_parts.append(f"externalId={_cef_escape(str(event.get('pce_event_id', '')))}")
        ext_parts.append(f"outcome={_cef_escape(str(event.get('status', '')))}")

        return header + "|" + " ".join(ext_parts)

    def format_flow(self, flow: dict) -> str:
        action = _cef_escape(str(flow.get("action", "unknown")))
        header = (
            f"CEF:0|Illumio|PCE|{_PCE_VERSION}"
            f"|traffic.flow|traffic.flow|3"
        )

        ts = flow.get("first_detected", "")
        ext_parts = []
        if ts:
            ext_parts.append(f"rt={_ts_to_epoch_ms(ts)}")
        ext_parts.append(f"src={_cef_escape(str(flow.get('src_ip', '')))}")
        ext_parts.append(f"dst={_cef_escape(str(flow.get('dst_ip', '')))}")
        ext_parts.append(f"dpt={flow.get('port', 0)}")
        ext_parts.append(f"proto={_cef_escape(str(flow.get('protocol', '')))}")
        ext_parts.append(f"act={action}")
        ext_parts.append(f"dvchost={_cef_escape(str(flow.get('pce_fqdn', '')))}")

        return header + "|" + " ".join(ext_parts)
