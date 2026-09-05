"""Rule-field coverage gate (UI redesign v2, failure point #2).

The previous redesign attempt shipped rule drawers that silently dropped backend
fields: a rule edited through the new UI came back with fewer keys than it went
in with. This test makes that a test failure. Every key a rule of a given type
carries — the union of design/v2/snapshots/rules.json's captured keys AND the
keys the live backend actually returns for a rule created through this run
(minus the identity/state keys listed in INTERNAL) — must be present in that
type's drawer as an element with data-field="<key>", editable or read-only,
but present and named.

Task 6 review (2026-08-15), Important finding: this file used to drive a
static `http.server` over `design/v2/mockup` and check the FROZEN mockup's
`alerting.mjs`, never the shipped `src/static/js/v2/areas/alerting.mjs` — and
the checks that were actually run deselected 5 of this file's 6 tests
(test_openrule_drawer_contract_exists plus all four parametrized
test_drawer_fields_cover_snapshot_keys cases — bandwidth/event/system/
traffic), so the one guard purpose-built to catch a silently-dropped rule
field was checking dead code. Fixed by pointing this file at the real Flask app
(tests/v2_e2e_utils.py's build_v2_app + live server, the same harness
tests/test_v2_alerting_e2e.py uses) and driving window.__openRuleDrawer on
the production route, and by widening `wanted` to include the live-created
rule's own keys — not just the frozen snapshot — so a rules.py schema change
that isn't reflected in the (necessarily static) snapshot file still gets
caught against the CURRENT backend.

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
    (15 and 14 of 16) in the captured snapshot. A drawer that covers only the
    first rule still loses a field on the second, so the gate asserts against
    every key the type uses — snapshot union AND live-rule keys.

  * rules.json is a bare list (the capture stores /api/rules verbatim), which the
    sketch already tolerated; the unwrapping is kept.

  * ``window.__openRuleDrawer(type)`` is asserted to exist before it is used, so
    a renamed contract fails with that sentence instead of a JS TypeError.

  * The probed rule for each type is a real one this run creates through the
    real POST /api/rules/<type> handler and deletes afterward (the same
    task-owned setup/cleanup shape as test_v2_alerting_e2e.py's traffic-rule
    CRUD test) — not a destructive endpoint, and not the frozen mockup's
    canned fixture data. alerting.mjs's window.__openRuleDrawer falls back to
    the first rule of that type in state.rules (alerting.mjs:1167-1174) when
    called with no rule, which is exactly what this creates.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

pytest_plugins = ["tests.v2_e2e_utils"]

ROOT = pathlib.Path(__file__).resolve().parents[2] / "design" / "v2"
SNAP = ROOT / "snapshots" / "rules.json"

R_RULES = "#/alerting/rules"

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
    """type -> the union of the keys every captured snapshot rule of that type carries."""
    out = {}
    for rule in _rules():
        out.setdefault(rule["type"], set()).update(rule.keys())
    return out


def test_snapshot_has_all_four_rule_types():
    """Without all four types the coverage assertion below proves nothing."""
    have = set(_keys_by_type())
    assert have >= {"event", "system", "traffic", "bandwidth"}, (
        "the staging appliance needs at least one rule of each type before the "
        f"snapshot is recaptured; this one has {sorted(have)}"
    )


def _goto_rules(page, base_url):
    page.set_default_timeout(15_000)
    page.goto(base_url + "/" + R_RULES)
    page.wait_for_selector('body[data-booted="true"]')
    page.wait_for_selector("[data-cov='AL-01'] table")


# Drives the app's own core/api.mjs (dynamic import — same module the
# production UI uses) rather than a bare page.request.post, because
# POST/DELETE /api/rules/* is CSRF-protected (WTF_CSRF_CHECK_DEFAULT=True,
# src/gui/__init__.py:239-247) and api.mjs is what attaches/refreshes the
# X-CSRF-Token header. The page must already be on the app's origin.
def _api_post(page, path, body):
    return page.evaluate(
        "async (args) => { const { api } = await import('/static/js/v2/core/api.mjs'); "
        "return api.post(args[0], args[1]); }",
        [path, body],
    )


def _api_get(page, path):
    return page.evaluate(
        "async (path) => { const { api } = await import('/static/js/v2/core/api.mjs'); "
        "return api.get(path); }",
        path,
    )


def _api_del(page, path):
    return page.evaluate(
        "async (path) => { const { api } = await import('/static/js/v2/core/api.mjs'); "
        "return api.del(path); }",
        path,
    )


def _seed_live_rule(page, rtype, name):
    """POST one real rule of `rtype` through the live backend and return the
    exact object /api/rules reports for it — the "rules 真回應鍵" source."""
    path = "/api/rules/" + DRAWER_OF.get(rtype, rtype)
    body = {"name": name}
    if DRAWER_OF.get(rtype, rtype) in ("traffic", "bandwidth"):
        body["filters"] = {}
    result = _api_post(page, path, body)
    assert result and result.get("ok") is True, (path, result)
    rules = _api_get(page, "/api/rules") or []
    matches = [r for r in rules if r.get("name") == name]
    assert matches, f"created rule {name!r} not found in /api/rules response"
    return matches[0]


def _delete_by_name(page, name):
    rules = _api_get(page, "/api/rules") or []
    for r in rules:
        if r.get("name") == name:
            _api_del(page, "/api/rules/" + str(r["index"]))


def test_openrule_drawer_contract_exists(v2_page):
    page, base_url = v2_page
    _goto_rules(page, base_url)
    assert page.evaluate("typeof window.__openRuleDrawer") == "function", (
        "js/areas/alerting.mjs must expose window.__openRuleDrawer(type) — it is "
        "the contract this gate and window.__openAllForAudit() both use"
    )


@pytest.mark.parametrize("rtype", sorted(_keys_by_type()))
def test_drawer_fields_cover_snapshot_keys(v2_page, rtype):
    page, base_url = v2_page
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    _goto_rules(page, base_url)

    name = "e2e-field-cov-" + rtype
    live_rule = _seed_live_rule(page, rtype, name)
    try:
        wanted = (_keys_by_type()[rtype] | set(live_rule.keys())) - INTERNAL

        # Reload so state.rules (loaded once at mount) picks up the rule just
        # created — window.__openRuleDrawer(ty) with no rule argument falls
        # back to the first live rule of that type (alerting.mjs:1167-1174).
        page.reload()
        page.wait_for_selector('body[data-booted="true"]')
        page.wait_for_selector("[data-cov='AL-01'] table")

        page.evaluate("window.__drawerProbe = window.__openRuleDrawer(%s)" % json.dumps(DRAWER_OF.get(rtype, rtype)))
        page.wait_for_timeout(300)
        have = set(page.eval_on_selector_all(
            ".drawer [data-field]", "els => els.map(e => e.dataset.field)"))
        missing = wanted - have
        page.evaluate("window.__drawerProbe && window.__drawerProbe.close()")
        assert not missing, f"{rtype} drawer missing fields: {sorted(missing)}"
        assert errors == [], errors
    finally:
        _delete_by_name(page, name)


@pytest.mark.parametrize("rtype", sorted(_keys_by_type()))
def test_drawer_labels_are_words_not_keys(v2_page, rtype):
    """The other half of "present AND NAMED", which nothing was checking.

    The gate above asks whether a backend key is present in the drawer. It
    says nothing about what the row is CALLED — and `roField` used to take one
    argument for both, so the visible label WAS the storage key. Renaming the
    labels to catalogue keys therefore printed `gui_al_ro_type` on screen and
    broke the data-field contract at the same time, and every existing lint
    stayed green: tests/test_gui_copy_lint.py matches a string literal in the
    source (blind to `filterFieldRows`, which passes a variable), and the
    settings-page DOM check only visits `#/system/*`.

    So this reads the rendered labels: none may be a snake_case identifier
    (`src_label`, `throttle_state`) or one of our own catalogue keys
    (`gui_...`). Those are the two ways this row has actually gone wrong.
    """
    page, base_url = v2_page
    _goto_rules(page, base_url)
    name = "e2e-label-cov-" + rtype
    _seed_live_rule(page, rtype, name)
    try:
        page.reload()
        page.wait_for_selector('body[data-booted="true"]')
        page.wait_for_selector("[data-cov='AL-01'] table")
        page.evaluate("window.__drawerProbe = window.__openRuleDrawer(%s)"
                      % json.dumps(DRAWER_OF.get(rtype, rtype)))
        page.wait_for_timeout(300)
        labels = page.eval_on_selector_all(
            ".drawer .rofields .c", "els => els.map(e => e.textContent.trim())")
        page.evaluate("window.__drawerProbe && window.__drawerProbe.close()")
        assert labels, f"{rtype} drawer rendered no read-only rows"
        offenders = [
            text for text in labels
            if text.startswith("gui_")
            or re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", text)
        ]
        assert offenders == [], f"{rtype} drawer labels are keys: {offenders}"
    finally:
        _delete_by_name(page, name)
