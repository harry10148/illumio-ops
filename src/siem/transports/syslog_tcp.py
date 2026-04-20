from __future__ import annotations
import socket
import threading
from loguru import logger
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
        s.connect((self._host, self._port))
        self._sock = s

    def send(self, payload: str) -> None:
        data = (payload + "\n").encode("utf-8")
        with self._lock:
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

    def close(self) -> None:
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
