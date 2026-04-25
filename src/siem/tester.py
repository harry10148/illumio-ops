"""Shared synthetic-event tester for SIEM destinations."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.config_models import SiemDestinationSettings


@dataclass
class TestResult:
    ok: bool
    error: Optional[str] = None
    latency_ms: int = 0


def send_test_event(dest_cfg: SiemDestinationSettings) -> TestResult:
    started = time.monotonic()
    try:
        formatter = _build_formatter(dest_cfg.format)
        transport = _build_transport(dest_cfg)
        payload = formatter.format_event(_synthetic_event())
        transport.send(payload)
        transport.close()
        return TestResult(ok=True, latency_ms=int((time.monotonic() - started) * 1000))
    except Exception as exc:
        return TestResult(ok=False, error=str(exc),
                          latency_ms=int((time.monotonic() - started) * 1000))


def _synthetic_event() -> dict:
    return {"event_type": "siem.test", "severity": "info", "status": "success",
            "pce_fqdn": "illumio-ops-test", "pce_event_id": "test-0000",
            "timestamp": datetime.now(timezone.utc).isoformat()}


def _build_formatter(fmt: str):
    from src.siem.formatters.cef import CEFFormatter
    from src.siem.formatters.json_line import JSONLineFormatter
    return CEFFormatter() if fmt.startswith("cef") else JSONLineFormatter()


def _build_transport(dest_cfg: SiemDestinationSettings):
    """Build live transport. Deferred imports so tests can monkey-patch this symbol."""
    from src.siem.transports.syslog_udp import SyslogUDPTransport
    from src.siem.transports.syslog_tcp import SyslogTCPTransport
    from src.siem.transports.syslog_tls import SyslogTLSTransport
    from src.siem.transports.splunk_hec import SplunkHECTransport

    t = dest_cfg.transport.lower()
    if t == "hec":
        return SplunkHECTransport(
            dest_cfg.endpoint,
            token=dest_cfg.hec_token or "",
            verify_tls=dest_cfg.tls_verify,
        )

    # For syslog transports, parse host:port from endpoint
    host, _, port_str = dest_cfg.endpoint.rpartition(":")
    port = int(port_str) if port_str.isdigit() else 514
    if not host:
        host = dest_cfg.endpoint

    if t == "udp":
        return SyslogUDPTransport(host, port)
    if t == "tcp":
        return SyslogTCPTransport(host, port)
    if t == "tls":
        return SyslogTLSTransport(
            host, port,
            tls_verify=dest_cfg.tls_verify,
            ca_bundle=dest_cfg.tls_ca_bundle,
        )
    raise ValueError(f"unsupported transport: {t}")
