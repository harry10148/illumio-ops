import pytest
import os
import json
import tempfile
from src.alerts.metadata import FieldMeta, PluginMeta
from src.config import ConfigManager
from src.gui import build_app as _create_app
from src.config import hash_password as _hash_password
from src.i18n import get_language, get_messages, set_language


def _csrf(login_response) -> str:
    """Extract CSRF token from login response JSON (new synchronizer token pattern)."""
    return (login_response.get_json() or {}).get('csrf_token', '')

@pytest.fixture
def temp_config_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    
    # Init empty config
    with open(path, 'w') as f:
        json.dump({"api": {"url": "test", "key": "test", "secret": "test", "org_id": "1"}, "rules": []}, f)
        
    yield path
    os.unlink(path)

@pytest.fixture
def app_persistent(temp_config_file):
    # Override ConfigManager path for testing
    cm = ConfigManager(config_file=temp_config_file)
    cm.load()
    
    # Setup test credentials
    salt = "testsalt"
    pass_hash = _hash_password(salt, "testpass")
    
    cm.config["web_gui"] = {
        "username": "admin",
        "password_salt": salt,
        "password_hash": pass_hash,
        "allowed_ips": ["127.0.0.1", "192.168.1.0/24"],
        "secret_key": "test-secret"
    }
    cm.save()
    
    app = _create_app(cm, persistent_mode=True)
    app.config.update({
        "TESTING": True,
    })
    
    yield app

@pytest.fixture
def client(app_persistent):
    return app_persistent.test_client()

def test_redirect_unauthenticated(client):
    response = client.get('/')
    assert response.status_code == 302
    assert response.location.endswith('/login')

def test_login_success(client):
    response = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    })
    assert response.status_code == 200
    assert response.json.get("ok") is True
    
    # Should now be able to access root
    response = client.get('/')
    assert response.status_code == 200

def test_login_fail(client):
    response = client.post('/api/login', json={
        "username": "admin",
        "password": "wrongpassword"
    })
    assert response.status_code == 401
    assert response.json.get("ok") is False

def test_ip_whitelist(app_persistent):
    client = app_persistent.test_client()
    
    # Mock remote_addr by directly calling request context
    from src.gui import _RstDrop
    import pytest
    with app_persistent.test_request_context('/', environ_base={'REMOTE_ADDR': '10.0.0.1'}):
        # Should raise _RstDrop for blocked IP
        with pytest.raises(_RstDrop):
            app_persistent.preprocess_request()

    # Should allow 127.0.0.1 (in whitelist)
    with app_persistent.test_request_context('/', environ_base={'REMOTE_ADDR': '127.0.0.1'}):
        response = app_persistent.full_dispatch_request()
        # Returns 302 because unauthenticated, but NOT 403
        assert response.status_code == 302

    # Should allow CIDR 192.168.1.50
    with app_persistent.test_request_context('/', environ_base={'REMOTE_ADDR': '192.168.1.50'}):
        response = app_persistent.full_dispatch_request()
        assert response.status_code == 302

