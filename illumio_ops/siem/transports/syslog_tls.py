from __future__ import annotations

import socket
import ssl
import threading

from loguru import logger

from illumio_ops.siem.transports._stream import (
    frame_payload,
    graceful_close,
    peer_closed,
)
from illumio_ops.siem.transports.base import Transport


class SyslogTLSTransport(Transport):
    def __init__(self, host: str, port: int, tls_verify: bool = True, ca_bundle: str | None = None,
                 timeout: float = 10.0, framing: str = "lf") -> None:
        self._framing = framing
        self._host = host
        self._port = port
        self._tls_verify = tls_verify
        self._ca_bundle = ca_bundle
        self._timeout = timeout
        self._sock: ssl.SSLSocket | None = None
        self._lock = threading.Lock()

    def _connect(self) -> ssl.SSLSocket:
        if self._ca_bundle:
            # Trust the operator's bundle only: cafile makes create_default_context skip the system store, whereas
            # load_verify_locations on a default context would add it on top of every public CA.
            ctx = ssl.create_default_context(cafile=self._ca_bundle)
        else:
            ctx = ssl.create_default_context()
        if not self._tls_verify:
            logger.warning("TLS verification disabled — plaintext risk")
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.settimeout(self._timeout)
        sock = ctx.wrap_socket(raw, server_hostname=self._host)
        try:
            sock.connect((self._host, self._port))
        except Exception:
            sock.close()
            raise
        self._sock = sock
        return sock

    def send(self, payload: str) -> None:
        data = frame_payload(payload, self._framing)
        with self._lock:
            if self._sock is not None and peer_closed(self._sock):
                logger.info("TLS syslog peer closed the connection, reconnecting")
                self._drop_socket()
            sock = self._sock or self._connect()
            try:
                sock.sendall(data)
            except (OSError, ssl.SSLError):
                logger.warning("TLS syslog connection lost, reconnecting")
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
                    logger.warning("TLS syslog close was not graceful: {}", exc)
