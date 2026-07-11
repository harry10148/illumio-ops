"""Quarantine endpoint tests (split from test_gui_security.py for M9)."""
from unittest.mock import patch

from src.i18n import get_messages, set_language

from src.exceptions import TrafficQueryError
from tests._helpers import _csrf


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


def test_truncation_translation_keys_present():
    set_language("zh_TW")
    messages = get_messages("zh_TW")
    assert "{cap}" in messages["gui_results_truncated"]
    assert "{cap}" in messages["gui_top10_truncated"]
    en = get_messages("en")
    assert "{cap}" in en["gui_results_truncated"]
    set_language("en")


def test_quarantine_search_reports_truncation(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    from src.analyzer import Analyzer, QUERY_RESULT_CAP

    def fake_query(self, params):
        self.last_query_stats = {"total_matches": 1234, "cap": QUERY_RESULT_CAP,
                                 "truncated": True}
        return [{"policy_decision": "allowed"}]

    monkeypatch.setattr(Analyzer, "query_flows", fake_query)
    r = client.post('/api/quarantine/search', json={"mins": 60},
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                    headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    assert r.json["ok"] is True
    assert r.json["total_matches"] == 1234
    assert r.json["truncated"] is True


def test_quarantine_search_forwards_object_filter_keys(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    captured = {}
    from src.analyzer import Analyzer
    def fake_query(self, params):
        captured.update(params)
        return []
    monkeypatch.setattr(Analyzer, "query_flows", fake_query)

    client.post('/api/quarantine/search', json={
        "mins": 60,
        "src_labels": ["app=erp", "app=web"],
        "dst_iplists": ["/orgs/1/sec_policy/active/ip_lists/7"],
        "src_workloads": ["/orgs/1/workloads/abc"],
        "ex_dst_workloads": ["/orgs/1/workloads/zzz"],
        "any_iplist": "corp-vpn",
        "ex_any_workload": "/orgs/1/workloads/q",
        "src_label_groups": ["app_group"],
        "ex_dst_label_groups": ["dmz_group"],
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
       headers={'X-CSRF-Token': csrf_token})

    assert captured.get("src_labels") == ["app=erp", "app=web"]
    assert captured.get("dst_iplists") == ["/orgs/1/sec_policy/active/ip_lists/7"]
    assert captured.get("src_workloads") == ["/orgs/1/workloads/abc"]
    assert captured.get("ex_dst_workloads") == ["/orgs/1/workloads/zzz"]
    assert captured.get("any_iplist") == "corp-vpn"
    assert captured.get("ex_any_workload") == "/orgs/1/workloads/q"
    assert captured.get("src_label_groups") == ["app_group"]
    assert captured.get("ex_dst_label_groups") == ["dmz_group"]


# ── Task 2 (deferred minors hardening): a PCE-side query failure (e.g.
# submit 406) must surface as a distinguishable error, not as ok:true with
# an empty result indistinguishable from a genuine 0-flow match.


def test_quarantine_search_surfaces_query_failure(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    with patch("src.analyzer.Analyzer.query_flows",
               side_effect=TrafficQueryError("submit failed: 406 - bad payload")):
        r = client.post('/api/quarantine/search', json={"mins": 60},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                        headers={'X-CSRF-Token': csrf_token})

    assert r.status_code == 502
    body = r.get_json()
    assert body["ok"] is False
    assert "406" in body["error"]


def test_quarantine_apply_writes_audit_log(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    monkeypatch.setattr("src.api_client.ApiClient.check_and_create_quarantine_labels",
                        lambda self: {"Mild": "/orgs/1/labels/1"})
    monkeypatch.setattr("src.api_client.ApiClient.get_workload",
                        lambda self, href: {"href": href, "labels": []})
    monkeypatch.setattr("src.api_client.ApiClient.update_workload_labels",
                        lambda self, href, labels: True)

    records = []

    class _Rec:
        def info(self, msg):
            records.append(msg)

    from src.module_log import ModuleLog
    monkeypatch.setattr(ModuleLog, "get", classmethod(lambda cls, name: _Rec()))

    r = client.post('/api/quarantine/apply',
                    json={"href": "/orgs/1/workloads/1", "level": "Mild"},
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                    headers={'X-CSRF-Token': csrf_token})
    assert r.json["ok"] is True
    audit = [m for m in records if "quarantine_apply" in m]
    assert len(audit) == 1
    assert "/orgs/1/workloads/1" in audit[0]
    assert "Mild" in audit[0]
    assert "user=admin" in audit[0]


def test_quarantine_lift_removes_only_quarantine_labels(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    q = {"Mild": "/orgs/1/labels/1", "Moderate": "/orgs/1/labels/2", "Severe": "/orgs/1/labels/3"}
    monkeypatch.setattr("src.api_client.ApiClient.check_and_create_quarantine_labels",
                        lambda self: q)
    monkeypatch.setattr("src.api_client.ApiClient.get_workload", lambda self, href: {
        "href": href,
        "labels": [{"href": "/orgs/1/labels/2"}, {"href": "/orgs/1/labels/77"}],
    })
    calls = []
    monkeypatch.setattr("src.api_client.ApiClient.update_workload_labels",
                        lambda self, href, labels: calls.append((href, labels)) or True)

    r = client.post('/api/quarantine/lift',
                    json={"hrefs": ["/orgs/1/workloads/1"]},
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                    headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    assert r.json["ok"] is True
    assert r.json["results"]["success"] == 1
    assert calls == [("/orgs/1/workloads/1", [{"href": "/orgs/1/labels/77"}])]


def test_quarantine_lift_skips_not_quarantined(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    monkeypatch.setattr("src.api_client.ApiClient.check_and_create_quarantine_labels",
                        lambda self: {"Mild": "/orgs/1/labels/1"})
    monkeypatch.setattr("src.api_client.ApiClient.get_workload", lambda self, href: {
        "href": href, "labels": [{"href": "/orgs/1/labels/77"}]})
    calls = []
    monkeypatch.setattr("src.api_client.ApiClient.update_workload_labels",
                        lambda self, href, labels: calls.append(href) or True)

    r = client.post('/api/quarantine/lift',
                    json={"hrefs": ["/orgs/1/workloads/1", "/orgs/1/labels/9"]},
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                    headers={'X-CSRF-Token': csrf_token})
    assert r.json["results"]["not_quarantined"] == 1
    assert r.json["results"]["skipped_invalid"] == 1
    assert calls == []


def test_quarantine_bulk_apply_writes_audit_log(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    monkeypatch.setattr("src.api_client.ApiClient.check_and_create_quarantine_labels",
                        lambda self: {"Mild": "/orgs/1/labels/1"})
    monkeypatch.setattr("src.api_client.ApiClient.get_workload",
                        lambda self, href: {"href": href, "labels": []})
    monkeypatch.setattr("src.api_client.ApiClient.update_workload_labels",
                        lambda self, href, labels: True)

    records = []

    class _Rec:
        def info(self, msg):
            records.append(msg)

    from src.module_log import ModuleLog
    monkeypatch.setattr(ModuleLog, "get", classmethod(lambda cls, name: _Rec()))

    client.post('/api/quarantine/bulk_apply',
                json={"hrefs": ["/orgs/1/workloads/1", "/orgs/1/workloads/2"], "level": "Mild"},
                environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                headers={'X-CSRF-Token': csrf_token})
    audit = [m for m in records if "quarantine_bulk_apply" in m]
    assert len(audit) == 1
    assert "success=2" in audit[0]
