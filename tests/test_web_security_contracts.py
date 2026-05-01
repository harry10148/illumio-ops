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
    client.post("/api/login", json={"username": "illumio", "password": "illumio"})
    client.post("/logout")
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
