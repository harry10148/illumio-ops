import socketserver
import threading

import pytest


# ── UDP ──────────────────────────────────────────────────────────────────────

class _UDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data, _ = self.request
        self.server.received.append(data.decode("utf-8"))


def _udp_server():
    srv = socketserver.UDPServer(("127.0.0.1", 0), _UDPHandler)
    srv.received = []
    return srv


def test_udp_transport_sends_payload():
    from src.siem.transports.syslog_udp import SyslogUDPTransport
    srv = _udp_server()
    t = threading.Thread(target=srv.handle_request)
    t.start()
    port = srv.server_address[1]
    tr = SyslogUDPTransport("127.0.0.1", port)
    tr.send("hello udp")
    t.join(timeout=2)
    tr.close()
    srv.server_close()
    assert any("hello udp" in m for m in srv.received)


# ── TCP ──────────────────────────────────────────────────────────────────────

class _TCPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline()
        self.server.received.append(line.decode("utf-8").strip())


def _tcp_server():
    srv = socketserver.TCPServer(("127.0.0.1", 0), _TCPHandler)
    srv.received = []
    return srv


def test_tcp_transport_sends_payload():
    from src.siem.transports.syslog_tcp import SyslogTCPTransport
    srv = _tcp_server()
    t = threading.Thread(target=srv.handle_request)
    t.start()
    port = srv.server_address[1]
    tr = SyslogTCPTransport("127.0.0.1", port)
    tr.send("hello tcp")
    t.join(timeout=2)
    tr.close()
    srv.server_close()
    assert any("hello tcp" in m for m in srv.received)


def test_tcp_transport_reconnects_after_close():
    from src.siem.transports.syslog_tcp import SyslogTCPTransport
    # First server — accept one message then close
    srv1 = _tcp_server()
    t1 = threading.Thread(target=srv1.handle_request)
    t1.start()
    port = srv1.server_address[1]
    tr = SyslogTCPTransport("127.0.0.1", port)
    tr.send("msg1")
    t1.join(timeout=2)
    srv1.server_close()

    # Start second server on different port
    srv2 = _tcp_server()
    t2 = threading.Thread(target=srv2.handle_request)
    t2.start()
    port2 = srv2.server_address[1]

    # Point transport at new port and force reconnect by closing existing socket
    tr._host = "127.0.0.1"
    tr._port = port2
    if tr._sock:
        tr._sock.close()
        tr._sock = None

    tr.send("msg2")
    t2.join(timeout=2)
    tr.close()
    srv2.server_close()
    assert any("msg2" in m for m in srv2.received)
