from __future__ import annotations
import socket
import ssl
import threading
from typing import Optional
from loguru import logger
from src.siem.transports._stream import frame_payload, graceful_close, peer_closed
from src.siem.transports.base import Transport


class SyslogTLSTransport(Transport):
    def __init__(
        self,
        host: str,
        port: int,
        tls_verify: bool = True,
        ca_bundle: Optional[str] = None,
        timeout: float = 10.0,
        framing: str = "lf",
    ):
        self._framing = framing
        self._host = host
        self._port = port
        self._tls_verify = tls_verify
        self._ca_bundle = ca_bundle
        self._timeout = timeout
        self._sock: ssl.SSLSocket | None = None
        self._lock = threading.Lock()

    def _connect(self) -> None:
        if self._ca_bundle:
            # Pin trust to the operator-provided bundle only: passing cafile
            # makes create_default_context skip loading the system CA store,
            # whereas load_verify_locations on a default context would ADD the
            # bundle on top of every public CA (defeating the pin).
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
            # Don't leak the wrapped socket fd if the handshake/connect fails;
            # only publish self._sock after a successful connect.
            try:
                sock.close()
            except Exception:
                pass
            raise
        self._sock = sock

    def send(self, payload: str) -> None:
        data = frame_payload(payload, self._framing)
        with self._lock:
            if self._sock is not None and peer_closed(self._sock):
                # 對端已關閉時第一個 sendall() 仍會「成功」而資料被丟掉，
                # 所以送之前先確認，已關閉就重連。
                logger.info("TLS syslog peer closed the connection, reconnecting")
                self._drop_socket()
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
                    logger.warning("TLS syslog close was not graceful: {}", exc)
