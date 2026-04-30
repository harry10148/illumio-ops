"""Tests for Phase 5 security hardening: log sanitization and error disclosure."""
import json
import os
import tempfile
import pytest

from src.gui import _safe_log


def test_remote_addr_crlf_stripped():
    result = _safe_log("1.2.3.4\r\nX-Injected: evil")
    assert '\r' not in result
    assert '\n' not in result
    assert result.startswith("1.2.3.4")


def test_safe_log_tab_replaced():
    result = _safe_log("value\twith\ttabs")
    assert '\t' not in result


def test_safe_log_truncates():
    long_str = "a" * 300
    result = _safe_log(long_str)
    assert len(result) == 200


def test_safe_log_clean_passthrough():
    result = _safe_log("192.168.1.1")
    assert result == "192.168.1.1"


def test_internal_server_error_hides_details():
    """Global error handler must not leak traceback text to the client."""
    from src.config import ConfigManager, hash_password
    from src.gui import build_app as _create_app

    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, 'w') as f:
            json.dump({
                "api": {"url": "test", "key": "test", "secret": "test", "org_id": "1"},
                "rules": [],
            }, f)

        cm = ConfigManager(config_file=path)
        cm.load()
        cm.config["web_gui"] = {
            "username": "admin",
            "password": hash_password("testpass"),
            "allowed_ips": [],
            "secret_key": "test-secret",
        }
        cm.save()

        app = _create_app(cm, persistent_mode=True)
        app.config["TESTING"] = True

        # Register a route that always raises to trigger the global error handler.
        @app.route('/api/_test_error')
        def _boom():
            raise RuntimeError("secret internal detail should not leak")

        with app.test_client() as client:
            # Log in first so the auth check passes.
            login_resp = client.post('/api/login', json={"username": "admin", "password": "testpass"})
            csrf = (login_resp.get_json() or {}).get('csrf_token', '')

            resp = client.get('/api/_test_error', headers={"X-CSRFToken": csrf})
            assert resp.status_code == 500
            data = resp.get_json()
            assert data is not None
            assert "request_id" in data
            # Exception details must not appear in the response body.
            body_text = json.dumps(data)
            assert "secret internal detail" not in body_text
            assert "Traceback" not in body_text
            assert "RuntimeError" not in body_text
    finally:
        os.unlink(path)
