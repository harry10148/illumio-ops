from __future__ import annotations

import re
from datetime import datetime, timezone


def _escape_sd_param(value: str) -> str:
    """Escape structured-data param values per RFC5424: backslash, quote, right-bracket."""
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("]", "\\]")
    return value


def parse_record_time(value: object) -> datetime | None:
    """把 PCE 的 ISO8601 時間字串（或 datetime）轉成 aware UTC datetime；無法解析回 None。"""
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
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def event_record_time(event: dict) -> datetime | None:
    """Audit event 的發生時間（PCE `timestamp`）。"""
    return parse_record_time(event.get("timestamp"))


def flow_record_time(flow: dict) -> datetime | None:
    """Traffic flow 的時間，取值順序與 cef_pce 的 rt 一致（last_detected 優先）。"""
    tr = flow.get("timestamp_range") or {}
    for candidate in (flow.get("timestamp"), flow.get("last_detected"),
                      tr.get("last_detected"), flow.get("first_detected"),
                      tr.get("first_detected")):
        dt = parse_record_time(candidate)
        if dt is not None:
            return dt
    return None


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
    """Wrap payload in an RFC5424 syslog header.

    Returns: '<PRI>VERSION TIMESTAMP HOSTNAME APP-NAME PROCID MSGID STRUCTURED-DATA MSG'

    timestamp: 記錄本身的時間（事件發生／flow 偵測時間）。有積壓或 DLQ replay
    時，用送出當下的時間會讓 SIEM 的時間軸偏移數小時，所以呼叫端應盡量帶入；
    None 才退回 now()。
    """
    pri = facility * 8 + severity
    when = timestamp.astimezone(timezone.utc) if timestamp else datetime.now(timezone.utc)
    ts = when.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    header = f"<{pri}>1 {ts} {hostname} {app_name} {proc_id} {msg_id} -"
    return f"{header} {payload}"
