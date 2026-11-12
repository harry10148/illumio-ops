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


# ── what is quarantined now (purpose-led UI spec §6.4) ──

def test_the_hosts_in_quarantine_now_with_who_put_them_there(client, ctx):
    from datetime import UTC, datetime

    from illumio_ops.store import quarantine_actions
    from illumio_ops.store.flowdb import labels as label_store
    from illumio_ops.store.flowdb import workloads
    from tests.e2e.test_fleet_e2e import _wl
    now = datetime.now(UTC)
    w = "/orgs/1/workloads/"
    with ctx.flows().connect() as conn:
        severe = label_store.label_set_id(conn, (("Quarantine", "Severe"), ("env", "Prod")))
        mild = label_store.label_set_id(conn, (("Quarantine", "Mild"),))
        plain = label_store.label_set_id(conn, (("env", "Prod"),))
        workloads.replace_inventory(conn, [_wl(w + "a", "a", "selective", severe, now), _wl(w + "b", "b", "idle", mild, now),
                                           _wl(w + "c", "c", "selective", plain, now)])
        conn.commit()
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        for result in ("failed", "ok"):
            quarantine_actions.add(conn, pce_url=pce.url, org_id=pce.org_id, at=now, by="illumio", action="apply",
                                   workload_href=w + "a", hostname="a", level="Severe", previous_level=None,
                                   original_labels=[], result=result, detail=None)
        conn.commit()
    login(client)
    data = client.get("/api/quarantine/current", environ_overrides=LOCAL).get_json()["data"]
    assert data["write_key"] is False  # the list needs no write key
    got = {i["key"]: i for i in data["items"]}
    assert set(got) == {w + "a", w + "b"}
    assert (got[w + "a"]["level"], got[w + "a"]["applied_by"], got[w + "a"]["no_enforcement"]) == ("Severe", "illumio", False)
    assert got[w + "a"]["applied_at"] is not None and got[w + "a"]["name"] == "a"
    # the label is on it but this tool has no record of putting it there; Idle: the label isolates nothing
    assert (got[w + "b"]["applied_at"], got[w + "b"]["applied_by"], got[w + "b"]["no_enforcement"]) == (None, None, True)
    # this tool released the host since, and the label is on it again: someone else put it there
    with ctx.db() as conn:
        quarantine_actions.add(conn, pce_url=pce.url, org_id=pce.org_id, at=now, by="illumio", action="remove",
                               workload_href=w + "a", hostname="a", level=None, previous_level="Severe",
                               original_labels=[], result="ok", detail=None)
        conn.commit()
    again = {i["key"]: i for i in client.get("/api/quarantine/current", environ_overrides=LOCAL).get_json()["data"]["items"]}
    assert (again[w + "a"]["applied_at"], again[w + "a"]["applied_by"]) == (None, None)
