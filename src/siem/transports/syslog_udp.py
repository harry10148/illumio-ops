from __future__ import annotations
import socket
from loguru import logger
from src.siem.transports.base import Transport

_MAX_UDP_SAFE = 1400


class SyslogUDPTransport(Transport):
    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Resolved lazily on first send and cached: sendto() with a hostname
        # would pay a blocking getaddrinfo() for every datagram in the hot
        # dispatch loop (up to batch_size per tick).
        self._addr: tuple | None = None

    def send(self, payload: str) -> None:
        data = payload.encode("utf-8")
        if len(data) > _MAX_UDP_SAFE:
            logger.warning(
                "UDP payload {} bytes exceeds safe MTU ({}); fragmentation risk",
                len(data), _MAX_UDP_SAFE,
            )
        if self._addr is None:
            self._addr = socket.getaddrinfo(
                self._host, self._port, socket.AF_INET, socket.SOCK_DGRAM
            )[0][4]
        try:
            self._sock.sendto(data, self._addr)
        except OSError:
            # Drop the cached resolution so the next attempt re-resolves
            # (keeps DNS-failover behavior).
            self._addr = None
            raise

    def close(self) -> None:
        self._sock.close()
