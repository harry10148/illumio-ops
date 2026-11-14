"""A new alert rule starts from a list of scenarios (purpose-led UI spec §10, stage 4): four groups, each scenario
naming the rules that already cover it. A rule that matches events by a pattern is listed apart, under no category,
and nothing on the page says a scenario has no rule — the list cannot know what a pattern covers."""
from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import expect

from illumio_ops.domain.alertpack import best_practice_rules, pack_rule_id
from illumio_ops.domain.event_catalog import CATEGORY_KEYS, catalog
from illumio_ops.domain.values import DetectorKind, Language, SystemCheck
from illumio_ops.i18n import translate
from tests.e2e import ui_rules
from tests.e2e.conftest import NARROW, sign_in

GROUPS = {"event": len(CATEGORY_KEYS), "flow": 3, "detector": len(DetectorKind), "system": len(SystemCheck)}


def _open(page, live_app):
    page.goto(f"{live_app.url}/alerts/rules/new")
    page.wait_for_selector("[data-role=scenario-list] [data-scenario-group=event] [data-scenario]")
    page.wait_for_load_state("networkidle")
    return page.locator("[data-role=scenario-list]")


def _row(listing, scenario: str):
    return listing.locator(f"[data-scenario='{scenario}']")


def _add_rule(live_app, **fields) -> str:
    rule = {"id": uuid.uuid4().hex, "name": "Everything", "pack_key": None, "enabled": True, "notify": True,
            "severity": None, "cooldown_minutes": 30, "throttle": None, "type": "event", "event_types": ["*"],
            "status": "all", "event_severity": "all", "match_fields": {}, "threshold": "immediate",
            "threshold_count": 1, "window_minutes": 10} | fields
    s = live_app.ctx.settings
    s.update(s.current().revision, lambda d: d["alerts"]["rules"].append(rule))
    return str(rule["id"])


def _language(live_app, language: str) -> None:
    s = live_app.ctx.settings
    s.update(s.current().revision, lambda d: d["display"].update(language=language))


def test_the_numbers_this_file_counts_on():
    """What the row counts below stand on: 11 categories that each hold events, 21 detectors, 6 checks."""
    assert GROUPS == {"event": 11, "flow": 3, "detector": 21, "system": 6}
    assert {e.category for e in catalog()} == set(CATEGORY_KEYS)


