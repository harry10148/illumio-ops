"""notification_type extraction and rule matching (capacity alerts rely on it:
hard_limit.exceeded / soft_limit.exceeded are notification types, not event types)."""
from __future__ import annotations

import pytest

from src.events.matcher import matches_event_rule
from src.events.normalizer import normalize_event

PRUNE_EVENT = {
    "href": "/orgs/1/events/abc",
    "event_type": "system_task.prune_old_log_events",
    "timestamp": "2026-07-04T03:00:00Z",
    "severity": "err",
    "status": None,
    "notifications": [
        {"notification_type": "hard_limit.exceeded", "info": {}},
    ],
}


def test_normalizer_extracts_notification_types():
    norm = normalize_event(PRUNE_EVENT)
    assert norm["notification_types"] == ["hard_limit.exceeded"]


def test_normalizer_handles_missing_notifications():
    norm = normalize_event({"event_type": "user.login", "timestamp": "2026-07-04T00:00:00Z"})
    assert norm["notification_types"] == []


def test_rule_matches_on_notification_type():
    rule = {
        "filter_value": "system_task.prune_old_log_events",
        "filter_status": "all",
        "filter_severity": "all",
        "match_fields": {"notification_type": "hard_limit.exceeded|soft_limit.exceeded"},
    }
    assert matches_event_rule(rule, PRUNE_EVENT)


def test_rule_rejects_when_notification_type_absent():
    rule = {
        "filter_value": "system_task.prune_old_log_events",
        "filter_status": "all",
        "filter_severity": "all",
        "match_fields": {"notification_type": "hard_limit.exceeded"},
    }
    benign = dict(PRUNE_EVENT, notifications=[{"notification_type": "system_task.event_pruning_completed"}])
    assert not matches_event_rule(rule, benign)


# ── severity：PCE 實際送 "err"，GUI/CLI 存的是 "error" ─────────────────────────

def _sev_rule(sev):
    return {"filter_value": "agent.tampering", "filter_status": "all",
            "filter_severity": sev}


def _sev_event(sev):
    return {"event_type": "agent.tampering", "status": "success", "severity": sev}


@pytest.mark.parametrize("rule_sev,event_sev,expected", [
    ("error", "err", True),          # GUI/CLI 選 error 必須命中 PCE 的 err
    ("err", "err", True),
    ("error", "error", True),
    ("error", "warning", False),
    ("error|warning", "err", True),
    ("!error", "err", False),
    ("!error", "info", True),
    ("all", "err", True),
    ("ERROR", "err", True),
])
def test_severity_err_error_alias(rule_sev, event_sev, expected):
    from src.events.matcher import matches_event_rule
    assert matches_event_rule(_sev_rule(rule_sev), _sev_event(event_sev)) is expected


_LOGIN_FAILED = {
    "href": "/orgs/1/events/login-fail",
    "event_type": "user.sign_in",
    "status": "failure",
    "severity": "info",
    "timestamp": "2026-09-11T03:04:05Z",
    "created_by": {"system": {}},
    "notifications": [{
        "notification_type": "user.login_failed",
        # REST API 文件 user.sign_in failure 範例的形狀
        "info": {"associated_user": {"supplied_username": "attacker@example.com"}},
    }],
}


def test_login_failure_target_is_the_supplied_username():
    """登入失敗的帳號在 info.associated_user.supplied_username；舊版只讀
    info.user，告警看不出是哪個帳號在嘗試登入（created_by 本來就是 system）。"""
    normalized = normalize_event(_LOGIN_FAILED)
    assert normalized["target_type"] == "user"
    assert normalized["target_name"] == "attacker@example.com"


def test_audit_report_reads_supplied_username_from_associated_user():
    from src.report.audit_generator import _extract_supplied_username
    assert _extract_supplied_username(_LOGIN_FAILED["notifications"]) == "attacker@example.com"
    legacy = [{"info": {"supplied_username": "old@example.com"}}]
    assert _extract_supplied_username(legacy) == "old@example.com"
