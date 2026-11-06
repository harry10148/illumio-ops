"""SIEM routes (P7 Task 7): the HEC token never leaves, a kept token never follows a changed destination, removing a
source forgets its cursor, the DLQ list/resend/purge/export, and a test line that needs no save."""
import json

from illumio_ops.services.siem import tester
from illumio_ops.store import siem as store
from tests.services.siem.conftest import NOW, FakeTransport

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


def test_turning_certificate_verification_off_needs_a_confirmation(client, ctx):
    login(client)
    s = configured(client)["siem"]
    s["destinations"][0].update(verify_tls=False, hec_token="HEC-SECRET")  # a saved token follows no such change
    r = put(client, s)
    assert r.status_code == 409
    err = r.get_json()["error"]
    assert err["code"] == "tls_unverified" and err["field"] == "siem.destinations.0.verify_tls"
    assert err["params"] == {"names": "splunk"}
    assert ctx.settings.current().siem.destinations[0].verify_tls is True
    r = client.open("/api/siem/settings", method="PUT",
                    json={"revision": view(client)["revision"], "siem": s, "confirm_tls_unverified": True},
                    environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})
    assert r.status_code == 200, r.get_json()
    assert ctx.settings.current().siem.destinations[0].verify_tls is False
    # Already confirmed: an unrelated change saves without asking again.
    s = view(client)["siem"]
    s["destinations"][0]["name"] = "renamed"
    assert put(client, s).status_code == 200


def test_a_new_unverified_destination_and_a_switch_to_tls_ask_too_but_plain_syslog_does_not(client):
    login(client)
    s = view(client)["siem"]
    s.update(enabled=True, destinations=[dest(transport="tls", hec_token="", port=6514, verify_tls=False)])
    assert put(client, s).status_code == 409
    s["destinations"] = [dest(transport="tcp", hec_token="", port=514, verify_tls=False)]
    assert put(client, s).status_code == 200  # verification means nothing to plain TCP
    s = view(client)["siem"]
    s["destinations"][0].update(transport="tls", port=6514)
    r = put(client, s)
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "tls_unverified"


def test_the_status_says_which_destinations_do_not_verify(client):
    login(client)
    s = configured(client)["siem"]
    st = client.get("/api/siem/status", environ_overrides=LOCAL).get_json()["data"]
    assert st["destinations"][0]["tls_unverified"] is False
    s["destinations"][0].update(verify_tls=False, hec_token="HEC-SECRET")
    r = client.open("/api/siem/settings", method="PUT",
                    json={"revision": view(client)["revision"], "siem": s, "confirm_tls_unverified": True},
                    environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})
    assert r.status_code == 200
    st = client.get("/api/siem/status", environ_overrides=LOCAL).get_json()["data"]
    assert st["destinations"][0]["tls_unverified"] is True


def _fill(ctx, rows):
    from datetime import timedelta
    with ctx.db() as conn:
        for i, (error, days, payload) in enumerate(rows):
            store.quarantine(conn, destination_id=DEST, source="audit", record_id=i, external_id=f"audit:{i}",
                             event_time=NOW, payload=payload, sent_as="[]", error=error, attempts=2,
                             at=NOW - timedelta(days=days))
        return [d.id for d in store.dlq_after(conn, destination_id=DEST, after_id=0, limit=100)]


def test_one_dlq_line_in_full(client, ctx):
    login(client)
    configured(client)
    long_line = "x" * 5000 + "END"
    [dead] = _fill(ctx, [("refused: 400", 0, long_line)])
    page = client.get("/api/siem/dlq", environ_overrides=LOCAL).get_json()["data"]
    assert len(page["items"][0]["preview"]) == 300
    r = client.get(f"/api/siem/dlq/{dead}", environ_overrides=LOCAL)
    assert r.status_code == 200
    d = r.get_json()["data"]
    assert d["payload"] == long_line and d["destination"] == "splunk" and d["attempts"] == 2
    assert d["error"] == "refused: 400" and d["external_id"] == "audit:0"
    r = client.get(f"/api/siem/dlq/{dead + 1}", environ_overrides=LOCAL)
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"


def test_the_dlq_list_and_export_by_error(client, ctx):
    login(client)
    configured(client)
    _fill(ctx, [("refused: 400", 0, "a"), ("format: x", 0, "b"), ("refused: 413", 0, "c")])
    page = client.get("/api/siem/dlq?error=refused", environ_overrides=LOCAL).get_json()["data"]
    assert page["total"] == 2 and {x["error"] for x in page["items"]} == {"refused: 400", "refused: 413"}
    out = client.get(f"/siem/dlq/export?destination_id={DEST}&error=format", environ_overrides=LOCAL)
    assert [json.loads(x)["payload"] for x in out.get_data(as_text=True).splitlines()] == ["b"]
    assert client.get("/siem/dlq/export?error=" + "x" * 201, environ_overrides=LOCAL).status_code == 400


def test_purge_older_than_days(client, ctx):
    login(client)
    configured(client)
    _fill(ctx, [("e", 40, "old"), ("e", 1, "new")])
    r = post(client, "/api/siem/dlq/purge", {"destination_id": DEST, "older_than_days": 30})
    assert r.status_code == 200 and r.get_json()["data"]["deleted"] == 1
    with ctx.db() as conn:
        [left] = store.dlq_page(conn, destination_id=DEST, limit=5, offset=0)
    assert left.payload == "new"
    r = post(client, "/api/siem/dlq/purge", {"ids": [left.id], "older_than_days": 30})
    assert r.status_code == 400  # one or the other


def test_the_dlq_retention_is_a_setting_the_page_keeps(client, ctx):
    login(client)
    s = configured(client)["siem"]
    assert s["dlq_retention_days"] == 30
    s["dlq_retention_days"] = 7
    assert put(client, s).status_code == 200
    assert ctx.settings.current().siem.dlq_retention_days == 7
    s = view(client)["siem"]
    s["destinations"][0]["name"] = "renamed"
    assert put(client, s).status_code == 200
    assert ctx.settings.current().siem.dlq_retention_days == 7
    s["dlq_retention_days"] = -1
    assert put(client, s).status_code == 400
