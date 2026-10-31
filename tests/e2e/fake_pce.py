"""A stand-in PCE for browser tests: canned responses for the health endpoints."""
from __future__ import annotations

import json
import threading
from typing import Any

from werkzeug.serving import make_server
from werkzeug.wrappers import Request, Response

DEFAULTS: dict[str, tuple[int, bytes]] = {
    "/api/v2/noop": (204, b""),
    "/api/v2/health": (200, json.dumps([{"status": "normal"}]).encode()),
    "/api/v2/node_available": (200, b""),
}


class FakePce:
    def __init__(self) -> None:
        self.responses = dict(DEFAULTS)
        self.calls: list[str] = []
        self._server = make_server("127.0.0.1", 0, self._app, threaded=True)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def set(self, path: str, status: int, body: Any = b"") -> None:
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.responses[path] = (status, raw)

    def _app(self, environ: dict[str, Any], start_response: Any) -> Any:
        req = Request(environ)
        self.calls.append(req.path)
        status, body = self.responses.get(req.path, (404, b""))
        return Response(body, status=status, content_type="application/json")(environ, start_response)

    def start(self) -> FakePce:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
