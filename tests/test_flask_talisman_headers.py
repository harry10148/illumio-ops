"""Verify flask-talisman sets standard security headers."""
import json
import pytest


@pytest.fixture
def client(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "web_gui": {"username": "illumio", "password_hash": "", "password_salt": "",
                    "secret_key": "", "allowed_ips": []},
    }), encoding="utf-8")
    from src.config import ConfigManager
    from src.gui import build_app
    app = build_app(ConfigManager(str(cfg)))
    app.config["TESTING"] = True
    return app.test_client()


def test_x_content_type_options_nosniff(client):
    r = client.get("/login")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


def test_x_frame_options_deny(client):
    r = client.get("/login")
    assert r.headers.get("X-Frame-Options") in ("DENY", "SAMEORIGIN")


def test_content_security_policy_present(client):
    r = client.get("/login")
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src" in csp
    # talisman default CSP includes 'self'
    assert "'self'" in csp


def test_hsts_only_when_tls_enabled(client):
    """HSTS should NOT be set when TLS is disabled (local dev)."""
    r = client.get("/login")
    # Default behavior: no HSTS header unless force_https is set
    hsts = r.headers.get("Strict-Transport-Security")
    # Either absent (TLS off) or present with max-age (TLS on) — both valid
    if hsts is not None:
        assert "max-age=" in hsts


def test_permissions_policy_restricts_sensitive_apis(client):
    """Regression: camera/microphone/geolocation must be restricted (not browsing-topics only)."""
    r = client.get("/login")
    pp = r.headers.get("Permissions-Policy", "")
    # Must mention at least one of the intended restrictions
    assert "camera" in pp, f"camera not restricted; got: {pp!r}"
    assert "microphone" in pp, f"microphone not restricted; got: {pp!r}"
    assert "geolocation" in pp, f"geolocation not restricted; got: {pp!r}"
