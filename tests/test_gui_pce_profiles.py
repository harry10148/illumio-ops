"""D2 子項 3：/api/pce-profiles 收到非數字 id 必須回 400（而非 500）。"""
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
    """Sanity：數字 id 以字串傳入（例如 JS 表單）仍然可用。"""
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
