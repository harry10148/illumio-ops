from __future__ import annotations

import re
from datetime import datetime, timezone


def _escape_sd_param(value: str) -> str:
    """Escape structured-data param values per RFC5424: backslash, quote, right-bracket."""
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("]", "\\]")
    return value


def wrap_rfc5424(
    payload: str,
    *,
    facility: int = 1,   # user-level messages
    severity: int = 6,   # informational
    hostname: str = "-",
    app_name: str = "illumio-ops",
    proc_id: str = "-",
    msg_id: str = "-",
) -> str:
    """Wrap payload in an RFC5424 syslog header.

    Returns: '<PRI>VERSION TIMESTAMP HOSTNAME APP-NAME PROCID MSGID STRUCTURED-DATA MSG'
    """
    pri = facility * 8 + severity
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    header = f"<{pri}>1 {ts} {hostname} {app_name} {proc_id} {msg_id} -"
    return f"{header} {payload}"
