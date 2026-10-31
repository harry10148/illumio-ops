"""SIEM routes (P7 Task 7): the HEC token never leaves, a kept token never follows a changed destination, removing a
source forgets its cursor, the DLQ list/resend/purge/export, and a test line that needs no save."""
import json

from illumio_ops.services.siem import tester
from illumio_ops.store import siem as store
from tests_v6.services.siem.conftest import NOW, FakeTransport

from .conftest import LOCAL, csrf, login, post

DEST = "a" * 32


def dest(**kw):
    base = {"id": DEST, "name": "splunk", "enabled": True, "transport": "hec", "format": "json",
            "host": "splunk.example", "port": 8088, "framing": "lf", "verify_tls": True, "hec_token": "HEC-SECRET",
            "batch_size": 100, "max_retries": 10, "sources": ["audit", "findings"], "new_connection_decisions": [], "new_connection_internal_only": True,
            "mask_pii": False}
    base.update(kw)
    return base


def view(client):
    return client.get("/api/siem/settings", environ_overrides=LOCAL).get_json()["data"]


def put(client, siem, revision=None):
    rev = view(client)["revision"] if revision is None else revision
    return client.open("/api/siem/settings", method="PUT", json={"revision": rev, "siem": siem},
                       environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})


def configured(client, **kw):
    s = view(client)["siem"]
    s.update(enabled=True, destinations=[dest(**kw)])
    r = put(client, s)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


def test_the_hec_token_never_leaves(client):
    login(client)
    data = configured(client)
    assert data["siem"]["destinations"][0]["hec_token"] == "********"
    assert "HEC-SECRET" not in json.dumps(view(client))
    assert "HEC-SECRET" not in client.get("/api/siem/status", environ_overrides=LOCAL).get_data(as_text=True)


def test_the_mask_keeps_the_token_and_a_new_host_needs_it_again(client, ctx):
    login(client)
    s = configured(client)["siem"]
    s["destinations"][0]["name"] = "renamed"
    assert put(client, s).status_code == 200
    assert ctx.settings.current().siem.destinations[0].hec_token == "HEC-SECRET"
    s = view(client)["siem"]
    s["destinations"][0]["host"] = "evil.example"
    r = put(client, s)
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "credentials_required"
    assert ctx.settings.current().siem.destinations[0].host == "splunk.example"


def test_an_incomplete_destination_is_refused_with_its_field(client):
    login(client)
    s = view(client)["siem"]
    s.update(enabled=True, destinations=[dest(hec_token="", host="")])
    r = put(client, s)
    assert r.status_code == 400 and r.get_json()["error"]["field"].startswith("siem.destinations.0")


def test_a_source_taken_away_forgets_its_place(client, ctx):
    login(client)
    configured(client)
    with ctx.db() as conn:
        for source in ("audit", "alerts", "detections"):
            store.start_cursor(conn, DEST, source, pce_url="", org_id="", last_id=5)
    s = view(client)["siem"]
    s["destinations"][0]["sources"] = ["audit"]
    assert put(client, s).status_code == 200
    with ctx.db() as conn:
        assert sorted(src for (_, src) in store.cursors(conn)) == ["audit"]
    s["destinations"] = []
    assert put(client, s).status_code == 200
    with ctx.db() as conn:
        assert store.cursors(conn) == {}


def test_a_test_line_uses_the_saved_token_without_a_save(client, monkeypatch):
    login(client)
    configured(client)
    seen = []
    monkeypatch.setattr(tester, "transport_for", lambda d: seen.append(d.hec_token) or FakeTransport())
    d = view(client)["siem"]["destinations"][0]
    d["name"] = "unsaved"
    r = post(client, "/api/siem/test", {"destination": d})
    assert r.status_code == 200 and r.get_json()["data"]["ok"] and seen == ["HEC-SECRET"]


def test_dlq_list_resend_purge_and_export(client, ctx, monkeypatch):
    from illumio_ops.services.siem import dlq
    from illumio_ops.services.siem.dispatch import sent_as
    from illumio_ops.settings.schema import SiemDestination
    login(client)
    configured(client)
    made = sent_as(SiemDestination.model_validate(dest()))
    with ctx.db() as conn:
        for i in range(3):
            store.quarantine(conn, destination_id=DEST, source="audit", record_id=i, external_id=f"audit:{i}",
                             event_time=NOW, payload=f"line {i}", sent_as=made, error="refused: 400", attempts=1,
                             at=NOW)
    page = client.get(f"/api/siem/dlq?destination_id={DEST}&limit=2", environ_overrides=LOCAL).get_json()["data"]
    assert page["total"] == 3 and len(page["items"]) == 2 and page["items"][0]["destination"] == "splunk"
    t = FakeTransport()
    monkeypatch.setattr(dlq, "transport_for", lambda d: t)
    first = page["items"][0]["id"]
    r = post(client, "/api/siem/dlq/resend", {"ids": [first]}).get_json()["data"]
    assert r["sent"] == 1 and r["remaining"] == 2 and len(t.lines) == 1
    exported = client.get(f"/siem/dlq/export?destination_id={DEST}", environ_overrides=LOCAL)
    assert exported.status_code == 200 and "attachment" in exported.headers["Content-Disposition"]
    lines = exported.get_data(as_text=True).splitlines()
    assert len(lines) == 2 and "HEC-SECRET" not in exported.get_data(as_text=True)
    assert post(client, "/api/siem/dlq/purge", {"destination_id": DEST}).get_json()["data"]["deleted"] == 2


def test_the_export_needs_a_session(client):
    r = client.get("/siem/dlq/export", environ_overrides=LOCAL)
    assert r.status_code == 401
