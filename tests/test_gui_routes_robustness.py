"""Robustness tests for GUI route error/edge paths.

Covers the non-i18n correctness fixes:
  * reports.py — `lang` must be bound BEFORE the try so an early failure
    returns a clean localized error via `_err_with_log` instead of raising
    UnboundLocalError (which masked the real error under a different request_id).
  * rule_scheduler.py / admin.py — unguarded int() on query params must not
    surface as a 500.
  * rule_scheduler.py — rs_schedule_delete must tolerate an empty/null body.
"""
from unittest.mock import patch

from tests._helpers import _csrf


def _login(client):
    login = client.post(
        "/api/login",
        json={"username": "admin", "password": "testpass"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert login.status_code == 200
    return _csrf(login)


# ── Fix 1: reports.py `lang` UnboundLocalError in error handlers ──────────────
# Patch each generator so construction raises BEFORE the point where `lang` used
# to be assigned (inside the try). With the bug, the except's
# `_err_with_log(..., lang=lang)` raised UnboundLocalError and the handler's
# category never reached the log; with the fix it logs the handler category and
# never logs UnboundLocalError.

def _assert_clean_early_failure(resp, caplog, category):
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["ok"] is False
    assert "request_id" in body
    # The handler's own _err_with_log ran → `lang` was bound in the except.
    assert category in caplog.text
    assert "UnboundLocalError" not in caplog.text


def test_audit_report_early_failure_no_unbound_lang(client, caplog):
    csrf = _login(client)
    with patch("src.report.audit_generator.AuditGenerator", side_effect=RuntimeError("boom")):
        r = client.post(
            "/api/audit_report/generate",
            json={"lang": "zh_TW"},
            headers={"X-CSRF-Token": csrf},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
    _assert_clean_early_failure(r, caplog, "report_audit_generate")


def test_ven_status_report_early_failure_no_unbound_lang(client, caplog):
    csrf = _login(client)
    with patch("src.report.ven_status_generator.VenStatusGenerator", side_effect=RuntimeError("boom")):
        r = client.post(
            "/api/ven_status_report/generate",
            json={"lang": "zh_TW"},
            headers={"X-CSRF-Token": csrf},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
    _assert_clean_early_failure(r, caplog, "report_ven_status_generate")


def test_policy_usage_report_early_failure_no_unbound_lang(client, caplog):
    csrf = _login(client)
    with patch("src.report.policy_usage_generator.PolicyUsageGenerator", side_effect=RuntimeError("boom")):
        r = client.post(
            "/api/policy_usage_report/generate",
            json={"lang": "zh_TW"},
            headers={"X-CSRF-Token": csrf},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
    _assert_clean_early_failure(r, caplog, "report_policy_usage_generate")


# ── Fix 4: unguarded int() on query params → must not 500 ─────────────────────

def test_rs_rulesets_non_numeric_page_size_does_not_500(client):
    _login(client)
    with patch("src.api_client.ApiClient.update_label_cache", return_value=None), \
         patch("src.api_client.ApiClient.get_all_rulesets", return_value=[]):
        r = client.get(
            "/api/rule_scheduler/rulesets?page=abc&size=xyz",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
    assert r.status_code == 200
    body = r.get_json()
    assert body["page"] == 1 and body["size"] == 50
    assert body["items"] == []


def test_api_log_get_non_numeric_n_does_not_500(client):
    _login(client)
    r = client.get(
        "/api/logs/reports?n=abc",
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["module"] == "reports"


# ── Fix 5: rs_schedule_delete must tolerate a null/empty JSON body ────────────

def test_rs_schedule_delete_null_body_does_not_500(client):
    csrf = _login(client)
    r = client.post(
        "/api/rule_scheduler/schedules/delete",
        data="null",
        content_type="application/json",
        headers={"X-CSRF-Token": csrf},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["deleted"] == []


def test_rs_schedule_create_missing_type_rejected(client):
    """BUG-3（2026-07-24 審查）：缺 type 不得存成畸形 recurring（無 days）
    導致 check() 每 tick KeyError；直接 400。"""
    csrf = _login(client)
    # 端點改用三態的 get_provision_state（'unknown' 要能與 'draft' 區分），
    # is_provisioned 已不在這條路徑上。
    with patch("src.api_client.ApiClient.has_draft_changes", lambda self, h: False), \
         patch("src.api_client.ApiClient.get_provision_state", lambda self, h: 'active'):
        r = client.post(
            "/api/rule_scheduler/schedules",
            json={"href": "/orgs/1/sec_policy/active/rule_sets/1", "name": "x"},
            headers={"X-CSRF-Token": csrf},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
    assert r.status_code == 400


def test_rs_schedule_create_unknown_type_rejected(client):
    csrf = _login(client)
    with patch("src.api_client.ApiClient.has_draft_changes", lambda self, h: False), \
         patch("src.api_client.ApiClient.get_provision_state", lambda self, h: 'active'):
        r = client.post(
            "/api/rule_scheduler/schedules",
            json={"href": "/orgs/1/sec_policy/active/rule_sets/1", "name": "x", "type": "weird"},
            headers={"X-CSRF-Token": csrf},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
    assert r.status_code == 400


# ── #13: server must derive is_ruleset from the href, not trust the caller ────

def test_rs_schedule_create_derives_is_ruleset_from_href(client, monkeypatch, tmp_path, caplog):
    """toggle_and_provision picks its provisioning scope (the object itself vs.
    its parent ruleset) from the stored is_ruleset flag. Today's v2 front end
    derives it correctly from the href (automation.mjs RULE_HREF), but the
    endpoint accepted any caller's claim verbatim — a direct API call or a
    tampered request could desync it from the href. Send a href that is a rule
    (matches one of the three PCE rule collections api_client.py's
    has_draft_changes checks, Task 4 6a6f8e83: sec_rules/deny_rules/rules)
    together with a claim of is_ruleset=True, and assert the stored value is
    the href-derived False, with a warning logged about the disagreement."""
    import json
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr("src.gui.routes.rule_scheduler._resolve_config_dir",
                        lambda: str(config_dir))

    csrf = _login(client)
    href = "/orgs/1/sec_policy/active/rule_sets/1/sec_rules/7"
    with patch("src.api_client.ApiClient.has_draft_changes", lambda self, h: False), \
         patch("src.api_client.ApiClient.get_provision_state", lambda self, h: 'active'), \
         patch("src.api_client.ApiClient.update_rule_note", lambda self, h, n: True):
        r = client.post(
            "/api/rule_scheduler/schedules",
            json={
                "href": href, "name": "x", "type": "recurring",
                "is_ruleset": True,  # WRONG on purpose: href is a rule
                "days": ["mon"], "start": "00:00", "end": "01:00",
            },
            headers={"X-CSRF-Token": csrf},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
    assert r.status_code == 200

    stored = json.loads((config_dir / "rule_schedules.json").read_text(encoding="utf-8"))
    assert stored[href]["is_ruleset"] is False
    assert "is_ruleset" in caplog.text
