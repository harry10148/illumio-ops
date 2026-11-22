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


RULE_FORM_FIELD_COVERAGE = {
    "EventRule": {
        "cooldown_minutes": "input[name=cooldown_minutes]", "enabled": "input[name=form_rule_state]",
        "event_severity": "input[name=event_severity]", "event_types": "[data-role=event-picker]",
        "match_fields": "textarea[name=match_fields]", "name": "input[name=name]",
        "notify": "input[name=form_rule_state]", "severity": "select[name=severity]",
        "status": "input[name=status]", "threshold": "input[name=threshold]",
        "threshold_count": "input[name=threshold_count]", "throttle": "input[name=throttle_on]",
        "window_minutes": "input[name=window_minutes]",
    },
    "TrafficRule": {
        "condition": "[data-role=flow-condition]", "cooldown_minutes": "input[name=cooldown_minutes]",
        "enabled": "input[name=form_rule_state]", "name": "input[name=name]",
        "notify": "input[name=form_rule_state]", "severity": "select[name=severity]",
        "threshold_connections": "input[name=threshold]", "throttle": "input[name=throttle_on]",
        "window_minutes": "input[name=window_minutes]",
    },
    "BandwidthRule": {
        "condition": "[data-role=flow-condition]", "cooldown_minutes": "input[name=cooldown_minutes]",
        "enabled": "input[name=form_rule_state]", "name": "input[name=name]",
        "notify": "input[name=form_rule_state]", "severity": "select[name=severity]",
        "threshold_mbps": "input[name=threshold]", "throttle": "input[name=throttle_on]",
        "window_minutes": "input[name=window_minutes]",
    },
    "VolumeRule": {
        "condition": "[data-role=flow-condition]", "cooldown_minutes": "input[name=cooldown_minutes]",
        "enabled": "input[name=form_rule_state]", "name": "input[name=name]",
        "notify": "input[name=form_rule_state]", "severity": "select[name=severity]",
        "threshold_mb": "input[name=threshold]", "throttle": "input[name=throttle_on]",
        "window_minutes": "input[name=window_minutes]",
    },
    "FlowCondition": {
        "decisions": "input[name=decision_blocked]", "dst": "[data-side=dst]", "dst_exclude": "[data-side=dst_exclude]",
        "either": "[data-side=either]", "either_exclude": "[data-side=either_exclude]",
        "exclude_ports": "input[name=exclude_ports]", "exclude_processes": "input[name=exclude_processes]",
        "exclude_services": "[data-role=exclude_service]", "exclude_system_accounts": "input[name=exclude_system_accounts]",
        "exclude_transmissions": "input[name=exclude_transmission_multicast]",
        "exclude_windows_services": "input[name=exclude_windows_services]", "initiator_process": "input[name=initiator_process]",
        "initiator_processes": "textarea[name=initiator_processes]", "initiator_user": "input[name=initiator_user]",
        "initiator_users": "textarea[name=initiator_users]", "ports": "input[name=ports]",
        "service_process": "input[name=service_process]", "service_processes": "textarea[name=service_processes]",
        "service_user": "input[name=service_user]", "service_users": "textarea[name=service_users]",
        "services": "[data-role=service]", "src": "[data-side=src]", "src_exclude": "[data-side=src_exclude]",
        "text": "input[name=text]", "transmissions": "input[name=transmission_broadcast]",
        "windows_services": "input[name=windows_services]",
    },
    "EndpointFilter": {
        "hrefs": "[data-role=src-advanced] [data-href]", "ip_lists": "[data-role=src_ip_list] [data-ip-list]",
        "ips": "input[name=src_ips]", "label_groups": "[data-role=src_label_group] [data-label-group]",
        "labels": "[data-side=src] .chip", "match": "select[name=src_match]", "public": "input[name=src_public]",
    },
    "PortProto": {"port": "input[name=ports]", "proto": "input[name=ports]", "to_port": "input[name=ports]"},
    "Throttle": {"count": "input[name=throttle_count]", "period_minutes": "input[name=throttle_period]"},
}
RULE_FORM_KEPT_AS_STORED = {
    "EventRule": {"id", "pack_key", "type"}, "TrafficRule": {"id", "pack_key", "type"},
    "BandwidthRule": {"id", "pack_key", "type"}, "VolumeRule": {"id", "pack_key", "type"},
    "FlowCondition": set(), "EndpointFilter": set(), "PortProto": set(), "Throttle": set(),
}


