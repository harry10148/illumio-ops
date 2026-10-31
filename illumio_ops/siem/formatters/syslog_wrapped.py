from __future__ import annotations

from typing import Any

from illumio_ops.siem.formatters.base import Formatter
from illumio_ops.siem.formatters.syslog_header import event_record_time, wrap_rfc5424

_SYSLOG_SEV_MAP = {
    "info": 6,
    "warning": 4,
    "warn": 4,
    "error": 3,
    "err": 3,
    "critical": 2,
    "crit": 2,
}


class SyslogWrappedFormatter(Formatter):
    """Wraps an inner formatter's output in an RFC5424 syslog header (syslog_cef, syslog_json, syslog_cef_pce)."""

    def __init__(self, inner: Formatter, host: str = "illumio-ops") -> None:
        self._inner = inner
        # RFC5424 hostname when the record carries no pce_fqdn: identifies the forwarder rather than NILVALUE "-".
        self._host = host

    def format_event(self, event: dict[str, Any]) -> str:
        payload = self._inner.format_event(event)
        sev_str = str(event.get("severity", "info")).lower()
        sev_num = _SYSLOG_SEV_MAP.get(sev_str, 6)
        hostname = str(event.get("pce_fqdn") or self._host)
        return wrap_rfc5424(payload, severity=sev_num, hostname=hostname, timestamp=event_record_time(event))
