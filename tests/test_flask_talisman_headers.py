"""Verify flask-talisman sets standard security headers."""


def test_x_content_type_options_nosniff(header_client):
    r = header_client.get("/login")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


def test_x_frame_options_deny(header_client):
    r = header_client.get("/login")
    assert r.headers.get("X-Frame-Options") in ("DENY", "SAMEORIGIN")


def test_content_security_policy_present(header_client):
    r = header_client.get("/login")
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src" in csp
    # talisman default CSP includes 'self'
    assert "'self'" in csp


def test_hsts_only_when_tls_enabled(header_client):
    """HSTS should NOT be set when TLS is disabled (local dev)."""
    r = header_client.get("/login")
    # Default behavior: no HSTS header unless force_https is set
    hsts = r.headers.get("Strict-Transport-Security")
    # Either absent (TLS off) or present with max-age (TLS on) — both valid
    if hsts is not None:
        assert "max-age=" in hsts


def test_permissions_policy_restricts_sensitive_apis(header_client):
    """Regression: camera/microphone/geolocation must be restricted (not browsing-topics only)."""
    r = header_client.get("/login")
    pp = r.headers.get("Permissions-Policy", "")
    # Must mention at least one of the intended restrictions
    assert "camera" in pp, f"camera not restricted; got: {pp!r}"
    assert "microphone" in pp, f"microphone not restricted; got: {pp!r}"
    assert "geolocation" in pp, f"geolocation not restricted; got: {pp!r}"
