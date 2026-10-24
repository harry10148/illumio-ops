import time
from pathlib import Path

import pytest

from illumio_ops.web.app import create_app
from illumio_ops.web.ipallow import RstDrop

from .conftest import LOCAL, login, make_ctx


@pytest.fixture
def guarded_app(tmp_path, static_dir):
    ctx = make_ctx(tmp_path, allowed_ips=["127.0.0.1", "192.168.1.0/24"])
    a = create_app(ctx, use_https=False, static_dir=static_dir)
    a.testing = True
    return a


def test_ip_gate_is_the_first_before_request_hook(guarded_app):
    assert guarded_app.before_request_funcs[None][0].__name__ == "ip_allowlist_gate"


@pytest.mark.parametrize("path", ["/", "/assets/app.js", "/api/auth/csrf", "/api/auth/login"])
def test_blocked_ip_gets_rst_drop_on_every_path(guarded_app, path):
    with (guarded_app.test_request_context(path, environ_base={"REMOTE_ADDR": "10.0.0.1"}),
          pytest.raises(RstDrop)):
        guarded_app.preprocess_request()


@pytest.mark.parametrize("remote", ["127.0.0.1", "192.168.1.50", "::ffff:127.0.0.1"])
def test_allowed_ip_passes(guarded_app, remote):
    r = guarded_app.test_client().get("/api/auth/csrf", environ_overrides={"REMOTE_ADDR": remote})
    assert r.status_code == 200


def test_blocked_ip_receives_no_http_body(guarded_app):
    r = guarded_app.test_client().get("/api/auth/csrf", environ_overrides={"REMOTE_ADDR": "10.0.0.1"})
    assert r.data == b""


def _csp(r):
    out = {}
    for part in r.headers["Content-Security-Policy"].split(";"):
        bits = part.strip().split()
        if bits:
            out[bits[0]] = " ".join(bits[1:])
    return out


def test_security_headers(client):
    r = client.get("/", environ_overrides=LOCAL)
    csp = _csp(r)
    assert csp["default-src"] == "'self'" and csp["script-src"] == "'self'"
    assert "'unsafe-inline'" in csp["style-src"] and "nonce-" not in r.headers["Content-Security-Policy"]
    assert csp["img-src"] == "'self' data:" and csp["connect-src"] == "'self'" and csp["font-src"] == "'self'"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert r.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert r.headers["Cross-Origin-Resource-Policy"] == "same-site"
    assert "Server" not in r.headers
    pp = r.headers["Permissions-Policy"]
    for feature in ("camera", "microphone", "geolocation", "interest-cohort", "browsing-topics", "payment", "usb"):
        assert f"{feature}=()" in pp
    assert "Strict-Transport-Security" not in r.headers


def test_hsts_only_over_https(tmp_path, static_dir):
    a = create_app(make_ctx(tmp_path), use_https=True, static_dir=static_dir)
    a.testing = True
    r = a.test_client().get("/", environ_overrides=LOCAL, base_url="https://localhost")
    hsts = r.headers["Strict-Transport-Security"]
    assert "max-age=31536000" in hsts and "includeSubDomains" in hsts and "preload" in hsts


def test_session_cookie_flags(client):
    r = login(client)
    cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Secure" not in cookie


def test_index_is_no_store(client):
    assert client.get("/", environ_overrides=LOCAL).headers["Cache-Control"] == "no-store"


def test_spa_fallback_serves_index_for_unknown_paths(client):
    r = client.get("/system/pce", environ_overrides=LOCAL)
    assert r.status_code == 200 and b"/assets/app.js" in r.data
    assert client.get("/assets/app.js", environ_overrides=LOCAL).data == b"console.log(1)"


def test_unknown_api_path_is_not_spa(client):
    login(client)
    r = client.get("/api/does-not-exist", environ_overrides=LOCAL)
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"


def test_api_requires_login_returns_401_envelope(client):
    r = client.get("/api/auth/me", environ_overrides=LOCAL)
    assert r.status_code == 401
    assert r.get_json() == {"ok": False, "data": None, "meta": {"partial": False, "truncated": False, "notes": []},
                            "error": {"code": "auth_required", "message_key": "err_auth_required",
                                      "params": {}, "field": None}}


def test_csrf_missing_on_api_post_returns_400_with_new_token(client):
    login(client)
    r = client.post("/api/auth/logout", json={}, environ_overrides=LOCAL)
    body = r.get_json()
    assert r.status_code == 400 and body["error"]["code"] == "csrf_error"
    assert body["data"]["csrf_token"]


def test_login_rate_limited_after_five(client):
    for _ in range(5):
        login(client, password="wrong-password")
    r = login(client, password="wrong-password")
    assert r.status_code == 429 and r.get_json()["error"]["code"] == "rate_limited"


def test_max_content_length_is_25mb(app):
    assert app.config["MAX_CONTENT_LENGTH"] == 25 * 1024 * 1024


def test_limiter_uses_file_storage_in_limiter_dir(tmp_path, static_dir, monkeypatch):
    monkeypatch.delenv("ILLUMIO_OPS_RATELIMIT_URI")
    ctx = make_ctx(tmp_path)
    a = create_app(ctx, use_https=False, static_dir=static_dir)
    assert a.config["RATELIMIT_STORAGE_URI"] == f"file://{ctx.paths.limiter_dir}"
    from illumio_ops.web.security import JsonFileStorage

    limiter = next(iter(a.extensions["limiter"]))
    assert isinstance(limiter._storage, JsonFileStorage)


def test_limiter_snapshot_survives_restart_and_drops_expired(tmp_path):
    from illumio_ops.web.security import JsonFileStorage

    uri = f"file://{tmp_path / 'lim'}"
    s1 = JsonFileStorage(uri)
    s1.incr("ip:1.2.3.4", expiry=60)
    s1.incr("ip:1.2.3.4", expiry=60)
    s1.incr("short", expiry=1)
    time.sleep(1.1)
    s2 = JsonFileStorage(uri)
    assert s2.get("ip:1.2.3.4") == 2
    assert s2.get("short") == 0
    assert Path(tmp_path / "lim" / "rate_limits.json").exists()
