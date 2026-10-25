"""The real cheroot server: refused peers get a TCP reset before TLS or HTTP."""
import socket
import ssl
import threading
import time

import pytest
from flask import Flask

from illumio_ops.web import tls
from illumio_ops.web.server import serve
from tests_v6.web.test_tls import _tls


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def run_server(tmp_path):
    started = []

    def start(allowed, use_tls=False):
        app = Flask("t")
        app.add_url_rule("/x", "x", lambda: "hello")
        port = _free_port()
        ctx = None
        if use_tls:
            cert, key = tls.ensure_self_signed(tmp_path, _tls())
            ctx = tls.build_ssl_context(_tls())
            ctx.load_cert_chain(cert, key)
        stop = threading.Event()
        th = threading.Thread(target=serve, args=(app, "127.0.0.1", port, ctx, stop),
                              kwargs={"peer_allowed": allowed}, daemon=True)
        th.start()
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)
        started.append((stop, th))
        return port

    yield start
    for stop, th in started:
        stop.set()
        th.join(timeout=10)


def _raw_exchange(port: int, payload: bytes) -> bytes:
    # Under load the server's RST can land before the client's connect() completes,
    # so a reset at connect time is the same outcome: no HTTP bytes.
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=3)
    except ConnectionResetError:
        return b""
    got = b""
    try:
        s.sendall(payload)
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            got += chunk
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        s.close()
    return got


def test_allowed_peer_gets_http(run_server):
    port = run_server(lambda ip: True)
    got = _raw_exchange(port, b"GET /x HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
    assert got.startswith(b"HTTP/1.1 200") and b"hello" in got
    assert b"Server: Web" in got  # no cheroot version banner


@pytest.mark.parametrize("payload", [
    b"GET /x HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n",
    b"POST /x HTTP/1.1\r\nHost: x\r\nExpect: 100-continue\r\nContent-Length: 2\r\n\r\n",
])
def test_refused_peer_gets_zero_http_bytes(run_server, payload):
    port = run_server(lambda ip: False)
    assert _raw_exchange(port, payload) == b""


def test_refused_peer_gets_no_tls_handshake(run_server):
    port = run_server(lambda ip: False, use_tls=True)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with (pytest.raises((ssl.SSLError, ConnectionResetError, OSError)),
          socket.create_connection(("127.0.0.1", port), timeout=3) as raw,
          ctx.wrap_socket(raw, server_hostname="localhost")):
        pass


def test_allowed_peer_tls_works(run_server):
    port = run_server(lambda ip: True, use_tls=True)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection(("127.0.0.1", port), timeout=3) as raw, \
            ctx.wrap_socket(raw, server_hostname="localhost") as s:
        s.sendall(b"GET /x HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        assert s.recv(4096).startswith(b"HTTP/1.1 200")


def test_server_keeps_serving_after_refusals(run_server):
    state = {"refuse": False}  # a switch, not a countdown: late readiness probes must not consume it
    port = run_server(lambda ip: not state["refuse"])
    state["refuse"] = True
    request = b"GET /x HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"
    assert _raw_exchange(port, request) == b""
    assert _raw_exchange(port, request) == b""
    state["refuse"] = False
    assert _raw_exchange(port, request).startswith(b"HTTP/1.1 200")
