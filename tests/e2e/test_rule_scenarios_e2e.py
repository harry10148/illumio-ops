"""Detection and system rule scenarios, plus the legacy URL redirects from alert-rules-page spec §4.8."""
from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import expect

from illumio_ops.domain.alertpack import best_practice_rules
from illumio_ops.domain.values import DetectorKind, Language, SystemCheck
from illumio_ops.i18n import translate
from tests.e2e import ui_rules
from tests.e2e.conftest import NARROW, sign_in

GROUPS = {"detector": len(DetectorKind), "system": len(SystemCheck)}


def _open(page, live_app):
    page.goto(f"{live_app.url}/alerts/rules/new?only=special")
    page.wait_for_selector("[data-role=scenario-list] [data-scenario-group=detector] [data-scenario]")
    page.wait_for_load_state("networkidle")
    return page.locator("[data-role=scenario-list]")


def _row(listing, scenario: str):
    return listing.locator(f"[data-scenario='{scenario}']")


def _language(live_app, language: str) -> None:
    s = live_app.ctx.settings
    s.update(s.current().revision, lambda d: d["display"].update(language=language))


def test_the_numbers_this_file_counts_on():
    """The scenario list has 21 detectors and 6 system checks."""
    assert GROUPS == {"detector": 21, "system": 6}


