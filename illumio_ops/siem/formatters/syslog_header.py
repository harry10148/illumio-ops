"""RFC 5424 framing for the syslog_* formats (recycled from 5.x)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _escape_sd_param(value: str) -> str:
    """Escape structured-data param values per RFC5424: backslash, quote, right-bracket."""
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("]", "\\]")
    return value


def parse_record_time(value: object) -> datetime | None:
    """An ISO 8601 string (or a datetime) as an aware UTC datetime; None when it cannot be read."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def event_record_time(event: dict[str, Any]) -> datetime | None:
    """When the audit event happened (the PCE's `timestamp`)."""
    return parse_record_time(event.get("timestamp"))


def wrap_rfc5424(
    payload: str,
    *,
    timestamp: datetime | None = None,
    facility: int = 1,   # user-level messages
    severity: int = 6,   # informational
    hostname: str = "-",
    app_name: str = "illumio-ops",
    proc_id: str = "-",
    msg_id: str = "-",
) -> str:
    """'<PRI>VERSION TIMESTAMP HOSTNAME APP-NAME PROCID MSGID STRUCTURED-DATA MSG'.

    timestamp: the record's own time (when the event happened). With a backlog or a DLQ resend the time of sending
    would shift the SIEM's timeline by hours, so callers pass it; None falls back to now."""
    pri = facility * 8 + severity
    when = timestamp.astimezone(UTC) if timestamp else datetime.now(UTC)
    ts = when.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    header = f"<{pri}>1 {ts} {hostname} {app_name} {proc_id} {msg_id} -"
    return f"{header} {payload}"
