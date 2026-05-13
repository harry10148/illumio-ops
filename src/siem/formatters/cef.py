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

_PROTO_MAP = {6: "tcp", 17: "udp", 1: "icmp"}


def _proto_to_str(proto) -> str:
    if proto is None:
        return ""
    if isinstance(proto, str):
        return proto
    return _PROTO_MAP.get(int(proto), str(proto))


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
        # Handle both normalized form and raw PCE API form
        svc = flow.get("service") or {}
        src_ip = flow.get("src_ip") or (flow.get("src") or {}).get("ip", "")
        dst_ip = flow.get("dst_ip") or (flow.get("dst") or {}).get("ip", "")
        port = flow.get("port") or svc.get("port") or 0
        proto_raw = flow.get("protocol") or svc.get("proto")
        proto = _proto_to_str(proto_raw)
        action = flow.get("action") or flow.get("policy_decision") or "unknown"
        ts = flow.get("first_detected") or (flow.get("timestamp_range") or {}).get("first_detected", "")

        header = f"CEF:0|Illumio|PCE|{_PCE_VERSION}|traffic.flow|traffic.flow|3"
        ext_parts = []
        if ts:
            ext_parts.append(f"rt={_ts_to_epoch_ms(ts)}")
        ext_parts.append(f"src={_cef_escape(str(src_ip))}")
        ext_parts.append(f"dst={_cef_escape(str(dst_ip))}")
        ext_parts.append(f"dpt={port}")
        ext_parts.append(f"proto={_cef_escape(proto)}")
        ext_parts.append(f"act={_cef_escape(str(action))}")
        ext_parts.append(f"dvchost={_cef_escape(str(flow.get('pce_fqdn', '')))}")

        return header + "|" + " ".join(ext_parts)
