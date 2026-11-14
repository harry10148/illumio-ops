"""A policy decision is named in plain words with the PCE's own word beside it (purpose-led UI spec §5.6, stage 3a
Task 5) in the five places the console names one: the condition editor, the SIEM destination, the predicted-block
rows, the cross-environment connections and a rule's line of words. Read from the rendered page, in English (the
longest wording), at the wide and the narrow width: the words are there, a checkbox label stays on one line, and the
shared presentation rules still hold on that page in that state."""
import pytest
from playwright.sync_api import expect

from illumio_ops.services import workbench
from tests.e2e import test_lateral_e2e as lateral_e2e
from tests.e2e import test_predicted_e2e as predicted_e2e
from tests.e2e import ui_rules
from tests.e2e.conftest import NARROW, sign_in

ALLOWED = "Allowed (a rule allows it)"
PB = "Potentially Blocked"
WIDTHS = (1280, NARROW)

# The lines the element's own words are laid out on (1: they did not wrap); its checkbox is not text.
_LINES = """el => { const lines = new Set(); const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) { const r = document.createRange(); r.selectNodeContents(n);
    for (const x of r.getClientRects()) if (x.width > 0) lines.add(Math.round(x.bottom)); }
  return lines.size; }"""


@pytest.fixture(params=WIDTHS)
def page(request, browser, live_app):
    ctx = browser.new_context(locale="en-US", viewport={"width": request.param, "height": 900})
    p = ctx.new_page()
    sign_in(p, live_app.url)
    yield p
    ctx.close()


def _rules_hold(page) -> None:
    page.wait_for_load_state("networkidle")
    assert ui_rules.violations(page) == {}


def test_the_condition_editor_names_each_decision(page, live_app):
    page.goto(f"{live_app.url}/alerts/rules/new?form=full")
    form = page.locator("[data-role=rule-editor]")
    form.locator("select[name=type]").select_option("traffic")
    labels = {d: form.locator(f"label.check:has(input[name=decision_{d}])")
              for d in ("allowed", "potentially_blocked", "blocked", "unknown")}
    assert {d: lab.inner_text().strip() for d, lab in labels.items()} == {
        "allowed": ALLOWED, "potentially_blocked": PB, "blocked": "Blocked", "unknown": "Unknown"}
    assert {d: lab.evaluate(_LINES) for d, lab in labels.items()} == dict.fromkeys(labels, 1)
    _rules_hold(page)


def test_the_siem_destination_names_each_decision(page, live_app):
    page.goto(f"{live_app.url}/siem")
    page.locator("[data-role=siem-add]").click()
    card = page.locator("[data-role=siem-destination]")
    card.locator("input[name=siem_source_new_connections]").check()
    row = card.locator("[data-role=siem-decisions]")
    labels = {d: row.locator(f"label.check:has(input[name=siem_decision_{d}])")
              for d in ("allowed", "potentially_blocked", "blocked", "unknown")}
    assert {d: lab.inner_text().strip() for d, lab in labels.items()} == {
        "allowed": ALLOWED, "potentially_blocked": PB, "blocked": "Blocked", "unknown": "Unknown"}
    assert {d: lab.evaluate(_LINES) for d, lab in labels.items()} == dict.fromkeys(labels, 1)
    _rules_hold(page)


def test_the_predicted_rows_name_the_decision_now_and_the_draft_s(page, live_app, monkeypatch):
    monkeypatch.setattr(workbench, "predict_blocks", predicted_e2e._predicted)
    page.goto(f"{live_app.url}/investigate")
    panel = page.locator("[data-role=predicted]")
    panel.locator("[data-role=pred-run]").click()
    cells = panel.locator("[data-role=pred-rows] tbody tr td")
    expect(cells.nth(3)).to_have_text(PB)          # the decision the PCE reported
    expect(cells.nth(4)).to_have_text("Blocked (Override Deny)")  # what the draft policy would decide
    _rules_hold(page)


def test_the_cross_environment_connections_name_the_decision(page, live_app):
    lateral_e2e._seed(live_app)
    page.goto(f"{live_app.url}/detect")
    page.wait_for_selector("[data-section=status]")
    lateral_e2e.unfold(page)
    row = page.locator("[data-section=cross-env] tbody tr")
    expect(row).to_have_count(1)
    expect(row.locator("td").nth(-2)).to_have_text(ALLOWED)  # the last cell is the row's button
    _rules_hold(page)


def test_a_rule_s_line_of_words_names_its_decisions(page, live_app):
    rule = {"id": "d" * 32, "name": "Not yet blocked", "pack_key": None, "enabled": True, "notify": True,
            "severity": "high", "cooldown_minutes": 0, "throttle": None, "type": "traffic", "window_minutes": 60,
            "threshold_connections": 25,
            "condition": {"decisions": ["potentially_blocked", "allowed"], "ports": [{"port": 3389, "proto": 6}]}}
    ctx = live_app.ctx
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["alerts"]["rules"].append(rule))
    page.goto(f"{live_app.url}/alert-rules")
    cond = page.locator(f"[data-role=rule-list] tr[data-rule-id='{'d' * 32}'] [data-role=rule-condition]")
    assert f"{PB} or {ALLOWED}" in cond.inner_text()
    _rules_hold(page)
