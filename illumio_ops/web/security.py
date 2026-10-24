"""Security middleware settings, ported value-for-value from 5.x src/gui/__init__.py."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flask import Flask, Response, request
from flask_talisman import Talisman
from limits.storage.memory import MemoryStorage
from loguru import logger

from illumio_ops.paths import InstallPaths

RATELIMIT_URI_ENV = "ILLUMIO_OPS_RATELIMIT_URI"

CSP: dict[str, str | list[str]] = {
    "default-src": "'self'",
    "script-src": ["'self'"],
    "style-src": ["'self'", "'unsafe-inline'"],
    "img-src": ["'self'", "data:"],
    "font-src": "'self'",
    "connect-src": "'self'",
}
PERMISSIONS_POLICY = {f: "()" for f in (
    "camera", "microphone", "geolocation", "interest-cohort", "browsing-topics", "payment", "usb")}


class JsonFileStorage(MemoryStorage):
    """flask-limiter counters snapshotted to <dir>/rate_limits.json so limits survive a restart.

    limits ships no file backend; defining STORAGE_SCHEME registers this class for
    file:// URIs (limits' storage metaclass). Single-process only (v6 runs one process).
    """

    STORAGE_SCHEME = ["file"]  # noqa: RUF012 - read by limits' registry metaclass

    def __init__(self, uri: str | None = None, wrap_exceptions: bool = False, **options: Any) -> None:
        super().__init__(uri, wrap_exceptions=wrap_exceptions, **options)
        parsed = urlparse(uri or "")
        self._snapshot = Path(parsed.netloc + parsed.path) / "rate_limits.json"
        self._snapshot.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()  # request threads write the snapshot concurrently
        self._load_snapshot()

    def _load_snapshot(self) -> None:
        if not self._snapshot.exists():
            return
        try:
            data = json.loads(self._snapshot.read_text())
        except (OSError, ValueError) as exc:
            logger.warning("rate-limit snapshot unreadable, starting empty: {}", type(exc).__name__)
            return
        now = time.time()
        for key, entry in data.items():
            exp = float(entry.get("exp", 0))
            if exp > now:
                self.storage[key] = int(entry.get("val", 0))
                self.expirations[key] = exp

    def _write_snapshot(self) -> None:
        now = time.time()
        storage, expirations = dict(self.storage), dict(self.expirations)  # copies: the expiry timer mutates both
        data = {k: {"val": int(v), "exp": expirations.get(k, now)}
                for k, v in storage.items() if expirations.get(k, 0) > now}
        tmp = self._snapshot.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data))
            tmp.replace(self._snapshot)
        except OSError as exc:
            logger.warning("rate-limit snapshot write failed: {}", type(exc).__name__)

    def incr(self, key: str, expiry: float, amount: int = 1) -> int:
        with self._write_lock:
            result = super().incr(key, expiry, amount)
            self._write_snapshot()
        return result

    def check(self) -> bool:
        return self._snapshot.parent.is_dir()



def limiter_storage_uri(paths: InstallPaths) -> str:
    return os.environ.get(RATELIMIT_URI_ENV) or f"file://{paths.limiter_dir}"


def install_talisman(app: Flask, *, use_https: bool) -> None:
    talisman = Talisman(
        app,
        force_https=use_https,
        strict_transport_security=use_https,
        strict_transport_security_max_age=31536000 if use_https else 0,
        strict_transport_security_include_subdomains=use_https,
        strict_transport_security_preload=use_https,
        session_cookie_secure=use_https,
        # Talisman writes SESSION_COOKIE_SAMESITE itself (default Lax), overriding app.config.
        session_cookie_samesite="Strict",
        content_security_policy=CSP,
        # No nonces: a nonce in style-src would make browsers ignore its 'unsafe-inline'.
        content_security_policy_nonce_in=[],
        frame_options="DENY",
        referrer_policy="strict-origin-when-cross-origin",
        permissions_policy=PERMISSIONS_POLICY,
    )
    # Test clients speak plain HTTP: skip the HTTPS redirect when app.testing,
    # replacing the hook in place so hook order (IP gate first) is preserved.
    original = talisman._force_https

    def _force_https_unless_testing() -> Response | None:
        return None if app.testing else original()

    hooks = app.before_request_funcs.setdefault(None, [])
    if original in hooks:
        hooks[hooks.index(original)] = _force_https_unless_testing


def add_static_headers(response: Response) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-site"
    response.headers.pop("Server", None)
    if not request.path.startswith(("/api/", "/assets/")):
        response.headers["Cache-Control"] = "no-store"  # index.html must never be stale
    return response
