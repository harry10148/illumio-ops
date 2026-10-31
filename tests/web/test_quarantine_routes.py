"""Quarantine API (P6d): signed in, CSRF on POST, no write key and no policy refused as conflicts, a PCE failure
said, the batch bounded, the history read back."""
import pytest

from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.services import quarantine

from .conftest import LOCAL, login, post

WL = "/orgs/1/workloads/w1"


def test_signed_in_and_csrf(client):
    assert client.get("/api/quarantine/history", environ_overrides=LOCAL).status_code == 401
    login(client)
    r = client.post("/api/quarantine/apply", json={"keys": [WL], "level": "Severe"}, environ_overrides=LOCAL)
    assert r.status_code in (400, 403)
    h = client.get("/api/quarantine/history", environ_overrides=LOCAL)
    assert h.status_code == 200 and h.get_json()["data"]["actions"] == []


def test_no_write_key_is_a_conflict(client):
    login(client)
    r = post(client, "/api/quarantine/remove", {"keys": [WL]})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "no_write_key"


@pytest.mark.parametrize(("exc", "status", "code"), [
    (quarantine.NoPolicy(), 409, "no_policy"), (PceCollectionIncomplete("/labels", 0, "HTTP 503"), 502, "pce_failed"),
    (ValueError("bad"), 400, "invalid_input")])
def test_failures_mapped(client, monkeypatch, exc, status, code):
    def boom(*a, **kw):
        raise exc
    monkeypatch.setattr(quarantine, "apply", boom)
    login(client)
    r = post(client, "/api/quarantine/apply", {"keys": [WL], "level": "Severe"})
    assert r.status_code == status and r.get_json()["error"]["code"] == code


def test_batch_bounded(client):
    login(client)
    r = post(client, "/api/quarantine/preview", {"keys": [WL] * 51, "level": "Severe"})
    assert r.status_code == 400
    assert post(client, "/api/quarantine/preview", {"keys": [], "level": "Severe"}).status_code == 400


def test_pce_not_configured_is_not_a_missing_write_key(client):
    login(client)
    r = post(client, "/api/quarantine/preview", {"keys": [WL], "level": "Severe"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "pce_not_configured"
