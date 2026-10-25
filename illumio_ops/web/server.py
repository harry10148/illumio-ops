"""cheroot server. Refused peers are dropped at accept time with a TCP reset: before the
TLS handshake and before cheroot parses or answers anything (including the
`100 Continue` it would send for `Expect: 100-continue`)."""
from __future__ import annotations

import socket
import ssl
import struct
import threading
from collections.abc import Callable
from typing import Any

from cheroot import wsgi
from cheroot.ssl.builtin import BuiltinSSLAdapter
from flask import Flask
from loguru import logger

_TLS_NOISE = ("SSLV3_ALERT", "UNEXPECTED_EOF_WHILE_READING")


class _FilteringListener:
    """Stands in for the listening socket; cheroot reads server.socket at every accept."""

    def __init__(self, inner: socket.socket, peer_allowed: Callable[[str], bool]) -> None:
        self._inner = inner
        self._peer_allowed = peer_allowed

    def accept(self) -> tuple[socket.socket, Any]:
        conn, addr = self._inner.accept()
        peer = addr[0] if isinstance(addr, tuple) else ""
        try:
            allowed = self._peer_allowed(peer)
        except Exception:  # noqa: BLE001 - an allowlist failure must fail closed, never crash the loop
            logger.exception("allowlist check failed; refusing the connection")
            allowed = False
        if allowed:
            return conn, addr
        logger.warning("refused a connection from a non-allowlisted address")
        try:
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        finally:
            conn.close()  # SO_LINGER 0: the kernel sends RST, not FIN
        raise TimeoutError("refused peer")  # cheroot treats a timeout as "no new connection"

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _HardenedSSLAdapter(BuiltinSSLAdapter):
    """Use our pre-built context; BuiltinSSLAdapter.__init__ would build its own."""

    def __init__(self, ctx: ssl.SSLContext) -> None:
        super(BuiltinSSLAdapter, self).__init__("", "")
        self.context = ctx
        self._server_env: dict[str, str] = {}


class _Server(wsgi.Server):
    def error_log(self, msg: str = "", level: int = 20, traceback: bool = False) -> None:
        if not any(k in str(msg) for k in _TLS_NOISE):  # handshake noise from scanners and closed tabs
            super().error_log(msg, level, traceback)


def serve(app: Flask, host: str, port: int, ssl_ctx: ssl.SSLContext | None, stop: threading.Event, *,
          peer_allowed: Callable[[str], bool] = lambda _ip: True) -> None:
    server = _Server((host, port), app, numthreads=10)
    server.server_name = "Web"  # no cheroot version in the Server header (5.x L-13)
    if ssl_ctx is not None:
        server.ssl_adapter = _HardenedSSLAdapter(ssl_ctx)
    server.prepare()
    server.socket = _FilteringListener(server.socket, peer_allowed)

    def stopper() -> None:
        stop.wait()
        server.stop()

    threading.Thread(target=stopper, name="server-stopper", daemon=True).start()
    logger.info("serving on {}:{} ({})", host, port, "https" if ssl_ctx else "http")
    try:
        server.serve()
    finally:
        stop.set()
        server.stop()
