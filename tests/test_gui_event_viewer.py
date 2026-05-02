"""Event viewer + catalog + i18n tests (split from test_gui_security.py for M9)."""
from src.i18n import get_language, set_language


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
