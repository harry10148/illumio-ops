"""Acceptance of the rule form (purpose-led UI spec §11, stage 4): three rules made from the rule list with nothing
but the page, each the rule the full form would have saved; and every rule there is — the built-in pack and the
shapes it does not have — opened and saved without a change, coming back exactly as it was."""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from illumio_ops.domain.alertpack import pack_rule_id
from tests.e2e.conftest import sign_in


def _rules(live_app) -> dict[str, dict]:
    return {r.id: r.model_dump(mode="json") for r in live_app.ctx.settings.current().alerts.rules}


def _named(live_app, name: str) -> dict:
    rule = next(r for r in _rules(live_app).values() if r["name"] == name)
    return {k: v for k, v in rule.items() if k not in ("id", "name")}


def _save(page) -> None:
    page.locator("[data-role=rule-editor]").get_by_role("button", name="Save").click()
    page.wait_for_selector("[data-role=rule-list]")


def _from_the_list(page, live_app, scenario: str):
    """Rule list → New rule → the scenario's "New": only what a reader can press."""
    page.goto(f"{live_app.url}/alert-rules")
    page.get_by_role("link", name="New rule").click()
    page.locator(f"[data-role=scenario-list] [data-scenario='{scenario}'] [data-role=scenario-new]").click()
    page.wait_for_selector("[data-role=short-form]")
    return page.locator("[data-role=rule-editor]")


def _full_form(page, live_app, rule_type: str):
    page.goto(f"{live_app.url}/alerts/rules/new?form=full")
    form = page.locator("[data-role=rule-editor]")
    form.locator("select[name=type]").select_option(rule_type)
    return form


def test_three_rules_made_from_the_rule_list(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)

    # 1. an event rule: pick the category, tick an event, save
    form = _from_the_list(page, live_app, "event:policy")
    form.locator("input[name=name]").fill("Label deleted")
    form.locator("[data-role=event-checklist] input[data-event-type='label.delete']").check()
    _save(page)
    form = _full_form(page, live_app, "event")
    form.locator("input[name=name]").fill("Label deleted, full form")
    form.locator("input[name=event_types]").fill("label.delete")
    _save(page)
    assert _named(live_app, "Label deleted") == _named(live_app, "Label deleted, full form")

    # 2. a traffic rule: pick the connections scenario, give the threshold, save
    form = _from_the_list(page, live_app, "flow:traffic")
    form.locator("input[name=name]").fill("Many connections")
    form.locator("input[name=threshold]").fill("500")
    form.locator("input[name=window_minutes]").fill("30")
    _save(page)
    form = _full_form(page, live_app, "traffic")
    form.locator("input[name=name]").fill("Many connections, full form")
    form.locator("input[name=threshold]").fill("500")
    form.locator("input[name=window_minutes]").fill("30")
    _save(page)
    made = _named(live_app, "Many connections")
    assert made == _named(live_app, "Many connections, full form")
    assert (made["threshold_connections"], made["window_minutes"], made["condition"]["ports"]) == (500, 30, [])

    # 3. an existing rule opened from the scenario that names it, its quiet time changed
    rid = pack_rule_id("rule_agent_tampering")
    before = _rules(live_app)
    page.goto(f"{live_app.url}/alert-rules")
    page.get_by_role("link", name="New rule").click()
    page.locator(f"[data-scenario='event:agent_security'] [data-role=covered-by][href='/alerts/rules/{rid}']").click()
    form = page.locator("[data-role=rule-editor]")
    expect(form.locator("input[name=event_types]")).to_have_value("agent.tampering")
    form.locator("input[name=cooldown_minutes]").fill("90")
    _save(page)
    after = _rules(live_app)
    assert after[rid] == before[rid] | {"cooldown_minutes": 90}
    assert {k: v for k, v in after.items() if k != rid} == {k: v for k, v in before.items() if k != rid}


def _open_and_save_each(page, live_app, ids) -> None:
    for rid in ids:
        page.goto(f"{live_app.url}/alerts/rules/{rid}")
        form = page.locator("[data-role=rule-editor]")
        expect(form.locator("select[name=severity]")).to_be_visible()
        page.wait_for_load_state("networkidle")
        _save(page)


def test_every_built_in_rule_opens_and_saves_unchanged(context, live_app):
    before = _rules(live_app)
    assert len(before) == 35 and all(r["pack_key"] for r in before.values())
    page = context.new_page()
    sign_in(page, live_app.url)
    revision = live_app.ctx.settings.current().revision
    _open_and_save_each(page, live_app, list(before))
    assert live_app.ctx.settings.current().revision == revision + len(before)   # each one really was saved
    after = _rules(live_app)
    assert list(after) == list(before)
    for rid, rule in before.items():
        assert after[rid] == rule, rule["pack_key"]


