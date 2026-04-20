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

    def send(self, payload: str) -> None:
        data = payload.encode("utf-8")
        if len(data) > _MAX_UDP_SAFE:
            logger.warning(
                "UDP payload {} bytes exceeds safe MTU ({}); fragmentation risk",
                len(data), _MAX_UDP_SAFE,
            )
        self._sock.sendto(data, (self._host, self._port))

    def close(self) -> None:
        self._sock.close()
