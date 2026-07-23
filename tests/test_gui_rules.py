"""best_practices, event_rule, rules_api tests (split from test_gui_security.py for M9)."""
import json
import os
import tempfile

from src.config import ConfigManager
from src.gui import build_app as _create_app


from tests._helpers import _csrf


def test_best_practices_append_mode_preserves_existing_rules(app_persistent):
    cm = app_persistent.config["CM"]
    cm.config["rules"] = [
        {
            "id": 1,
            "type": "event",
            "name": "Custom Existing Rule",
            "filter_key": "event_type",
            "filter_value": "request.authentication_failed",
            "filter_status": "all",
            "filter_severity": "all",
            "threshold_type": "count",
            "threshold_count": 9,
            "threshold_window": 15,
            "cooldown_minutes": 20,
        }
    ]
    cm.save()

    client = app_persistent.test_client()
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200
    csrf_token = _csrf(login)

    response = client.post('/api/actions/best-practices', json={
        "mode": "append_missing"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})

    assert response.status_code == 200
    assert response.json["ok"] is True
    summary = response.json["summary"]
    assert summary["mode"] == "append_missing"
    assert summary["backup_created"] is True
    assert summary["added_count"] > 0
    assert summary["skipped_count"] > 0

    cm.load()
    names = [rule["name"] for rule in cm.config["rules"]]
    assert "Custom Existing Rule" in names
    existing = next(rule for rule in cm.config["rules"] if rule["name"] == "Custom Existing Rule")
    assert existing["threshold_count"] == 9
    assert cm.config["rule_backups"][-1]["rule_count"] == 1
    assert not any(rule.get("type") == "system" and rule.get("filter_value") == "pce_health" for rule in cm.config["rules"])


def test_best_practices_replace_mode_replaces_rules(app_persistent):
    cm = app_persistent.config["CM"]
    cm.config["rules"] = [
        {
            "id": 1,
            "type": "event",
            "name": "Temporary Rule",
            "filter_key": "event_type",
            "filter_value": "agent.tampering",
            "filter_status": "all",
            "filter_severity": "all",
            "threshold_type": "immediate",
            "threshold_count": 1,
            "threshold_window": 10,
            "cooldown_minutes": 10,
        }
    ]
    cm.save()

    client = app_persistent.test_client()
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200
    csrf_token = _csrf(login)

    response = client.post('/api/actions/best-practices', json={
        "mode": "replace"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})

    assert response.status_code == 200
    assert response.json["ok"] is True
    summary = response.json["summary"]
    assert summary["mode"] == "replace"
    assert summary["replaced_count"] == 1

    cm.load()
    names = [rule["name"] for rule in cm.config["rules"]]
    assert "Temporary Rule" not in names
    assert cm.config["rule_backups"][-1]["rule_count"] == 1
    assert not any(rule.get("type") == "system" and rule.get("filter_value") == "pce_health" for rule in cm.config["rules"])


