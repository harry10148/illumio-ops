"""GUI endpoint tests for rule hit count enablement + generation routes."""
from unittest.mock import MagicMock, patch

from tests._helpers import _csrf

from src.api.reports import RuleHitCountPullTimeout
from src.report.rule_hit_count_enablement import EnablementStatus, RuleHitCountNotEnabled


def _login(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200
    return _csrf(login)


def _fake_result(count=3):
    r = MagicMock()
    r.record_count = count
    r.module_results = {"kpis": {"total_rules": count, "hit_rules": 1}}
    return r


def test_enablement_status_endpoint(client):
    _login(client)
    st = EnablementStatus("partial", True, False, "missing: VEN firewall_settings scopes")
    with patch("src.gui.routes.reports.check_enablement", return_value=st):
        r = client.get("/api/rule_hit_count/enablement",
                       environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    body = r.get_json()
    assert body["ok"] is True
    assert body["state"] == "partial"
    assert body["pce_report_enabled"] is True


def test_enable_endpoint_runs_enable(client):
    csrf_token = _login(client)
    with patch("src.gui.routes.reports.enable_rule_hit_count",
               return_value=["pce_report_template", "ven_firewall_settings_draft",
                             "provisioned"]) as en:
        r = client.post("/api/rule_hit_count/enable", json={},
                        headers={"X-CSRF-Token": csrf_token},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    body = r.get_json()
    assert body["ok"] is True
    assert body["steps_done"][-1] == "provisioned"
    # GUI v1 enables ALL VENs — scopes must be None
    assert en.call_args.kwargs.get("scopes") is None


def test_generate_native_returns_files(client):
    csrf_token = _login(client)
    with patch("src.report.rule_hit_count_generator.RuleHitCountGenerator") as MockGen:
        MockGen.return_value.generate_from_native.return_value = _fake_result()
        MockGen.return_value.export.return_value = [
            "/tmp/x/Illumio_Rule_Hit_Count_Report_x.html"]
        r = client.post(
            "/api/rule_hit_count_report/generate",
            json={"source": "native", "lang": "zh_TW", "format": "html"},
            headers={"X-CSRF-Token": csrf_token},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        )
    body = r.get_json()
    assert body["ok"] is True
    assert body["files"] == ["Illumio_Rule_Hit_Count_Report_x.html"]


def test_generate_not_enabled_returns_needs_enablement(client):
    csrf_token = _login(client)
    exc = RuleHitCountNotEnabled(EnablementStatus("disabled", False, False, "off"))
    with patch("src.report.rule_hit_count_generator.RuleHitCountGenerator") as MockGen:
        MockGen.return_value.generate_from_native.side_effect = exc
        r = client.post(
            "/api/rule_hit_count_report/generate",
            json={"source": "native", "lang": "en"},
            headers={"X-CSRF-Token": csrf_token},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        )
    body = r.get_json()
    assert body["ok"] is False
    assert body["needs_enablement"] is True
    assert body["state"] == "disabled"


def test_generate_native_pull_timeout_returns_pull_timeout_flag(client):
    """Finding 1: RuleHitCountPullTimeout must not fall into the generic 500
    handler — the GUI needs to tell the caller the PCE is still preparing the
    report, distinct from a hard failure."""
    csrf_token = _login(client)
    exc = RuleHitCountPullTimeout("/orgs/1/reports/abc123")
    with patch("src.report.rule_hit_count_generator.RuleHitCountGenerator") as MockGen:
        MockGen.return_value.generate_from_native.side_effect = exc
        r = client.post(
            "/api/rule_hit_count_report/generate",
            json={"source": "native", "lang": "en"},
            headers={"X-CSRF-Token": csrf_token},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        )
    body = r.get_json()
    assert body["ok"] is False
    assert body["pull_timeout"] is True
    assert body["error"]
    assert "Internal server error" not in body.get("error", "")
    assert r.status_code != 500


def test_enable_endpoint_writes_audit_log(client, monkeypatch):
    """Finding 2: enable success must be recorded in the actions audit log
    (operator + result), mirroring actions.py's _audit_action convention."""
    csrf_token = _login(client)

    records = []

    class _Rec:
        def info(self, msg):
            records.append(msg)

    from src.module_log import ModuleLog
    monkeypatch.setattr(ModuleLog, "get", classmethod(
        lambda cls, name: _Rec() if name == "actions" else MagicMock()))

    with patch("src.gui.routes.reports.enable_rule_hit_count",
               return_value=["pce_report_template", "ven_firewall_settings_draft",
                             "provisioned"]):
        r = client.post("/api/rule_hit_count/enable", json={},
                        headers={"X-CSRF-Token": csrf_token},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert r.get_json()["ok"] is True
    audit = [m for m in records if "rule_hit_count_enable" in m]
    assert len(audit) == 1
    assert "user=admin" in audit[0]
