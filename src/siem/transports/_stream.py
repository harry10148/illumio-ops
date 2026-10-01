"""TCP／TLS syslog transport 共用的連線存活偵測與 graceful close。

兩個在 loopback 實測過的遺失情境：

1. 對端已送 FIN（重啟、閒置逾時）後，第一個 sendall() 仍回報成功——資料進了
   本機 kernel buffer，對端 kernel 收到後回 RST 丟掉。送出前偵測對端是否已關閉，
   已關閉就先重連。
2. TLS 1.3 server 在握手後會送 session ticket。client 從不讀，close() 時接收
   buffer 裡還有未讀資料，kernel 就送 RST 而不是 FIN；對端 kernel 收到 RST 會
   丟掉它還沒交給應用程式的資料——也就是這一批的尾段。graceful close 先關寫端、
   把對端送來的東西讀乾淨，再關 socket。
"""
from __future__ import annotations

import select
import socket
import ssl
import time


def peer_closed(sock: socket.socket) -> bool:
    """對端是否已關閉連線（收到 FIN／RST）。不阻塞。

    可讀時把對端送來的資料讀掉（syslog server 不會送應用資料；TLS 的
    session ticket 由 ssl 模組在 recv 內部消化）。讀到 EOF 代表對端已關閉。
    """
    try:
        readable, _, _ = select.select([sock], [], [], 0)
    except (OSError, ValueError):
        return True
    pending = sock.pending() if isinstance(sock, ssl.SSLSocket) else 0
    if not readable and not pending:
        return False
    previous_timeout = sock.gettimeout()
    sock.setblocking(False)
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                return True
    except (ssl.SSLWantReadError, ssl.SSLWantWriteError, BlockingIOError, InterruptedError):
        return False
    except (ssl.SSLError, OSError):
        return True
    finally:
        try:
            sock.settimeout(previous_timeout)
        except OSError:
            pass


def graceful_close(sock: socket.socket, linger_seconds: float = 2.0) -> None:
    """關寫端 → 讀到對端 EOF（或 linger 到期）→ close。

    對端在這段期間回 RST 代表這條連線上的資料不保證送達：拋出 OSError，
    呼叫端不得把這一批標成已送出。linger 到期而對端仍未關閉不算失敗——
    資料已交給 kernel，且接收 buffer 已讀乾淨，close() 會送 FIN 而非 RST。
    """
    try:
        # SSLSocket.shutdown() 會先拆掉 TLS 層再對底層 socket shutdown，之後的
        # recv 讀的是原始 bytes——這裡只需要把它們讀掉，不需要解密。
        sock.shutdown(socket.SHUT_WR)
        deadline = time.monotonic() + linger_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                chunk = sock.recv(4096)
            except (socket.timeout, TimeoutError):
                break
            if not chunk:
                break
    finally:
        try:
            sock.close()
        except OSError:
            pass
