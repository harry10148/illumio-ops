"""Acceptance of the rule form (purpose-led UI spec §11, stage 4): three rules made from the rule list with nothing
but the page, each the rule the full form would have saved; and every rule there is — the built-in pack and the
shapes it does not have — opened and saved without a change, coming back exactly as it was."""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from illumio_ops.domain.alertpack import best_practice_rules, pack_rule_id
from tests.e2e.conftest import sign_in


def _rules(live_app) -> dict[str, dict]:
    return {r.id: r.model_dump(mode="json") for r in live_app.ctx.settings.current().alerts.rules}


def _named(live_app, name: str) -> dict:
    rule = next(r for r in _rules(live_app).values() if r["name"] == name)
    return {k: v for k, v in rule.items() if k not in ("id", "name")}


def _save(page) -> None:
    form = page.locator("[data-role=rule-form]")
    if form.count():
        form.locator("button[type=submit]").click()
        expect(form).to_have_count(0)  # the form closes once the rule is saved
        return
    page.locator("[data-role=rule-editor]").locator("button[type=submit]").click()
    page.wait_for_selector("[data-role=rules-event]")


def _from_the_list(page, live_app, scenario: str):
    """Rule list → the one event/flow form; the type is the only starting choice."""
    page.goto(f"{live_app.url}/alert-rules")
    page.get_by_role("link", name="New rule").click()
    form = page.locator("[data-role=rule-form]")
    if scenario.startswith("flow:"):
        form.locator("input[name=rule_kind][value=flow]").check()
    return form


def _full_form(page, live_app, rule_type: str):
    page.goto(f"{live_app.url}/alert-rules?rule=new")
    form = page.locator("[data-role=rule-form]")
    if rule_type in ("traffic", "bandwidth", "volume"):
        form.locator("input[name=rule_kind][value=flow]").check()
        if rule_type != "traffic":
            form.locator(f"input[name=flow_metric][value={rule_type}]").check()
    return form


def test_three_rules_made_from_the_rule_list(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)

    # 1. an event rule: pick the category, tick an event, save
    form = _from_the_list(page, live_app, "event:policy")
    form.locator("input[name=name]").fill("Label deleted")
    form.locator("input[data-event-type='label.delete']").check()
    _save(page)
    form = _full_form(page, live_app, "event")
    form.locator("input[name=name]").fill("Label deleted, full form")
    form.locator("input[data-event-type='label.delete']").check()
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
    page.goto(f"{live_app.url}/alert-rules?rule={rid}")
    form = page.locator("[data-role=rule-form]")
    expect(form.locator("[data-role=event-picker] input[data-event-type='agent.tampering']")).to_be_checked()
    form.locator("[data-role=rule-form-advanced] > summary").click()  # folded: the pack's own cooldown
    form.locator("input[name=cooldown_minutes]").fill("90")
    _save(page)
    after = _rules(live_app)
    assert after[rid] == before[rid] | {"cooldown_minutes": 90}
    assert {k: v for k, v in after.items() if k != rid} == {k: v for k, v in before.items() if k != rid}


def _open_and_save_each(page, live_app, rules) -> None:
    for rid, saved in rules.items():
        if saved["type"] in ("event", "traffic", "bandwidth", "volume"):
            page.goto(f"{live_app.url}/alert-rules?rule={rid}")
            form = page.locator("[data-role=rule-form]")
            if saved["type"] in ("traffic", "bandwidth", "volume"):
                more = form.locator("details[data-role=flow-more]")
                expect(more).to_have_count(1)
                expect(form.locator("input[name=decision_unknown]")).to_be_visible()
                has_more_values = any(key not in {"src", "dst", "ports", "decisions"} and bool(value)
                                      for key, value in saved["condition"].items())
                assert more.evaluate("element => element.open") is has_more_values, saved["name"]
        else:
            page.goto(f"{live_app.url}/alerts/rules/{rid}")
            form = page.locator("[data-role=rule-editor]")
        expect(form.locator("select[name=severity]")).to_be_visible()
        page.wait_for_load_state("networkidle")
        _save(page)


