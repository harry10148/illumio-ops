"""Quarantine endpoint tests (split from test_gui_security.py for M9)."""
from src.i18n import get_messages, set_language


def _csrf(login_response) -> str:
    """Extract CSRF token from login response JSON (new synchronizer token pattern)."""
    return (login_response.get_json() or {}).get('csrf_token', '')


def test_quarantine_apply_rejects_non_workload_href(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    csrf_token = _csrf(login)

    response = client.post(
        '/api/quarantine/apply',
        json={"href": "/orgs/1/labels/99", "level": "Mild"},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf_token},
    )
    assert response.status_code == 200
    assert response.json["ok"] is False
    assert "workload" in response.json["error"].lower()


def test_quarantine_bulk_apply_skips_invalid_and_deduplicates(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    csrf_token = _csrf(login)

    monkeypatch.setattr("src.api_client.ApiClient.check_and_create_quarantine_labels", lambda self: {"Mild": "/orgs/1/labels/1"})
    monkeypatch.setattr("src.api_client.ApiClient.get_workload", lambda self, href: {"href": href, "labels": []})
    calls = []

    def fake_update(self, href, labels):
        calls.append((href, labels))
        return True

    monkeypatch.setattr("src.api_client.ApiClient.update_workload_labels", fake_update)

    response = client.post(
        '/api/quarantine/bulk_apply',
        json={"hrefs": ["/orgs/1/workloads/1", "/orgs/1/workloads/1", "/orgs/1/labels/99"], "level": "Mild"},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf_token},
    )
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["results"]["success"] == 1
    assert response.json["results"]["skipped_invalid"] == 1
    assert len(calls) == 1
    assert calls[0][0] == "/orgs/1/workloads/1"


def test_quarantine_translation_keys_present():
    set_language("zh_TW")
    messages = get_messages("zh_TW")
    assert messages["gui_q_title"]
    assert messages["gui_q_both"]
    assert messages["gui_q_invalid_target"]
    set_language("en")
