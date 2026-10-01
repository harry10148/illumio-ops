from __future__ import annotations
import socket
import threading
from loguru import logger
from src.siem.transports._stream import graceful_close, peer_closed
from src.siem.transports.base import Transport


class SyslogTCPTransport(Transport):
    def __init__(self, host: str, port: int, timeout: float = 10.0):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()

    def _connect(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self._timeout)
        try:
            s.connect((self._host, self._port))
        except Exception:
            # Don't leak the socket fd if connect fails; only publish
            # self._sock after a successful connect (mirrors syslog_tls).
            try:
                s.close()
            except Exception:
                pass
            raise
        self._sock = s

    def send(self, payload: str) -> None:
        data = (payload + "\n").encode("utf-8")
        with self._lock:
            if self._sock is not None and peer_closed(self._sock):
                # 對端已關閉時第一個 sendall() 仍會「成功」而資料被丟掉，
                # 所以送之前先確認，已關閉就重連。
                logger.info("TCP syslog peer closed the connection, reconnecting")
                self._drop_socket()
            if self._sock is None:
                self._connect()
            try:
                self._sock.sendall(data)
            except (BrokenPipeError, ConnectionResetError, OSError):
                logger.warning("TCP syslog connection lost, reconnecting")
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
                self._connect()
                self._sock.sendall(data)

    def _drop_socket(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass
        self._sock = None

    def finish_batch(self) -> None:
        """確認這一批已送達對端：graceful close，對端 reset 時拋 OSError。"""
        with self._lock:
            if self._sock is None:
                return
            sock, self._sock = self._sock, None
            graceful_close(sock)

    def close(self) -> None:
        with self._lock:
            if self._sock:
                sock, self._sock = self._sock, None
                try:
                    graceful_close(sock)
                except Exception as exc:
                    logger.warning("TCP syslog close was not graceful: {}", exc)
