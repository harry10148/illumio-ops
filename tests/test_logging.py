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


def test_log_redacts_password_field(tmp_path):
    """L4: loguru sinks should redact secret-looking key=value pairs."""
    from loguru import logger as _logger
    from src.loguru_config import setup_loguru
    log_file = tmp_path / 'test.log'
    setup_loguru(log_file=str(log_file), level='DEBUG')
    _logger.info('Connecting with password=hunter2-secret-value')
    _logger.info('PCE response: {"api_key": "abcd1234secret"}')
    _logger.info('webhook_url=https://hooks.example.com/abc123')
    _logger.info('authorization: Bearer my-bearer-token-xyz')
    # Flush all enqueued sinks deterministically.
    _logger.complete()
    text = log_file.read_text()
    # The secret values must be scrubbed
    assert 'hunter2-secret-value' not in text
    assert 'abcd1234secret' not in text
    assert 'abc123' not in text
    assert 'my-bearer-token-xyz' not in text
    # The redaction marker must appear
    assert '[REDACTED]' in text


def test_log_does_not_redact_non_secret_fields(tmp_path):
    """L4: regression guard — common non-secret fields must not match."""
    from loguru import logger as _logger
    from src.loguru_config import setup_loguru
    log_file = tmp_path / 'test.log'
    setup_loguru(log_file=str(log_file), level='DEBUG')
    _logger.info('User login: username=alice')
    _logger.info('Cache hit: cache_key=session-12345')
    _logger.info('Partition: partition_key=tenant-foo')
    _logger.info('Connecting to port=8443')
    _logger.complete()
    text = log_file.read_text()
    assert 'username=alice' in text, "username should not be redacted"
    assert 'cache_key=session-12345' in text, "cache_key (not api_key) should not be redacted"
    assert 'partition_key=tenant-foo' in text, "partition_key should not be redacted"
    assert 'port=8443' in text, "port should not be redacted"
    assert '[REDACTED]' not in text, "no redaction marker should appear in this output"
