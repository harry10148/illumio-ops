from __future__ import annotations

import socket
import threading

from loguru import logger

from illumio_ops.siem.transports._stream import (
    frame_payload,
    graceful_close,
    peer_closed,
)
from illumio_ops.siem.transports.base import Transport


class SyslogTCPTransport(Transport):
    def __init__(self, host: str, port: int, timeout: float = 10.0, framing: str = "lf") -> None:
        self._framing = framing
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()

    def _connect(self) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self._timeout)
        try:
            s.connect((self._host, self._port))
        except Exception:
            s.close()  # don't leak the fd; publish self._sock only after a successful connect
            raise
        self._sock = s
        return s

    def send(self, payload: str) -> None:
        data = frame_payload(payload, self._framing)
        with self._lock:
            if self._sock is not None and peer_closed(self._sock):
                # After the peer closed, the first sendall() still "succeeds" and the data is lost: reconnect first.
                logger.info("TCP syslog peer closed the connection, reconnecting")
                self._drop_socket()
            sock = self._sock or self._connect()
            try:
                sock.sendall(data)
            except OSError:
                logger.warning("TCP syslog connection lost, reconnecting")
                self._drop_socket()
                self._connect().sendall(data)

    def _drop_socket(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    def finish_batch(self) -> None:
        """Confirm the batch reached the peer: graceful close, OSError when the peer resets."""
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
                except OSError as exc:
                    logger.warning("TCP syslog close was not graceful: {}", exc)
