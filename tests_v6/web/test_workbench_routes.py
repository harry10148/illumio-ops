"""Workbench API (P6a): segments, dimension tops, an alert's evidence; signed in, CSRF on POST."""
from datetime import UTC, datetime

from illumio_ops.domain.values import DataOrigin
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.services.reports.test_findings import flow

from .conftest import LOCAL, login, post

REQ = {"mode": "flows", "start": "2026-10-21T00:00:00Z", "end": "2026-10-27T00:00:00Z", "view": "detail"}


def _seed(ctx):
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"].update(mode="full"))
    with ctx.flows().connect() as conn:
        upsert_flows(conn, [flow(src="a", dst="db"), flow(src="b", dst="db")], origin=DataOrigin.INGEST,
                     now=datetime(2026, 10, 27, tzinfo=UTC))


def test_run_and_dimension(client, ctx):
    login(client)
    _seed(ctx)
    r = post(client, "/api/workbench/run", {"request": REQ})
    assert r.status_code == 200 and len(r.get_json()["data"]["result"]["detail"]) == 2
    d = post(client, "/api/workbench/dimension", {"request": REQ, "dimension": "src_host"})
    assert d.status_code == 200 and len(d.get_json()["data"]["rows"]) == 2


def test_dimension_of_the_other_source_refused(client, ctx):
    login(client)
    r = post(client, "/api/workbench/dimension", {"request": REQ, "dimension": "event_type"})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "invalid_input"


def test_period_over_30_days_refused(client):
    login(client)
    r = post(client, "/api/workbench/run", {"request": {**REQ, "start": "2026-09-01T00:00:00Z"}})
    assert r.status_code == 400


def test_from_alert_not_found(client):
    login(client)
    assert client.get("/api/workbench/from-alert/999", environ_overrides=LOCAL).status_code == 404


def test_meta_and_login(client):
    assert client.get("/api/workbench/meta", environ_overrides=LOCAL).status_code == 401
    login(client)
    assert client.get("/api/workbench/meta", environ_overrides=LOCAL).get_json()["data"]["max_days"] == 30


def test_run_needs_csrf(client):
    login(client)
    r = client.post("/api/workbench/run", json={"request": REQ}, environ_overrides=LOCAL)
    assert r.status_code in (400, 403)


def test_pce_switch_during_read_is_409(client, ctx, monkeypatch):
    """Final review #1: an answer read across a PCE switch is refused with its own code, not a 500."""
    from illumio_ops.services import workbench
    from illumio_ops.store.flowdb.db import StaleGeneration

    def stale(*a, **k):
        raise StaleGeneration("switched")
    login(client)
    monkeypatch.setattr(workbench, "run", stale)
    monkeypatch.setattr(workbench, "dimension", stale)
    for path, body in (("/api/workbench/run", {"request": REQ}),
                       ("/api/workbench/dimension", {"request": REQ, "dimension": "src_host"})):
        r = post(client, path, body)
        assert r.status_code == 409 and r.get_json()["error"]["code"] == "pce_switched"


def test_home_focus(client, ctx):
    """P6b: the focus list as stored; before the first hourly run it says so."""
    assert client.get("/api/home/focus", environ_overrides=LOCAL).status_code == 401
    login(client)
    data = client.get("/api/home/focus", environ_overrides=LOCAL).get_json()["data"]
    assert data["computed_at"] is None and data["items"] == []
