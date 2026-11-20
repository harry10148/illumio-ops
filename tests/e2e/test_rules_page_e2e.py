from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from playwright.sync_api import expect

from illumio_ops.store.flowdb import ip_lists
from tests.e2e.conftest import sign_in
from tests.e2e.test_rule_form_acceptance_e2e import OTHER_SHAPES


def _settings_rules(live_app) -> list[dict]:
    return [rule.model_dump(mode="json") for rule in live_app.ctx.settings.current().alerts.rules]


def _add_rules(live_app, rules: list[dict]) -> None:
    live_app.ctx.settings.update(live_app.ctx.settings.current().revision,
                                 lambda data: data["alerts"]["rules"].extend(rules))


def test_each_rule_appears_once_in_the_table_for_its_kind(context, live_app):
    rules = _settings_rules(live_app)
    assert len(rules) == 35 and all(rule["pack_key"] for rule in rules)
    extra = [rule | {"id": uuid.uuid4().hex} for rule in OTHER_SHAPES]
    _add_rules(live_app, extra)

    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules")
    page.locator("[data-role=rules-event]").wait_for()
    all_rows = page.locator(".rules-table tr[data-rule-id]")
    expect(all_rows).to_have_count(len(rules) + len(extra))
    for rule in rules + extra:
        row = page.locator(f"tr[data-rule-id='{rule['id']}']")
        expect(row).to_have_count(1)
        kind = "event" if rule["type"] == "event" else "flow" if rule["type"] in {"traffic", "bandwidth", "volume"} else "special"
        expect(page.locator(f"[data-role=rules-{kind}] tr[data-rule-id='{rule['id']}']")).to_have_count(1)
        for other in {"event", "flow", "special"} - {kind}:
            expect(page.locator(f"[data-role=rules-{other}] tr[data-rule-id='{rule['id']}']")).to_have_count(0)


def test_three_state_control_sends_whole_rule_and_preserves_other_fields(context, live_app):
    rule = {"id": "e" * 32, "name": "State transitions", "pack_key": None, "enabled": True, "notify": True,
            "severity": None, "cooldown_minutes": 45, "throttle": {"count": 2, "period_minutes": 90},
            "type": "event", "event_types": ["user.sign_in"], "status": "failure", "event_severity": "err|warning",
            "match_fields": {"created_by.user.username": "!admin"}, "threshold": "count", "threshold_count": 4,
            "window_minutes": 15}
    _add_rules(live_app, [rule])
    before = rule.copy()
    payloads: list[dict] = []
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules")
    group = page.locator(f"tr[data-rule-id='{rule['id']}'] [data-role=rule-state]")

    def capture(request):
        if request.method == "PUT" and f"/{rule['id']}" in request.url:
            payloads.append(json.loads(request.post_data or "{}"))

    page.on("request", capture)
    for state, expected_enabled, expected_notify in (("rec", True, False), ("off", False, False), ("on", True, True)):
        group.locator(f"input[value='{state}']").check()
        expect(group.locator("input:checked")).to_have_attribute("value", state)
        expect(group).to_have_attribute("data-state", "saved")  # the pick shows at once; the settings change on save
        current = next(r for r in _settings_rules(live_app) if r["id"] == rule["id"])
        assert current["enabled"] is expected_enabled and current["notify"] is expected_notify
        assert {k: v for k, v in current.items() if k not in {"enabled", "notify"}} == {
            k: v for k, v in before.items() if k not in {"enabled", "notify"}}
    assert len(payloads) == 3
    for sent, state in zip(payloads, ("rec", "off", "on"), strict=True):
        assert isinstance(sent["revision"], int)
        assert sent["rule"]["enabled"] is (state != "off")
        assert sent["rule"]["notify"] is (state == "on")
        assert {k: v for k, v in sent["rule"].items() if k not in {"enabled", "notify"}} == {
            k: v for k, v in before.items() if k not in {"enabled", "notify"}}


