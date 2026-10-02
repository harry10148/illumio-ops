"""Regression tests for the security review fixes: credential redirect on a
host change, report endpoints scoped to report files, strict href shapes,
request caps, and one-line JSON audit records."""
import json
import os
import tempfile

import pytest

from src.config import ConfigManager, hash_password
from src.gui import build_app as _create_app
from src.gui._helpers import (
    _is_forbidden_report_output_dir,
    _is_report_file,
    _is_rule_href,
    _is_workload_href,
    _resolve_reports_dir,
)
from tests._helpers import _csrf

LOCAL = {"REMOTE_ADDR": "127.0.0.1"}


@pytest.fixture
def app(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump({
            "api": {"url": "https://pce.example.com:8443", "key": "k",
                    "secret": "real-secret", "org_id": "1"},
            "smtp": {"host": "smtp.example.com", "port": 587, "password": "smtp-pw"},
            "report": {"output_dir": str(tmp_path / "reports")},
            "rules": [],
        }, f)
    cm = ConfigManager(config_file=path)
    cm.load()
    cm.config["web_gui"] = {"username": "admin", "password": hash_password("testpass"),
                            "allowed_ips": [], "secret_key": "test-secret"}
    cm.save()
    application = _create_app(cm, persistent_mode=True)
    application.config.update({"TESTING": True})
    yield application
    os.unlink(path)


@pytest.fixture
def authed(app):
    client = app.test_client()
    login = client.post("/api/login", json={"username": "admin", "password": "testpass"},
                        environ_overrides=LOCAL)
    assert login.status_code == 200
    return client, _csrf(login)


def _post(client, csrf, url, body):
    return client.post(url, json=body, headers={"X-CSRFToken": csrf}, environ_overrides=LOCAL)


# ── Stored secrets never follow an address change on their own ───────────────

def test_new_pce_host_without_secret_is_refused(authed, app):
    client, csrf = authed
    res = _post(client, csrf, "/api/settings",
                {"api": {"url": "https://attacker.example.com:8443"}, "pce_target_change": "same-pce"})
    assert res.status_code == 400
    cm = app.config["CM"]
    cm.load()
    assert cm.config["api"]["url"] == "https://pce.example.com:8443"


def test_new_pce_host_with_secret_is_accepted(authed, app):
    client, csrf = authed
    res = _post(client, csrf, "/api/settings",
                {"api": {"url": "https://pce2.example.com:8443", "secret": "typed-again"},
                 "pce_target_change": "same-pce"})
    assert res.status_code == 200, res.get_json()


def test_same_pce_host_other_path_needs_no_secret(authed):
    """Only host/port matter; re-saving the same address is not a move."""
    client, csrf = authed
    res = _post(client, csrf, "/api/settings", {"api": {"url": "https://pce.example.com:8443"}})
    assert res.status_code == 200, res.get_json()


def test_new_smtp_host_without_password_is_refused(authed, app):
    client, csrf = authed
    res = _post(client, csrf, "/api/settings", {"smtp": {"host": "attacker.example.com"}})
    assert res.status_code == 400
    cm = app.config["CM"]
    cm.load()
    assert cm.config["smtp"]["host"] == "smtp.example.com"
    res = _post(client, csrf, "/api/settings",
                {"smtp": {"host": "smtp2.example.com", "password": "pw2"}})
    assert res.status_code == 200


# ── Report endpoints serve report files only, never config/state ─────────────

def test_report_output_dir_may_not_overlap_app_dirs():
    for bad in ("config", "logs", "data", "src", ".", "config/sub"):
        assert _is_forbidden_report_output_dir(bad), bad
    assert not _is_forbidden_report_output_dir("reports/")


def test_settings_refuses_report_dir_pointing_at_config(authed, app):
    client, csrf = authed
    res = _post(client, csrf, "/api/settings", {"report": {"output_dir": "config"}})
    assert res.status_code == 400


def test_report_endpoints_refuse_non_report_files(authed, app):
    client, csrf = authed
    reports_dir = _resolve_reports_dir(app.config["CM"])
    os.makedirs(reports_dir, exist_ok=True)
    with open(os.path.join(reports_dir, "secrets.txt"), "w") as f:
        f.write("x")
    with open(os.path.join(reports_dir, "r.html"), "w") as f:
        f.write("<p>ok</p>")
    assert client.get("/reports/secrets.txt", environ_overrides=LOCAL).status_code == 403
    assert client.get("/reports/r.html", environ_overrides=LOCAL).status_code == 200
    res = client.delete("/api/reports/secrets.txt", headers={"X-CSRFToken": csrf},
                        environ_overrides=LOCAL)
    assert res.status_code == 400
    assert os.path.exists(os.path.join(reports_dir, "secrets.txt"))


def test_is_report_file_extension_and_location(tmp_path):
    assert _is_report_file(str(tmp_path / "a.html"))
    assert not _is_report_file(str(tmp_path / "a.db"))
    assert not _is_report_file(str(tmp_path / "config.json.bak"))


# ── Strict href shapes for PCE writes ────────────────────────────────────────

@pytest.mark.parametrize("href,ok", [
    ("/orgs/1/workloads/0b5c4c1e-1111-2222-3333-444455556666", True),
    ("/orgs/1/workloads/abc", True),
    ("/orgs/1/workloads/abc/../../labels/1", False),
    ("/orgs/1/workloads/", False),
    ("/orgs/x/workloads/1", False),
    ("/orgs/1/labels/1", False),
    ("/orgs/1/workloads/1?x=1", False),
])
def test_workload_href_shape(href, ok):
    assert _is_workload_href(href) is ok


@pytest.mark.parametrize("href,ok", [
    ("/orgs/1/sec_policy/draft/rule_sets/12", True),
    ("/orgs/1/sec_policy/active/rule_sets/12/sec_rules/3", True),
    ("/orgs/1/sec_policy/draft/rule_sets/12/deny_rules/3", True),
    ("/orgs/1/sec_policy/draft/rule_sets/12/../../firewall_settings", False),
    ("/orgs/1/sec_policy/draft/firewall_settings", False),
    ("/orgs/1/workloads/1", False),
])
def test_rule_href_shape(href, ok):
    assert _is_rule_href(href) is ok


def test_rule_schedule_create_refuses_non_rule_href(authed):
    client, csrf = authed
    res = _post(client, csrf, "/api/rule_scheduler/schedules",
                {"href": "/orgs/1/sec_policy/draft/firewall_settings", "type": "one_time"})
    assert res.status_code == 400


def test_quarantine_bulk_apply_is_capped(authed):
    client, csrf = authed
    hrefs = [f"/orgs/1/workloads/{i}" for i in range(501)]
    res = _post(client, csrf, "/api/quarantine/bulk_apply", {"hrefs": hrefs, "level": "Mild"})
    assert res.status_code == 400


# ── Audit records ────────────────────────────────────────────────────────────

def test_login_attempts_are_audited(app, monkeypatch):
    records = []

    class _Rec:
        def info(self, msg):
            records.append(msg)

    from src.module_log import ModuleLog
    monkeypatch.setattr(ModuleLog, "get", classmethod(lambda cls, name: _Rec()))
    client = app.test_client()
    client.post("/api/login", json={"username": "admin", "password": "wrong"}, environ_overrides=LOCAL)
    client.post("/api/login", json={"username": "admin", "password": "testpass"}, environ_overrides=LOCAL)
    entries = [json.loads(m) for m in records if m.startswith("{")]
    logins = [e for e in entries if e["action"] == "login"]
    assert [e["result"] for e in logins] == ["failure", "success"]
    assert all(e["user"] == "admin" and e["remote_addr"] == "127.0.0.1" for e in logins)


def test_module_log_keeps_one_entry_per_line(tmp_path):
    from src.module_log import ModuleLog
    log = ModuleLog("crlf_test")
    log.info("quarantine_apply: href=/orgs/1/workloads/1\r\n2026-01-01 [INFO ] forged")
    msg = log._buffer[-1]["msg"]
    assert "\n" not in msg and "\r" not in msg
    assert "\\r\\n" in msg


# ── Channel secrets stay out of error text ───────────────────────────────────

def test_webhook_error_text_never_carries_the_url():
    from types import SimpleNamespace
    from src.alerts.plugins import WebhookAlertPlugin, scrub_webhook_url

    secret_url = "hooks.example.com/services/T000/B000/SECRETTOKEN"  # no scheme → ValueError
    cm = SimpleNamespace(config={"alerts": {"webhook_url": secret_url}})
    reporter = SimpleNamespace(_build_webhook_payload=lambda subject: {"text": subject})
    res = WebhookAlertPlugin(cm).send(reporter, "s")
    assert res["status"] == "failed"
    assert "SECRETTOKEN" not in res["error"] and "SECRETTOKEN" not in res["target"]

    full = "https://hooks.example.com/services/T000/B000/SECRETTOKEN?sig=abc"
    msg = scrub_webhook_url(f"502 for POST /services/T000/B000/SECRETTOKEN?sig=abc and {full}", full)
    assert "SECRETTOKEN" not in msg and "sig=abc" not in msg
