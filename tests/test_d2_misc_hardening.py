"""D2 misc hardening: session cookie Secure flag, login.html password
minlength, and write-lock coverage for /api/security and /api/tls/config.
"""
from __future__ import annotations

import inspect
import json


def _write_config(tmp_path, **web_gui_overrides):
    cfg = tmp_path / "config.json"
    web_gui = {
        "username": "illumio",
        "password": "illumio",
        "secret_key": "x" * 64,
        "allowed_ips": [],
    }
    web_gui.update(web_gui_overrides)
    cfg.write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "web_gui": web_gui,
    }), encoding="utf-8")
    return str(cfg)


# ── Sub-item 1: session cookie Secure flag must track use_https ────────────

def test_session_cookie_secure_when_https_enabled(tmp_path):
    from src.config import ConfigManager
    from src.gui import build_app

    cm = ConfigManager(config_file=_write_config(tmp_path))
    app = build_app(cm, use_https=True)
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_session_cookie_not_secure_when_https_disabled(tmp_path):
    """Without this fix, SESSION_COOKIE_SECURE was hardcoded True even when
    TLS is off, so a browser talking to the GUI over plain HTTP would never
    send the session cookie back — login would appear to silently fail."""
    from src.config import ConfigManager
    from src.gui import build_app

    cm = ConfigManager(config_file=_write_config(tmp_path))
    app = build_app(cm, use_https=False)
    assert app.config["SESSION_COOKIE_SECURE"] is False


# ── Sub-item 2: login.html password fields must match backend's 12-char min ─

def test_login_page_password_minlength_matches_backend(tmp_path):
    from src.config import ConfigManager
    from src.gui import build_app

    cm = ConfigManager(config_file=_write_config(tmp_path))
    app = build_app(cm, use_https=False)
    app.config["TESTING"] = True
    body = app.test_client().get("/login").get_data(as_text=True)
    assert 'id="new-password"' in body
    assert body.count('minlength="12"') >= 2, "both password fields must require 12 chars (matches config.py's 12-512 rule)"
    assert 'minlength="8"' not in body


# ── Sub-item 5: /api/security and /api/tls/config must serialize saves ─────

def test_api_security_post_holds_write_lock_across_load_mutate_save():
    from src.gui.routes import config as config_routes
    src = inspect.getsource(config_routes.make_config_blueprint)
    # crude structural check: the api_security_post body (bounded by the next
    # @bp.route) must contain the write_lock context manager, matching the
    # existing api_save_settings / api_pce_profiles_action convention.
    start = src.index("def api_security_post")
    end = src.index("# ── API: Settings")
    body = src[start:end]
    assert "with cm.write_lock:" in body


def test_api_tls_config_holds_write_lock_across_load_mutate_save():
    from src.gui.routes import config as config_routes
    src = inspect.getsource(config_routes.make_config_blueprint)
    start = src.index("def api_tls_config")
    end = src.index("def api_tls_renew")
    body = src[start:end]
    assert "with cm.write_lock:" in body