def test_event_rule_test_returns_current_vs_legacy_diff(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    # Isolate alerts.json (which now holds rules) — auto-derived /tmp/alerts.json
    # would be shared across tests and pollute rules state.
    alerts_path = path + ".alerts"
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({
                "api": {"url": "https://pce.test", "key": "test", "secret": "test", "org_id": "1"},
                "rules": [
                    {
                        "id": 1,
                        "type": "event",
                        "name": "Nested rule",
                        "filter_value": "request.authentication_failed",
                        "filter_status": "failure",
                        "filter_severity": "err",
                        "match_fields": {"created_by.user.username": "admin@example.com"},
                    }
                ],
                "web_gui": {
                    "username": "admin",
                    "password": "testpass",
                    "allowed_ips": ["127.0.0.1"],
                    "secret_key": "test-secret",
                },
            }, f)

        cm = ConfigManager(config_file=path, alerts_file=alerts_path)
        cm.load()
        app = _create_app(cm, persistent_mode=True)
        app.config.update({"TESTING": True})
        client = app.test_client()

        login = client.post('/api/login', json={
            "username": "admin",
            "password": "testpass"
        }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        assert login.status_code == 200

        def fake_fetch_events_strict(self, start_time_str, end_time_str=None, max_results=5000):
            return [{
                "href": "/orgs/1/events/abc",
                "timestamp": "2026-04-08T12:00:00Z",
                "event_type": "request.authentication_failed",
                "status": "failure",
                "severity": "err",
                "created_by": {"user": {"username": "other@example.com"}},
                "action": {"api_method": "POST", "api_endpoint": "/api/v2/users/login", "src_ip": "10.0.0.5"},
            }]

        monkeypatch.setattr("src.api_client.ApiClient.fetch_events_strict", fake_fetch_events_strict)

        response = client.get('/api/events/rule_test?idx=0&mins=60', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        assert response.status_code == 200
        assert response.json["ok"] is True
        assert response.json["summary"]["current_count"] == 0
        assert response.json["summary"]["legacy_count"] == 1
        assert response.json["summary"]["status"] == "legacy_more"
        assert response.json["only_legacy"][0]["event_type"] == "request.authentication_failed"
    finally:
        os.unlink(path)
        if os.path.exists(alerts_path):
            os.unlink(alerts_path)


def test_event_rule_create_persists_throttle_and_rejects_invalid(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    csrf_token = _csrf(login)

    res = client.post('/api/rules/event', json={
        "name": "Burst auth failures",
        "filter_value": "request.authentication_failed",
        "match_fields": {"created_by.user.username": "admin@example.com"},
        "threshold_type": "count",
        "threshold_count": 2,
        "threshold_window": 10,
        "cooldown_minutes": 5,
        "throttle": "2/10m",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert res.status_code == 200
    assert res.json["ok"] is True

    rules = client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert rules.status_code == 200
    created = next(rule for rule in rules.json if rule["name"] == "Burst auth failures")
    assert created["throttle"] == "2/10m"
    assert created["match_fields"] == {"created_by.user.username": "admin@example.com"}

    bad = client.post('/api/rules/event', json={
        "name": "Bad throttle",
        "filter_value": "request.authentication_failed",
        "threshold_type": "count",
        "threshold_count": 2,
        "threshold_window": 10,
        "cooldown_minutes": 5,
        "throttle": "nonsense",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert bad.status_code == 400
    assert bad.json["ok"] is False


def test_event_rule_create_rejects_non_numeric_threshold(client):
    """D2 子項 3：裸 int(d.get('threshold_count'/'threshold_window'/
    'cooldown_minutes')) 收到非數字輸入不可 500。"""
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200
    csrf_token = _csrf(login)

    for bad_field in ("threshold_count", "threshold_window", "cooldown_minutes"):
        payload = {
            "name": "Bad numeric rule",
            "filter_value": "request.authentication_failed",
            "threshold_type": "count",
            "threshold_count": 2,
            "threshold_window": 10,
            "cooldown_minutes": 5,
        }
        payload[bad_field] = "oops"
        res = client.post('/api/rules/event', json=payload,
                          environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                          headers={'X-CSRF-Token': csrf_token})
        assert res.status_code == 400, f"{bad_field} should be rejected with 400"
        assert res.json["ok"] is False


def test_rules_api_returns_throttle_state(client, monkeypatch, tmp_path):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    csrf_token = _csrf(login)

    res = client.post('/api/rules/event', json={
        "name": "Throttle surfaced",
        "filter_value": "request.authentication_failed",
        "threshold_type": "count",
        "threshold_count": 2,
        "threshold_window": 10,
        "cooldown_minutes": 5,
        "throttle": "2/10m",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert res.status_code == 200

    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({
        "alert_history": {},
        "throttle_state": {
            str(next_rule["id"] if (next_rule := client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).json[-1]) else 0): {
                "cooldown_suppressed": 2,
                "throttle_suppressed": 3,
                "next_allowed_at": "2026-04-08T12:10:00Z",
            }
        }
    }), encoding='utf-8')
    monkeypatch.setattr("src.gui.routes.rules._resolve_state_file", lambda: str(state_file))

    rules = client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert rules.status_code == 200
    created = next(rule for rule in rules.json if rule["name"] == "Throttle surfaced")
    assert created["throttle_state"]["cooldown_suppressed"] == 2
    assert created["throttle_state"]["throttle_suppressed"] == 3
    assert created["throttle_state"]["next_allowed_at"] == "2026-04-08T12:10:00Z"


def _login_csrf(client):
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200
    return _csrf(login)


def test_event_rule_rejects_window_over_24h(client):
    """threshold_window 超過 1440 分鐘要被拒——analyzer history 保留有上限，
    超大視窗會被靜默低估（2026-07-24 審查 A3）。"""
    token = _login_csrf(client)
    resp = client.post("/api/rules/event",
                       json={"name": "big window", "filter_value": "user.login",
                             "threshold_type": "count", "threshold_count": 5,
                             "threshold_window": 2000},
                       headers={"X-CSRF-Token": token},
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 400
    assert "1440" in (resp.get_json() or {}).get("error", "")


def test_event_rule_accepts_window_within_cap(client):
    token = _login_csrf(client)
    resp = client.post("/api/rules/event",
                       json={"name": "ok window", "filter_value": "user.login",
                             "threshold_type": "count", "threshold_count": 5,
                             "threshold_window": 180},
                       headers={"X-CSRF-Token": token},
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200


def test_traffic_rule_rejects_window_over_24h(client):
    token = _login_csrf(client)
    resp = client.post("/api/rules/traffic",
                       json={"name": "big window", "threshold_count": 5,
                             "threshold_window": 2000},
                       headers={"X-CSRF-Token": token},
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 400
    assert "1440" in (resp.get_json() or {}).get("error", "")
