"""The short form a scenario opens (purpose-led UI spec §10, stage 4): the few fields a rule of that scenario needs, and
every other field of the full form under "Advanced" — one mounted form, saving exactly the rule the full form saves."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from illumio_ops.domain.event_catalog import catalog
from tests.e2e import ui_rules
from tests.e2e.conftest import sign_in

# one scenario of each group, and the rule type its form edits
SCENARIOS = {"event:agent_security": "event", "flow:traffic": "traffic", "detector:pivot_chain": "lateral",
             "system:disk_low": "system"}
# what the short form shows, by the controls' names (the event checklist's boxes carry data-event-type, not a name)
SHORT = {"event": {"name", "threshold", "notify"}, "traffic": {"name", "window_minutes", "threshold", "notify"},
         "lateral": {"name", "min_severity", "notify"}, "system": {"name", "notify"}}
# what the full form has and the scenario's form does not: the type is the scenario's, and "each occurrence" is one event
NOT_CARRIED = {"event": {"type", "threshold_count"}, "traffic": {"type"}, "lateral": {"type"}, "system": {"type"}}

_NAMES = "(els) => [...new Set(els.map((e) => e.getAttribute('name')))]"
_FIELDS = "input[name], select[name], textarea[name]"


def _open(page, live_app, scenario: str):
    page.goto(f"{live_app.url}/alerts/rules/new?scenario={scenario}")
    page.wait_for_selector("[data-role=short-form]")
    page.wait_for_load_state("networkidle")
    return page.locator("[data-role=rule-editor]")


def _full(page, live_app, rule_type: str):
    page.goto(f"{live_app.url}/alerts/rules/new?form=full")
    form = page.locator("[data-role=rule-editor]")
    form.locator("select[name=type]").select_option(rule_type)
    page.wait_for_load_state("networkidle")
    return form


def _save(page, form) -> None:
    form.get_by_role("button", name="Save").click()
    page.wait_for_selector("[data-role=rule-list]")


def _saved(live_app, name: str) -> dict:
    rule = next(r for r in live_app.ctx.settings.current().alerts.rules if r.name == name)
    return {k: v for k, v in rule.model_dump(mode="json").items() if k not in ("id", "name")}


def _language(live_app, language: str) -> None:
    s = live_app.ctx.settings
    s.update(s.current().revision, lambda d: d["display"].update(language=language))


@pytest.fixture
def page(context, live_app):
    p = context.new_page()
    sign_in(p, live_app.url)
    return p


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_the_short_form_shows_its_fields_and_advanced_holds_the_rest(page, live_app, scenario):
    rule_type = SCENARIOS[scenario]
    full = set(_full(page, live_app, rule_type).locator(_FIELDS).evaluate_all(_NAMES))
    form = _open(page, live_app, scenario)
    short = form.locator("[data-role=short-form]")
    in_condition = set(short.locator(f"[data-role=condition] :is({_FIELDS})").evaluate_all(_NAMES))
    assert set(short.locator(_FIELDS).evaluate_all(_NAMES)) - in_condition == SHORT[rule_type]
    assert bool(in_condition) == (rule_type == "traffic")   # a traffic rule's condition is the rule: it is not tucked away
    advanced = form.locator("details[data-role=advanced]")
    expect(advanced).to_have_count(1)
    assert advanced.evaluate("(e) => e.open") is False
    assert ui_rules.violations(page) == {}
    expect(form.locator(".btn-primary")).to_have_count(1)
    expect(form.locator(".btn-primary")).to_have_text("Save")
    expect(page.locator("[data-role=scenario-back]")).to_have_attribute("href", "/alerts/rules/new")
    advanced.locator("> summary").click()
    assert advanced.evaluate("(e) => e.open") is True
    here = set(form.locator(_FIELDS).evaluate_all(_NAMES))
    assert full - here == NOT_CARRIED[rule_type], sorted(full - here)
    assert set(advanced.locator(_FIELDS).evaluate_all(_NAMES)) >= full - SHORT[rule_type] - in_condition - NOT_CARRIED[rule_type]
    page.wait_for_load_state("networkidle")
    assert ui_rules.violations(page) == {}


def test_event_short_form_saves_what_the_full_form_saves(page, live_app):
    form = _open(page, live_app, "event:agent_security")
    expect(form.locator("input[name=name]")).to_have_value("VEN security")   # the category's name, to start from
    form.locator("input[name=name]").fill("Short event")
    # an event no built-in rule is about alone: nothing but what is typed here goes into the rule
    form.locator("[data-role=event-checklist] input[data-event-type='agent.activate_clone']").check()
    expect(form.locator("[data-role=pack-prefill]")).to_have_count(0)
    _save(page, form)
    form = _full(page, live_app, "event")
    form.locator("input[name=name]").fill("Full event")
    form.locator("input[name=event_types]").fill("agent.activate_clone")
    _save(page, form)
    assert _saved(live_app, "Short event") == _saved(live_app, "Full event")
    assert _saved(live_app, "Short event")["event_types"] == ["agent.activate_clone"]


def test_event_short_form_counts_within_a_window(page, live_app):
    form = _open(page, live_app, "event:user_access")
    form.locator("input[name=name]").fill("Short count")
    form.locator("[data-role=event-checklist] input[data-event-type='user.sign_in']").check()
    short = form.locator("[data-role=short-form]")
    expect(short.locator("input[name=threshold_count]")).to_have_count(0)   # each occurrence: nothing to count
    short.locator("select[name=threshold]").select_option("count")
    short.locator("input[name=window_minutes]").fill("20")
    short.locator("input[name=threshold_count]").fill("4")
    _save(page, form)
    form = _full(page, live_app, "event")
    form.locator("input[name=name]").fill("Full count")
    form.locator("input[name=event_types]").fill("user.sign_in")
    form.locator("select[name=threshold]").select_option("count")
    form.locator("input[name=window_minutes]").fill("20")
    form.locator("input[name=threshold_count]").fill("4")
    _save(page, form)
    assert _saved(live_app, "Short count") == _saved(live_app, "Full count")
    assert _saved(live_app, "Short count")["threshold"] == "count"
    # and back to each occurrence is one event again
    form = _open(page, live_app, "event:user_access")
    form.locator("input[name=name]").fill("Short each")
    form.locator("[data-role=event-checklist] input[data-event-type='user.sign_in']").check()
    short = form.locator("[data-role=short-form]")
    short.locator("select[name=threshold]").select_option("count")
    short.locator("input[name=threshold_count]").fill("9")
    short.locator("select[name=threshold]").select_option("immediate")
    _save(page, form)
    each = _saved(live_app, "Short each")
    assert (each["threshold"], each["threshold_count"]) == ("immediate", 1)


def test_traffic_short_form_saves_what_the_full_form_saves(page, live_app):
    form = _open(page, live_app, "flow:traffic")
    form.locator("input[name=name]").fill("Short traffic")
    form.locator("input[name=ports]").fill("22")
    form.locator("input[name=ports]").blur()
    form.locator("input[name=decision_blocked]").check()
    form.locator("input[name=threshold]").fill("7")
    _save(page, form)
    form = _full(page, live_app, "traffic")
    form.locator("input[name=name]").fill("Full traffic")
    form.locator("input[name=ports]").fill("22")
    form.locator("input[name=ports]").blur()
    form.locator("input[name=decision_blocked]").check()
    form.locator("input[name=threshold]").fill("7")
    _save(page, form)
    assert _saved(live_app, "Short traffic") == _saved(live_app, "Full traffic")
    assert _saved(live_app, "Short traffic")["threshold_connections"] == 7


@pytest.mark.parametrize("scenario", ["flow:bandwidth", "flow:volume"])
def test_the_other_flow_scenarios_open_their_own_type(page, live_app, scenario):
    form = _open(page, live_app, scenario)
    form.locator("input[name=name]").fill("Short flow")
    _save(page, form)
    assert _saved(live_app, "Short flow")["type"] == scenario.split(":")[1]


def test_detector_short_form_saves_what_the_full_form_saves(page, live_app):
    form = _open(page, live_app, "detector:pivot_chain")
    expect(form.locator("input[name=name]")).to_have_value("Pivot chain")
    form.locator("input[name=name]").fill("Short lateral")
    form.locator("select[name=min_severity]").select_option("high")
    _save(page, form)
    form = _full(page, live_app, "lateral")
    form.locator("input[name=name]").fill("Full lateral")
    form.locator("input[name=detector_pivot_chain]").check()
    form.locator("input[name=detector_fanout]").uncheck()
    form.locator("select[name=min_severity]").select_option("high")
    _save(page, form)
    assert _saved(live_app, "Short lateral") == _saved(live_app, "Full lateral")
    assert _saved(live_app, "Short lateral")["detectors"] == ["pivot_chain"]


def test_system_short_form_saves_what_the_full_form_saves(page, live_app):
    form = _open(page, live_app, "system:disk_low")
    expect(form.locator("input[name=name]")).to_have_value("Disk space low")
    form.locator("input[name=name]").fill("Short system")
    _save(page, form)
    form = _full(page, live_app, "system")
    form.locator("input[name=name]").fill("Full system")
    form.locator("select[name=check]").select_option("disk_low")
    _save(page, form)
    assert _saved(live_app, "Short system") == _saved(live_app, "Full system")
    assert _saved(live_app, "Short system")["check"] == "disk_low"


def test_event_types_are_the_ticked_ones_in_catalog_order(page, live_app):
    in_category = [e.event_type for e in catalog() if e.category == "auth_api"]
    first, last = in_category[0], in_category[-1]
    form = _open(page, live_app, "event:auth_api")
    boxes = form.locator("[data-role=event-checklist] input[type=checkbox][data-event-type]")
    assert boxes.evaluate_all("(els) => els.map((e) => e.dataset.eventType)") == in_category
    # what a box says is the catalog's description, never the type string
    words = form.locator("[data-role=event-checklist]").inner_text()
    assert not any(t in words for t in in_category)
    save = form.get_by_role("button", name="Save")
    expect(save).to_be_disabled()
    expect(form.locator("[data-role=need-event]")).to_be_visible()
    form.locator(f"input[data-event-type='{last}']").check()
    form.locator(f"input[data-event-type='{first}']").check()
    expect(save).to_be_enabled()
    expect(form.locator("[data-role=need-event]")).to_have_count(0)
    form.locator("input[name=name]").fill("Two of them")
    _save(page, form)
    assert _saved(live_app, "Two of them")["event_types"] == [first, last]
    # unticking the last one disables saving again
    form = _open(page, live_app, "event:auth_api")
    form.locator(f"input[data-event-type='{first}']").check()
    form.locator(f"input[data-event-type='{first}']").uncheck()
    expect(form.get_by_role("button", name="Save")).to_be_disabled()


def test_opening_advanced_does_not_remount_the_condition(page, live_app):
    """The condition's inputs keep what was typed until they are left (defaultValue + onBlur): a form mounted again
    between the short view and Advanced would lose it."""
    form = _open(page, live_app, "flow:traffic")
    form.locator("input[name=name]").fill("Typed then opened")
    ports = form.locator("input[name=ports]")
    ports.focus()
    page.keyboard.type("8443")
    ports.evaluate("(e) => { e.dataset.same = 'yes'; }")
    advanced = form.locator("details[data-role=advanced]")
    for state in (True, False):   # opened and closed without the input losing focus
        advanced.evaluate("(e, open) => { e.open = open; }", state)
        page.wait_for_timeout(100)
    assert ports.evaluate("(e) => [e.value, e.dataset.same, e === document.activeElement]") == ["8443", "yes", True]
    ports.blur()
    _save(page, form)
    assert [p["port"] for p in _saved(live_app, "Typed then opened")["condition"]["ports"]] == [8443]


def test_advanced_opens_by_itself_only_when_it_holds_a_value(page, live_app):
    form = _open(page, live_app, "detector:pivot_chain")
    advanced = form.locator("details[data-role=advanced]")
    form.locator("select[name=min_severity]").select_option("critical")   # a short-form field: Advanced stays shut
    form.locator("input[name=notify]").uncheck()
    assert advanced.evaluate("(e) => e.open") is False
    advanced.locator("> summary").click()
    advanced.locator("input[name=cooldown_minutes]").fill("45")
    advanced.locator("> summary").click()   # the reader may close it; the page does not
    assert advanced.evaluate("(e) => e.open") is False
    advanced.evaluate("(e) => { e.open = true; }")
    advanced.locator("input[name=cooldown_minutes]").fill("0")
    advanced.locator("> summary").click()
    assert advanced.evaluate("(e) => e.open") is False


@pytest.mark.parametrize("language", ["en", "zh_TW"])
def test_nothing_untranslated_in_either_language(browser, live_app, language):
    _language(live_app, language)
    ctx = browser.new_context(locale="zh-TW" if language == "zh_TW" else "en-US", viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    sign_in(page, live_app.url)
    for scenario in SCENARIOS:
        form = _open(page, live_app, scenario)
        form.locator("details[data-role=advanced]").evaluate("(e) => { e.open = true; }")
        text = page.locator("main").inner_text()
        left = re.findall(r"\b(?:scn|rule|rules|evcat|evdesc|cond|detector_name|alert_type|purpose|severity|btn)_[a-z0-9_]+\b(?!\.)", text)
        assert left == [] and "{" not in text, (scenario, left)
        assert ui_rules.violations(page) == {}, scenario
    ctx.close()


# ── Task 4: a built-in rule's settings whole or not at all; Advanced opens on any value; channels; preview ──

PACK_FIELDS = ("status", "event_severity", "match_fields", "threshold", "threshold_count", "window_minutes", "severity",
               "cooldown_minutes", "throttle")
BLANK_EVENT = {"status": "all", "event_severity": "all", "match_fields": {}, "threshold": "immediate", "threshold_count": 1,
               "window_minutes": 10, "severity": None, "cooldown_minutes": 30, "throttle": None}
# Every property of the six rule models, by where a scenario's form puts it. FIXED is never a control: the id and the
# pack key are the server's, the type is the scenario's.
FIXED = {"id", "pack_key", "type"}
SHORT_PROPS = {
    "event": {"name", "notify", "event_types", "threshold", "threshold_count", "window_minutes"},
    "traffic": {"name", "notify", "condition", "threshold_connections", "window_minutes"},
    "bandwidth": {"name", "notify", "condition", "threshold_mbps", "window_minutes"},
    "volume": {"name", "notify", "condition", "threshold_mb", "window_minutes"},
    "system": {"name", "notify"},
    "lateral": {"name", "notify", "min_severity"},
}
_VALUE = "(e) => e.type === 'checkbox' ? e.checked : e.value"
_COMMON = {
    "severity": ("critical", {"select[name=severity]": "critical"}),
    "cooldown_minutes": (77, {"input[name=cooldown_minutes]": "77"}),
    "throttle": ({"count": 2, "period_minutes": 33},
                 {"input[name=throttle_on]": True, "input[name=throttle_count]": "2", "input[name=throttle_period]": "33"}),
    "enabled": (False, {"input[name=enabled]": False}),
}
# per type, each property under Advanced: a value that is not blank(type)'s, and the controls that must show it
ADVANCED_PROPS = {
    "event": _COMMON | {
        "status": ("failure", {"input[name=status]": "failure"}),
        "event_severity": ("err", {"input[name=event_severity]": "err"}),
        "match_fields": ({"notification_type": "hard_limit.exceeded"},
                         {"textarea[name=match_fields]": "notification_type=hard_limit.exceeded"}),
    },
    "traffic": _COMMON, "bandwidth": _COMMON, "volume": _COMMON,
    "system": _COMMON | {"check": ("disk_low", {"select[name=check]": "disk_low"})},
    "lateral": _COMMON | {
        "detectors": (["pivot_chain", "cross_env"], {"input[name=detector_pivot_chain]": True,
                                                    "input[name=detector_cross_env]": True, "input[name=detector_fanout]": False}),
        "critical_assets_only": (True, {"input[name=critical_assets_only]": True}),
        "exclude": ({"public": False, "ips": ["10.9.9.9"]}, {"input[name=exclude_public]": False,
                                                            "input[name=exclude_ips]": "10.9.9.9"}),
    },
}
_MODELS = {"event": "EventRule", "traffic": "TrafficRule", "bandwidth": "BandwidthRule", "volume": "VolumeRule",
           "system": "SystemRule", "lateral": "LateralRule"}
_BASE = {"id": "", "name": "", "pack_key": None, "enabled": True, "notify": True, "cooldown_minutes": 30, "throttle": None}
BLANK = {   # blank(type) of RuleEditor.tsx
    "event": _BASE | {"type": "event", "severity": None, "event_types": ["agent.tampering"], "status": "all",
                      "event_severity": "all", "match_fields": {}, "threshold": "immediate", "threshold_count": 1,
                      "window_minutes": 10},
    "traffic": _BASE | {"type": "traffic", "severity": "medium", "condition": {}, "threshold_connections": 25, "window_minutes": 10},
    "bandwidth": _BASE | {"type": "bandwidth", "severity": "medium", "condition": {}, "threshold_mbps": 100, "window_minutes": 60},
    "volume": _BASE | {"type": "volume", "severity": "medium", "condition": {}, "threshold_mb": 1024, "window_minutes": 60},
    "system": _BASE | {"type": "system", "severity": "high", "check": "pce_health", "cooldown_minutes": 60},
    "lateral": _BASE | {"type": "lateral", "severity": None, "detectors": ["fanout"], "min_severity": "medium",
                        "critical_assets_only": False, "exclude": {"public": True}, "cooldown_minutes": 0},
}


def _pack(key: str) -> dict:
    from illumio_ops.domain.alertpack import best_practice_rules
    return next(r for r in best_practice_rules(notify_new_defaults=True) if r.pack_key == key).model_dump(mode="json")


def _tick(form, *types: str) -> None:
    for t in types:
        form.locator(f"[data-role=event-checklist] input[data-event-type='{t}']").check()


def _is_open(form) -> bool:
    return bool(form.locator("details[data-role=advanced]").evaluate("(e) => e.open"))


def test_the_field_lists_cover_every_property_of_every_rule_model():
    """A property added to a rule model lands in none of the lists below and turns this red: it then has to be given
    a place in the short form or under Advanced (where the page opens Advanced when it holds a value)."""
    import json
    from pathlib import Path
    contracts = json.loads((Path(__file__).resolve().parents[2] / "web" / "src" / "api" / "contracts.json").read_text())
    defs = contracts["operations"]["alert_rules.create"]["request_schema"]["$defs"]
    for rule_type, model in _MODELS.items():
        props = set(defs[model]["properties"])
        assert props == FIXED | SHORT_PROPS[rule_type] | set(ADVANCED_PROPS[rule_type]), rule_type
        assert props == set(BLANK[rule_type]), rule_type
        assert not SHORT_PROPS[rule_type] & set(ADVANCED_PROPS[rule_type])
    assert set(PACK_FIELDS) <= SHORT_PROPS["event"] | set(ADVANCED_PROPS["event"])


def test_ticking_a_built_in_rules_events_brings_its_settings_whole(page, live_app):
    form = _open(page, live_app, "event:user_access")
    form.locator("input[name=name]").fill("Like the pack")
    _tick(form, "user.sign_in")
    expect(form.locator("[data-role=pack-prefill]")).to_have_count(0)
    assert not _is_open(form)
    _tick(form, "user.login")
    expect(form.locator("[data-role=pack-prefill]")).to_have_text("Uses the settings of the built-in rule “Login Failures”.")
    assert _is_open(form)
    expect(form.locator("input[name=status]")).to_be_visible()
    expect(form.locator("input[name=status]")).to_have_value("failure")
    expect(form.locator("[data-role=short-form] select[name=threshold]")).to_have_value("count")
    expect(form.locator("[data-role=short-form] input[name=threshold_count]")).to_have_value("5")
    expect(form.locator("input[name=throttle_period]")).to_have_value("15")
    _save(page, form)
    mine, pack = _saved(live_app, "Like the pack"), _pack("rule_login_failed")
    assert sorted(mine.pop("event_types")) == sorted(pack.pop("event_types"))   # the same set; ticked ones are in catalog order
    assert mine.pop("pack_key") is None and pack.pop("pack_key") == "rule_login_failed"
    assert mine == {k: v for k, v in pack.items() if k not in ("id", "name")}


def test_one_event_of_a_built_in_rule_brings_nothing(page, live_app):
    form = _open(page, live_app, "event:user_access")
    form.locator("input[name=name]").fill("Only sign-in")
    _tick(form, "user.sign_in")
    expect(form.locator("[data-role=pack-prefill]")).to_have_count(0)
    expect(form.locator("[data-role=short-form] select[name=threshold]")).to_have_value("immediate")
    assert not _is_open(form)
    _save(page, form)
    mine = _saved(live_app, "Only sign-in")
    assert {k: mine[k] for k in PACK_FIELDS} == BLANK_EVENT and mine["event_types"] == ["user.sign_in"]


def test_leaving_a_built_in_rules_events_keeps_what_was_changed_by_hand(page, live_app):
    form = _open(page, live_app, "event:user_access")
    form.locator("input[name=name]").fill("Was like the pack")
    _tick(form, "user.sign_in", "user.login")
    expect(form.locator("input[name=status]")).to_have_value("failure")
    form.locator("input[name=cooldown_minutes]").fill("45")
    form.locator("[data-role=event-checklist] input[data-event-type='user.login']").uncheck()
    expect(form.locator("[data-role=pack-prefill]")).to_have_count(0)
    expect(form.locator("input[name=cooldown_minutes]")).to_have_value("45")
    expect(form.locator("input[name=status]")).to_have_value("all")
    expect(form.locator("[data-role=short-form] select[name=threshold]")).to_have_value("immediate")
    expect(form.locator("input[name=throttle_on]")).not_to_be_checked()
    _save(page, form)
    mine = _saved(live_app, "Was like the pack")
    assert {k: mine[k] for k in PACK_FIELDS} == BLANK_EVENT | {"cooldown_minutes": 45}
    # and ticking it again brings the built-in rule's settings back, whole
    form = _open(page, live_app, "event:user_access")
    _tick(form, "user.sign_in", "user.login")
    form.locator("input[name=cooldown_minutes]").fill("45")
    form.locator("[data-role=event-checklist] input[data-event-type='user.login']").uncheck()
    _tick(form, "user.login")
    expect(form.locator("input[name=cooldown_minutes]")).to_have_value("30")
    expect(form.locator("input[name=status]")).to_have_value("failure")


def test_every_built_in_event_rule_shows_each_setting_it_brings(page, live_app):
    """For each built-in event rule whose events sit in one category: every setting brought in is in a control the
    reader can see, and Advanced is open exactly when one of them is under it."""
    from illumio_ops.domain.alertpack import best_practice_rules
    category = {e.event_type: e.category for e in catalog()}
    under_advanced = set(PACK_FIELDS) - SHORT_PROPS["event"]
    seen = 0
    for rule in best_practice_rules(notify_new_defaults=True):
        if rule.type != "event" or len({category[t] for t in rule.event_types}) != 1:
            continue
        seen += 1
        pack = rule.model_dump(mode="json")
        form = _open(page, live_app, f"event:{category[rule.event_types[0]]}")
        _tick(form, *rule.event_types)
        expect(form.locator("[data-role=pack-prefill]")).to_have_count(1)
        assert _is_open(form) == any(pack[f] != BLANK_EVENT[f] for f in under_advanced), rule.pack_key
        shows = {"select[name=threshold]": pack["threshold"]}
        if pack["threshold"] == "count":
            shows |= {"input[name=threshold_count]": str(pack["threshold_count"]), "input[name=window_minutes]": str(pack["window_minutes"])}
        else:
            assert pack["threshold_count"] == 1   # "each occurrence" says all of it
        if _is_open(form):
            shows |= {"input[name=status]": pack["status"], "input[name=event_severity]": pack["event_severity"],
                      "select[name=severity]": pack["severity"] or "", "input[name=cooldown_minutes]": str(pack["cooldown_minutes"]),
                      "input[name=throttle_on]": pack["throttle"] is not None}
            if pack["throttle"]:
                shows |= {"input[name=throttle_count]": str(pack["throttle"]["count"]),
                          "input[name=throttle_period]": str(pack["throttle"]["period_minutes"])}
        for selector, value in shows.items():
            control = form.locator(selector)
            expect(control).to_be_visible()
            assert control.evaluate(_VALUE) == value, (rule.pack_key, selector)
        assert pack["match_fields"] == {}
    assert seen == 15


def test_an_edit_page_shows_every_field_and_folds_none(page, live_app):
    """Each property a scenario's form keeps under Advanced, set alone to a value that is not the blank one: the edit
    page shows it without anything being opened."""
    import uuid
    made = []
    for rule_type, fields in ADVANCED_PROPS.items():
        for prop, (value, shows) in fields.items():
            assert BLANK[rule_type][prop] != value, (rule_type, prop)
            rule = BLANK[rule_type] | {"id": uuid.uuid4().hex, "name": f"{rule_type} {prop}", prop: value}
            made.append((rule, shows))
    s = live_app.ctx.settings
    s.update(s.current().revision, lambda d: d["alerts"]["rules"].extend(r for r, _ in made))
    for rule, shows in made:
        page.goto(f"{live_app.url}/alerts/rules/{rule['id']}")
        form = page.locator("[data-role=rule-editor]")
        expect(form.locator("input[name=name]")).to_have_value(rule["name"])
        expect(form.locator("[data-role=short-form], details[data-role=advanced]")).to_have_count(0)
        for selector, value in shows.items():
            control = form.locator(selector)
            expect(control).to_be_visible()
            assert control.evaluate(_VALUE) == value, (rule["name"], selector)


def test_the_short_form_names_the_channels_that_are_on(page, live_app):
    form = _open(page, live_app, "system:disk_low")
    line = form.locator("[data-role=short-form] [data-role=notify-channels]")
    expect(line).to_contain_text("No notification channel is turned on.")
    expect(line.locator("a")).to_have_attribute("href", "/alert-rules?tab=channels")
    s = live_app.ctx.settings

    def turn_on(d):
        d["alerts"]["channels"]["webhook"].update(enabled=True, url="https://hook.example/in")
        d["alerts"]["channels"]["smtp"].update(enabled=True, host="mail.example", sender="ops@example.com",
                                               recipients=["soc@example.com"])
    s.update(s.current().revision, turn_on)
    form = _open(page, live_app, "system:disk_low")
    line = form.locator("[data-role=short-form] [data-role=notify-channels]")
    expect(line).to_contain_text("Notifications go to: Email (SMTP), Webhook.")
    assert ui_rules.violations(page) == {}
    # the full form and an edit page are as they were: no such line
    page.goto(f"{live_app.url}/alerts/rules/new?form=full")
    page.wait_for_selector("[data-role=rule-editor]")
    expect(page.locator("[data-role=notify-channels]")).to_have_count(0)


def test_a_system_scenario_has_no_trial_run(page, live_app):
    form = _open(page, live_app, "system:disk_low")
    expect(form.get_by_role("button", name="Try on the last 24 hours")).to_have_count(0)
    expect(form.locator("[data-role=preview-na]")).to_have_text("A system check cannot be tried on past data.")
    for scenario in ("event:agent_security", "flow:traffic", "detector:pivot_chain"):
        form = _open(page, live_app, scenario)
        expect(form.get_by_role("button", name="Try on the last 24 hours")).to_have_count(1)
        expect(form.locator("[data-role=preview-na]")).to_have_count(0)
    form.get_by_role("button", name="Try on the last 24 hours").click()
    expect(form.locator("[data-role=preview]")).to_be_visible()
