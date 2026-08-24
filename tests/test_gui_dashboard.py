"""Dashboards/reports/schedule tests (split from test_gui_security.py for M9)."""
import json
import threading
from unittest.mock import patch

from src.exceptions import TrafficQueryError
from tests._helpers import _csrf


def test_ui_translations_include_schedule_keys(client):
    """The schedule strings must reach the browser's catalogue.

    Phase 2A Task 11: the legacy `/` embedded the whole catalogue as a JSON
    <script> block, so this used to scrape the rendered page. The v2 shell
    fetches it from GET /api/ui_translations instead (core/i18n.mjs), so the
    same invariant is asserted against that response — and now against the
    parsed keys rather than a substring of HTML, which also rules out a key
    that only appears inside some unrelated value.
    """
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    })
    assert login.status_code == 200

    response = client.get('/api/ui_translations')

    assert response.status_code == 200
    catalogue = response.get_json()
    for key in ("sched_enabled_short", "sched_disabled_short", "sched_running"):
        assert key in catalogue, key
        assert catalogue[key], key


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
    monkeypatch.setattr("src.gui.routes.reports._resolve_state_file", lambda: str(state_file))
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


def test_report_endpoint_rejects_path_traversal_format(client, monkeypatch):
    """Security: report format field must be allowlisted, not passed through raw.

    Asserts the normalized value handed to the worker, not the status code:
    /api/reports/generate validates synchronously but always answers 200 once a
    job is created, so a status-code assertion stays green even if the
    allowlist at src/gui/routes/reports.py is deleted.
    """
    import types
    from src.gui.routes import reports as reports_mod

    captured = {}

    class _FakeThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            captured['args'] = args

        def start(self):
            pass  # never run the real report worker from a test

    monkeypatch.setattr(
        reports_mod, 'threading', types.SimpleNamespace(Thread=_FakeThread)
    )

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
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json().get("ok") is True
    payload = captured['args'][1]
    assert payload['fmt'] == 'all', (
        "format outside the allowlist must be normalized to 'all', "
        f"got {payload['fmt']!r}"
    )

    # …and an allowlisted value must survive, so the test cannot be satisfied
    # by hardcoding 'all'.
    captured.clear()
    resp = client.post(
        '/api/reports/generate',
        json={'format': 'csv', 'source': 'api'},
        headers={'X-CSRF-Token': csrf},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert captured['args'][1]['fmt'] == 'csv'


def test_top10_reports_truncation_flag(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    from src.analyzer import Analyzer, QUERY_RESULT_CAP

    def fake_query(self, params):
        self.last_query_stats = {"total_matches": 2000, "cap": QUERY_RESULT_CAP,
                                 "truncated": True}
        return [{"policy_decision": "allowed"}]

    monkeypatch.setattr(Analyzer, "query_flows", fake_query)
    r = client.post('/api/dashboard/top10', json={"mins": 30},
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                    headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    assert r.json.get("truncated") is True
    assert r.json.get("cap") == QUERY_RESULT_CAP


def test_save_dashboard_query_stores_filterbar_keys(client):
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    r = client.post('/api/dashboard/queries', json={
        "name": "Q1", "rank_by": "count", "pd": 3,
        "filters": {
            "src_labels": ["app=erp", "app=web"],
            "dst_iplists": ["/orgs/1/sec_policy/active/ip_lists/7"],
            "src_workloads": ["/orgs/1/workloads/abc"],
            "src_label_groups": ["PG-Prod"],
            "src_ip_in": ["10.0.0.1"],
            "ex_dst_ip": ["10.9.9.9"],
            "any_label": "env=prod",
            "any_iplist": "corp-vpn",
            "ex_any_workload": "/orgs/1/workloads/xyz",
        },
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    assert r.json["ok"] is True

    saved = client.get('/api/dashboard/queries',
                       environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).get_json()[-1]
    assert saved["src_labels"] == ["app=erp", "app=web"]
    assert saved["dst_iplists"] == ["/orgs/1/sec_policy/active/ip_lists/7"]
    assert saved["src_workloads"] == ["/orgs/1/workloads/abc"]
    assert saved["src_label_groups"] == ["PG-Prod"]
    assert saved["src_ip_in"] == ["10.0.0.1"]
    assert saved["ex_dst_ip"] == ["10.9.9.9"]
    assert saved["any_label"] == "env=prod"          # 既有 bug 修復
    assert saved["any_iplist"] == "corp-vpn"
    assert saved["ex_any_workload"] == "/orgs/1/workloads/xyz"
    assert saved["name"] == "Q1"


def test_save_dashboard_query_legacy_branch_unchanged(client):
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    r = client.post('/api/dashboard/queries', json={
        "name": "Legacy", "rank_by": "count", "pd": 3,
        "src": "app=erp", "dst": "10.0.0.5", "ex_src": "env=dev",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    assert r.json["ok"] is True

    saved = client.get('/api/dashboard/queries',
                       environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).get_json()[-1]
    assert saved["src_label"] == "app=erp"
    assert saved["dst_ip_in"] == "10.0.0.5"
    assert saved["ex_src_label"] == "env=dev"


def test_top10_forwards_object_and_plural_filters(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    from src.analyzer import Analyzer
    captured = {}

    def fake_query_flows(self, params):
        captured.update(params)
        return []

    monkeypatch.setattr(Analyzer, "query_flows", fake_query_flows)
    r = client.post('/api/dashboard/top10', json={
        "mins": 30, "pd": 3, "rank_by": "count",
        "src_labels": ["app=erp", "app=web"],
        "dst_iplists": ["/orgs/1/sec_policy/active/ip_lists/7"],
        "src_workloads": ["/orgs/1/workloads/abc"],
        "src_label_groups": ["PG-Prod"],
        "ex_dst_labels": ["env=dev"],
        "any_iplist": "corp-vpn",
        "ex_any_workload": "/orgs/1/workloads/xyz",
        "src_label": "role=db",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200

    assert captured.get("src_labels") == ["app=erp", "app=web"]
    assert captured.get("dst_iplists") == ["/orgs/1/sec_policy/active/ip_lists/7"]
    assert captured.get("src_workloads") == ["/orgs/1/workloads/abc"]
    assert captured.get("src_label_groups") == ["PG-Prod"]
    assert captured.get("ex_dst_labels") == ["env=dev"]
    assert captured.get("any_iplist") == "corp-vpn"
    assert captured.get("ex_any_workload") == "/orgs/1/workloads/xyz"
    assert captured.get("src_label") == "role=db"    # 舊 scalar key 不回歸


# ── final-review Finding 1: top10 must not print "unavailable" as 0.00,
# and must not flatten every lower bound into a point value. Spec's
# call-site table names dashboard.py's top10 sort/format explicitly -- it
# had zero hunks in the whole branch until this fix.

def test_top10_bandwidth_excludes_unmeasurable_rows_and_uses_the_ge_prefixed_string(
        app_persistent, monkeypatch):
    """max_bandwidth_mbps is absent (not None) on a row calculate_mbps could
    not evaluate -- `.get("max_bandwidth_mbps", 0)` used to substitute 0 and
    sort/print it as a measured zero. And the widget re-derived val_fmt with
    its own `:.2f} Mbps`, discarding the "≥ " prefix formatted_bandwidth
    already carries for a lower bound."""
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    from src.analyzer import Analyzer

    def fake_query(self, params):
        return [
            # unmeasurable: no rate key at all (calculate_mbps returned None)
            {"policy_decision": "allowed", "source": {}, "destination": {}, "service": {}},
            # a provable lower bound -- must render with "≥", not a bare number
            {"policy_decision": "allowed", "source": {}, "destination": {}, "service": {},
             "max_bandwidth_mbps": 493.30, "formatted_bandwidth": "≥ 493.30 Mbps"},
        ]

    monkeypatch.setattr(Analyzer, "query_flows", fake_query)
    r = client.post('/api/dashboard/top10', json={"mins": 30, "rank_by": "bandwidth"},
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                    headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    rows = r.json["data"]
    # the unmeasurable row must not appear at all (spec: "算不出來的列不參與")
    assert len(rows) == 1
    assert rows[0]["val_fmt"] == "≥ 493.30 Mbps"


def test_top10_volume_excludes_unmeasurable_rows(app_persistent, monkeypatch):
    """Same absence-vs-zero bug on the volume ranking: total_volume_mb is
    absent on a row calculate_volume_mb could not evaluate."""
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    from src.analyzer import Analyzer

    def fake_query(self, params):
        return [
            {"policy_decision": "allowed", "source": {}, "destination": {}, "service": {}},
            {"policy_decision": "allowed", "source": {}, "destination": {}, "service": {},
             "total_volume_mb": 2.0},
        ]

    monkeypatch.setattr(Analyzer, "query_flows", fake_query)
    r = client.post('/api/dashboard/top10', json={"mins": 30, "rank_by": "volume"},
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                    headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    rows = r.json["data"]
    assert len(rows) == 1


# ── Task 2 (deferred minors hardening): PCE-side query failure must
# surface as 502, matching the quarantine search endpoint's behaviour.


def test_top10_surfaces_query_failure(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    with patch("src.analyzer.Analyzer.query_flows",
               side_effect=TrafficQueryError("poll timed out after 300s")):
        r = client.post('/api/dashboard/top10', json={"mins": 30},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                        headers={'X-CSRF-Token': csrf_token})

    assert r.status_code == 502
    body = r.get_json()
    assert body["ok"] is False
    assert "timed out" in body["error"]
