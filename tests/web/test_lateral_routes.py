"""Lateral movement API (P6c): signed in, CSRF on POST, an all-empty deny rule refused, the previous PCE and a
lightweight simulation without a computed graph refused as conflicts, a failed pull said."""
import pytest

from illumio_ops.services import lateral_view
from illumio_ops.services.collect.guard import BindingMismatch
from illumio_ops.services.ondemand import OnDemandFailed

from .conftest import LOCAL, login, post

PROPOSAL = {"src": {"hrefs": ["/orgs/1/workloads/a"]}, "dst": {"hrefs": ["/orgs/1/workloads/b"]},
            "ports": [{"port": 3389, "proto": 6}]}


@pytest.fixture(autouse=True)
def _no_held():
    lateral_view.drop()
    yield
    lateral_view.drop()


def test_view_signed_in_only(client):
    assert client.get("/api/lateral", environ_overrides=LOCAL).status_code == 401
    login(client)
    r = client.get("/api/lateral", environ_overrides=LOCAL)
    assert r.status_code == 200 and r.get_json()["data"]["state"] == "not_computed"


def test_compute_outside_lightweight_refused(client):
    login(client)
    assert post(client, "/api/lateral/compute", {"days": 7}).status_code == 400
    assert post(client, "/api/lateral/compute", {"days": 5}).status_code == 400


def test_simulate(client):
    login(client)
    r = post(client, "/api/lateral/simulate", {"proposal": PROPOSAL})
    assert r.status_code == 200 and r.get_json()["data"]["simulation"]["blocked_flows"] == 0


def test_all_empty_proposal_refused(client):
    login(client)
    r = post(client, "/api/lateral/simulate", {"proposal": {"src": {}, "dst": {}}})
    assert r.status_code == 400


def test_simulate_needs_csrf(client):
    login(client)
    r = client.post("/api/lateral/simulate", json={"proposal": PROPOSAL}, environ_overrides=LOCAL)
    assert r.status_code in (400, 403)


@pytest.mark.parametrize(("exc", "status", "code"), [
    (BindingMismatch("x"), 409, "pce_switched"), (lateral_view.NotComputed(), 409, "not_computed"),
    (OnDemandFailed("the PCE timed out"), 502, "pull_failed")])
def test_failures_mapped(client, monkeypatch, exc, status, code):
    def boom(*a, **kw):
        raise exc
    monkeypatch.setattr(lateral_view, "simulate", boom)
    monkeypatch.setattr(lateral_view, "view", boom)
    login(client)
    r = post(client, "/api/lateral/simulate", {"proposal": PROPOSAL})
    assert r.status_code == status and r.get_json()["error"]["code"] == code
    if code == "pce_switched":
        assert client.get("/api/lateral", environ_overrides=LOCAL).status_code == 409
