from __future__ import annotations

import socket
from typing import Any

from loguru import logger

from illumio_ops.siem.transports.base import Transport

_MAX_UDP_SAFE = 1400


class SyslogUDPTransport(Transport):
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Resolved lazily on first send and cached: sendto() with a hostname would pay a blocking getaddrinfo()
        # for every datagram in the dispatch loop.
        self._addr: Any = None

    def send(self, payload: str) -> None:
        data = payload.encode("utf-8")
        if len(data) > _MAX_UDP_SAFE:
            logger.warning("UDP payload {} bytes exceeds safe MTU ({}); fragmentation risk", len(data), _MAX_UDP_SAFE)
        if self._addr is None:
            self._addr = socket.getaddrinfo(self._host, self._port, socket.AF_INET, socket.SOCK_DGRAM)[0][4]
        try:
            self._sock.sendto(data, self._addr)
        except OSError:
            self._addr = None  # re-resolve next time (keeps DNS failover)
            raise

    def close(self) -> None:
        self._sock.close()
