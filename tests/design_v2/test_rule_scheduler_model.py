"""Rule-scheduler data-model gate (UI redesign v2, failure point #1).

The previous redesign attempt lost the rule scheduler's DUAL TARGET model: a
schedule addresses EITHER a whole ruleset (href .../rule_sets/<id>) OR one single
rule inside one (href .../rule_sets/<id>/sec_rules/<rid>), and the redesign
collapsed both into one nameless "schedule" row — after which the rule level was
unreachable from the UI.

This gate makes that class of loss a test failure. It serves the mockup, opens
#/automation/rules, and compares the AU-08 table against snapshots/rs_schedules.json:

  1. one row per stored schedule — no silent grouping, no dropped rows;
  2. the set of target kinds rendered equals the set the hrefs imply;
  3. the one_time schedule shows its expire_at (the field the recurring shape
     does not have — losing it is how "expires 2027-01-01" becomes "no timing");
  4. the rule-level row shows its rule-level detail (parent ruleset + the rule's
     own name), which is exactly what a ruleset-only model cannot render.

Departure from the task brief's sketch: the snapshot is a BARE LIST (the endpoint
returns `jsonify(result)`, rule_scheduler.py:300), not {"schedules": [...]}, so the
unwrapping tolerates both and the tests assert against the list.
"""
import json
import pathlib
import re
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2] / "design" / "v2"
SNAP = ROOT / "snapshots" / "rs_schedules.json"
PORT = 8380
ROUTE = f"http://127.0.0.1:{PORT}/index.html#/automation/rules"

# Same regex the UI uses (automation.mjs RULE_HREF): a rule href is a ruleset
# href with one more pair of segments, across all THREE rule collections the
# PCE exposes (sec_rules = allow, rules = legacy allow, deny_rules = deny /
# override_deny — rule_scheduler.py:160-166 reads all three).
RULE_HREF = re.compile(r"/rule_sets/[^/]+/(sec_rules|rules|deny_rules)/")


def _schedules():
    snap = json.loads(SNAP.read_text())
    rows = snap["schedules"] if isinstance(snap, dict) and "schedules" in snap else snap
    assert rows, "測試機需至少有 1 筆 ruleset 排程＋1 筆 rule 排程，缺就先建再重抓"
    return rows


def _kind(entry):
    """Primary judge: the product's own authoritative `is_ruleset` field — the
    flag the create form sends (rule-scheduler.js:449) and the one
    api_client.py:1325 uses to pick the PROVISION scope (rule-scheduler.js:504
    displays it as authoritative). Cross-check: the SAME RULE_HREF regex the UI
    uses, matched only against href. The two must agree; a disagreement is
    exactly the dual-target collapse this gate exists to catch, so it fails
    loudly with the offending entry instead of silently picking one side.

    The previous heuristic (`"/sec_rules/" in json.dumps(entry)`) was wrong on
    two independent counts: (a) it only recognises ONE of the three rule
    collections, so every deny-rule schedule (href .../deny_rules/<id>) reads
    as "ruleset" and would fail a CORRECTLY rendered UI; (b) json.dumps(entry)
    scans every string field of the entry, not just href, so an unrelated field
    that happens to contain the substring "/sec_rules/" would misclassify the
    row.
    """
    href = str(entry.get("href", ""))
    by_is_ruleset = "ruleset" if entry.get("is_ruleset") else "rule"
    by_href = "rule" if RULE_HREF.search(href) else "ruleset"
    assert by_is_ruleset == by_href, (
        f"is_ruleset and href disagree on target kind for entry: "
        f"is_ruleset={entry.get('is_ruleset')!r} -> {by_is_ruleset!r}, "
        f"href={href!r} -> {by_href!r}; entry={entry!r}"
    )
    return by_is_ruleset


@pytest.fixture(scope="module")
def page():
    pytest.importorskip("playwright.sync_api", exc_type=ImportError)
    from playwright.sync_api import sync_playwright

    srv = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "-d", str(ROOT / "mockup")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(0.8)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            pg = browser.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.errors = errors
            pg.goto(ROUTE)
            pg.wait_for_selector("[data-cov='AU-08'] [data-sched-target-kind]", timeout=10000)
            yield pg
            browser.close()
    finally:
        srv.terminate()
        srv.wait(timeout=10)


def _rows(page):
    return page.eval_on_selector_all(
        "[data-cov='AU-08'] [data-sched-target-kind]",
        "els => els.map(e => ({kind: e.dataset.schedTargetKind, "
        "id: e.dataset.schedId, text: e.textContent}))")


def test_schedule_rows_mirror_snapshot(page):
    """Row count AND each row's own kind must mirror its own stored schedule.

    A set-of-kinds comparison ({kind} == {kind}) is blind to a same-size swap:
    a reviewer mutation that renders the 619 ruleset schedule's row with
    kind="rule" and the 1724 rule schedule's row with kind="ruleset" leaves the
    set {"ruleset", "rule"} unchanged, so that comparison alone stays green on
    a UI that mislabels every row. Binding each rendered row to its own
    schedule via data-sched-id (the schedule's href, set in automation.mjs next
    to data-sched-target-kind) turns this into a per-row assertion that a swap
    cannot pass.
    """
    schedules = _schedules()
    rows = _rows(page)
    assert len(rows) == len(schedules)

    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {s["href"] for s in schedules}, (
        f"rendered row ids do not mirror snapshot hrefs: "
        f"rows={sorted(by_id)} snapshot={sorted(s['href'] for s in schedules)}"
    )
    for s in schedules:
        row = by_id[s["href"]]
        expected = _kind(s)
        assert row["kind"] == expected, (
            f"schedule {s['href']!r} is {expected!r} by is_ruleset/href but "
            f"rendered with data-sched-target-kind={row['kind']!r}: {row}"
        )
    assert page.errors == [], page.errors


def test_both_target_levels_are_present(page):
    """Guard the guard: with only one level in the snapshot, the test above would
    pass on a UI that renders one level."""
    kinds = {_kind(s) for s in _schedules()}
    assert kinds == {"ruleset", "rule"}, f"snapshot no longer covers both levels: {kinds}"


def test_one_time_schedule_renders_its_expire_at(page):
    """A one_time schedule's timing IS its expire_at; a recurring-only row shape
    would drop it."""
    one_time = [s for s in _schedules() if s.get("type") == "one_time"]
    assert one_time, "snapshot carries no one_time schedule"
    body = page.inner_text("[data-cov='AU-08']")
    for s in one_time:
        stamp = str(s["expire_at"]).replace("T", " ")
        assert stamp in body, f"expire_at {stamp} is not rendered in AU-08"


def test_rule_level_row_shows_rule_target_detail(page):
    """The rule-level row must name the rule AND the ruleset that contains it —
    the detail a ruleset-only model has nowhere to put."""
    rules = [s for s in _schedules() if _kind(s) == "rule"]
    assert rules, "snapshot carries no rule-level schedule"
    rows = _rows(page)
    for s in rules:
        hit = [r for r in rows if r["kind"] == "rule"
               and str(s.get("detail_name", "")) in r["text"]
               and str(s.get("detail_rs", "")) in r["text"]]
        assert hit, (f"no rule row carries both detail_name={s.get('detail_name')!r} "
                     f"and detail_rs={s.get('detail_rs')!r}: {rows}")
