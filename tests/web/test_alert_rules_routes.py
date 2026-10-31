"""Alert rules API: list with status, create / update / delete through the settings file, preview, pack."""
from illumio_ops.domain.alertpack import pack_rule_id

from .conftest import LOCAL, csrf, login, post

CUSTOM = {"id": "0" * 32, "name": "SSH to prod", "pack_key": "ignored", "enabled": True, "notify": True,
          "severity": "high", "cooldown_minutes": 30, "throttle": None, "type": "traffic",
          "condition": {"ports": [{"port": 22, "proto": 6}], "decisions": ["blocked"]}, "threshold_connections": 5,
          "window_minutes": 10}


def rules(client):
    return client.get("/api/alert-rules", environ_overrides=LOCAL).get_json()["data"]


def put(client, url, body):
    return client.open(url, method="PUT", json=body, environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})


def delete(client, url, body):
    return client.open(url, method="DELETE", json=body, environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})


def test_list_has_pack_with_names(client):
    login(client)
    data = rules(client)
    names = {i["rule"]["id"]: i["display_name"] for i in data["items"]}
    assert names[pack_rule_id("rule_agent_tampering")] == "Agent Tampering Detected" and data["pack_missing"] == 0


def test_create_assigns_id(client):
    login(client)
    rev = rules(client)["revision"]
    r = post(client, "/api/alert-rules", {"revision": rev, "rule": CUSTOM})
    data = r.get_json()["data"]
    mine = [i["rule"] for i in data["items"] if i["rule"]["name"] == "SSH to prod"]
    assert r.status_code == 200 and len(mine) == 1
    assert mine[0]["id"] != "0" * 32 and len(mine[0]["id"]) == 32 and mine[0]["pack_key"] is None


def test_update_keeps_id_and_pack_key(client):
    login(client)
    data = rules(client)
    rid = pack_rule_id("rule_agent_tampering")
    rule = next(i["rule"] for i in data["items"] if i["rule"]["id"] == rid)
    changed = rule | {"id": "f" * 32, "pack_key": None, "name": "Tamper", "cooldown_minutes": 5}
    out = put(client, f"/api/alert-rules/{rid}", {"revision": data["revision"], "rule": changed}).get_json()["data"]
    saved = next(i["rule"] for i in out["items"] if i["rule"]["id"] == rid)
    assert saved["cooldown_minutes"] == 5 and saved["pack_key"] == "rule_agent_tampering"


def test_update_unknown_rule_404(client):
    login(client)
    data = rules(client)
    r = put(client, f"/api/alert-rules/{'e' * 32}", {"revision": data["revision"], "rule": CUSTOM})
    assert r.status_code == 404


def test_delete(client):
    login(client)
    data = rules(client)
    rid = pack_rule_id("rule_agent_clone")
    out = delete(client, f"/api/alert-rules/{rid}", {"revision": data["revision"]}).get_json()["data"]
    assert rid not in {i["rule"]["id"] for i in out["items"]} and out["pack_missing"] == 1


def test_invalid_regex_400_with_field(client):
    login(client)
    bad = CUSTOM | {"type": "event", "event_types": ["agent.(x"], "status": "all", "event_severity": "all",
                    "match_fields": {}, "threshold": "immediate", "threshold_count": 1, "window_minutes": 10}
    for k in ("condition", "threshold_connections"):
        del bad[k]
    r = post(client, "/api/alert-rules", {"revision": rules(client)["revision"], "rule": bad})
    err = r.get_json()["error"]
    assert r.status_code == 400 and err["code"] == "invalid_input" and "event_types" in err["field"]
    assert "agent.(x" not in r.get_data(as_text=True)


def test_stale_revision_409(client):
    login(client)
    r = post(client, "/api/alert-rules", {"revision": 9999, "rule": CUSTOM})
    assert r.status_code == 409


def test_preview_route(client):
    login(client)
    r = post(client, "/api/alert-rules/preview", {"rule": CUSTOM, "hours": 24})
    data = r.get_json()["data"]
    assert r.status_code == 200 and data["status"] == "ok" and data["would_fire"] == 0


def test_pack_modes(client):
    login(client)
    data = rules(client)
    rid = pack_rule_id("rule_agent_clone")
    data = delete(client, f"/api/alert-rules/{rid}", {"revision": data["revision"]}).get_json()["data"]
    out = post(client, "/api/alert-rules/pack", {"revision": data["revision"], "mode": "append_missing"})
    assert rid in {i["rule"]["id"] for i in out.get_json()["data"]["items"]}
    bad = post(client, "/api/alert-rules/pack", {"revision": out.get_json()["data"]["revision"], "mode": "everything"})
    assert bad.status_code == 400
