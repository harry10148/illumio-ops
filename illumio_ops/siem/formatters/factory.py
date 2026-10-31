from __future__ import annotations

from illumio_ops.domain.values import SiemFormat
from illumio_ops.siem.formatters.base import Formatter
from illumio_ops.siem.formatters.cef import CEFFormatter
from illumio_ops.siem.formatters.cef_pce import PceNativeCEFFormatter
from illumio_ops.siem.formatters.normalized_json import NormalizedJSONFormatter
from illumio_ops.siem.formatters.syslog_wrapped import SyslogWrappedFormatter


def formatter_for(fmt: SiemFormat, *, pce_fqdn: str = "", pce_version: str = "unknown",
                  host: str = "illumio-ops") -> Formatter:
    """The formatter of a destination's format. pce_fqdn and pce_version go on relayed audit events (cef_pce names the
    PCE as their device); host is the syslog host of this product's own events."""
    inner: Formatter
    if fmt in (SiemFormat.CEF_PCE, SiemFormat.SYSLOG_CEF_PCE):
        inner = PceNativeCEFFormatter(pce_fqdn=pce_fqdn, pce_version=pce_version)
    elif fmt in (SiemFormat.CEF, SiemFormat.SYSLOG_CEF):
        inner = CEFFormatter(pce_fqdn=pce_fqdn, pce_version=pce_version)
    else:
        inner = NormalizedJSONFormatter()
    if fmt in (SiemFormat.SYSLOG_CEF, SiemFormat.SYSLOG_JSON, SiemFormat.SYSLOG_CEF_PCE):
        return SyslogWrappedFormatter(inner, host=host)
    return inner
