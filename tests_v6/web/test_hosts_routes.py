"""Host profile API (P6b): signed in, CSRF on POST, a bad key refused without echoing it."""
from tests_v6.services.analysis.test_tamper import HOST, _ctx

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