def test_field_lists_cover_every_property_of_every_rule_model():
    """Contract properties must all have a selector or be explicitly retained by the editor."""
    import json
    from pathlib import Path
    contracts = json.loads((Path(__file__).resolve().parents[2] / "web" / "src" / "api" / "contracts.json").read_text())
    defs = contracts["operations"]["alert_rules.create"]["request_schema"]["$defs"]
    for model, fields in RULE_FORM_FIELD_COVERAGE.items():
        kept = RULE_FORM_KEPT_AS_STORED[model]
        assert set(defs[model]["properties"]) == set(fields) | kept, model
        assert set(fields).isdisjoint(kept), model
        assert all(selector.startswith(("input", "select", "textarea", "[")) for selector in fields.values()), model
        assert kept <= {"id", "pack_key", "type"}, model
    # The full forms for detection and system rules remain covered while those rules keep their existing editor.
    for rule_type, model in _MODELS.items():
        if rule_type in ("system", "lateral"):
            props = set(defs[model]["properties"])
            assert props == FIXED | SHORT_PROPS[rule_type] | set(ADVANCED_PROPS[rule_type]), rule_type
            assert props == set(BLANK[rule_type]), rule_type
        assert not SHORT_PROPS[rule_type] & set(ADVANCED_PROPS[rule_type])
    assert set(PACK_FIELDS) <= SHORT_PROPS["event"] | set(ADVANCED_PROPS["event"])