_EVENT = {"name": "", "pack_key": None, "enabled": True, "notify": True, "severity": None, "cooldown_minutes": 30,
          "throttle": None, "type": "event", "event_types": ["*"], "status": "all", "event_severity": "all",
          "match_fields": {}, "threshold": "immediate", "threshold_count": 1, "window_minutes": 10}
# shapes the built-in pack does not have
OTHER_SHAPES = [
    _EVENT | {"name": "either of two", "event_types": ["agent.tampering|agent.suspend"]},
    _EVENT | {"name": "a regular expression", "event_types": ["^user\\.(sign_in|login)$", "rule_set\\..*"]},
    _EVENT | {"name": "everything", "event_types": ["*"], "status": "failure", "event_severity": "err|warning"},
    _EVENT | {"name": "not in the catalog", "event_types": ["vendor.brand_new", "agent.tampering"], "enabled": False},
    _EVENT | {"name": "field matches", "event_types": ["system_task.prune_old_log_events"], "threshold": "count",
              "threshold_count": 3, "window_minutes": 45, "severity": "critical", "notify": False,
              "match_fields": {"notification_type": "hard_limit.exceeded", "created_by.user.username": "!admin@example.com"},
              "throttle": {"count": 2, "period_minutes": 120}},
    _EVENT | {"name": "each time, three per host", "event_types": ["agent.tampering"], "threshold_count": 3},
    {"name": "traffic with every exclusion", "pack_key": None, "enabled": True, "notify": True, "severity": "low",
     "cooldown_minutes": 5, "throttle": {"count": 3, "period_minutes": 60}, "type": "traffic",
     "threshold_connections": 40, "window_minutes": 15,
     "condition": {"decisions": ["blocked", "potentially_blocked"], "ports": [{"port": 445, "proto": 6}],
                   "src": {"labels": [{"key": "env", "values": ["Prod", "Dev"]}]}, "dst": {"ips": ["10.1.0.0/16"]},
                   "either": {"public": True}, "initiator_process": "psexec.exe", "initiator_user": "corp\\svc",
                   "windows_services": ["wuauserv"], "transmissions": ["broadcast"],
                   "src_exclude": {"ips": ["10.9.9.9"]}, "dst_exclude": {"labels": [{"key": "app", "values": ["Backup"]}]},
                   "either_exclude": {"public": True}, "exclude_ports": [{"port": 53, "proto": 17}, {"port": 8000, "to_port": 8100}],
                   "exclude_processes": ["svchost.exe"], "exclude_windows_services": ["Spooler"],
                   "exclude_transmissions": ["multicast"], "exclude_system_accounts": True}},
    {"name": "bandwidth by half an Mbps", "pack_key": None, "enabled": True, "notify": True, "severity": "high",
     "cooldown_minutes": 0, "throttle": None, "type": "bandwidth", "threshold_mbps": 0.5, "window_minutes": 60,
     "condition": {"dst": {"public": True}}},
    {"name": "volume", "pack_key": None, "enabled": True, "notify": True, "severity": "medium", "cooldown_minutes": 30,
     "throttle": None, "type": "volume", "threshold_mb": 2048.5, "window_minutes": 120, "condition": {}},
    {"name": "lateral with nothing left out", "pack_key": None, "enabled": True, "notify": True, "severity": "critical",
     "cooldown_minutes": 15, "throttle": None, "type": "lateral", "detectors": ["off_hours", "fanout", "data_staging"],
     "min_severity": "low", "critical_assets_only": True, "exclude": None},
    {"name": "lateral leaving out addresses", "pack_key": None, "enabled": True, "notify": False, "severity": None,
     "cooldown_minutes": 0, "throttle": None, "type": "lateral", "detectors": ["cross_env"], "min_severity": "high",
     "critical_assets_only": False, "exclude": {"ips": ["10.9.9.9", "10.8.0.0/16"], "labels": [{"key": "role", "values": ["Scanner"]}]}},
    {"name": "a system check, low", "pack_key": None, "enabled": False, "notify": True, "severity": "low",
     "cooldown_minutes": 720, "throttle": {"count": 1, "period_minutes": 1440}, "type": "system", "check": "siem_backlog"},
]


def test_rules_of_other_shapes_open_and_save_unchanged(context, live_app):
    rules = [r | {"id": uuid.uuid4().hex} for r in OTHER_SHAPES]
    s = live_app.ctx.settings
    s.update(s.current().revision, lambda d: d["alerts"].__setitem__("rules", rules))
    before = _rules(live_app)   # as the settings file holds them once validated
    assert list(before) == [r["id"] for r in rules]
    page = context.new_page()
    sign_in(page, live_app.url)
    revision = s.current().revision
    _open_and_save_each(page, live_app, list(before))
    assert s.current().revision == revision + len(before)
    after = _rules(live_app)
    for rid, rule in before.items():
        assert after[rid] == rule, rule["name"]
