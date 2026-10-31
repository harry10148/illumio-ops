"""TCP／TLS syslog 的送達保證（loopback 實測過的兩個遺失情境）。

1. 對端關閉後第一個 sendall() 仍回成功 → 資料被對端 RST 丟掉。
2. TLS 1.3 session ticket 未讀就 close() → 送 RST，對端丟掉這一批的尾段。
"""
from __future__ import annotations

import socket
import ssl
import threading
import time

from tests_v6.siem.test_transport_tls import _generate_self_signed


def _listen():
    ls = socket.socket()
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind(("127.0.0.1", 0))
    ls.listen(5)
    ls.settimeout(5)
    return ls, ls.getsockname()[1]


def test_tcp_detects_peer_close_and_resends_on_new_connection():
    from illumio_ops.siem.transports.syslog_tcp import SyslogTCPTransport

    ls, port = _listen()
    counts: list[int] = []

    def serve():
        first = True
        while True:
            try:
                c, _ = ls.accept()
            except OSError:
                return
            buf = b""
            while True:
                d = c.recv(65536)
                if not d:
                    break
                buf += d
                if first and buf.count(b"\n") >= 5:
                    break  # 模擬 syslog server 重啟：讀 5 筆後關閉
            counts.append(buf.count(b"\n"))
            first = False
            c.close()

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    tr = SyslogTCPTransport("127.0.0.1", port)
    for i in range(50):
        tr.send(f"line {i}")
        if i == 4:
            time.sleep(0.3)  # 讓對端的 FIN 先到
    tr.finish_batch()
    time.sleep(0.5)
    ls.close()
    assert sum(counts) == 50


def test_tls_finish_batch_delivers_whole_batch(tmp_path):
    """slow reader 讓資料留在對端 buffer；直接 close() 會丟尾段，finish_batch 不會。"""
    from illumio_ops.siem.transports.syslog_tls import SyslogTLSTransport

    cert, key = _generate_self_signed(tmp_path)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    ls, port = _listen()
    counts: list[int] = []

    def serve():
        try:
            c, _ = ls.accept()
            s = ctx.wrap_socket(c, server_side=True)
        except OSError:
            return
        buf = b""
        try:
            while True:
                time.sleep(0.002)
                d = s.recv(256)
                if not d:
                    break
                buf += d
        except OSError:
            pass
        counts.append(buf.count(b"\n"))
        s.close()

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    tr = SyslogTLSTransport("127.0.0.1", port, ca_bundle=cert)
    for i in range(100):
        tr.send("x" * 200 + str(i))
    tr.finish_batch()
    th.join(timeout=10)
    ls.close()
    assert counts == [100]




def test_frame_payload_lf_and_octet_counting():
    from illumio_ops.siem.transports._stream import frame_payload
    assert frame_payload("abc") == b"abc\n"
    # 長度以 UTF-8 位元組計（中文每字 3 bytes），訊息內的換行不會被切開
    msg = "標籤\nx"
    assert frame_payload(msg, "octet_counting") == b"8 " + msg.encode("utf-8")


def test_tcp_octet_counting_on_the_wire():
    from illumio_ops.siem.transports.syslog_tcp import SyslogTCPTransport

    ls, port = _listen()
    got = []

    def serve():
        c, _ = ls.accept()
        buf = b""
        while True:
            d = c.recv(65536)
            if not d:
                break
            buf += d
        got.append(buf)
        c.close()

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    tr = SyslogTCPTransport("127.0.0.1", port, framing="octet_counting")
    tr.send("hello\nworld")
    tr.finish_batch()
    th.join(timeout=5)
    ls.close()
    assert got == [b"11 hello\nworld"]


def test_framing_defaults_to_lf_in_schema():
    from src.config_models import SiemDestinationSettings
    assert SiemDestinationSettings(name="d").framing == "lf"
