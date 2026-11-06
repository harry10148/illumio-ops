"""VEN fleet API: signed in, CSRF on POST, the list filters checked, no write key a conflict, a PCE failure said, a
label selection larger than a batch refused with its size, the batch bounded, the record read back."""
import pytest

from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.services import fleet_write

from .conftest import LOCAL, login, post

WL = "/orgs/1/workloads/w1"


def test_signed_in_and_csrf(client):
    assert client.get("/api/fleet/overview", environ_overrides=LOCAL).status_code == 401
    login(client)
    r = client.post("/api/fleet/traffic-rate/apply", json={"keys": [WL]}, environ_overrides=LOCAL)
    assert r.status_code in (400, 403)
    o = client.get("/api/fleet/overview", environ_overrides=LOCAL)
    assert o.status_code == 200 and o.get_json()["data"]["total"] == 0
    h = client.get("/api/fleet/hosts?mode=full&env=Prod&q=web", environ_overrides=LOCAL)
    assert h.status_code == 200 and h.get_json()["data"]["hosts"] == []
    a = client.get("/api/fleet/actions", environ_overrides=LOCAL)
    assert a.status_code == 200 and a.get_json()["data"]["actions"] == []


def test_list_filter_checked(client):
    login(client)
    r = client.get("/api/fleet/hosts?online=sometimes", environ_overrides=LOCAL)
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "invalid_input"


def test_no_write_key_is_a_conflict(client):
    login(client)
    r = post(client, "/api/fleet/enforcement/apply", {"target": "full", "hosts": [{"key": WL, "from_mode": "idle"}]})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "no_write_key"
    r = post(client, "/api/fleet/traffic-rate/apply", {"keys": [WL]})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "no_write_key"


@pytest.mark.parametrize(("exc", "status", "code"), [
    (PceCollectionIncomplete("/x", 0, "HTTP 503"), 502, "pce_failed"), (ValueError("bad"), 400, "invalid_input"),
    (fleet_write.SelectionTooLarge(73), 400, "too_many")])
def test_failures_mapped(client, monkeypatch, exc, status, code):
    def boom(*a, **kw):
        raise exc
    monkeypatch.setattr(fleet_write, "preview", boom)
    login(client)
    r = post(client, "/api/fleet/enforcement/preview", {"target": "full", "keys": [WL]})
    assert r.status_code == status and r.get_json()["error"]["code"] == code
    if code == "too_many":
        assert r.get_json()["error"]["params"] == {"n": "73", "max": "50"}


def test_hosts_or_labels_and_bounded(client):
    login(client)
    assert post(client, "/api/fleet/enforcement/preview", {"target": "full"}).status_code == 400
    both = {"target": "full", "keys": [WL], "labels": [{"key": "env", "value": "Prod"}]}
    assert post(client, "/api/fleet/enforcement/preview", both).status_code == 400
    assert post(client, "/api/fleet/traffic-rate/check", {"keys": [WL] * 51}).status_code == 400
    assert post(client, "/api/fleet/enforcement/apply", {"target": "full", "hosts": []}).status_code == 400


def test_label_preview_resolves_on_the_server(client, monkeypatch):
    seen = {}
    def preview(ctx, keys, target):
        seen["keys"] = keys
        raise ValueError("stop here")
    monkeypatch.setattr(fleet_write, "select", lambda ctx, picks: seen.setdefault("picks", picks) and [WL])
    monkeypatch.setattr(fleet_write, "preview", preview)
    login(client)
    post(client, "/api/fleet/enforcement/preview", {"target": "full", "labels": [{"key": "env", "value": "Prod"}]})
    assert seen["keys"] == [WL] and seen["picks"][0].value == "Prod"
