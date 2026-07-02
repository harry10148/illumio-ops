"""D2 sub-item 3: /api/pce-profiles must return 400 (not 500) on a non-numeric id."""
from tests._helpers import _csrf


def _login(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200
    return _csrf(login)


def test_pce_profiles_update_rejects_non_numeric_id(client):
    csrf = _login(client)
    res = client.post('/api/pce-profiles', json={
        "action": "update",
        "id": "not-an-id",
        "name": "x",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf})
    assert res.status_code == 400
    assert res.json["ok"] is False


def test_pce_profiles_activate_rejects_non_numeric_id(client):
    csrf = _login(client)
    res = client.post('/api/pce-profiles', json={
        "action": "activate",
        "id": "not-an-id",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf})
    assert res.status_code == 400
    assert res.json["ok"] is False


def test_pce_profiles_delete_rejects_non_numeric_id(client):
    csrf = _login(client)
    res = client.post('/api/pce-profiles', json={
        "action": "delete",
        "id": "not-an-id",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf})
    assert res.status_code == 400
    assert res.json["ok"] is False


def test_pce_profiles_update_accepts_numeric_string_id(client):
    """Sanity: a numeric id (as a string, e.g. from a JS form) still works."""
    csrf = _login(client)
    added = client.post('/api/pce-profiles', json={
        "action": "add",
        "name": "lab",
        "url": "https://pce.lab.test:8443",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf})
    assert added.status_code == 200
    pid = added.json["profile"]["id"]

    res = client.post('/api/pce-profiles', json={
        "action": "update",
        "id": str(pid),
        "name": "lab-renamed",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf})
    assert res.status_code == 200
    assert res.json["ok"] is True
