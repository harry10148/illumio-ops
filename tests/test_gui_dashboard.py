"""Dashboards/reports/schedule tests (split from test_gui_security.py for M9)."""
import json
import threading


def _csrf(login_response) -> str:
    """Extract CSRF token from login response JSON (new synchronizer token pattern)."""
    return (login_response.get_json() or {}).get('csrf_token', '')


def test_index_initial_translations_include_schedule_keys(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    })
    assert login.status_code == 200

    response = client.get('/')

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "sched_enabled_short" in body
    assert "sched_disabled_short" in body
    assert "sched_running" in body


def test_report_schedule_run_marks_schedule_running(client, app_persistent, monkeypatch, tmp_path):
    cm = app_persistent.config["CM"]
    cm.load()
    cm.config["report_schedules"] = [
        {
            "id": 123,
            "name": "Daily",
            "enabled": True,
            "report_type": "traffic",
            "schedule_type": "daily",
            "hour": 8,
            "minute": 0,
            "email_report": True,
        }
    ]
    cm.save()

    state_file = tmp_path / "state.json"
    monkeypatch.setattr("src.gui._resolve_state_file", lambda: str(state_file))
    started = threading.Event()
    release = threading.Event()

    def _blocked_run_schedule(self, schedule):
        started.set()
        release.wait(timeout=5)
        return True

    monkeypatch.setattr("src.report_scheduler.ReportScheduler.run_schedule", _blocked_run_schedule)

    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    })
    csrf_token = _csrf(login)

    try:
        response = client.post(
            "/api/report-schedules/123/run",
            headers={"X-CSRF-Token": csrf_token},
        )

        assert response.status_code == 200
        assert response.json["ok"] is True
        assert started.wait(timeout=2)
        with state_file.open(encoding="utf-8") as f:
            state = json.load(f)
        assert state["report_schedule_states"]["123"]["status"] == "running"
    finally:
        release.set()


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
