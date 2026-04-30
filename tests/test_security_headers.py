"""Phase 3 security header contracts: CSP nonce, Cross-Origin headers, Server header, rate limits."""
from __future__ import annotations

import json
import pytest


@pytest.fixture
def client(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "web_gui": {"username": "illumio", "password": "illumio",
                    "secret_key": "", "allowed_ips": []},
    }), encoding="utf-8")
    from src.config import ConfigManager
    from src.gui import build_app
    app = build_app(ConfigManager(str(cfg)))
    app.config["TESTING"] = True
    return app.test_client()


def _parse_csp(headers) -> dict[str, str]:
    """Parse CSP header into a dict keyed by directive name."""
    csp = headers.get("Content-Security-Policy", "")
    result: dict[str, str] = {}
    for part in csp.split(";"):
        part = part.strip()
        if not part:
            continue
        tokens = part.split(None, 1)
        key = tokens[0].lower()
        value = tokens[1] if len(tokens) > 1 else ""
        result[key] = value
    return result


def test_csp_no_unsafe_inline(client):
    r = client.get("/login")
    csp = _parse_csp(r.headers)
    assert "'unsafe-inline'" not in csp.get("script-src", ""), \
        "script-src must not contain 'unsafe-inline'"
    assert "'unsafe-inline'" not in csp.get("style-src", ""), \
        "style-src must not contain 'unsafe-inline'"


def test_csp_has_nonce(client):
    r = client.get("/login")
    csp = _parse_csp(r.headers)
    assert "'nonce-" in csp.get("script-src", ""), \
        f"script-src must contain a nonce; got: {csp.get('script-src')!r}"
    assert "'nonce-" in csp.get("style-src", ""), \
        f"style-src must contain a nonce; got: {csp.get('style-src')!r}"


def test_server_header_removed(client):
    r = client.get("/login")
    assert "Server" not in r.headers, \
        f"Server header must be stripped; got: {r.headers.get('Server')!r}"


def test_cross_origin_opener_policy(client):
    r = client.get("/login")
    assert r.headers.get("Cross-Origin-Opener-Policy") == "same-origin"


def test_cross_origin_resource_policy(client):
    r = client.get("/login")
    assert r.headers.get("Cross-Origin-Resource-Policy") == "same-site"


def test_rate_limit_login_returns_429(client):
    """Exhaust /api/login limit (5 per minute) and confirm 429."""
    for _ in range(5):
        client.post("/api/login", json={"username": "x", "password": "y"})
    r = client.post("/api/login", json={"username": "x", "password": "y"})
    assert r.status_code == 429
