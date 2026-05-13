from __future__ import annotations

from src.siem.formatters.base import Formatter
from src.siem.formatters.syslog_header import wrap_rfc5424

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
    """Wraps an inner formatter's output in an RFC5424 syslog header.

    Used for syslog_cef and syslog_json format modes where the receiving
    syslog server requires proper RFC5424 framing.
    """

    def __init__(self, inner: Formatter):
        self._inner = inner

    def format_event(self, event: dict) -> str:
        payload = self._inner.format_event(event)
        sev_str = str(event.get("severity", "info")).lower()
        sev_num = _SYSLOG_SEV_MAP.get(sev_str, 6)
        hostname = str(event.get("pce_fqdn") or "-")
        return wrap_rfc5424(payload, severity=sev_num, hostname=hostname)

    def format_flow(self, flow: dict) -> str:
        payload = self._inner.format_flow(flow)
        hostname = str(flow.get("pce_fqdn") or "-")
        return wrap_rfc5424(payload, severity=6, hostname=hostname)
