from __future__ import annotations
import socket
import ssl
import threading
from typing import Optional
from loguru import logger
from src.siem.transports.base import Transport


class SyslogTLSTransport(Transport):
    def __init__(
        self,
        host: str,
        port: int,
        tls_verify: bool = True,
        ca_bundle: Optional[str] = None,
        timeout: float = 10.0,
    ):
        self._host = host
        self._port = port
        self._tls_verify = tls_verify
        self._ca_bundle = ca_bundle
        self._timeout = timeout
        self._sock: ssl.SSLSocket | None = None
        self._lock = threading.Lock()

    def _connect(self) -> None:
        ctx = ssl.create_default_context()
        if self._ca_bundle:
            ctx.load_verify_locations(self._ca_bundle)
        if not self._tls_verify:
            logger.warning("TLS verification disabled — plaintext risk")
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.settimeout(self._timeout)
        self._sock = ctx.wrap_socket(raw, server_hostname=self._host)
        self._sock.connect((self._host, self._port))

    def send(self, payload: str) -> None:
        data = (payload + "\n").encode("utf-8")
        with self._lock:
            if self._sock is None:
                self._connect()
            try:
                self._sock.sendall(data)
            except (BrokenPipeError, ConnectionResetError, OSError, ssl.SSLError):
                logger.warning("TLS syslog connection lost, reconnecting")
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