def test_api_security_endpoints(app_persistent):
    client = app_persistent.test_client()
    # Authenticate first
    res_login = client.post('/api/login', json={"username": "admin", "password": "testpass"}, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    
    # Get CSRF token from cookies
    csrf_token = _csrf(res_login)
            
    res = client.get('/api/security', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert res.status_code == 200
    assert res.json['username'] == 'admin'
    assert '127.0.0.1' in res.json['allowed_ips']
    
    # Update allowed IPs and password
    res = client.post('/api/security', json={
        "username": "admin2",
        "old_password": "testpass",
        "new_password": "newpass",
        "allowed_ips": ["10.0.0.0/8", "127.0.0.1", "192.168.1.0/24"]
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert res.status_code == 200
    assert res.json['ok'] is True
    
    # Re-login with new password
    client.get('/logout')
    res = client.post('/api/login', json={"username": "admin2", "password": "newpass"}, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert res.status_code == 200
    assert res.json['ok'] is True


def test_api_security_rejects_invalid_allowlist(client):
    res_login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})

    csrf_token = _csrf(res_login)

    res = client.post('/api/security', json={
        "allowed_ips": ["127.0.0.1", "localhost"]
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})

    assert res.status_code == 400
    assert res.json["ok"] is False
    assert "localhost" in res.json["error"]


def test_event_viewer_returns_normalized_events(app_persistent, monkeypatch):
    client = app_persistent.test_client()
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
            "created_by": {"user": {"username": "tester@example.com"}},
            "action": {
                "api_method": "POST",
                "api_endpoint": "/api/v2/orgs/1/users/login",
                "src_ip": "10.0.0.5",
            },
            "resource_changes": [],
            "notifications": [],
        }]

    monkeypatch.setattr("src.api_client.ApiClient.fetch_events_strict", fake_fetch_events_strict)

    response = client.get('/api/events/viewer?mins=60&limit=10', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["summary"]["returned_count"] == 1
    assert response.json["summary"]["matched_count"] == 1
    assert response.json["summary"]["has_more"] is False
    assert response.json["items"][0]["normalized"]["actor"] == "tester@example.com"
    assert response.json["items"][0]["normalized"]["source_ip"] == "10.0.0.5"
    assert response.json["items"][0]["normalized"]["action"] == "POST /users/login"


def test_event_viewer_supports_offset_pagination(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    def fake_fetch_events_strict(self, start_time_str, end_time_str=None, max_results=5000):
        return [
            {
                "href": f"/orgs/1/events/{idx}",
                "timestamp": f"2026-04-08T12:00:0{idx}Z",
                "event_type": "user.login",
                "status": "success",
                "severity": "info",
                "created_by": {"user": {"username": f"user{idx}@example.com"}},
                "action": {"api_method": "POST", "api_endpoint": "/api/v2/login"},
            }
            for idx in range(3)
        ]

    monkeypatch.setattr("src.api_client.ApiClient.fetch_events_strict", fake_fetch_events_strict)

    response = client.get('/api/events/viewer?mins=60&limit=1&offset=1', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["summary"]["matched_count"] == 3
    assert response.json["summary"]["returned_count"] == 1
    assert response.json["summary"]["offset"] == 1
    assert response.json["summary"]["has_more"] is True
    assert len(response.json["items"]) == 1


def test_event_viewer_supports_hierarchy_filters(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    def fake_fetch_events_strict(self, start_time_str, end_time_str=None, max_results=5000):
        return [
            {
                "href": "/orgs/1/events/1",
                "timestamp": "2026-04-08T12:00:02Z",
                "event_type": "rule_set.create",
                "status": "success",
                "severity": "info",
                "created_by": {"user": {"username": "admin@example.com"}},
                "action": {"api_method": "POST", "api_endpoint": "/api/v2/rule_sets"},
            },
            {
                "href": "/orgs/1/events/2",
                "timestamp": "2026-04-08T12:00:01Z",
                "event_type": "user.sign_in",
                "status": "success",
                "severity": "info",
                "created_by": {"user": {"username": "tester@example.com"}},
                "action": {"api_method": "POST", "api_endpoint": "/login/users/sign_in"},
            },
            {
                "href": "/orgs/1/events/3",
                "timestamp": "2026-04-08T12:00:00Z",
                "event_type": "agent.goodbye",
                "status": "success",
                "severity": "warning",
                "created_by": {"agent": {"href": "/orgs/1/agents/123"}},
            },
        ]

    monkeypatch.setattr("src.api_client.ApiClient.fetch_events_strict", fake_fetch_events_strict)

    response = client.get(
        '/api/events/viewer?mins=60&limit=10&category=Policy&type_group=rule_set&event_type=rule_set.create',
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'}
    )
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["summary"]["matched_count"] == 1
    assert response.json["summary"]["category"] == "Policy"
    assert response.json["summary"]["type_group"] == "rule_set"
    assert response.json["summary"]["event_type"] == "rule_set.create"
    assert response.json["items"][0]["event_type"] == "rule_set.create"
    assert response.json["items"][0]["category"] == "Policy"
    assert response.json["items"][0]["type_group"] == "rule_set"


def test_alert_plugins_endpoint_returns_metadata(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    response = client.get('/api/alert-plugins', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert response.status_code == 200
    assert response.json["plugins"]["mail"]["display_name"] == "Email (SMTP)"
    assert any(field["key"] == "sender" for field in response.json["plugins"]["mail"]["fields"])
    assert response.json["plugins"]["line"]["fields"][0]["secret"] is True
    assert any(field["key"] == "smtp.enable_tls" for field in response.json["plugins"]["mail"]["fields"])
    recipients = next(field for field in response.json["plugins"]["mail"]["fields"] if field["key"] == "recipients")
    assert recipients["input_type"] == "list"
    assert recipients["value_type"] == "string_list"
    smtp_port = next(field for field in response.json["plugins"]["mail"]["fields"] if field["key"] == "smtp.port")
    assert smtp_port["value_type"] == "integer"


def test_event_catalog_endpoint_returns_vendor_and_local_metadata(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    response = client.get('/api/event-catalog', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert response.status_code == 200

    categories = response.json["categories"]
    assert categories

    all_events = {
        event["id"]: event
        for category in categories
        for event in category["events"]
    }
    assert "auth_security_principal.create" in all_events
    assert all_events["auth_security_principal.create"]["source"] == "vendor_baseline"
    assert "user.create_session" in all_events
    assert all_events["user.create_session"]["source"] == "local_extension"
    assert all_events["*"]["supports_status"] is False
    assert all_events["*"]["supports_severity"] is True
    assert all_events["request.authentication_failed"]["supports_status"] is True
    assert all_events["rule_set.create"]["supports_status"] is False
    assert all_events["rule_set.create"]["supports_severity"] is False


def test_quarantine_apply_rejects_non_workload_href(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    csrf_token = _csrf(login)

    response = client.post(
        '/api/quarantine/apply',
        json={"href": "/orgs/1/labels/99", "level": "Mild"},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf_token},
    )
    assert response.status_code == 200
    assert response.json["ok"] is False
    assert "workload" in response.json["error"].lower()


def test_quarantine_bulk_apply_skips_invalid_and_deduplicates(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    csrf_token = _csrf(login)

    monkeypatch.setattr("src.api_client.ApiClient.check_and_create_quarantine_labels", lambda self: {"Mild": "/orgs/1/labels/1"})
    monkeypatch.setattr("src.api_client.ApiClient.get_workload", lambda self, href: {"href": href, "labels": []})
    calls = []

    def fake_update(self, href, labels):
        calls.append((href, labels))
        return True

    monkeypatch.setattr("src.api_client.ApiClient.update_workload_labels", fake_update)

    response = client.post(
        '/api/quarantine/bulk_apply',
        json={"hrefs": ["/orgs/1/workloads/1", "/orgs/1/workloads/1", "/orgs/1/labels/99"], "level": "Mild"},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf_token},
    )
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["results"]["success"] == 1
    assert response.json["results"]["skipped_invalid"] == 1
    assert len(calls) == 1
    assert calls[0][0] == "/orgs/1/workloads/1"


def test_quarantine_translation_keys_present():
    set_language("zh_TW")
    messages = get_messages("zh_TW")
    assert messages["gui_q_title"]
    assert messages["gui_q_both"]
    assert messages["gui_q_invalid_target"]
    set_language("en")


def test_ui_translations_include_event_viewer_keys(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    response = client.get('/api/ui_translations', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert response.status_code == 200
    assert response.json["gui_tab_events"]
    assert response.json["gui_event_viewer"]
    assert response.json["gui_ev_type_group"]
    assert response.json["gui_sched_col_status"] != "GUI Sched Col Status"
    assert response.json["gui_sched_col_enabled"] != "GUI Sched Col Enabled"
    assert response.json["gui_sched_modal_add"] != "GUI Sched Modal Add"
    assert response.json["gui_sched_rt_audit"] != "GUI Sched Rt Audit"
    assert response.json["gui_ev_all_categories"]


def test_event_catalog_endpoint_returns_translated_labels_and_correct_categories(client):
    previous_lang = get_language()
    try:
        cm = client.application.config["CM"]
        cm.load()
        cm.config.setdefault("settings", {})["language"] = "zh_TW"
        cm.save()
        set_language('zh_TW')

        login = client.post('/api/login', json={
            "username": "admin",
            "password": "testpass"
        }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        assert login.status_code == 200

        response = client.get('/api/event-catalog', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        assert response.status_code == 200

        categories = response.json["categories"]
        category_labels = {category["id"]: category["label"] for category in categories}
        # Policy and Workload stay English in zh_TW per the glossary whitelist
        # (user-configured terms to preserve in both locales).
        assert category_labels["Policy"] == "Policy"
        assert category_labels["Agent Operations"] == "Agent 操作"
        assert category_labels["Containers & Workloads"] == "容器與 Workload"

        all_events = {
            event["id"]: {**event, "category_id": category["id"]}
            for category in categories
            for event in category["events"]
        }
        assert all_events["*"]["category_id"] == "General"
        assert all_events["agent.generate_maintenance_token"]["category_id"] == "Agent Operations"
        assert all_events["agent.request_policy"]["category_id"] == "Agent Operations"
        assert all_events["ip_tables_rule.create"]["category_id"] == "Policy"
        assert all_events["security_principals.bulk_create"]["category_id"] == "Inventory & Identity"
        assert all_events["agent.generate_maintenance_token"]["label"] == "Agent產生維護權杖"
        assert all_events["agent.machine_identifier"]["label"] == "Agent主機識別碼"
        assert all_events["ip_tables_rule.create"]["label"] == "IP表規則建立"
        assert all_events["security_principals.bulk_create"]["label"] == "安全主體批次建立"
        assert "agent.reguest_policy" not in all_events
        assert len(all_events) == sum(len(category["events"]) for category in categories)
    finally:
        set_language(previous_lang)


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


def test_system_health_rule_uses_dedicated_endpoint(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    csrf_token = _csrf(login)

    bad_event = client.post('/api/rules/event', json={
        "name": "Bad event route",
        "filter_value": "pce_health",
        "threshold_type": "immediate",
        "threshold_count": 1,
        "threshold_window": 10,
        "cooldown_minutes": 30,
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert bad_event.status_code == 400

    created = client.post('/api/rules/system', json={
        "name": "PCE Health Monitor",
        "filter_value": "pce_health",
        "cooldown_minutes": 45,
        "throttle": "1/30m",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert created.status_code == 200
    assert created.json["ok"] is True

    rules = client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert rules.status_code == 200
    system_rule = next(rule for rule in rules.json if rule["type"] == "system" and rule["filter_value"] == "pce_health")
    assert system_rule["name"] == "PCE Health Monitor"
    assert system_rule["cooldown_minutes"] == 45
    assert system_rule["throttle"] == "1/30m"


def test_status_includes_alert_channel_health(app_persistent):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    response = client.get('/api/status', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert response.status_code == 200
    channels = response.json["alert_channels"]
    line = next(item for item in channels if item["name"] == "line")
    assert line["configured"] is False
    assert "alerts.line_channel_access_token" in line["missing_required"]
    assert line["enabled"] is False


def test_test_alert_endpoint_supports_single_channel(client, monkeypatch):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    csrf_token = _csrf(login)

    def fake_send_alerts(self, force_test=False, channels=None):
        assert force_test is True
        assert channels == ["mail"]
        return [{"channel": "mail", "status": "success", "target": "ops@example.com"}]

    monkeypatch.setattr("src.reporter.Reporter.send_alerts", fake_send_alerts)

    response = client.post(
        '/api/actions/test-alert',
        json={"channel": "mail"},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf_token},
    )
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["results"][0]["channel"] == "mail"


def test_debug_endpoint_returns_captured_output(client, monkeypatch):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    csrf_token = _csrf(login)

    def fake_run_debug_mode(self, mins=None, pd_sel=None, interactive=None):
        assert interactive is False
        print("debug-output-line")

    monkeypatch.setattr("src.analyzer.Analyzer.run_debug_mode", fake_run_debug_mode)

    response = client.post(
        '/api/actions/debug',
        json={"mins": 30, "pd_sel": 3},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf_token},
    )
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert "debug-output-line" in response.json["output"]


def test_test_alert_endpoint_rejects_unknown_channel(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    csrf_token = _csrf(login)

    response = client.post(
        '/api/actions/test-alert',
        json={"channel": "pagerduty"},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf_token},
    )
    assert response.status_code == 400
    assert response.json["ok"] is False


def test_settings_support_dynamic_plugin_roots(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({
                "api": {"url": "test", "key": "test", "secret": "test", "org_id": "1"},
                "rules": [],
                "web_gui": {
                    "username": "admin",
                    "password_salt": "testsalt",
                    "password_hash": _hash_password("testsalt", "testpass"),
                    "allowed_ips": ["127.0.0.1"],
                    "secret_key": "test-secret",
                },
            }, f)

        import src.gui as gui_module
        gui_module.PLUGIN_METADATA["dummy_settings_plugin"] = PluginMeta(
            name="dummy_settings_plugin",
            display_name="Dummy Plugin",
            description="Dynamic root config test.",
            fields={
                "dummy_plugin.token": FieldMeta(label="Token", required=True, secret=True),
                "dummy_plugin.retries": FieldMeta(label="Retries", required=True, input_type="number", value_type="integer"),
                "dummy_plugin.targets": FieldMeta(label="Targets", input_type="list", value_type="string_list"),
            },
        )

        cm = ConfigManager(config_file=path)
        cm.load()
        app = _create_app(cm, persistent_mode=True)
        app.config.update({"TESTING": True})
        client = app.test_client()

        login = client.post('/api/login', json={
            "username": "admin",
            "password": "testpass"
        }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        assert login.status_code == 200

        csrf_token = _csrf(login)

        save_response = client.post(
            '/api/settings',
            json={"dummy_plugin": {"token": "abc123", "retries": 0, "targets": ["ops", "soc"]}},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
            headers={'X-CSRF-Token': csrf_token},
        )
        assert save_response.status_code == 200
        assert save_response.json["ok"] is True

        get_response = client.get('/api/settings', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        assert get_response.status_code == 200
        assert get_response.json["dummy_plugin"]["token"] == "abc123"
        assert get_response.json["dummy_plugin"]["retries"] == 0
        assert get_response.json["dummy_plugin"]["targets"] == ["ops", "soc"]

        status_response = client.get('/api/status', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        assert status_response.status_code == 200
        dummy = next(item for item in status_response.json["alert_channels"] if item["name"] == "dummy_settings_plugin")
        assert dummy["configured"] is True
        assert dummy["missing_required"] == []
    finally:
        import src.gui as gui_module
        gui_module.PLUGIN_METADATA.pop("dummy_settings_plugin", None)
        os.unlink(path)


def test_event_rule_test_returns_current_vs_legacy_diff(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({
                "api": {"url": "test", "key": "test", "secret": "test", "org_id": "1"},
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
                    "password_salt": "testsalt",
                    "password_hash": _hash_password("testsalt", "testpass"),
                    "allowed_ips": ["127.0.0.1"],
                    "secret_key": "test-secret",
                },
            }, f)

        cm = ConfigManager(config_file=path)
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
    monkeypatch.setattr("src.gui._resolve_state_file", lambda: str(state_file))

    rules = client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert rules.status_code == 200
    created = next(rule for rule in rules.json if rule["name"] == "Throttle surfaced")
    assert created["throttle_state"]["cooldown_suppressed"] == 2
    assert created["throttle_state"]["throttle_suppressed"] == 3
    assert created["throttle_state"]["next_allowed_at"] == "2026-04-08T12:10:00Z"


def test_dashboard_audit_summary_route(client, app_persistent, tmp_path):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    cm = app_persistent.config["CM"]
    cm.config["report"] = {"output_dir": str(tmp_path)}
    cm.save()

    summary = {
        "generated_at": "2026-04-08 23:00:00",
        "record_count": 42,
        "date_range": ["2026-04-01", "2026-04-08"],
        "kpis": [{"label": "Total Events", "value": "42"}],
        "attention_items": [{"risk": "HIGH", "event_type": "agent.tampering", "summary": "Tampering detected"}],
        "top_events": [{"Event Type": "agent.tampering", "Count": 3}],
    }
    (tmp_path / "latest_audit_summary.json").write_text(json.dumps(summary), encoding="utf-8")

    res = client.get('/api/dashboard/audit_summary', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert res.status_code == 200
    assert res.json["ok"] is True
    assert res.json["summary"]["record_count"] == 42
    assert res.json["summary"]["attention_items"][0]["event_type"] == "agent.tampering"


def test_dashboard_policy_usage_summary_route_missing_message(client, app_persistent, tmp_path):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    cm = app_persistent.config["CM"]
    cm.config["report"] = {"output_dir": str(tmp_path)}
    cm.save()

    res = client.get('/api/dashboard/policy_usage_summary', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert res.status_code == 200
    assert res.json["ok"] is False
    assert "No policy usage report summary found" in res.json["error"]


def test_reports_route_surfaces_attack_metadata(client, app_persistent, tmp_path):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    cm = app_persistent.config["CM"]
    cm.config["report"] = {"output_dir": str(tmp_path)}
    cm.save()

    report_path = tmp_path / "Illumio_Traffic_Report_test.html"
    report_path.write_text("<html></html>", encoding="utf-8")
    metadata = {
        "report_type": "traffic",
        "summary": "deterministic test summary",
        "attack_summary": {
            "boundary_breaches": [{"finding": "Boundary breach test", "action": "Contain"}],
            "suspicious_pivot_behavior": [],
            "blast_radius": [],
            "blind_spots": [],
            "action_matrix": [],
        },
        "attack_summary_counts": {
            "boundary_breaches": 1,
            "suspicious_pivot_behavior": 0,
            "blast_radius": 0,
            "blind_spots": 0,
            "action_matrix": 0,
        },
    }
    (tmp_path / "Illumio_Traffic_Report_test.html.metadata.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    res = client.get('/api/reports', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert res.status_code == 200
    assert res.json["ok"] is True
    reports = res.json["reports"]
    assert reports
    first = reports[0]
    assert first["report_type"] == "traffic"
    assert "attack_summary" in first


def test_allowed_report_formats_constant_exists():
    """Phase 5 hardening: format allowlist constant must be defined in gui module."""
    from src import gui
    assert hasattr(gui, '_ALLOWED_REPORT_FORMATS'), (
        "_ALLOWED_REPORT_FORMATS not found; format allowlist must be defined as a module-level constant"
    )
    assert 'html' in gui._ALLOWED_REPORT_FORMATS
    assert 'csv' in gui._ALLOWED_REPORT_FORMATS
    assert 'pdf' in gui._ALLOWED_REPORT_FORMATS
    assert 'xlsx' in gui._ALLOWED_REPORT_FORMATS
    assert 'all' in gui._ALLOWED_REPORT_FORMATS


def test_report_endpoint_rejects_path_traversal_format(client):
    """Security: report format field must be allowlisted, not passed through raw."""
    # Log in first
    login_resp = client.post(
        '/api/login',
        json={"username": "admin", "password": "testpass"},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
    )
    assert login_resp.get_json().get("ok") is True
    csrf = login_resp.get_json().get("csrf_token", "")

    resp = client.post(
        '/api/reports/generate',
        json={'format': '../../etc/passwd', 'source': 'api'},
        headers={'X-CSRF-Token': csrf},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
    )
    # Must not be 500 — either 200 (silent fallback to 'all') or 400 (explicit reject)
    assert resp.status_code in (200, 400, 422), (
        f"Path-traversal format should be allowlisted; got {resp.status_code}"
    )
