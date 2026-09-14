from __future__ import annotations

from datetime import datetime, timezone

from src.siem.formatters.base import Formatter  # noqa: F401 — re-exported for callers
from src.siem.formatters.cef_pce import PceNativeCEFFormatter

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


def _first_not_none(*values):
    """First value that is not None. Unlike an `or` chain this keeps
    legitimate falsy values (flat-format pd=0 'allowed', zero counters)."""
    for v in values:
        if v is not None:
            return v
    return None


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


def _cef_header_escape(value: str) -> str:
    """Escape CEF *header* fields. Per the CEF spec only '\\' and '|' are
    special in the header; '=' is a literal there (unlike extension values)."""
    value = value.replace("\\", "\\\\")
    value = value.replace("|", "\\|")
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


class CEFFormatter(PceNativeCEFFormatter):
    """`cef` / `syslog_cef`: the ArcSight dialect of the PCE-native CEF shape.

    Same keys, order and Signature IDs (`event_type.status`) as `cef_pce`;
    rt is epoch milliseconds, values are CEF-escaped, empty values are
    omitted.  The previous `cef` line (bare event_type, its own severity
    scale, summary msg=) was retired on 2026-09-12 — SOC rules written
    against the PCE's own syslog now match either format.
    """

    def __init__(self, *, pce_fqdn: str = "", pce_version: str = "unknown"):
        super().__init__(pce_fqdn=pce_fqdn, pce_version=pce_version, dialect="arcsight")


def _extract_actor(created_by: dict) -> str:
    """Resolve created_by dict to a display string."""
    if created_by.get("system"):
        return "system"
    user = created_by.get("user") or {}
    if user.get("username"):
        return user["username"]
    if user.get("name"):
        return user["name"]
    sa = created_by.get("service_account") or {}
    if sa.get("name"):
        return sa["name"]
    return ""


def _format_resource_changes(rc: list) -> str:
    """Summarise resource_changes as 'change_type:resource_type:name ...'."""
    parts = []
    for change in rc[:5]:
        change_type = change.get("change_type", "")
        resource = change.get("resource") or {}
        for res_type, res_val in resource.items():
            name = res_val.get("name", "") if isinstance(res_val, dict) else ""
            parts.append(f"{change_type}:{res_type}:{name}" if name else f"{change_type}:{res_type}")
            break
    return " ".join(parts)


def _format_labels(labels) -> str:
    """Format PCE label list [{"key":k,"value":v}] or dict {k:v} as 'k:v k:v'."""
    if isinstance(labels, dict):
        return " ".join(f"{k}:{v}" for k, v in labels.items() if k and v)
    parts = []
    for lbl in labels:
        k = lbl.get("key", "")
        v = lbl.get("value", "")
        if k and v:
            parts.append(f"{k}:{v}")
    return " ".join(parts)
