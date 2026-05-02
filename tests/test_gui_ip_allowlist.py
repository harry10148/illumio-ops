"""api/security + IP allowlist tests (split from test_gui_security.py for M9)."""
import pytest


def _csrf(login_response) -> str:
    """Extract CSRF token from login response JSON (new synchronizer token pattern)."""
    return (login_response.get_json() or {}).get('csrf_token', '')


def test_ip_whitelist(app_persistent):
    client = app_persistent.test_client()

    # Mock remote_addr by directly calling request context
    from src.gui import _RstDrop
    import pytest
    with app_persistent.test_request_context('/', environ_base={'REMOTE_ADDR': '10.0.0.1'}):
        # Should raise _RstDrop for blocked IP
        with pytest.raises(_RstDrop):
            app_persistent.preprocess_request()

    # Should allow 127.0.0.1 (in whitelist)
    with app_persistent.test_request_context('/', environ_base={'REMOTE_ADDR': '127.0.0.1'}):
        response = app_persistent.full_dispatch_request()
        # Returns 302 because unauthenticated, but NOT 403
        assert response.status_code == 302

    # Should allow CIDR 192.168.1.50
    with app_persistent.test_request_context('/', environ_base={'REMOTE_ADDR': '192.168.1.50'}):
        response = app_persistent.full_dispatch_request()
        assert response.status_code == 302


def test_ip_whitelist_allows_single_ipv4_when_remote_is_ipv4_mapped_ipv6(app_persistent):
    from src.gui import _RstDrop

    with app_persistent.test_request_context('/', environ_base={'REMOTE_ADDR': '::ffff:127.0.0.1'}):
        response = app_persistent.full_dispatch_request()
        assert response.status_code == 302

    with app_persistent.test_request_context('/', environ_base={'REMOTE_ADDR': '::ffff:192.168.1.99'}):
        response = app_persistent.full_dispatch_request()
        assert response.status_code == 302

    with app_persistent.test_request_context('/', environ_base={'REMOTE_ADDR': '::ffff:10.0.0.1'}):
        with pytest.raises(_RstDrop):
            app_persistent.preprocess_request()

def test_api_security_endpoints(app_persistent):
    client = app_persistent.test_client()
    # Authenticate first
    res_login = client.post('/api/login', json={"username": "admin", "password": "testpass"}, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})

    # Get CSRF token from cookies
    csrf_token = _csrf(res_login)

    res = client.get('/api/security', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert res.status_code == 200
    assert res.json['username'] == 'admin'
    assert '127.0.0.1' in res.json['allowed_ips']

    # Update allowed IPs and password
    res = client.post('/api/security', json={
        "username": "admin2",
        "old_password": "testpass",
        "new_password": "newpassword123",
        "allowed_ips": ["10.0.0.0/8", "127.0.0.1", "192.168.1.0/24"]
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert res.status_code == 200
    assert res.json['ok'] is True

    # Re-login with new password
    client.post('/logout', environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                headers={'X-CSRF-Token': csrf_token})
    res = client.post('/api/login', json={"username": "admin2", "password": "newpassword123"}, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert res.status_code == 200
    assert res.json['ok'] is True


def test_api_security_save_does_not_require_old_password(app_persistent):
    """An authenticated session is sufficient to change credentials and
    settings; old_password is no longer requested or verified."""
    client = app_persistent.test_client()
    res_login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(res_login)

    # No-op save (nothing changed) — still 200.
    res = client.post('/api/security', json={
        "username": "admin",
        "allowed_ips": ["127.0.0.1", "192.168.1.0/24"],
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
       headers={'X-CSRF-Token': csrf_token})
    assert res.status_code == 200
    assert res.json["ok"] is True

    # Password change without old_password — also succeeds.
    res = client.post('/api/security', json={
        "new_password": "freshPassword42",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
       headers={'X-CSRF-Token': csrf_token})
    assert res.status_code == 200
    assert res.json["ok"] is True


def test_api_security_rejects_invalid_allowlist(client):
    res_login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})

    csrf_token = _csrf(res_login)

    res = client.post('/api/security', json={
        "old_password": "testpass",
        "allowed_ips": ["127.0.0.1", "localhost"]
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})

    assert res.status_code == 400
    assert res.json["ok"] is False
    assert "localhost" in res.json["error"]


def test_api_security_normalizes_single_ip_allowlist_entries(app_persistent):
    client = app_persistent.test_client()
    res_login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(res_login)

    res = client.post('/api/security', json={
        "old_password": "testpass",
        "allowed_ips": ["::ffff:192.168.1.1", "127.0.0.1/32", "::1"]
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})

    assert res.status_code == 200
    refreshed = client.get('/api/security', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert refreshed.status_code == 200
    assert "192.168.1.1" in refreshed.json["allowed_ips"]
    assert "127.0.0.1/32" in refreshed.json["allowed_ips"]
    assert "::1" in refreshed.json["allowed_ips"]
