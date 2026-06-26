"""Tests for SyslogTLSTransport — loopback TLS server fixture via cryptography lib."""
from __future__ import annotations

import datetime
import ipaddress
import socket
import ssl
import threading

import pytest


# ── cert fixture ─────────────────────────────────────────────────────────────

def _generate_self_signed(tmp_path):
    """Return (cert_pem_path, key_pem_path) for a 127.0.0.1 self-signed cert."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
        )
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return str(cert_path), str(key_path)


class _TLSServer:
    """Accept exactly one TLS connection and read one newline-terminated line."""

    def __init__(self, cert_path: str, key_path: str):
        self.received: list[str] = []
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        raw.bind(("127.0.0.1", 0))
        raw.listen(1)
        raw.settimeout(5.0)
        self._raw = raw
        self._ctx = ctx
        self.port: int = raw.getsockname()[1]

    def handle_one(self) -> None:
        try:
            conn, _ = self._raw.accept()
            with self._ctx.wrap_socket(conn, server_side=True) as tls_conn:
                tls_conn.settimeout(3.0)
                buf = b""
                while b"\n" not in buf:
                    chunk = tls_conn.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                self.received.append(buf.decode("utf-8").strip())
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._raw.close()
        except Exception:
            pass


# ── tests ────────────────────────────────────────────────────────────────────

def test_tls_transport_sends_payload_with_verified_cert(tmp_path):
    """Full TLS handshake against a loopback server using a self-signed CA bundle."""
    cert_path, key_path = _generate_self_signed(tmp_path)
    srv = _TLSServer(cert_path, key_path)
    t = threading.Thread(target=srv.handle_one, daemon=True)
    t.start()

    from src.siem.transports.syslog_tls import SyslogTLSTransport

    tr = SyslogTLSTransport(
        "127.0.0.1", srv.port, tls_verify=True, ca_bundle=cert_path
    )
    try:
        tr.send("hello tls verified")
    finally:
        tr.close()

    t.join(timeout=3)
    srv.close()
    assert any("hello tls verified" in m for m in srv.received)


def test_tls_transport_verify_disabled_skips_cert_check(tmp_path):
    """tls_verify=False allows connection without providing a CA bundle."""
    cert_path, key_path = _generate_self_signed(tmp_path)
    srv = _TLSServer(cert_path, key_path)
    t = threading.Thread(target=srv.handle_one, daemon=True)
    t.start()

    from src.siem.transports.syslog_tls import SyslogTLSTransport

    # No ca_bundle — would fail cert verification if tls_verify=True
    tr = SyslogTLSTransport("127.0.0.1", srv.port, tls_verify=False)
    try:
        tr.send("hello tls no-verify")
    finally:
        tr.close()

    t.join(timeout=3)
    srv.close()
    assert any("hello tls no-verify" in m for m in srv.received)


def test_tls_connect_failure_does_not_leave_socket_set():
    """Regression: when connect() fails, _connect must not leave self._sock
    pointing at an unconnected (leaked) SSLSocket — it must close + stay None."""
    from src.siem.transports.syslog_tls import SyslogTLSTransport

    # Reserve then release a port so nothing is listening — connect() is refused.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    dead_port = probe.getsockname()[1]
    probe.close()

    tr = SyslogTLSTransport("127.0.0.1", dead_port, tls_verify=False, timeout=2.0)
    with pytest.raises(OSError):
        tr._connect()
    assert tr._sock is None


def test_tls_transport_reconnects_after_connection_lost(tmp_path):
    """Transport reconnects transparently when the server drops the connection."""
    cert_path, key_path = _generate_self_signed(tmp_path)

    # First server — accept msg1 then shut down
    srv1 = _TLSServer(cert_path, key_path)
    t1 = threading.Thread(target=srv1.handle_one, daemon=True)
    t1.start()

    from src.siem.transports.syslog_tls import SyslogTLSTransport

    tr = SyslogTLSTransport(
        "127.0.0.1", srv1.port, tls_verify=True, ca_bundle=cert_path
    )
    tr.send("msg1")
    t1.join(timeout=3)
    srv1.close()

    # Second server — transport must reconnect and deliver msg2
    srv2 = _TLSServer(cert_path, key_path)
    t2 = threading.Thread(target=srv2.handle_one, daemon=True)
    t2.start()

    # Force the transport to see a broken connection on next send
    tr._port = srv2.port
    with tr._lock:
        if tr._sock:
            try:
                tr._sock.close()
            except Exception:
                pass
            tr._sock = None

    tr.send("msg2")
    t2.join(timeout=3)
    tr.close()
    srv2.close()

    assert any("msg2" in m for m in srv2.received)
