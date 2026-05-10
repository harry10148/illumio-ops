"""Tests for /api/workloads/accelerate route."""
from tests._helpers import _csrf


def _login(client):
    login = client.post(
        '/api/login',
        json={"username": "admin", "password": "testpass"},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
    )
    assert login.status_code == 200
    return _csrf(login)


def test_accelerate_rejects_empty_hrefs(client):
    csrf = _login(client)
    r = client.post(
        '/api/workloads/accelerate',
        json={"hrefs": [], "duration_minutes": 0},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf},
    )
    assert r.status_code == 200
    assert r.json["ok"] is False
    assert "no" in r.json["error"].lower() or "valid" in r.json["error"].lower()


def test_accelerate_filters_invalid_hrefs(client, monkeypatch):
    csrf = _login(client)
    captured = {}

    def fake(self, hrefs):
        captured["hrefs"] = list(hrefs)
        return len(hrefs), 0

    monkeypatch.setattr(
        "src.api_client.ApiClient.set_flow_reporting_frequency", fake
    )

    r = client.post(
        '/api/workloads/accelerate',
        json={
            "hrefs": [
                "/orgs/1/workloads/aaa",
                "/orgs/1/labels/99",        # invalid: not a workload href
                "",                          # invalid: empty
                "/orgs/1/workloads/bbb",
            ],
            "duration_minutes": 30,
        },
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf},
    )
    assert r.status_code == 200
    assert r.json["ok"] is True
    assert r.json["success"] == 2
    assert r.json["failed"] == 0
    assert r.json["skipped_invalid"] == 2
    assert captured["hrefs"] == ["/orgs/1/workloads/aaa", "/orgs/1/workloads/bbb"]


def test_accelerate_bubbles_partial_failure(client, monkeypatch):
    csrf = _login(client)
    monkeypatch.setattr(
        "src.api_client.ApiClient.set_flow_reporting_frequency",
        lambda self, hrefs: (3, 1),
    )

    r = client.post(
        '/api/workloads/accelerate',
        json={
            "hrefs": [f"/orgs/1/workloads/{i}" for i in range(4)],
            "duration_minutes": 0,
        },
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf},
    )
    assert r.status_code == 200
    assert r.json["ok"] is True
    assert r.json["success"] == 3
    assert r.json["failed"] == 1
    assert r.json["skipped_invalid"] == 0