def test_state_save_failure_reverts_and_shows_the_error(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules")
    group = page.locator("[data-role=rules-event] [data-role=rule-state]").first
    before = group.locator("input:checked").get_attribute("value")
    page.route("**/api/alert-rules/*", lambda route: route.fulfill(
        status=500, content_type="application/json",
        body='{"ok": false, "data": null, "error": {"code": "internal", "message_key": "error_internal", "params": {}}}')
        if route.request.method == "PUT" else route.continue_())
    next_state = "off" if before != "off" else "rec"
    group.locator(f"input[value='{next_state}']").check()
    expect(group).to_have_attribute("data-state", "failed")
    expect(group.locator("input:checked")).to_have_attribute("value", before)
    expect(page.locator(".form-error")).to_be_visible()


def test_conditions_thresholds_named_ip_lists_and_search(context, live_app):
    ip_list_href = "/orgs/1/sec_policy/active/ip_lists/7"
    with live_app.ctx.flows().connect() as conn:
        ip_lists.replace_all(conn, [ip_lists.IpListRow(ip_list_href, "Scanner addresses", ("10.8.0.0/16",))],
                             at=datetime(2026, 11, 20, tzinfo=UTC))
        conn.commit()
    base = {"pack_key": None, "enabled": True, "notify": True, "cooldown_minutes": 0, "throttle": None}
    event = base | {"id": "f" * 32, "name": "Field paths", "severity": None, "type": "event",
                    "event_types": ["user.sign_in", "vendor.login"], "status": "failure", "event_severity": "err|warning",
                    "match_fields": {"created_by.user.username": "!admin", "notification_type": "hard_limit.exceeded"},
                    "threshold": "immediate", "threshold_count": 1, "window_minutes": 10}
    excluded = base | {"id": "a" * 32, "name": "Exclude scanner", "severity": "high", "type": "traffic",
                "condition": {"src": {"ips": ["10.1.2.3"], "ip_lists": [ip_list_href]},
                              "src_exclude": {"ips": ["10.9.9.9"]}, "exclude_ports": [{"port": 22, "proto": 6}]},
                "threshold_connections": 25, "window_minutes": 10}
    thresholds = [
        base | {"id": "1" * 32, "name": "Event immediate", "severity": None, "type": "event", "event_types": ["user.login"],
               "status": "all", "event_severity": "all", "match_fields": {}, "threshold": "immediate", "threshold_count": 1, "window_minutes": 10},
        base | {"id": "2" * 32, "name": "Event each check", "severity": None, "type": "event", "event_types": ["user.login"],
               "status": "all", "event_severity": "all", "match_fields": {}, "threshold": "immediate", "threshold_count": 3, "window_minutes": 10},
        base | {"id": "3" * 32, "name": "Event count", "severity": None, "type": "event", "event_types": ["user.login"],
               "status": "all", "event_severity": "all", "match_fields": {}, "threshold": "count", "threshold_count": 5, "window_minutes": 15},
        base | {"id": "4" * 32, "name": "Traffic threshold", "severity": "medium", "type": "traffic", "condition": {}, "threshold_connections": 25, "window_minutes": 10},
        base | {"id": "5" * 32, "name": "Bandwidth threshold", "severity": "medium", "type": "bandwidth", "condition": {}, "threshold_mbps": 80, "window_minutes": 60},
        base | {"id": "6" * 32, "name": "Volume threshold", "severity": "medium", "type": "volume", "condition": {}, "threshold_mb": 2048, "window_minutes": 120},
    ]
    _add_rules(live_app, [event, excluded, *thresholds])

    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules")
    event_row = page.locator(f"tr[data-rule-id='{event['id']}']")
    expect(event_row.locator("[data-role=rule-condition]")).to_contain_text("created_by.user.username = !admin")
    expect(event_row.locator("[data-role=rule-condition]")).to_contain_text("notification_type = hard_limit.exceeded")
    expect(event_row.locator("[data-role=rule-condition]")).to_contain_text("failure only")
    flow_row = page.locator(f"tr[data-rule-id='{excluded['id']}']")
    expect(flow_row.locator("[data-role=rule-condition]")).to_contain_text("10.1.2.3")
    expect(flow_row.locator("[data-role=rule-condition]")).to_contain_text("Scanner addresses")
    expect(flow_row.locator("[data-role=rule-exclusion]")).to_contain_text("10.9.9.9")
    expect(flow_row.locator("[data-role=rule-exclusion]")).to_contain_text("22")

    for rid, expected in (("1" * 32, "each occurrence"), ("2" * 32, "same host ≥ 3"), ("3" * 32, "15 min, ≥ 5 times")):
        expect(page.locator(f"tr[data-rule-id='{rid}'] [data-role=rule-threshold]")).to_contain_text(expected)
    for rid, expected in (("4" * 32, "10 min, ≥ 25 connections"), ("5" * 32, "rate ≥ 80 Mbps"), ("6" * 32, "transfer ≥ 2048 MB")):
        expect(page.locator(f"tr[data-rule-id='{rid}'] [data-role=rule-threshold]")).to_contain_text(expected)
    expect(page.locator(f"tr[data-rule-id='{event['id']}'] .rules-activity")).to_contain_text("No trigger recorded")

    search = page.get_by_role("searchbox", name="Search rules")
    for term, rid, table in (("vendor.login", event["id"], "event"), ("10.1.2.3", excluded["id"], "flow"),
                             ("Scanner addresses", excluded["id"], "flow")):
        search.fill(term)
        expect(page.locator(f"[data-role=rules-{table}] tr[data-rule-id='{rid}']")).to_have_count(1)
        expect(page.locator(".rules-table tr[data-rule-id]")).to_have_count(1)


def test_header_counts_include_all_kinds_and_three_states(context, live_app):
    rules = _settings_rules(live_app)
    rules.extend([
        {"id": "b" * 32, "name": "Count record", "pack_key": None, "enabled": True, "notify": False,
         "severity": None, "cooldown_minutes": 0, "throttle": None, "type": "event", "event_types": ["user.login"],
         "status": "all", "event_severity": "all", "match_fields": {}, "threshold": "immediate", "threshold_count": 1, "window_minutes": 10},
        {"id": "c" * 32, "name": "Count off", "pack_key": None, "enabled": False, "notify": True, "severity": "high",
         "cooldown_minutes": 0, "throttle": None, "type": "system", "check": "siem_backlog"},
    ])
    live_app.ctx.settings.update(live_app.ctx.settings.current().revision, lambda data: data["alerts"].__setitem__("rules", rules))
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules")
    summary = page.locator("[data-role=rules-summary]")
    expect(summary).to_contain_text(f"Event rules {sum(r['type'] == 'event' for r in rules)}")
    expect(summary).to_contain_text(f"Traffic rules {sum(r['type'] in {'traffic', 'bandwidth', 'volume'} for r in rules)}")
    expect(summary).to_contain_text(f"Detections and system checks {sum(r['type'] in {'lateral', 'system'} for r in rules)}")
    expect(summary).to_contain_text(f"Notifying {sum(r['enabled'] and r['notify'] for r in rules)}")
    expect(summary).to_contain_text(f"Recording only {sum(r['enabled'] and not r['notify'] for r in rules)}")
    expect(summary).to_contain_text(f"Disabled {sum(not r['enabled'] for r in rules)}")
    expect(summary).to_contain_text("Triggers in the last 7 days 0")

