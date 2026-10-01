"""TCP／TLS syslog 的送達保證（loopback 實測過的兩個遺失情境）。

1. 對端關閉後第一個 sendall() 仍回成功 → 資料被對端 RST 丟掉。
2. TLS 1.3 session ticket 未讀就 close() → 送 RST，對端丟掉這一批的尾段。
"""
from __future__ import annotations

import socket
import ssl
import threading
import time

from tests.test_transport_tls import _generate_self_signed


def _listen():
    ls = socket.socket()
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind(("127.0.0.1", 0))
    ls.listen(5)
    ls.settimeout(5)
    return ls, ls.getsockname()[1]


def test_tcp_detects_peer_close_and_resends_on_new_connection():
    from src.siem.transports.syslog_tcp import SyslogTCPTransport

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
    from src.siem.transports.syslog_tls import SyslogTLSTransport

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


def test_dispatcher_does_not_mark_sent_when_delivery_unconfirmed(tmp_path):
    from datetime import datetime, timezone

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from src.pce_cache.models import PceEvent, SiemDispatch
    from src.pce_cache.schema import init_schema
    from src.siem.dispatcher import DestinationDispatcher
    from src.siem.formatters.cef import CEFFormatter

    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    sf = sessionmaker(engine)
    now = datetime.now(timezone.utc)
    with sf.begin() as s:
        ev = PceEvent(pce_href="/orgs/1/events/1", pce_event_id="u1", timestamp=now,
                      event_type="policy.update", severity="info", status="success",
                      pce_fqdn="pce.test", raw_json='{"event_type":"policy.update"}',
                      ingested_at=now)
        s.add(ev)
        s.flush()
        s.add(SiemDispatch(source_table="pce_events", source_id=ev.id,
                           destination="d", status="pending", retries=0, queued_at=now))

    class ResetOnFinish:
        def send(self, p): pass
        def finish_batch(self): raise ConnectionResetError("peer reset")
        def close(self): pass

    result = DestinationDispatcher("d", sf, CEFFormatter(), ResetOnFinish(), max_retries=5).tick()
    assert result["sent"] == 0 and result["failed"] == 1
    with sf() as s:
        row = s.execute(select(SiemDispatch)).scalar_one()
    assert row.status == "pending"
    assert row.retries == 1