def test_every_built_in_rule_opens_and_saves_unchanged(context, live_app):
    before = _rules(live_app)
    pack = {rule.id: rule.model_dump(mode="json") for rule in best_practice_rules(notify_new_defaults=True)}
    assert before == pack
    assert len(before) == 35 and all(r["pack_key"] for r in before.values())
    page = context.new_page()
    sign_in(page, live_app.url)
    revision = live_app.ctx.settings.current().revision
    _open_and_save_each(page, live_app, before)
    assert live_app.ctx.settings.current().revision == revision + len(before)   # each one really was saved
    after = _rules(live_app)
    assert list(after) == list(before)
    for rid, rule in before.items():
        assert after[rid] == rule, rule["pack_key"]


_EVENT = {"name": "", "pack_key": None, "enabled": True, "notify": True, "severity": None, "cooldown_minutes": 30,
          "throttle": None, "type": "event", "event_types": ["*"], "status": "all", "event_severity": "all",
          "match_fields": {}, "threshold": "immediate", "threshold_count": 1, "window_minutes": 10}
# shapes the built-in pack does not have
_ALL_FLOW_FIELDS = {
    "src": {"labels": [{"key": "env", "values": ["Prod"]}], "ips": ["10.1.2.3"],
            "hrefs": ["/orgs/1/workloads/123"], "ip_lists": ["/orgs/1/sec_policy/active/ip_lists/7"],
            "label_groups": ["/orgs/1/sec_policy/active/label_groups/3"], "public": True, "match": "all"},
    "dst": {"ips": ["10.2.3.4"]},
    "src_exclude": {"ips": ["10.3.4.5"]},
    "dst_exclude": {"public": True},
    "either": {"ips": ["10.4.5.6"]},
    "either_exclude": {"ips": ["10.5.6.7"]},
    "ports": [{"port": 445, "proto": 6}, {"port": 8080, "proto": None},
               {"port": 8000, "to_port": 8100, "proto": 47},
               {"port": 1000, "to_port": 1005, "proto": None}, {"port": -1, "proto": 1},
               {"port": None, "proto": 47}],
    "exclude_ports": [{"port": 53, "proto": 17}, {"port": 8080, "to_port": 8081, "proto": None}],
    "decisions": ["blocked", "potentially_blocked"],
    "initiator_process": "initiator.exe", "initiator_user": "corp\\initiator",
    "service_process": "service.exe", "service_user": "corp\\service",
    "initiator_processes": ["first.exe", "second.exe"], "initiator_users": ["first-user", "second-user"],
    "service_processes": ["worker.exe", "agent.exe"], "service_users": ["worker-user", "agent-user"],
    "text": "stored flow text", "exclude_system_accounts": True,
    "services": ["/orgs/1/sec_policy/active/services/2"],
    "exclude_services": ["/orgs/1/sec_policy/active/services/4"],
    "windows_services": ["wuauserv"], "exclude_windows_services": ["Spooler"],
    "transmissions": ["broadcast"], "exclude_transmissions": ["multicast"],
    "exclude_processes": ["excluded.exe"],
}
OTHER_SHAPES = [
    _EVENT | {"name": "either of two", "event_types": ["agent.tampering|agent.suspend"]},
    _EVENT | {"name": "a regular expression", "event_types": ["^user\\.(sign_in|login)$", "rule_set\\..*"]},
    _EVENT | {"name": "a pattern with a comma", "event_types": ["^agent\\.(a|b){1,3}$", "user.login"]},
    _EVENT | {"name": "everything", "event_types": ["*"], "status": "failure", "event_severity": "err|warning"},
    _EVENT | {"name": "event severity error alias", "event_types": ["user.login"], "event_severity": "error"},
    _EVENT | {"name": "event severity wildcard", "event_types": ["user.login"], "event_severity": "*"},
    _EVENT | {"name": "event severity empty", "event_types": ["user.login"], "event_severity": ""},
    _EVENT | {"name": "event severity negated", "event_types": ["user.login"], "event_severity": "!info"},
    _EVENT | {"name": "event severity pattern", "event_types": ["user.login"], "event_severity": "^warn.*$"},
    _EVENT | {"name": "nonstandard status", "event_types": ["user.login"], "status": "!success"},
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
    {"name": "traffic with every flow field", "pack_key": None, "enabled": True, "notify": True, "severity": "medium",
     "cooldown_minutes": 17, "throttle": None, "type": "traffic", "threshold_connections": 73, "window_minutes": 25,
     "condition": _ALL_FLOW_FIELDS},
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
    # Settings parses these through the domain AlertRule adapter; retain a direct validation assertion so a fixture
    # cannot silently stop exercising a valid stored shape.
    from pydantic import TypeAdapter

    from illumio_ops.domain.alertrules import AlertRule
    adapter = TypeAdapter(AlertRule)
    for rule in before.values():
        adapter.validate_python(rule)
    page = context.new_page()
    sign_in(page, live_app.url)
    revision = s.current().revision
    _open_and_save_each(page, live_app, before)
    assert s.current().revision == revision + len(before)
    after = _rules(live_app)
    for rid, rule in before.items():
        assert after[rid] == rule, rule["name"]


def test_unknown_decision_can_be_saved_from_the_traffic_form(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?rule=new")
    form = page.locator("[data-role=rule-form]")
    form.locator("input[name=rule_kind][value=flow]").check()
    expect(form.locator("details[data-role=flow-more]")).to_have_count(1)
    form.locator("input[name=name]").fill("Unknown decision")
    form.locator("input[name=decision_unknown]").check()
    form.locator("button[type=submit]").click()
    expect(form).to_have_count(0)
    saved = next(r for r in _rules(live_app).values() if r["name"] == "Unknown decision")
    assert saved["condition"]["decisions"] == ["unknown"]


# ── an event pattern may hold a comma: the form edits the list as a list, one pattern per line ─────────────

COMMA = "^agent\\.(a|b){1,3}$"


def _event_rule(live_app, name: str, event_types: list[str]) -> str:
    rid = uuid.uuid4().hex
    s = live_app.ctx.settings
    s.update(s.current().revision, lambda d: d["alerts"]["rules"].append(_EVENT | {"id": rid, "name": name,
                                                                                    "event_types": event_types}))
    return rid


def test_a_pattern_with_a_comma_is_one_entry_opened_saved_and_edited(context, live_app):
    rid = _event_rule(live_app, "Comma", [COMMA, "user.login"])
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?rule={rid}")
    form = page.locator("[data-role=rule-form]")
    box = form.locator("textarea[name=event_types]")
    expect(box).to_have_value(COMMA)   # catalog entries are controlled by the picker
    page.wait_for_load_state("networkidle")
    _save(page)
    assert _rules(live_app)[rid]["event_types"] == [COMMA, "user.login"]   # saved unchanged: the same list

    page.goto(f"{live_app.url}/alert-rules?rule={rid}")
    form = page.locator("[data-role=rule-form]")
    box = form.locator("textarea[name=event_types]")
    expect(box).to_have_value(COMMA)
    form.locator("input[data-event-type='user.login']").uncheck()
    form.locator("input[data-event-type='user.sign_in']").check()
    _save(page)
    assert _rules(live_app)[rid]["event_types"] == [COMMA, "user.sign_in"]   # the first is whole


def test_a_pattern_with_a_comma_typed_into_a_new_rule_is_one_entry(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    form = _full_form(page, live_app, "event")
    form.locator("input[name=name]").fill("Typed comma")
    more = form.locator("details.event-more")
    if not more.evaluate("(e) => e.open"):
        more.locator("summary").click()
    box = form.locator("textarea[name=event_types]")
    box.fill(COMMA)
    expect(box).to_have_value(COMMA)
    form.locator("input[data-event-type='user.sign_in']").check()
    form.locator("input[data-event-type='agent.tampering']").check()
    _save(page)
    assert _named(live_app, "Typed comma")["event_types"] == [COMMA, "user.sign_in", "agent.tampering"]


def test_a_rule_with_no_event_type_typed_is_refused_at_the_field(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    form = _full_form(page, live_app, "event")
    form.locator("input[name=name]").fill("Nothing typed")
    more = form.locator("details.event-more")
    if not more.evaluate("(e) => e.open"):
        more.locator("summary").click()
    form.locator("textarea[name=event_types]").fill("  \n\n")
    form.locator("button[type=submit]").click()
    expect(form.locator(".field-error[data-field*=event_types]").first).to_be_visible()
    assert "Nothing typed" not in [r["name"] for r in _rules(live_app).values()]