@pytest.mark.parametrize("language", ["en", "zh_TW"])
def test_four_groups_with_every_scenario(browser, live_app, language):
    _language(live_app, language)
    ctx = browser.new_context(locale="zh-TW" if language == "zh_TW" else "en-US", viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    sign_in(page, live_app.url)
    listing = _open(page, live_app)
    assert listing.locator("[data-scenario-group]").evaluate_all("(els) => els.map((e) => e.dataset.scenarioGroup)") == list(GROUPS)
    for group, n in GROUPS.items():
        expect(listing.locator(f"[data-scenario-group={group}] [data-scenario]")).to_have_count(n)
    # every row has a name and a sentence, and none of them is a key left untranslated or an unfilled placeholder
    texts = listing.locator("[data-scenario]").evaluate_all(
        "(els) => els.map((e) => [e.querySelector('[data-role=scenario-name]').innerText.trim(),"
        " e.querySelector('[data-role=scenario-desc]').innerText.trim()])")
    assert all(name and desc for name, desc in texts), texts
    body = listing.inner_text()
    assert not re.search(r"\b(scn|evcat|detector_name|rule_system|alert_type|purpose)_\w+", body) and "{" not in body
    assert ui_rules.violations(page) == {}
    ctx.close()


def test_a_scenario_names_the_rules_that_cover_it(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    listing = _open(page, live_app)
    tamper = translate(Language.EN, "rule_agent_tampering")
    link = _row(listing, "event:agent_security").locator("[data-role=covered-by]", has_text=tamper)
    expect(link).to_have_text(f"Existing rule: {tamper}")
    # one rule, two categories: workloads.unpair and agents.unpair sit in different ones
    unpair = translate(Language.EN, "rule_bulk_unpair")
    for category in ("containers_workloads", "agent_operations"):
        expect(_row(listing, f"event:{category}").locator("[data-role=covered-by]", has_text=unpair)).to_have_count(1)
    # one rule, three detectors
    directory = translate(Language.EN, "rule_anomaly_directory")
    for kind in ("auth_to_non_dc", "new_dc_client", "directory_surge"):
        expect(_row(listing, f"detector:{kind}").locator("[data-role=covered-by]", has_text=directory)).to_have_count(1)
    expect(_row(listing, "flow:traffic").locator("[data-role=covered-by]")).to_have_text(
        f"Existing rule: {translate(Language.EN, 'rule_high_blocked')}")
    expect(_row(listing, "system:disk_low").locator("[data-role=covered-by]")).to_have_count(1)
    # a scenario no rule is filed under has no such line, and no words in its place
    quiet = _row(listing, "flow:bandwidth")
    expect(quiet.locator("[data-role=covered-by]")).to_have_count(0)
    assert quiet.locator("[data-role=scenario-new]").count() == 1
    link.click()
    page.wait_for_selector("[data-role=rule-editor]")
    assert page.url.endswith(f"/alerts/rules/{pack_rule_id('rule_agent_tampering')}")
    expect(page.locator("[data-role=rule-editor] textarea[name=event_types]")).to_have_value("agent.tampering")


def test_covered_scenarios_come_first_in_their_group(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    listing = _open(page, live_app)
    for group in GROUPS:
        covered = listing.locator(f"[data-scenario-group={group}] [data-scenario]").evaluate_all(
            "(els) => els.map((e) => e.querySelector('[data-role=covered-by]') !== null)")
        assert covered == sorted(covered, reverse=True), (group, covered)
    # the rest keep the order they are defined in: the event catalog's, the detector list's
    packed = {d.value for r in best_practice_rules(notify_new_defaults=True) if r.type == "lateral" for d in r.detectors}
    rest = listing.locator("[data-scenario-group=detector] [data-scenario]:not(:has([data-role=covered-by]))").evaluate_all(
        "(els) => els.map((e) => e.dataset.scenario.split(':')[1])")
    assert rest == [d.value for d in DetectorKind if d.value not in packed]


def test_a_rule_matching_by_pattern_is_listed_apart(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    listing = _open(page, live_app)
    expect(listing.locator("[data-role=pattern-rules]")).to_have_count(0)   # the pack names catalog types only
    everything = _add_rule(live_app)
    either = _add_rule(live_app, name="Either", event_types=["agent.tampering|agent.suspend"])
    unlisted = _add_rule(live_app, name="Unlisted", event_types=["vendor.brand_new"])
    mixed = _add_rule(live_app, name="Mixed", event_types=["agent.clone_detected", "^user\\."])
    listing = _open(page, live_app)
    apart = listing.locator("[data-role=pattern-rules]")
    for rid in (everything, either, unlisted, mixed):
        expect(apart.locator(f"a[href='/alerts/rules/{rid}']")).to_have_count(1)
    expect(apart.locator(f"[data-rule-id='{everything}']")).to_contain_text("each occurrence")   # its condition, as the rule list words it
    in_rows = listing.locator("[data-scenario] [data-role=covered-by]").evaluate_all("(els) => els.map((e) => e.getAttribute('href'))")
    for rid in (everything, either, unlisted):
        assert f"/alerts/rules/{rid}" not in in_rows
    # a rule naming a catalog type beside a pattern is under that type's category as well
    expect(_row(listing, "event:agent_security").locator(f"[data-role=covered-by][href='/alerts/rules/{mixed}']")).to_have_count(1)
    assert ui_rules.violations(page) == {}


@pytest.mark.parametrize("language", ["en", "zh_TW"])
def test_the_page_never_says_a_scenario_has_no_rule(browser, live_app, language):
    """With the pack, with a pattern rule beside it, and with no rule at all."""
    _language(live_app, language)
    ctx = browser.new_context(locale="zh-TW" if language == "zh_TW" else "en-US", viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    sign_in(page, live_app.url)
    said = []
    for prepare in (lambda: None, lambda: _add_rule(live_app),
                    lambda: live_app.ctx.settings.update(live_app.ctx.settings.current().revision,
                                                         lambda d: d["alerts"].__setitem__("rules", []))):
        prepare()
        listing = _open(page, live_app)
        said.append((listing.inner_text(), listing.locator("[data-role=covered-by]").count()))
    ctx.close()
    for text, _ in said:
        assert not re.search(r"no rules?\b|not covered|uncovered|沒有規則|尚無規則|無規則|未涵蓋", text, re.IGNORECASE)
    assert said[0][1] > 0 and said[2][1] == 0   # with no rule at all the lines are simply not there


def test_new_rule_on_the_rule_list_opens_the_scenarios(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules")
    page.get_by_role("link", name="New rule").click()
    listing = page.locator("[data-role=scenario-list]")
    expect(listing).to_be_visible()
    assert page.url.endswith("/alerts/rules/new")
    # no filled primary action on the page: nothing here is saved
    assert listing.locator("a, button").evaluate_all(
        "(els, fill) => els.filter((e) => getComputedStyle(e).backgroundColor === fill).length", ui_rules.PRIMARY_FILL) == 0
    # a scenario's "New" opens the short form of that scenario; the last link the form as it was
    checked = "(e) => e.checked"
    _row(listing, "detector:pivot_chain").locator("[data-role=scenario-new]").click()
    form = page.locator("[data-role=rule-editor]:has([data-role=short-form])")
    expect(form.locator("[data-role=scenario]")).to_contain_text("Pivot chain")
    assert form.locator("input[name=detector_pivot_chain]").evaluate(checked) is True
    assert form.locator("input[name=detector_fanout]").evaluate(checked) is False
    page.locator("[data-role=scenario-back]").click()
    _row(page.locator("[data-role=scenario-list]"), "system:disk_low").locator("[data-role=scenario-new]").click()
    assert page.locator("[data-role=short-form] ~ details select[name=check]").evaluate("(e) => e.value") == "disk_low"
    page.go_back()
    _row(page.locator("[data-role=scenario-list]"), "flow:volume").locator("[data-role=scenario-new]").click()
    expect(page.locator("[data-role=short-form]")).to_contain_text("MB")
    page.go_back()
    page.locator("[data-role=scenario-list] [data-role=full-form]").click()
    expect(page.locator("[data-role=rule-editor] select[name=type]")).to_have_value("event")
    assert page.url.endswith("/alerts/rules/new?form=full")


def test_the_list_fits_the_narrow_width(narrow_context, live_app):
    _add_rule(live_app)
    page = narrow_context.new_page()
    sign_in(page, live_app.url)
    _open(page, live_app)
    assert page.viewport_size["width"] == NARROW
    assert ui_rules.violations(page) == {}


# ── a scenario says what fires it first, its conditions after ──

WITHOUT_NOTES = {"detector:fanout", "detector:pivot_chain", "detector:cross_env", "detector:auth_to_non_dc",
                 "flow:traffic", *(f"system:{c.value}" for c in SystemCheck)}


@pytest.mark.parametrize(("language", "width"), [("en", 1280), ("zh_TW", 1280), ("en", NARROW)])
def test_a_row_says_what_fires_it_then_its_conditions(browser, live_app, language, width):
    _language(live_app, language)
    lang = Language.ZH_TW if language == "zh_TW" else Language.EN
    ctx = browser.new_context(locale="zh-TW" if language == "zh_TW" else "en-US", viewport={"width": width, "height": 900})
    page = ctx.new_page()
    sign_in(page, live_app.url)
    listing = _open(page, live_app)
    rows = listing.locator("[data-scenario-group=detector] [data-scenario], [data-scenario-group=flow] [data-scenario], "
                           "[data-scenario-group=system] [data-scenario]").evaluate_all(
        "(els) => els.map((e) => { const n = e.querySelector('[data-role=scenario-notes]');"
        " return [e.dataset.scenario, e.querySelector('[data-role=scenario-desc]').innerText.trim(),"
        " n ? n.innerText.trim() : null, n ? getComputedStyle(n).fontSize : null,"
        " getComputedStyle(e.querySelector('[data-role=scenario-desc]')).fontSize,"
        " n ? n.previousElementSibling.dataset.role : null]; })")
    assert len(rows) == 21 + 3 + 6
    for scenario, desc, notes, notes_size, desc_size, before in rows:
        group, name = scenario.split(":")
        key = {"detector": "scn_det_", "flow": "scn_flow_", "system": "scn_sys_"}[group] + name
        assert desc == translate(lang, key), scenario   # the trigger: one sentence
        assert desc.count("。" if language == "zh_TW" else ". ") == (1 if language == "zh_TW" else 0), scenario
        if scenario in WITHOUT_NOTES:
            assert notes is None, scenario
        else:
            assert notes == translate(lang, key + "_notes"), scenario
            assert before == "scenario-desc" and float(notes_size[:-2]) < float(desc_size[:-2]), scenario   # under it, as a hint
    assert sum(1 for r in rows if r[0].startswith("detector:") and r[2]) == 17
    assert ui_rules.violations(page) == {}
    ctx.close()


def test_the_short_form_shows_the_trigger_and_its_conditions(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/rules/new?scenario=detector:new_pair_port")
    top = page.locator("[data-role=short-form] [data-role=scenario]")
    expect(top).to_contain_text(translate(Language.EN, "scn_det_new_pair_port"))
    notes = page.locator("[data-role=short-form] [data-role=scenario-notes]")
    expect(notes).to_have_text(translate(Language.EN, "scn_det_new_pair_port_notes"))
    assert "hint" in notes.get_attribute("class").split()
    page.wait_for_load_state("networkidle")
    assert ui_rules.violations(page) == {}
    page.goto(f"{live_app.url}/alerts/rules/new?scenario=detector:fanout")
    page.wait_for_selector("[data-role=short-form] [data-role=scenario]")
    expect(page.locator("[data-role=scenario-notes]")).to_have_count(0)


def test_every_notes_key_belongs_to_a_scenario_sentence():
    """Nothing was dropped into a key no row shows: each *_notes key sits beside the sentence it continues."""
    from illumio_ops.i18n import dictionary
    for lang in (Language.EN, Language.ZH_TW):
        d = dictionary(lang)
        notes = {k for k in d if k.startswith("scn_") and k.endswith("_notes")}
        assert len(notes) == 19 and all(k[:-len("_notes")] in d for k in notes)
        group = {"scn_det_": "detector", "scn_flow_": "flow", "scn_sys_": "system"}
        assert {f"{group[k[:k.index('_', 4) + 1]]}:{k[k.index('_', 4) + 1:-len('_notes')]}" for k in notes}.isdisjoint(WITHOUT_NOTES)
