from __future__ import annotations

from typing import Any

from illumio_ops.siem.formatters.cef_pce import PceNativeCEFFormatter


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


class CEFFormatter(PceNativeCEFFormatter):
    """`cef` / `syslog_cef`: the ArcSight dialect of the PCE-native CEF shape.

    Same keys, order and Signature IDs (`event_type.status`) as `cef_pce`; rt is epoch milliseconds, values are
    CEF-escaped, empty values are omitted (5.x 2026-09-12: SOC rules written against the PCE's own syslog match
    either format)."""

    def __init__(self, *, pce_fqdn: str = "", pce_version: str = "unknown") -> None:
        super().__init__(pce_fqdn=pce_fqdn, pce_version=pce_version, dialect="arcsight")


def _extract_actor(created_by: dict[str, Any]) -> str:
    """Resolve created_by dict to a display string."""
    if created_by.get("system"):
        return "system"
    user = created_by.get("user") or {}
    if user.get("username"):
        return str(user["username"])
    if user.get("name"):
        return str(user["name"])
    sa = created_by.get("service_account") or {}
    if sa.get("name"):
        return str(sa["name"])
    return ""


def _format_resource_changes(rc: list[Any]) -> str:
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
