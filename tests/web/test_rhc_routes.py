"""Rule Hit Count settings (spec §6.5 RHC, P5c-2): the status, and turning it on only after the person confirms."""
from illumio_ops.domain.values import RhcState
from illumio_ops.services.rhc import EnableResult, RhcStatus
from illumio_ops.web.routes import rhc as rhc_routes

from .conftest import LOCAL, login, post


def _status(state=RhcState.DISABLED, reason=None):
    return RhcStatus(state=state, pce_report=False, ven_scopes=False, reason_key=reason, detail=None, write_key=True,
                     saas=False)


def test_status(client, monkeypatch):
    login(client)
    monkeypatch.setattr(rhc_routes, "rhc_status", lambda ctx: _status())
    r = client.get("/api/rhc", environ_overrides=LOCAL)
    assert r.status_code == 200 and r.get_json()["data"]["state"] == "disabled"


def test_enable_requires_confirmation(client, monkeypatch):
    login(client)
    called = []
    monkeypatch.setattr(rhc_routes, "enable_rhc", lambda ctx: called.append(1))
    r = post(client, "/api/rhc/enable", {"confirm": False})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "confirm_required" and called == []


def test_enable_rechecks_status(client, monkeypatch):
    login(client)
    monkeypatch.setattr(rhc_routes, "enable_rhc", lambda ctx: EnableResult(
        ok=True, steps_done=["pce_report_template"], skipped=[], error_key=None, detail=None))
    monkeypatch.setattr(rhc_routes, "rhc_status", lambda ctx: _status(RhcState.ENABLED))
    data = post(client, "/api/rhc/enable", {"confirm": True}).get_json()["data"]
    assert data["result"]["steps_done"] == ["pce_report_template"] and data["status"]["state"] == "enabled"


def test_enable_failure_is_not_success(client, monkeypatch):
    """A refusal comes back as the result (with its reason), not as a 2xx that reads as done."""
    login(client)
    monkeypatch.setattr(rhc_routes, "enable_rhc", lambda ctx: EnableResult(
        ok=False, steps_done=[], skipped=[], error_key="rhc_err_refused_saas", detail="HTTP 403"))
    monkeypatch.setattr(rhc_routes, "rhc_status", lambda ctx: _status())
    data = post(client, "/api/rhc/enable", {"confirm": True}).get_json()["data"]
    assert data["result"]["ok"] is False and data["result"]["error_key"] == "rhc_err_refused_saas"


def test_enable_needs_csrf(client):
    login(client)
    r = client.post("/api/rhc/enable", json={"confirm": True}, environ_overrides=LOCAL)
    assert r.status_code in (400, 403)


def test_rhc_requires_login(client):
    assert client.get("/api/rhc", environ_overrides=LOCAL).status_code == 401
