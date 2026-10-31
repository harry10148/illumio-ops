from __future__ import annotations

from illumio_ops.domain.values import SiemTransport
from illumio_ops.settings.schema import SiemDestination
from illumio_ops.siem.transports.base import Transport
from illumio_ops.siem.transports.splunk_hec import SplunkHECTransport
from illumio_ops.siem.transports.syslog_tcp import SyslogTCPTransport
from illumio_ops.siem.transports.syslog_tls import SyslogTLSTransport
from illumio_ops.siem.transports.syslog_udp import SyslogUDPTransport


def transport_for(dest: SiemDestination) -> Transport:
    verify = dest.verify_tls is not False
    bundle = dest.verify_tls if isinstance(dest.verify_tls, str) else None
    if dest.transport is SiemTransport.UDP:
        return SyslogUDPTransport(dest.host, dest.port)
    if dest.transport is SiemTransport.TCP:
        return SyslogTCPTransport(dest.host, dest.port, framing=dest.framing)
    if dest.transport is SiemTransport.TLS:
        return SyslogTLSTransport(dest.host, dest.port, tls_verify=verify, ca_bundle=bundle, framing=dest.framing)
    return SplunkHECTransport(f"https://{dest.host}:{dest.port}", token=dest.hec_token, verify_tls=verify,
                              ca_bundle=bundle)
