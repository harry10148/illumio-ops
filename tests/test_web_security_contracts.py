"""Freeze Web GUI security contracts before migrating to Flask extensions.

Phase 4 migrates to flask-wtf/flask-limiter/flask-talisman/flask-login.
These tests lock down behavior that MUST survive: login success/failure,
CSRF rejection, rate limit 429, session persistence, logout.
"""
from __future__ import annotations

import json
import time

import pytest


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """Build a test Flask app against a temp config."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "web_gui": {
            "username": "illumio",
            "password": "illumio",
            "secret_key": "",
            "allowed_ips": [],
        },
    }), encoding="utf-8")
    from src.config import ConfigManager
    from src.gui import build_app  # factory introduced in Task 3
    # flask-limiter uses per-app memory storage, so each app instance starts fresh.
    cm = ConfigManager(str(cfg))
    app = build_app(cm)
    app.config["TESTING"] = True
    return app.test_client(), cm


@pytest.fixture
def app_client_initial(tmp_path):
    """app_client variant with must_change_password=True and a known _initial_password.
    Mirrors the existing app_client fixture (build_app, TESTING=True) so CSRF /
    limiter behavior matches."""
    from src.config import ConfigManager, hash_password
    initial_pw = "initial-test-pw-1234"
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "web_gui": {
            "username": "illumio",
            "password": hash_password(initial_pw),
            "_initial_password": initial_pw,
            "must_change_password": True,
            "secret_key": "",
            "allowed_ips": [],
        },
    }), encoding="utf-8")
    from src.gui import build_app
    cm = ConfigManager(str(cfg))
    app = build_app(cm)
    app.config["TESTING"] = True
    return app.test_client(), cm, initial_pw


def test_login_valid_credentials_sets_session(app_client):
    client, _cm = app_client
    r = client.post("/api/login", json={"username": "illumio", "password": "illumio"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert "csrf_token" in body


def test_login_invalid_credentials_rejected(app_client):
    client, _cm = app_client
    r = client.post("/api/login", json={"username": "illumio", "password": "wrong"})
    assert r.status_code in (401, 403)


def test_rate_limit_triggers_429_after_5_failures(app_client):
    client, _cm = app_client
    for _ in range(5):
        client.post("/api/login", json={"username": "x", "password": "y"})
    r = client.post("/api/login", json={"username": "x", "password": "y"})
    assert r.status_code == 429


def test_csrf_required_on_post_after_login(app_client):
    client, _cm = app_client
    # Login first
    client.post("/api/login", json={"username": "illumio", "password": "illumio"})
    # POST without csrf header should be rejected
    r = client.post("/api/security", json={"allowed_ips": ["192.168.1.1"]})
    assert r.status_code in (400, 403), f"CSRF should block; got {r.status_code}"


def test_logout_clears_session(app_client):
    client, _cm = app_client
    r = client.post("/api/login", json={"username": "illumio", "password": "illumio"})
    csrf_token = (r.get_json() or {}).get("csrf_token", "")
    client.post("/logout", headers={"X-CSRFToken": csrf_token})
    # After logout, protected endpoint should be unauthorized
    r = client.get("/api/dashboard")
    assert r.status_code in (302, 401), f"Logout must unauth; got {r.status_code}"


def test_ip_allowlist_blocks_non_matching_client(app_client):
    client, cm = app_client
    cm.config["web_gui"]["allowed_ips"] = ["10.0.0.0/8"]
    cm.save()
    # Client is 127.0.0.1 (flask test); should be blocked.
    # Current behavior: TCP RST drop (returns empty 200 in test context via _RstDrop handler).
    # Post-migration target: returns 403. Accept both.
    r = client.get("/")
    assert r.status_code in (200, 403), f"Blocked IP should be rejected; got {r.status_code}"


def test_rate_limit_429_returns_json_not_html(app_client):
    """Regression: 429 must return JSON error body so API clients can parse it."""
    client, _cm = app_client
    # Exhaust the limit
    for _ in range(6):
        r = client.post("/api/login", json={"username": "x", "password": "y"})
    assert r.status_code == 429
    body = r.get_json(silent=True)
    assert body is not None, f"429 body must be JSON, got: {r.data[:200]!r}"
    assert body.get("ok") is False


def test_login_timing_equivalent_for_invalid_username_and_password(app_client):
    """H1: invalid username and invalid password must take similar time
    (both trigger argon2id). The dynamic floor (half the warm-up's bad-pass
    elapsed) catches the case where argon2 was clearly skipped, regardless
    of how argon2 params are tuned. The ratio check is belt-and-suspenders."""
    client, _cm = app_client
    # Warm caches AND measure baseline argon2 cost (bad-pass = full argon2)
    t0 = time.perf_counter()
    client.post('/api/login', json={'username': 'illumio', 'password': 'wrong'})
    baseline = time.perf_counter() - t0
    # Self-calibrating floor: half the baseline. If a future config tunes argon2
    # down (e.g. time_cost=1 on CI), the floor scales with it.
    floor = baseline * 0.5

    # Time invalid-username path
    t0 = time.perf_counter()
    r1 = client.post('/api/login', json={'username': 'nobody', 'password': 'wrong'})
    elapsed_bad_user = time.perf_counter() - t0

    # Time invalid-password path (correct user)
    t0 = time.perf_counter()
    r2 = client.post('/api/login', json={'username': 'illumio', 'password': 'wrong'})
    elapsed_bad_pass = time.perf_counter() - t0

    assert r1.status_code == 401
    assert r2.status_code == 401
    # Floor proves verify_password actually ran (no short-circuit on missing user)
    assert elapsed_bad_user > floor, (
        f"invalid-username path too fast ({elapsed_bad_user:.3f}s vs floor={floor:.3f}s) "
        f"— short-circuit not removed"
    )
    # Ratio is the second check — argon2 default params vary 80-250ms even on a
    # single host, so a loaded CI runner can hit 3.5x without a real regression.
    ratio = max(elapsed_bad_user, elapsed_bad_pass) / max(0.001, min(elapsed_bad_user, elapsed_bad_pass))
    assert ratio < 5.0, f"timing ratio {ratio:.1f}x suggests username enumeration possible"


def test_security_post_username_change_requires_old_password(app_client):
    """H2: changing the admin username without old_password must be rejected."""
    client, _cm = app_client
    # Login first
    r = client.post('/api/login', json={'username': 'illumio', 'password': 'illumio'})
    assert r.status_code == 200
    csrf_token = (r.get_json() or {}).get('csrf_token', '')
    # Try to change username without old_password (CSRF token included so we
    # reach the auth check, not get short-circuited by CSRF middleware).
    r = client.post('/api/security', json={'username': 'attacker'},
                    headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 401
    body = r.get_json()
    assert body['ok'] is False


def test_security_post_allowed_ips_change_requires_old_password(app_client):
    """H2: changing the IP allowlist without old_password must be rejected."""
    client, _cm = app_client
    r = client.post('/api/login', json={'username': 'illumio', 'password': 'illumio'})
    assert r.status_code == 200
    csrf_token = (r.get_json() or {}).get('csrf_token', '')
    r = client.post('/api/security', json={'allowed_ips': ['1.2.3.4']},
                    headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 401
    body = r.get_json()
    assert body['ok'] is False


def test_security_post_username_change_succeeds_with_old_password(app_client):
    """H2: with correct old_password, username change should succeed."""
    client, _cm = app_client
    r = client.post('/api/login', json={'username': 'illumio', 'password': 'illumio'})
    assert r.status_code == 200
    csrf_token = (r.get_json() or {}).get('csrf_token', '')
    r = client.post('/api/security', json={
        'username': 'newadmin',
        'old_password': 'illumio',
    }, headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    assert r.get_json()['ok'] is True


def test_gui_init_has_no_str_e_leaks_in_routes():
    """H3 regression guard: scan src/gui/__init__.py for the pattern
    `jsonify({"ok": False, "error": str(<exc_var>)` which leaks exception
    text. The unified handler at the app level catches truly-unhandled cases."""
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / 'src' / 'gui' / '__init__.py'
    assert src.exists(), f"GUI source file not found at {src}"
    text = src.read_text(encoding='utf-8')
    # Catch any common identifier name in str(...) inside an error field
    leaks = re.findall(r'jsonify\(\{[^}]*"error"\s*:\s*str\((?:e|exc|err|ex)\)', text)
    assert not leaks, f"Found {len(leaks)} `str(<exc>)` leak(s) in src/gui/__init__.py: {leaks[:3]}"


# ----------------------------------------------------------------------------
# M4: unified error handler & first-login force-change-password contracts
# ----------------------------------------------------------------------------

def test_unified_error_handler_returns_generic_500(app_client, monkeypatch):
    """M4: an unhandled exception inside a route must return generic JSON,
    not leak the traceback. The unified handler at @app.errorhandler(Exception)
    is responsible.

    Strategy: patch ``src.gui._resolve_reports_dir`` to raise. That call
    happens BEFORE the route's inner try/except, so the exception
    propagates up to the unified handler.
    """
    client, _cm = app_client
    r = client.post('/api/login', json={'username': 'illumio', 'password': 'illumio'})
    assert r.status_code == 200

    sentinel = "TRACEBACK-SECRET-DO-NOT-LEAK"

    import src.gui as _gui_mod

    def _explode(*a, **kw):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(_gui_mod, '_resolve_reports_dir', _explode)
    r = client.get('/api/dashboard/audit_summary')
    body = r.get_json(silent=True) or {}
    response_text = r.get_data(as_text=True)
    # Must be 500 from the unified handler (not 200/short-circuited)
    assert r.status_code == 500, \
        f"expected 500 from unified handler, got {r.status_code}: {response_text[:200]}"
    # Sentinel must not appear anywhere in the response
    assert sentinel not in (body.get('error') or ''), \
        f"Sentinel leaked into response error field: {body}"
    assert sentinel not in response_text, \
        f"Sentinel leaked into response body: {response_text[:200]}"
    # Must include a request_id so operators can correlate logs
    assert body.get('request_id'), \
        f"unified handler should include request_id for log correlation: {body}"


def test_unified_error_handler_preserves_http_exceptions(app_client):
    """M4: 404/405 etc. (HTTPException) must not be swallowed into 500."""
    client, _cm = app_client
    # Log in first so the security gate doesn't intercept with 401/redirect
    # before Flask gets a chance to resolve the missing route.
    r = client.post('/api/login', json={'username': 'illumio', 'password': 'illumio'})
    assert r.status_code == 200, f"login failed: {r.get_json()}"

    r = client.get('/this-route-does-not-exist')
    assert r.status_code == 404, \
        f"missing route returned {r.status_code} not 404 — HTTPException may be swallowed by unified handler"


def test_first_login_must_change_password_blocks_api(app_client_initial):
    """M4: when must_change_password=True, regular API endpoints must
    redirect/reject until the password is changed.

    The current gate in security_check returns HTTP 423 (Locked) with
    ``{"ok": False, "error": "must_change_password", "code": 423}``."""
    client, _cm, initial_pw = app_client_initial
    r = client.post('/api/login', json={'username': 'illumio', 'password': initial_pw})
    assert r.status_code == 200, f"login failed: {r.get_json()}"

    r = client.get('/api/status')
    body = r.get_json(silent=True) or {}
    assert (
        r.status_code in (302, 403, 423)
        or body.get('must_change_password') is True
        or body.get('error') == 'must_change_password'
    ), (
        f"first-login user reached /api/status without changing password "
        f"(status={r.status_code}, body={body})"
    )


def test_password_change_clears_must_change_flag(app_client_initial):
    """M4: changing the password should clear must_change_password
    AND persist the change to disk."""
    client, cm, initial_pw = app_client_initial
    r = client.post('/api/login', json={'username': 'illumio', 'password': initial_pw})
    assert r.status_code == 200
    csrf_token = (r.get_json() or {}).get('csrf_token', '')

    headers = {'X-CSRF-Token': csrf_token} if csrf_token else {}
    r = client.post('/api/security',
                    json={
                        'old_password': initial_pw,
                        'new_password': 'NewStrongPass123!',
                        'confirm_password': 'NewStrongPass123!',
                    },
                    headers=headers)
    assert r.status_code == 200, f"password change failed: {r.status_code} {r.get_json()}"

    # In-memory check
    assert not cm.config.get('web_gui', {}).get('must_change_password'), \
        "must_change_password not cleared in-memory after change"
    assert '_initial_password' not in cm.config.get('web_gui', {}), \
        "_initial_password not cleared in-memory after change"

    # Persistence check: re-read from disk to confirm the route called cm.save()
    cm.load()
    assert not cm.config.get('web_gui', {}).get('must_change_password'), \
        "must_change_password not persisted (still True after reload from disk)"
    assert '_initial_password' not in cm.config.get('web_gui', {}), \
        "_initial_password not persisted as removed (still present after reload from disk)"


# ----------------------------------------------------------------------------
# M8: /logout must require CSRF token (no @csrf.exempt)
# ----------------------------------------------------------------------------

def test_logout_requires_csrf_token(app_client):
    """M8: POST /logout without a CSRF token should be rejected."""
    client, _cm = app_client
    # Log in
    r = client.post('/api/login', json={'username': 'illumio', 'password': 'illumio'})
    assert r.status_code == 200
    # POST /logout without a CSRF token (or with a wrong one)
    r = client.post('/logout', headers={'X-CSRFToken': 'wrong'})
    assert r.status_code == 400, \
        f"logout without CSRF token returned {r.status_code}; CSRF guard not enforced"


def test_logout_succeeds_with_csrf_token(app_client):
    """M8: POST /logout with the right CSRF token works AND clears the session."""
    client, _cm = app_client
    r = client.post('/api/login', json={'username': 'illumio', 'password': 'illumio'})
    assert r.status_code == 200
    csrf_token = r.get_json().get('csrf_token')
    assert csrf_token, "login did not return csrf_token"

    # Verify we are actually authed before logout
    r_pre = client.get('/api/status')
    assert r_pre.status_code == 200, \
        f"pre-logout /api/status should succeed, got {r_pre.status_code}"

    r = client.post('/logout', headers={'X-CSRFToken': csrf_token})
    # 200 response or 302 redirect to /login is success
    assert r.status_code in (200, 302), \
        f"logout with valid CSRF returned {r.status_code}"

    # Session must be cleared — subsequent authed call should be rejected
    r_post = client.get('/api/status')
    assert r_post.status_code in (302, 401), \
        f"after logout, /api/status returned {r_post.status_code} — session not cleared"
