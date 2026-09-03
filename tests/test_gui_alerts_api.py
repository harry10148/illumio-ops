"""Phase 3A Task 3 — /api/alerts inbox API."""
from __future__ import annotations

import pytest

from src.alerts.store import AlertStore
from tests._helpers import _csrf

HDR = {"REMOTE_ADDR": "127.0.0.1"}


@pytest.fixture
def api(app_persistent, tmp_path, monkeypatch):
    db = tmp_path / "alerts.sqlite"
    monkeypatch.setattr("src.gui.routes.alerts.AlertStore", lambda: AlertStore(str(db)))
    cm = app_persistent.config["CM"]
    cm.config["rules"] = [
        {"id": "t1", "type": "traffic", "name": "SSH in", "threshold_type": "count", "threshold_count": 20,
         "threshold_window": 5, "pd": 2, "port": "22", "dst_label": "app=db", "filters": [{"k": "port", "v": "22"}]},
        {"id": 18, "type": "event", "name": "Login failed", "filter_key": "event_type",
         "filter_value": "user.sign_in", "threshold_type": "count", "threshold_count": 3, "threshold_window": 10},
    ]
    cm.save()
    st = AlertStore(str(db))
    ids = {}
    ids["t"] = st.insert(fired_at="2026-09-03T08:00:00Z", type="traffic", rule_id="t1", rule_name="SSH in",
                         severity="warning", summary="SSH in · 24", criteria="port 22",
                         payload={"raw_data": [1]}, dispatch=[{"channel": "mail", "status": "success"}])
    ids["e"] = st.insert(fired_at="2026-09-03T08:01:00Z", type="event", rule_id="18", rule_name="Login failed",
                         severity="warning", summary="Login failed · x", criteria="",
                         payload={}, dispatch=[])
    ids["s"] = st.insert(fired_at="2026-09-03T08:02:00Z", type="system", rule_id=None, rule_name="Watchdog",
                         severity="critical", summary="Watchdog · 503", criteria="", payload={}, dispatch=[])
    ids["gone"] = st.insert(fired_at="2026-09-03T08:03:00Z", type="traffic", rule_id="deleted-rule",
                            rule_name="Old", severity="warning", summary="Old", criteria="", payload={}, dispatch=[])
    st.close()
    client = app_persistent.test_client()
    login = client.post("/api/login", json={"username": "admin", "password": "testpass"}, environ_overrides=HDR)
    assert login.status_code == 200
    return client, _csrf(login), ids


def test_list_pages_filters_and_counts(api):
    client, _, ids = api
    r = client.get("/api/alerts?page=1&page_size=2", environ_overrides=HDR)
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] is True
    assert body["total"] == 4 and len(body["items"]) == 2 and body["page"] == 1
    assert body["items"][0]["id"] == ids["gone"]                     # newest first
    assert body["counts"] == {"new": 4, "ack": 0, "done": 0}
    assert client.get("/api/alerts?type=event", environ_overrides=HDR).get_json()["total"] == 1
    assert client.get("/api/alerts?since=2026-09-03T08:02:00Z", environ_overrides=HDR).get_json()["total"] == 2
    assert client.get("/api/alerts?since=not-a-date", environ_overrides=HDR).status_code == 400
    assert client.get("/api/alerts?type=bogus", environ_overrides=HDR).status_code == 400
    assert client.get("/api/alerts?page_size=5000", environ_overrides=HDR).get_json()["page_size"] == 200


def test_get_detail_and_404(api):
    client, _, ids = api
    r = client.get(f"/api/alerts/{ids['t']}", environ_overrides=HDR)
    assert r.status_code == 200
    assert r.get_json()["alert"]["payload"] == {"raw_data": [1]}
    assert r.get_json()["alert"]["dispatch"][0]["channel"] == "mail"
    assert client.get("/api/alerts/999999", environ_overrides=HDR).status_code == 404


def test_patch_status(api):
    client, csrf, ids = api
    r = client.patch(f"/api/alerts/{ids['t']}", json={"status": "ack"}, environ_overrides=HDR,
                     headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    got = client.get(f"/api/alerts/{ids['t']}", environ_overrides=HDR).get_json()["alert"]
    assert got["status"] == "ack" and got["status_by"] == "admin" and got["status_at"]
    assert client.get("/api/alerts", environ_overrides=HDR).get_json()["counts"]["ack"] == 1
    bad = client.patch(f"/api/alerts/{ids['t']}", json={"status": "closed"}, environ_overrides=HDR,
                       headers={"X-CSRF-Token": csrf})
    assert bad.status_code == 400
    missing = client.patch("/api/alerts/999999", json={"status": "done"}, environ_overrides=HDR,
                           headers={"X-CSRF-Token": csrf})
    assert missing.status_code == 404
    nocsrf = client.patch(f"/api/alerts/{ids['t']}", json={"status": "done"}, environ_overrides=HDR)
    assert nocsrf.status_code == 400 and nocsrf.get_json().get("code") == "csrf_error"


def test_traffic_query_rebuilds_from_rule(api):
    client, _, ids = api
    r = client.get(f"/api/alerts/{ids['t']}/traffic_query", environ_overrides=HDR)
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] is True
    assert body["rule"] == {"id": "t1", "name": "SSH in", "type": "traffic"}
    q = body["query"]
    assert q["type"] == "traffic" and q["pd"] == 2 and q["threshold_window"] == 5
    assert q["port"] == "22" and q["dst_label"] == "app=db"
    assert q["filters"] == [{"k": "port", "v": "22"}]
    assert "src_ip_in" not in q                                        # absent scalar keys are not invented
    assert "name" not in q and "threshold_count" not in q              # only query-relevant keys


def test_traffic_query_rejects_event_and_missing_rule(api):
    client, _, ids = api
    r = client.get(f"/api/alerts/{ids['e']}/traffic_query", environ_overrides=HDR)
    assert r.status_code == 400 and r.get_json()["code"] == "not_traffic"
    r = client.get(f"/api/alerts/{ids['gone']}/traffic_query", environ_overrides=HDR)
    assert r.status_code == 404 and r.get_json()["code"] == "rule_missing"
    r = client.get(f"/api/alerts/{ids['s']}/traffic_query", environ_overrides=HDR)
    assert r.status_code in (400, 404)
    assert client.get("/api/alerts/999999/traffic_query", environ_overrides=HDR).status_code == 404


def test_unauthenticated_is_rejected(app_persistent, tmp_path, monkeypatch):
    monkeypatch.setattr("src.gui.routes.alerts.AlertStore",
                        lambda: AlertStore(str(tmp_path / "alerts.sqlite")))
    client = app_persistent.test_client()
    assert client.get("/api/alerts", environ_overrides=HDR).status_code == 401
