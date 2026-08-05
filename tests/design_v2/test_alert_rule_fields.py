"""Rule-field coverage gate (UI redesign v2, failure point #2).

The previous redesign attempt shipped rule drawers that silently dropped backend
fields: a rule edited through the new UI came back with fewer keys than it went
in with. This test makes that a test failure. Every key a rule of a given type
carries in design/v2/snapshots/rules.json (minus the identity/state keys listed
in INTERNAL) must be present in that type's drawer as an element with
data-field="<key>" — editable or read-only, but present and named.

Departures from the task brief's sketch, and why:

  * ``idx`` -> ``index``. The brief's INTERNAL set names ``idx``; the payload key
    is ``index`` (gui/routes/rules.py:107 recomputes it on every GET and it is
    the address used by PUT/DELETE /api/rules/<idx>). Same concept, real name.
    ``created_at``/``updated_at``/``last_run``/``last_status`` are kept in the
    set although no rule carries them today — they cost nothing and keep the
    brief's intent if the backend ever adds them.

  * The union of a type's keys, not the first rule's. The sketch keeps one
    sample rule per type (``by_type.setdefault``), which would have missed
    ``rec_key`` (11 of the 16 event rules carry it) and ``name_key``/``desc_key``
    (15 and 14 of 16). A drawer that covers only the first rule still loses a
    field on the second, so the gate asserts against every key the type uses.

  * rules.json is a bare list (the capture stores /api/rules verbatim), which the
    sketch already tolerated; the unwrapping is kept.

  * The fixed ``sleep(0.8)`` is replaced by waiting for the AL-01 anchor. The
    drawer opener only exists after the snapshots have loaded, so a slow machine
    would otherwise fail on a race rather than on a missing field. The assertion
    itself is unchanged.

  * ``window.__openRuleDrawer(type)`` is asserted to exist before it is used, so
    a renamed contract fails with that sentence instead of a JS TypeError.
"""
import json
import pathlib
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2] / "design" / "v2"
SNAP = ROOT / "snapshots" / "rules.json"
PORT = 8379

# Keys that identify or annotate a rule rather than configure it.
INTERNAL = {"id", "idx", "index", "enabled", "created_at", "updated_at", "last_run", "last_status"}

# The drawer opened for "bandwidth" is the one that edits both metric types
# (rules.js:572-583 stores the metric in `type`), so a volume rule's keys are
# checked against the same drawer.
DRAWER_OF = {"bandwidth": "bandwidth", "volume": "bandwidth"}


def _rules():
    data = json.loads(SNAP.read_text(encoding="utf-8"))
    return data["rules"] if isinstance(data, dict) and "rules" in data else data


def _keys_by_type():
    """type -> the union of the keys every rule of that type carries."""
    out = {}
    for rule in _rules():
        out.setdefault(rule["type"], set()).update(rule.keys())
    return out


@pytest.fixture(scope="module")
def page():
    playwright = pytest.importorskip("playwright.sync_api", exc_type=ImportError)
    srv = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "-d", str(ROOT / "mockup")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.8)
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch()
            pg = browser.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.errors = errors
            pg.goto(f"http://127.0.0.1:{PORT}/index.html#/alerting/rules")
            pg.wait_for_selector("[data-cov='AL-01'] table", timeout=15000)
            yield pg
            browser.close()
    finally:
        srv.terminate()


def test_snapshot_has_all_four_rule_types():
    """Without all four types the coverage assertion below proves nothing."""
    have = set(_keys_by_type())
    assert have >= {"event", "system", "traffic", "bandwidth"}, (
        "the staging appliance needs at least one rule of each type before the "
        f"snapshot is recaptured; this one has {sorted(have)}"
    )


def test_openrule_drawer_contract_exists(page):
    assert page.evaluate("typeof window.__openRuleDrawer") == "function", (
        "js/areas/alerting.mjs must expose window.__openRuleDrawer(type) — it is "
        "the contract this gate and window.__openAllForAudit() both use"
    )


@pytest.mark.parametrize("rtype", sorted(_keys_by_type()))
def test_drawer_fields_cover_snapshot_keys(page, rtype):
    wanted = _keys_by_type()[rtype] - INTERNAL
    page.evaluate("window.__drawerProbe = window.__openRuleDrawer(%s)" % json.dumps(DRAWER_OF.get(rtype, rtype)))
    page.wait_for_timeout(300)
    have = set(page.eval_on_selector_all(
        ".drawer [data-field]", "els => els.map(e => e.dataset.field)"))
    missing = wanted - have
    page.evaluate("window.__drawerProbe && window.__drawerProbe.close()")
    assert not missing, f"{rtype} drawer missing fields: {sorted(missing)}"
    assert page.errors == [], page.errors
