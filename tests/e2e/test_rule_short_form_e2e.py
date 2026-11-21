"""The short form a scenario opens (purpose-led UI spec §10, stage 4): the few fields a rule of that scenario needs, and
every other field of the full form under "Advanced" — one mounted form, saving exactly the rule the full form saves."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from tests.e2e import ui_rules
from tests.e2e.conftest import sign_in

# one scenario of each group, and the rule type its form edits
SCENARIOS = {"detector:pivot_chain": "lateral", "system:disk_low": "system"}
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
    page.wait_for_selector("[data-role=rules-event]")
    expect(page.locator("[data-role=rule-form]")).to_have_count(0)  # saved: the form has closed


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
    assert not in_condition
    advanced = form.locator("details[data-role=advanced]")
    expect(advanced).to_have_count(1)
    assert advanced.evaluate("(e) => e.open") is False
    assert ui_rules.violations(page) == {}
    expect(form.locator(".btn-primary")).to_have_count(1)
    expect(form.locator(".btn-primary")).to_have_text("Save")
    expect(page.locator("[data-role=scenario-back]")).to_have_attribute("href", "/alerts/rules/new?only=special")
    advanced.locator("> summary").click()
    assert advanced.evaluate("(e) => e.open") is True
    here = set(form.locator(_FIELDS).evaluate_all(_NAMES))
    assert full - here == NOT_CARRIED[rule_type], sorted(full - here)
    assert set(advanced.locator(_FIELDS).evaluate_all(_NAMES)) >= full - SHORT[rule_type] - in_condition - NOT_CARRIED[rule_type]
    page.wait_for_load_state("networkidle")
    assert ui_rules.violations(page) == {}


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
        "status": ("failure", {"select[name=status]": "failure"}),
        "event_severity": ("err", {"input[name=event_severity_err]": True}),
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
        if rule["type"] in ("event", "traffic", "bandwidth", "volume"):
            page.goto(f"{live_app.url}/alert-rules?rule={rule['id']}")
            form = page.locator("[data-role=rule-form]")
            # the new form says enabled with its off / record / notify control, not a check box
            if "input[name=enabled]" in shows:
                shows = {k: v for k, v in shows.items() if k != "input[name=enabled]"}
                shows["input[name=form_rule_state]:checked"] = "off" if not rule["enabled"] else "on"
        else:
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
    for scenario in ("detector:pivot_chain",):
        form = _open(page, live_app, scenario)
        expect(form.get_by_role("button", name="Try on the last 24 hours")).to_have_count(1)
        expect(form.locator("[data-role=preview-na]")).to_have_count(0)
    form.get_by_role("button", name="Try on the last 24 hours").click()
    expect(form.locator("[data-role=preview]")).to_be_visible()
