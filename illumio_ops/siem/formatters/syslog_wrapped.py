from __future__ import annotations

from typing import Any

from illumio_ops.domain.values import Severity
from illumio_ops.siem.formatters.base import Formatter
from illumio_ops.siem.formatters.syslog_header import event_record_time, wrap_rfc5424
from illumio_ops.siem.records import SiemRecord

_SYSLOG_SEV_MAP = {
    "info": 6,
    "warning": 4,
    "warn": 4,
    "error": 3,
    "err": 3,
    "critical": 2,
    "crit": 2,
}


_RECORD_SEV = {None: 6, Severity.LOW: 5, Severity.MEDIUM: 4, Severity.HIGH: 3, Severity.CRITICAL: 2}


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

    def format_ops(self, rec: SiemRecord) -> str:
        """This product's own event: the forwarder is the host, the record's own time the timestamp."""
        return wrap_rfc5424(self._inner.format_ops(rec), severity=_RECORD_SEV.get(rec.severity, 6), hostname=self._host,
                            timestamp=rec.time)
