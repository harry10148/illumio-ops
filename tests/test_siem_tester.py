"""Tests for src/siem/tester.py — send_test_event and _build_transport for all types."""
from unittest.mock import MagicMock, patch
import pytest
from src.config_models import SiemDestinationSettings
from src.siem.tester import send_test_event, _build_transport, TestResult


def _dest(**kw):
    base = dict(name="demo", enabled=True, transport="udp",
                format="cef", host="127.0.0.1", port=514)
    base.update(kw)
    return SiemDestinationSettings(**base)


# ── send_test_event (transport mocked) ────────────────────────────────────────

def test_send_test_event_success():
    with patch("src.siem.tester._build_transport") as bt:
        tx = MagicMock()
        bt.return_value = tx
        r = send_test_event(_dest())
    assert isinstance(r, TestResult) and r.ok is True and r.error is None
    tx.send.assert_called_once()
    tx.close.assert_called_once()


def test_send_test_event_failure():
    with patch("src.siem.tester._build_transport") as bt:
        tx = MagicMock()
        tx.send.side_effect = RuntimeError("refused")
        bt.return_value = tx
        r = send_test_event(_dest())
    assert r.ok is False and "refused" in r.error


def test_send_test_event_hec_json():
    dest = _dest(format="json", transport="hec", hec_token="abc",
                 host="splunk.corp", port=8088)
    with patch("src.siem.tester._build_transport") as bt:
        bt.return_value = MagicMock()
        r = send_test_event(dest)
    assert r.ok is True


# ── _build_transport — per transport type ─────────────────────────────────────

def test_build_transport_udp():
    from src.siem.transports.syslog_udp import SyslogUDPTransport
    cfg = _dest(transport="udp", host="10.0.0.1", port=514)
    with patch("socket.socket"):
        t = _build_transport(cfg)
    assert isinstance(t, SyslogUDPTransport)
    assert t._host == "10.0.0.1"
    assert t._port == 514


def test_build_transport_tcp():
    from src.siem.transports.syslog_tcp import SyslogTCPTransport
    cfg = _dest(transport="tcp", host="10.0.0.2", port=1514)
    with patch("socket.socket"):
        t = _build_transport(cfg)
    assert isinstance(t, SyslogTCPTransport)
    assert t._host == "10.0.0.2"
    assert t._port == 1514


def test_build_transport_tls():
    from src.siem.transports.syslog_tls import SyslogTLSTransport
    cfg = _dest(transport="tls", host="syslog.corp", port=6514,
                tls_verify=False, tls_ca_bundle=None, profile="dev")
    with patch("socket.socket"), patch("ssl.create_default_context"):
        t = _build_transport(cfg)
    assert isinstance(t, SyslogTLSTransport)
    assert t._host == "syslog.corp"
    assert t._port == 6514


def test_build_transport_hec_constructs_url():
    from src.siem.transports.splunk_hec import SplunkHECTransport
    cfg = _dest(transport="hec", host="splunk.corp", port=8088, hec_token="tok123")
    with patch("requests.Session"):
        t = _build_transport(cfg)
    assert isinstance(t, SplunkHECTransport)
    assert "splunk.corp" in t._endpoint
    assert "8088" in t._endpoint
    assert "/services/collector" in t._endpoint


def test_build_transport_hec_custom_port():
    from src.siem.transports.splunk_hec import SplunkHECTransport
    cfg = _dest(transport="hec", host="splunk.internal", port=9999, hec_token="t")
    with patch("requests.Session"):
        t = _build_transport(cfg)
    assert "9999" in t._endpoint


def test_build_transport_unknown_raises():
    cfg = _dest(transport="mqtt")
    with pytest.raises(ValueError, match="unsupported"):
        _build_transport(cfg)


# ── send_test_event latency tracking ──────────────────────────────────────────

def test_send_test_event_latency_nonzero():
    import time
    def slow_send(_):
        time.sleep(0.01)
    with patch("src.siem.tester._build_transport") as bt:
        tx = MagicMock()
        tx.send.side_effect = slow_send
        bt.return_value = tx
        r = send_test_event(_dest())
    assert r.ok is True
    assert r.latency_ms >= 10