@pytest.mark.parametrize("language", ["en", "zh_TW"])
def test_detection_and_system_groups_have_every_scenario(browser, live_app, language):
    _language(live_app, language)
    ctx = browser.new_context(locale="zh-TW" if language == "zh_TW" else "en-US", viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    sign_in(page, live_app.url)
    listing = _open(page, live_app)
    assert listing.locator("[data-scenario-group]").evaluate_all("(els) => els.map((e) => e.dataset.scenarioGroup)") == list(GROUPS)
    for group, count in GROUPS.items():
        expect(listing.locator(f"[data-scenario-group={group}] [data-scenario]")).to_have_count(count)
    texts = listing.locator("[data-scenario]").evaluate_all(
        "(els) => els.map((e) => [e.querySelector('[data-role=scenario-name]').innerText.trim(),"
        " e.querySelector('[data-role=scenario-desc]').innerText.trim()])")
    assert all(name and desc for name, desc in texts), texts
    body = listing.inner_text()
    assert not re.search(r"\b(scn|evcat|detector_name|rule_system|alert_type|purpose)_\w+", body) and "{" not in body
    assert ui_rules.violations(page) == {}
    ctx.close()


def test_a_scenario_names_the_detection_and_system_rules_that_cover_it(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    listing = _open(page, live_app)
    directory = translate(Language.EN, "rule_anomaly_directory")
    for kind in ("auth_to_non_dc", "new_dc_client", "directory_surge"):
        expect(_row(listing, f"detector:{kind}").locator("[data-role=covered-by]", has_text=directory)).to_have_count(1)
    expect(_row(listing, "system:disk_low").locator("[data-role=covered-by]")).to_have_count(1)
    expect(_row(listing, "detector:quiet_host_wakes").locator("[data-role=covered-by]")).to_have_count(1)
    # a scenario no rule is filed under has no such line, and no words in its place
    expect(_row(listing, "detector:pivot_chain").locator("[data-role=covered-by]")).to_have_count(0)
    assert _row(listing, "detector:pivot_chain").locator("[data-role=scenario-new]").count() == 1
    assert ui_rules.violations(page) == {}


def test_covered_scenarios_come_first_in_their_group(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    listing = _open(page, live_app)
    for group in GROUPS:
        covered = listing.locator(f"[data-scenario-group={group}] [data-scenario]").evaluate_all(
            "(els) => els.map((e) => e.querySelector('[data-role=covered-by]') !== null)")
        assert covered == sorted(covered, reverse=True), (group, covered)
    packed = {detector.value for rule in best_practice_rules(notify_new_defaults=True) if rule.type == "lateral" for detector in rule.detectors}
    rest = listing.locator("[data-scenario-group=detector] [data-scenario]:not(:has([data-role=covered-by]))").evaluate_all(
        "(els) => els.map((e) => e.dataset.scenario.split(':')[1])")
    assert rest == [detector.value for detector in DetectorKind if detector.value not in packed]


@pytest.mark.parametrize("language", ["en", "zh_TW"])
def test_the_page_never_says_a_scenario_has_no_rule(browser, live_app, language):
    """With the pack, and with no rules at all."""
    _language(live_app, language)
    ctx = browser.new_context(locale="zh-TW" if language == "zh_TW" else "en-US", viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    sign_in(page, live_app.url)
    said = []
    for prepare in (lambda: None,
                    lambda: live_app.ctx.settings.update(live_app.ctx.settings.current().revision,
                                                         lambda d: d["alerts"].__setitem__("rules", []))):
        prepare()
        listing = _open(page, live_app)
        said.append((listing.inner_text(), listing.locator("[data-role=covered-by]").count()))
    ctx.close()
    for text, _ in said:
        assert not re.search(r"no rules?\b|not covered|uncovered|沒有規則|尚無規則|無規則|未涵蓋", text, re.IGNORECASE)
    assert said[0][1] > 0 and said[1][1] == 0


def test_new_rule_on_the_rules_page_opens_the_event_and_traffic_form(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules")
    page.get_by_role("link", name="New rule").click()
    expect(page.locator("[data-role=rule-form]")).to_be_visible()
    assert "rule=new" in page.url


def test_scenario_list_links_open_detection_and_system_forms(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    listing = _open(page, live_app)
    assert listing.locator("[data-scenario-group]").evaluate_all("(els) => els.map((e) => e.dataset.scenarioGroup)") == ["detector", "system"]
    assert listing.locator("[data-scenario-group=event], [data-scenario-group=flow]").count() == 0
    assert listing.locator("a, button").evaluate_all(
        "(els, fill) => els.filter((e) => getComputedStyle(e).backgroundColor === fill).length", ui_rules.PRIMARY_FILL) == 0
    _row(listing, "detector:pivot_chain").locator("[data-role=scenario-new]").click()
    form = page.locator("[data-role=rule-editor]:has([data-role=short-form])")
    expect(form.locator("[data-role=scenario]")).to_contain_text("Pivot chain")
    expect(form.locator("input[name=detector_pivot_chain]")).to_be_checked()
    expect(form.locator("input[name=detector_fanout]")).not_to_be_checked()
    page.locator("[data-role=scenario-back]").click()
    _row(page.locator("[data-role=scenario-list]"), "system:disk_low").locator("[data-role=scenario-new]").click()
    assert page.locator("[data-role=short-form] ~ details select[name=check]").evaluate("(e) => e.value") == "disk_low"
    page.goto(f"{live_app.url}/alerts/rules/new?form=full")
    form = page.locator("[data-role=rule-editor]")
    expect(form.locator("select[name=type]")).to_have_value("lateral")
    assert form.locator("select[name=type] option").evaluate_all("(els) => els.map((e) => e.value)") == ["lateral", "system"]
    assert page.url.endswith("/alerts/rules/new?form=full")


def _clone_rule(rule_type: str) -> dict:
    models = best_practice_rules(notify_new_defaults=True)
    if rule_type in ("bandwidth", "volume"):
        model = next(rule for rule in models if rule.type == "traffic")
    else:
        model = next(rule for rule in models if rule.type == rule_type)
    fields = model.model_dump(mode="json")
    if rule_type == "bandwidth":
        fields.pop("threshold_connections")
        fields.update(type="bandwidth", threshold_mbps=100, window_minutes=60)
    elif rule_type == "volume":
        fields.pop("threshold_connections")
        fields.update(type="volume", threshold_mb=1024, window_minutes=60)
    fields.update(id=uuid.uuid4().hex, name=f"Redirect {rule_type}", pack_key=None)
    return fields


def test_each_legacy_rule_url_redirects_by_rule_type(context, live_app):
    rules = {kind: _clone_rule(kind) for kind in ("event", "traffic", "bandwidth", "volume", "lateral", "system")}
    settings = live_app.ctx.settings
    settings.update(settings.current().revision, lambda d: d["alerts"]["rules"].extend(rules.values()))
    page = context.new_page()
    sign_in(page, live_app.url)

    # The old list route and bare new route now open the replacement list/form.
    page.goto(f"{live_app.url}/alerts/rules")
    page.wait_for_url("**/alert-rules")
    expect(page.locator("[data-role=rules-summary]")).to_be_visible()
    page.goto(f"{live_app.url}/alerts/rules/new")
    page.wait_for_url("**/alert-rules?rule=new")
    expect(page.locator("[data-role=rule-form]")).to_be_visible()

    # Old event and flow scenarios start in the new event/traffic form.
    for scenario in ("event:agent_security", "flow:traffic"):
        page.goto(f"{live_app.url}/alerts/rules/new?scenario={scenario}")
        page.wait_for_url("**/alert-rules?rule=new")
        expect(page.locator("[data-role=rule-form]")).to_be_visible()

    # Detection and system scenario URLs remain on the legacy short form; the special list is a supported new entry.
    for scenario in ("detector:fanout", "system:disk_low"):
        page.goto(f"{live_app.url}/alerts/rules/new?scenario={scenario}")
        page.wait_for_selector("[data-role=short-form]")
        assert page.url.endswith(f"/alerts/rules/new?scenario={scenario}")
    listing = _open(page, live_app)
    assert page.url.endswith("/alerts/rules/new?only=special")
    assert listing.locator("[data-scenario-group]").evaluate_all("(els) => els.map((e) => e.dataset.scenarioGroup)") == ["detector", "system"]

    for kind in ("event", "traffic", "bandwidth", "volume"):
        page.goto(f"{live_app.url}/alerts/rules/{rules[kind]['id']}")
        page.wait_for_url(f"**/alert-rules?rule={rules[kind]['id']}")
        expect(page.locator("[data-role=rule-form]")).to_be_visible()
    for kind in ("lateral", "system"):
        page.goto(f"{live_app.url}/alerts/rules/{rules[kind]['id']}")
        page.wait_for_selector("[data-role=rule-editor]")
        assert page.url.endswith(f"/alerts/rules/{rules[kind]['id']}")

    # The old full-form URL stays in place with only the two preserved types.
    page.goto(f"{live_app.url}/alerts/rules/new?form=full")
    page.wait_for_selector("[data-role=rule-editor]")
    expect(page.locator("select[name=type]")).to_have_value("lateral")
    assert page.locator("select[name=type] option").evaluate_all("(els) => els.map((e) => e.value)") == ["lateral", "system"]
    assert page.url.endswith("/alerts/rules/new?form=full")


def test_the_list_fits_the_narrow_width(narrow_context, live_app):
    page = narrow_context.new_page()
    sign_in(page, live_app.url)
    listing = _open(page, live_app)
    assert page.viewport_size["width"] == NARROW
    assert listing.locator("[data-scenario-group]").count() == 2
    assert ui_rules.violations(page) == {}


WITHOUT_NOTES = {"detector:fanout", "detector:cross_env", *(f"system:{check.value}" for check in SystemCheck)}


@pytest.mark.parametrize(("language", "width"), [("en", 1280), ("zh_TW", 1280), ("en", NARROW)])
def test_a_row_says_what_fires_it_then_its_conditions(browser, live_app, language, width):
    _language(live_app, language)
    lang = Language.ZH_TW if language == "zh_TW" else Language.EN
    ctx = browser.new_context(locale="zh-TW" if language == "zh_TW" else "en-US", viewport={"width": width, "height": 900})
    page = ctx.new_page()
    sign_in(page, live_app.url)
    listing = _open(page, live_app)
    rows = listing.locator("[data-scenario-group=detector] [data-scenario], [data-scenario-group=system] [data-scenario]").evaluate_all(
        "(els) => els.map((e) => { const n = e.querySelector('[data-role=scenario-notes]');"
        " return [e.dataset.scenario, e.querySelector('[data-role=scenario-desc]').innerText.trim(),"
        " n ? n.innerText.trim() : null, n ? getComputedStyle(n).fontSize : null,"
        " getComputedStyle(e.querySelector('[data-role=scenario-desc]')).fontSize,"
        " n ? n.previousElementSibling.dataset.role : null]; })")
    assert len(rows) == 21 + 6
    for scenario, desc, notes, notes_size, desc_size, before in rows:
        group, name = scenario.split(":")
        key = {"detector": "scn_det_", "system": "scn_sys_"}[group] + name
        assert desc == translate(lang, key), scenario
        assert desc.count("。" if language == "zh_TW" else ". ") == (1 if language == "zh_TW" else 0), scenario
        if scenario in WITHOUT_NOTES:
            assert notes is None, scenario
        else:
            assert notes == translate(lang, key + "_notes"), scenario
            assert before == "scenario-desc" and float(notes_size[:-2]) < float(desc_size[:-2]), scenario
    assert sum(1 for row in rows if row[0].startswith("detector:") and row[2]) == 19
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
    """Notes remain paired with the detector/system sentences and the preserved traffic-rule hints."""
    from illumio_ops.i18n import dictionary
    for lang in (Language.EN, Language.ZH_TW):
        d = dictionary(lang)
        notes = {key for key in d if key.startswith("scn_") and key.endswith("_notes")}
        assert len(notes) == 21
        assert all(key[:-len("_notes")] in d for key in notes if not key.startswith("scn_flow_"))
        assert all(key.startswith(("scn_det_", "scn_flow_")) for key in notes)
