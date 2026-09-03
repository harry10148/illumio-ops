"""Phase 3A Task 5 — POST /api/policy/explain route contract."""
from __future__ import annotations

import pytest

from tests._helpers import _csrf

HDR = {"REMOTE_ADDR": "127.0.0.1"}


@pytest.fixture
def client(app_persistent):
    c = app_persistent.test_client()
    login = c.post("/api/login", json={"username": "admin", "password": "testpass"}, environ_overrides=HDR)
    assert login.status_code == 200
    return c, _csrf(login)


def _post(client, body, csrf=None):
    c, token = client
    return c.post("/api/policy/explain", json=body, environ_overrides=HDR,
                  headers={"X-CSRF-Token": csrf or token})


def test_validation(client):
    assert _post(client, {}).status_code == 400
    assert _post(client, {"src": {"ip": "10.0.0.1"}, "dst": {}, "port": 22}).status_code == 400   # no proto
    assert _post(client, {"src": {"ip": "10.0.0.1"}, "dst": {}, "port": 22, "proto": "TCP",
                          "basis": "live"}).status_code == 400
    assert _post(client, {"src": "x", "dst": {}, "port": 22, "proto": 6}).status_code == 400


def test_success_passes_through_explain_flow(client, monkeypatch):
    seen = {}

    def fake(api, *, src, dst, port, proto, basis):
        seen.update(src=src, dst=dst, port=port, proto=proto, basis=basis)
        return {"basis": basis, "source": "pce_rule_search", "allow": [{"rule_href": "/r"}], "deny": [],
                "override_deny": [], "pce_status": 200, "pce_error": None}

    monkeypatch.setattr("src.gui.routes.policy.explain_flow", fake)
    monkeypatch.setattr("src.api_client.ApiClient.__enter__", lambda self: self)
    monkeypatch.setattr("src.api_client.ApiClient.__exit__", lambda self, *a: False)
    r = _post(client, {"src": {"href": "/orgs/1/workloads/a"}, "dst": {"ip": "10.1.2.20"},
                       "port": "22", "proto": "TCP", "basis": "draft"})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["ok"] is True and body["allow"][0]["rule_href"] == "/r"
    assert seen == {"src": {"href": "/orgs/1/workloads/a"}, "dst": {"ip": "10.1.2.20"},
                    "port": 22, "proto": 6, "basis": "draft"}


def test_pce_error_maps_to_502(client, monkeypatch):
    monkeypatch.setattr("src.gui.routes.policy.explain_flow",
                        lambda api, **kw: {"source": "pce_rule_search", "allow": [], "deny": [], "override_deny": [],
                                           "pce_status": 406, "pce_error": [{"token": "input_validation_error"}]})
    monkeypatch.setattr("src.api_client.ApiClient.__enter__", lambda self: self)
    monkeypatch.setattr("src.api_client.ApiClient.__exit__", lambda self, *a: False)
    r = _post(client, {"src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"}, "port": 22, "proto": 6})
    assert r.status_code == 502
    assert r.get_json()["ok"] is False and r.get_json()["code"] == "pce_error"


def test_csrf_required(client):
    c, _ = client
    r = c.post("/api/policy/explain", json={"src": {"ip": "10.0.0.1"}, "dst": {}, "port": 22, "proto": 6},
               environ_overrides=HDR)
    assert r.status_code == 400 and r.get_json().get("code") == "csrf_error"