def test_rule_form_field_controls_show_stored_nondefault_values(page, live_app):
    """Every mapped control is mounted for a stored non-default value and renders that value."""
    import uuid

    from tests.e2e.test_rule_form_acceptance_e2e import _ALL_FLOW_FIELDS

    event = {
        "id": uuid.uuid4().hex, "name": "Coverage event", "pack_key": None, "enabled": True, "notify": False,
        "severity": "high", "cooldown_minutes": 43, "throttle": {"count": 4, "period_minutes": 90},
        "type": "event", "event_types": ["user.sign_in", "vendor.off_catalog"], "status": "!success",
        "event_severity": "^warn.*$", "match_fields": {"created_by.user.username": "admin"},
        "threshold": "count", "threshold_count": 3, "window_minutes": 45,
    }
    flows = []
    for rule_type, threshold_key, threshold_value in (
        ("traffic", "threshold_connections", 73), ("bandwidth", "threshold_mbps", 2.5),
        ("volume", "threshold_mb", 2048.5),
    ):
        flows.append({
            "id": uuid.uuid4().hex, "name": f"Coverage {rule_type}", "pack_key": None, "enabled": True,
            "notify": True, "severity": "critical", "cooldown_minutes": 47,
            "throttle": {"count": 5, "period_minutes": 91}, "type": rule_type, "window_minutes": 35,
            threshold_key: threshold_value, "condition": _ALL_FLOW_FIELDS,
        })
    s = live_app.ctx.settings
    s.update(s.current().revision, lambda d: d["alerts"]["rules"].extend([event, *flows]))

    for rule in [event, *flows]:
        page.goto(f"{live_app.url}/alert-rules?rule={rule['id']}")
        form = page.locator("[data-role=rule-form]")
        model = {"event": "EventRule", "traffic": "TrafficRule", "bandwidth": "BandwidthRule", "volume": "VolumeRule"}[rule["type"]]
        for selector in RULE_FORM_FIELD_COVERAGE[model].values():
            expect(form.locator(selector).first).to_be_visible()
        expect(form.locator("input[name=cooldown_minutes]")).to_have_value(str(rule["cooldown_minutes"]))
        expect(form.locator("input[name=throttle_on]")).to_be_checked()
        expect(form.locator("input[name=throttle_count]")).to_have_value(str(rule["throttle"]["count"]))
        expect(form.locator("input[name=throttle_period]")).to_have_value(str(rule["throttle"]["period_minutes"]))
        expect(form.locator("select[name=severity]")).to_have_value(rule["severity"])
        expect(form.locator("input[name=window_minutes]")).to_have_value(str(rule["window_minutes"]))
        if rule["type"] != "event":
            threshold = rule[{"traffic": "threshold_connections", "bandwidth": "threshold_mbps", "volume": "threshold_mb"}[rule["type"]]]
            expect(form.locator("input[name=threshold]")).to_have_value(str(threshold))

    # Check representative values through the exact selectors mapped above, including the controls that render
    # their state as a chip or as a radio selection rather than an input's value string.
    page.goto(f"{live_app.url}/alert-rules?rule={event['id']}")
    form = page.locator("[data-role=rule-form]")
    expect(form.locator("input[name=name]")).to_have_value(event["name"])
    expect(form.locator("select[name=severity]")).to_have_value("high")
    expect(form.locator("input[name=form_rule_state][value=rec]")).to_be_checked()
    expect(form.locator("input[name=cooldown_minutes]")).to_have_value("43")
    expect(form.locator("input[name=throttle_count]")).to_have_value("4")
    expect(form.locator("input[name=throttle_period]")).to_have_value("90")
    expect(form.locator("input[name=event_severity]")).to_have_value("^warn.*$")
    expect(form.locator("input[name=status]")).to_have_value("!success")
    expect(form.locator("input[name=threshold][value=count]")).to_be_checked()
    expect(form.locator("input[name=threshold_count]")).to_have_value("3")
    expect(form.locator("input[name=window_minutes]")).to_have_value("45")
    expect(form.locator("[data-role=event-picker] input[data-event-type='user.sign_in']")).to_be_checked()
    expect(form.locator(".event-chip code")).to_have_text(["user.sign_in", "vendor.off_catalog"])
    expect(form.locator("textarea[name=match_fields]")).to_have_value("created_by.user.username=admin")

    flow = flows[0]
    page.goto(f"{live_app.url}/alert-rules?rule={flow['id']}")
    form = page.locator("[data-role=rule-form]")
    expect(form.locator("input[name=form_rule_state][value=on]")).to_be_checked()
    expect(form.locator("input[name=threshold]")).to_have_value("73")
    expect(form.locator("input[name=window_minutes]")).to_have_value("35")
    values = {
        "ports": "445/tcp, 8080/any, 8000-8100/proto:47, 1000-1005/any, -1/proto:1, proto:47",
        "exclude_ports": "53/udp, 8080-8081/any",
        "initiator_process": "initiator.exe", "initiator_user": "corp\\initiator",
        "service_process": "service.exe", "service_user": "corp\\service", "text": "stored flow text",
        "initiator_processes": "first.exe\nsecond.exe", "initiator_users": "first-user\nsecond-user",
        "service_processes": "worker.exe\nagent.exe", "service_users": "worker-user\nagent-user",
        "windows_services": "wuauserv", "exclude_windows_services": "Spooler",
        "exclude_processes": "excluded.exe", "src_ips": "10.1.2.3", "dst_ips": "10.2.3.4",
        "src_exclude_ips": "10.3.4.5", "either_ips": "10.4.5.6", "either_exclude_ips": "10.5.6.7",
    }
    for name, value in values.items():
        expect(form.locator(f"[name={name}]")).to_have_value(value)
    for selector in ("input[name=decision_blocked]", "input[name=exclude_system_accounts]",
                     "input[name=transmission_broadcast]", "input[name=exclude_transmission_multicast]",
                     "input[name=src_public]", "input[name=dst_exclude_public]", "input[name=src_public]"):
        expect(form.locator(selector)).to_be_checked()
    expect(form.locator("[data-side=src] .chip", has_text="env=Prod")).to_have_count(1)
    expect(form.locator("[data-role=src-advanced] [data-href]")).to_have_attribute("data-href", "/orgs/1/workloads/123")
    expect(form.locator("[data-role=src_label_group] [data-label-group]")).to_have_attribute(
        "data-label-group", "/orgs/1/sec_policy/active/label_groups/3")
    expect(form.locator("[data-role=src_ip_list] [data-ip-list]")).to_have_attribute(
        "data-ip-list", "/orgs/1/sec_policy/active/ip_lists/7")
    expect(form.locator("select[name=src_match]")).to_have_value("all")
    expect(form.locator("[data-role=service] [data-service]")).to_have_attribute(
        "data-service", "/orgs/1/sec_policy/active/services/2")
    expect(form.locator("[data-role=exclude_service] [data-service]")).to_have_attribute(
        "data-service", "/orgs/1/sec_policy/active/services/4")
    expect(form.locator("[data-side=dst_exclude] input[name=dst_exclude_public]")).to_be_checked()


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
