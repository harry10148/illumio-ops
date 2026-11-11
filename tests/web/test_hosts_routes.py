"""Host profile API (P6b): signed in, CSRF on POST, a bad key refused without echoing it."""
from tests.services.analysis.test_tamper import HOST, _ctx

from .conftest import LOCAL, login, post


def test_profile_and_notes(client, ctx, tmp_path):
    seeded = _ctx(tmp_path / "seed")
    with seeded.flows().connect() as src, ctx.flows().connect() as dst:
        src.backup(dst)
    assert client.get(f"/api/hosts/profile?key={HOST}", environ_overrides=LOCAL).status_code == 401
    login(client)
    r = client.get("/api/hosts/profile", query_string={"key": HOST}, environ_overrides=LOCAL)
    assert r.status_code == 200 and r.get_json()["data"]["name"] == "dev"
    added = post(client, "/api/hosts/tamper-notes", {"key": HOST, "pattern": "regular_cycle", "reason": "NetBird"})
    notes = added.get_json()["data"]["tamper"]["annotations"]
    assert added.status_code == 200 and [n["reason"] for n in notes] == ["NetBird"]
    removed = post(client, f"/api/hosts/tamper-notes/{notes[0]['id']}/remove", {"key": HOST})
    assert removed.status_code == 200 and removed.get_json()["data"]["tamper"]["annotations"] == []


def test_bad_key_not_echoed(client):
    login(client)
    r = client.get("/api/hosts/profile", query_string={"key": "<script>"}, environ_overrides=LOCAL)
    assert r.status_code == 400 and "<script>" not in r.get_data(as_text=True)
    assert post(client, "/api/hosts/ransomware-allows", {"key": "ip:10.0.0.1"}).status_code == 400


def test_note_needs_csrf(client):
    login(client)
    r = client.post("/api/hosts/tamper-notes", json={"key": HOST, "reason": "x"}, environ_overrides=LOCAL)
    assert r.status_code in (400, 403)


def test_refused_remove_changes_nothing(client, ctx, tmp_path):
    """Final review #4: a removal refused for its key must not have removed the note."""
    seeded = _ctx(tmp_path / "seed")
    with seeded.flows().connect() as src, ctx.flows().connect() as dst:
        src.backup(dst)
    login(client)
    added = post(client, "/api/hosts/tamper-notes", {"key": HOST, "reason": "NetBird"})
    note = added.get_json()["data"]["tamper"]["annotations"][0]["id"]
    assert post(client, f"/api/hosts/tamper-notes/{note}/remove", {"key": "invalid-key"}).status_code == 400
    r = client.get("/api/hosts/profile", query_string={"key": HOST}, environ_overrides=LOCAL)
    assert [n["id"] for n in r.get_json()["data"]["tamper"]["annotations"]] == [note]


def test_search(client, ctx):
    assert client.get("/api/hosts/search?q=web", environ_overrides=LOCAL).status_code == 401
    login(client)
    r = client.get("/api/hosts/search", query_string={"q": "10.2.3.4"}, environ_overrides=LOCAL)
    assert r.status_code == 200 and r.get_json()["data"]["items"] == [{"key": "ip:10.2.3.4", "name": "10.2.3.4",
                                                                       "managed": False}]
    assert client.get("/api/hosts/search", query_string={"q": "x" * 201}, environ_overrides=LOCAL).status_code == 400


# ── where to start without a host in hand (purpose-led UI spec §6.2) ──

def _alert_about(ctx, keys, *, severity="high", hours_ago=1):
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    from illumio_ops.domain.alert_devices import Device
    from illumio_ops.domain.alerting import Confidence, Trigger
    from illumio_ops.domain.values import AlertRuleType, Severity
    from illumio_ops.store import alerts as store
    at = datetime.now(UTC) - timedelta(hours=hours_ago)
    t = Trigger(rule_id="c" * 32, rule_type=AlertRuleType.EVENT, subject_key=keys[0], severity=Severity(severity),
                first_seen=at, last_seen=at, late=False, message_key="alert_system_disk_low", params={}, facts={},
                evidence=None, confidence=Confidence())
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        store.insert_alert(conn, pce_url=pce.url, org_id=pce.org_id, rule_name="", pack_key=None,
                           trigger=replace(t, devices=tuple(Device(k, "subject") for k in keys)), at=at,
                           channels=["line"], hold=None)
    return at


def test_the_hosts_recent_alerts_are_about_most_alerted_first(client, ctx):
    w = "/orgs/1/workloads/"
    _alert_about(ctx, [w + "a"], hours_ago=5)
    _alert_about(ctx, [w + "a", "ip:10.0.0.9"], severity="critical", hours_ago=4)
    _alert_about(ctx, [w + "a"], hours_ago=3)
    latest = _alert_about(ctx, [w + "b"], severity="medium", hours_ago=1)
    _alert_about(ctx, [w + "old"], hours_ago=24 * 9)  # before the period
    login(client)
    data = client.get("/api/hosts/alerted?days=7", environ_overrides=LOCAL).get_json()["data"]
    assert [(i["key"], i["alerts"], i["highest"], i["managed"]) for i in data["items"]] == [
        (w + "a", 3, "critical", True), (w + "b", 1, "medium", True), ("ip:10.0.0.9", 1, "critical", False)]
    assert data["items"][1]["last_at"].startswith(latest.isoformat()[:19]) and data["more"] == 0
    assert data["items"][2]["name"] == "10.0.0.9"


def test_no_alert_names_a_host_is_an_empty_list_not_an_error(client, ctx):
    login(client)
    data = client.get("/api/hosts/alerted", environ_overrides=LOCAL).get_json()["data"]
    assert data == {"items": [], "more": 0}
    assert client.get("/api/hosts/alerted?days=0", environ_overrides=LOCAL).status_code == 400
