"""Phase 2A Task 6 — in-process Playwright e2e for the v2 alerting area.

The suite drives the real Flask handlers and the real v2 UI.  It covers every
AL-01..AL-14 anchor, traffic-rule CRUD, the real rule highlight and rule-test
requests, the debug round-trip, backend error rendering, confirmation-only
paths for destructive operations, and teardown of both alerting sub-routes.

Destructive-operation discipline: AL-11 (reset watermark) and AL-12 (load
best practices) really mutate alert state and monitoring rules, so their
Confirm is never allowed to reach the backend. Both are covered twice: once
Cancel-only against the real app
(test_backend_error_and_confirmation_paths_do_not_fire_destructive_calls),
and once through Confirm against a success response fulfilled at the network
boundary (the two *_confirm_ok_* tests), which proves the request the UI
builds and how it renders success — and nothing about what the handler would
have done. Each of those tests says so in its own docstring.

The sandbox used by the implementation worker cannot launch Chromium or open
the live test server.  The file is still collected here so the Claude worker
can run it in the browser-capable environment and provide RED/GREEN evidence.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

pytest_plugins = ["tests.v2_e2e_utils"]

R_RULES = "#/alerting/rules"
R_OPS = "#/alerting/ops"
R_SYSTEM_PCE = "#/system/pce"
SLOW = 45_000


def _goto(page, base_url, route):
    page.set_default_timeout(SLOW)
    page.goto(base_url + "/" + route)
    page.wait_for_selector('body[data-booted="true"]')
    page.wait_for_selector("code:text-is('%s')" % route)
    page.wait_for_selector('[data-cov="%s"]' % ("AL-01" if route == R_RULES else "AL-08"))


def _navigate(page, route):
    page.evaluate("location.hash = '%s'" % route)
    page.wait_for_selector("code:text-is('%s')" % route)


def _labels(page):
    keys = [
        "gui_add_traffic", "gui_edit_rule", "gui_confirm", "gui_run_debug",
        "gui_reset_watermark_label", "gui_best_practices", "gui_load", "gui_cancel",
        "gui_run_btn", "gui_rule_name", "gui_save", "gui_json",
        "gui_err_invalid_number",
    ]
    return page.evaluate(
        "async (keys) => { const { t } = await import('/static/js/v2/core/i18n.mjs'); "
        "const out = {}; keys.forEach(k => { out[k] = t(k); }); return out; }",
        keys,
    )


def _covs(page):
    return set(page.eval_on_selector_all("[data-cov]", "els => els.map(e => e.dataset.cov)"))


def _missing_i18n(page):
    return page.evaluate(
        "async () => { const { i18n } = await import('/static/js/v2/core/i18n.mjs'); "
        "return i18n.missing(); }"
    )


def _palette_routes(page):
    return page.evaluate(
        "async () => { const { palette } = await import('/static/js/v2/components/palette.mjs'); "
        "return palette.list().map(c => c.route || null); }"
    )


def _open_all(page):
    page.evaluate("window.__openAllForAudit()")
    page.wait_for_timeout(250)


# The three helpers below drive the app's own core/api.mjs (dynamic import,
# same module the production UI uses) rather than a bare page.request.post,
# because POST/DELETE /api/rules/* is CSRF-protected
# (WTF_CSRF_CHECK_DEFAULT=True, src/gui/__init__.py:239-247) and api.mjs is
# what actually attaches/refreshes the X-CSRF-Token header (api.mjs:10-16).
# A page must already be on the app's origin for the dynamic import to
# resolve, so these are only called after a real _goto().
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


def test_rules_coverage_anchors_and_i18n(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_RULES)
    _open_all(page)

    expected = {"AL-%02d" % i for i in range(1, 8)}
    assert expected - _covs(page) == set()
    assert _missing_i18n(page) == []


def test_ops_coverage_anchors_and_i18n(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_OPS)
    _open_all(page)

    expected = {"AL-%02d" % i for i in range(8, 15)}
    assert expected - _covs(page) == set()
    assert _missing_i18n(page) == []


def test_traffic_rule_crud_sends_empty_filters_and_cleans_up(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_RULES)
    labels = _labels(page)
    name = "e2e-alerting-traffic"
    renamed = name + "-renamed"

    panel = page.locator('section[data-cov="AL-01"]')
    panel.get_by_role("button", name=labels["gui_add_traffic"], exact=True).click()
    drawer = page.locator("aside.drawer")
    drawer.wait_for(state="visible")
    drawer.locator('input[data-field="name"]').fill(name)

    with page.expect_request(
        lambda r: "/api/rules/traffic" in r.url and r.method == "POST"
    ) as info:
        drawer.locator(".drawer-f button.btn.primary").click()
    body = info.value.post_data_json
    assert body["filters"] == {}, body
    page.wait_for_selector("aside.drawer", state="detached")
    assert panel.locator("tbody tr").filter(has_text=name).count() == 1

    row = panel.locator("tbody tr").filter(has_text=name)
    row.get_by_role("button", name=labels["gui_edit_rule"], exact=True).click()
    edit = page.locator("aside.drawer")
    edit.locator('input[data-field="name"]').fill(renamed)
    with page.expect_request(
        lambda r: "/api/rules/" in r.url and r.method == "PUT"
    ) as update:
        edit.locator(".drawer-f button.btn.primary").click()
    update_body = update.value.post_data_json
    assert "index" not in update_body
    assert "id" not in update_body
    assert "cooldown_remaining" not in update_body
    assert "throttle_state" not in update_body
    page.wait_for_selector("aside.drawer", state="detached")

    row = panel.locator("tbody tr").filter(has_text=renamed)
    switch = row.locator("button.switch")
    with page.expect_request(
        lambda r: "/api/rules/" in r.url and r.method == "PUT"
    ) as toggle:
        switch.click()
    assert toggle.value.post_data_json == {"enabled": False}

    # AL-06: the real highlight endpoint is requested and the selected row is
    # marked in the list, rather than only changing a client-side snapshot.
    with page.expect_response(
        lambda r: "/api/rules/" in r.url and r.url.endswith("/highlight") and r.request.method == "GET"
    ) as highlight:
        row.get_by_role("button", name=labels["gui_json"], exact=True).click()
    assert highlight.value.json()["html"]
    page.wait_for_selector('section[data-cov="AL-06"] pre')
    page.wait_for_selector('tbody tr.hl')
    assert page.locator('section[data-cov="AL-06"] pre').inner_text()

    # Delete the one e2e rule through the real confirmation flow.
    # floatHost is a sibling of the AL-01 panel under .wb-main (mirrors the
    # frozen mockup's DOM), so the floatbar is not scoped inside `panel`.
    row.locator('input[type="checkbox"]').check()
    page.locator(".floatbar button.btn.danger").click()
    confirm = page.locator(".modal")
    confirm.wait_for(state="visible")
    with page.expect_request(
        lambda r: "/api/rules/" in r.url and r.method == "DELETE"
    ):
        confirm.get_by_role("button", name=labels["gui_confirm"], exact=True).click()
    page.wait_for_selector(".modal", state="detached")
    assert panel.locator("tbody tr").filter(has_text=renamed).count() == 0


def test_rule_test_uses_real_endpoint(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_RULES)
    labels = _labels(page)

    # AL-07's select is populated from event-type rules in state.rules
    # (alerting.mjs's eventRules filter), and the shared fixture seeds
    # "rules": [] — so without a rule of its own this test always took the
    # skip branch and the round trip never ran for real. Task-owned setup
    # through the real POST /api/rules/event handler (same shape as the
    # traffic-rule CRUD test's own fixture rule above), cleaned up after.
    name = "e2e-alerting-event-ruletest"
    created = _api_post(page, "/api/rules/event", {"name": name})
    assert created and created.get("ok") is True, created
    try:
        page.reload()
        page.wait_for_selector('body[data-booted="true"]')
        page.wait_for_selector("code:text-is('%s')" % R_RULES)
        page.wait_for_selector('[data-cov="AL-01"]')

        panel = page.locator('section[data-cov="AL-07"]')
        button = panel.get_by_role("button", name=labels["gui_run_btn"], exact=True)
        assert panel.locator("select option").count() > 0, (
            "the event rule created above should populate AL-07's select"
        )

        with page.expect_request(
            lambda r: "/api/events/rule_test?idx=" in r.url and r.method == "GET"
        ):
            button.click()
        page.wait_for_selector('[data-cov="AL-07"] [data-role="rule-test-result"]')
    finally:
        rules = _api_get(page, "/api/rules")
        for r in rules or []:
            if r.get("name") == name:
                _api_del(page, "/api/rules/" + str(r["index"]))


def test_debug_round_trip_renders_real_response(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_OPS)
    labels = _labels(page)
    panel = page.locator('section[data-cov="AL-09"]')

    with page.expect_request(
        lambda r: "/api/actions/debug" in r.url and r.method == "POST"
    ) as info:
        panel.get_by_role("button", name=labels["gui_run_debug"], exact=True).click()
    assert info.value.post_data_json["mins"] == "30"
    assert info.value.post_data_json["pd_sel"] == "3"
    page.wait_for_function(
        "() => document.querySelector('[data-cov=AL-13] pre.console').dataset.empty === 'false'",
        timeout=SLOW,
    )
    assert page.locator('[data-cov="AL-13"] pre.console').inner_text()


def test_backend_error_and_confirmation_paths_do_not_fire_destructive_calls(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_RULES)
    labels = _labels(page)

    # Invalid threshold is a real POST and must surface the handler's error.
    panel = page.locator('section[data-cov="AL-01"]')
    panel.get_by_role("button", name=labels["gui_add_traffic"], exact=True).click()
    drawer = page.locator("aside.drawer")
    drawer.locator('input[data-field="threshold_count"]').fill("0")
    with page.expect_request(
        lambda r: "/api/rules/traffic" in r.url and r.method == "POST"
    ):
        drawer.locator(".drawer-f button.btn.primary").click()
    page.wait_for_selector('.toast[data-tone="crit"]')
    drawer.get_by_role("button", name=labels["gui_cancel"], exact=True).click()

    _navigate(page, R_OPS)
    # AL-12's trigger button reads "Load" (gui_load); the panel title reads
    # "Load Best Practices" (gui_best_practices) — same split as the mockup.
    for cov, key in (("AL-11", "gui_reset_watermark_label"), ("AL-12", "gui_load")):
        panel = page.locator('section[data-cov="%s"]' % cov)
        panel.get_by_role("button", name=labels[key], exact=True).click()
        modal = page.locator(".modal")
        modal.wait_for(state="visible")
        assert modal.locator("ul.impact li").count() >= 1
        # The e2e never clicks Confirm for these destructive endpoints.
        modal.get_by_role("button", name=labels["gui_cancel"], exact=True).click()
        page.wait_for_selector(".modal", state="detached")


def _stub_ok(page, pattern, body):
    """Fulfil `pattern` with a success response at the network boundary."""
    posted: list[dict] = []

    def handler(route):
        posted.append(route.request.post_data_json)
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route(pattern, handler)
    return posted, handler


def test_reset_watermark_confirm_ok_sends_the_call_and_prints_the_stubbed_result(v2_page):
    """AL-11's OK path, which every existing test cancels out of.

    WHAT THIS PROVES: clicking Confirm really issues POST
    /api/actions/reset-watermark (an empty JSON body — the route takes none),
    and AL-13's console reacts to a 200 by printing the request line and the
    backend's own `output` string.

    WHAT THIS DOES NOT PROVE: anything about resetting a watermark. The POST
    is fulfilled at the network boundary, so actions.py never runs and no
    alert state, cooldown or event watermark is touched anywhere — this file's
    destructive-operation discipline is unchanged. Only the frontend's
    request-building and its rendering of a success are under test."""
    page, base_url = v2_page
    _goto(page, base_url, R_OPS)
    labels = _labels(page)
    posted, handler = _stub_ok(page, "**/api/actions/reset-watermark",
                               {"ok": True, "output": "e2e-watermark-reset-output"})
    try:
        panel = page.locator('section[data-cov="AL-11"]')
        panel.get_by_role("button", name=labels["gui_reset_watermark_label"], exact=True).click()
        modal = page.locator(".modal")
        modal.wait_for(state="visible")
        modal.get_by_role("button", name=labels["gui_confirm"], exact=True).click()

        console = page.locator('[data-cov="AL-13"] pre.console')
        page.wait_for_function(
            "() => document.querySelector('[data-cov=AL-13] pre.console')"
            ".textContent.includes('e2e-watermark-reset-output')",
            timeout=SLOW,
        )
        assert posted == [{}], posted
        assert "/api/actions/reset-watermark" in console.inner_text()
    finally:
        page.unroute("**/api/actions/reset-watermark", handler)


def test_best_practices_confirm_ok_sends_the_selected_mode_and_prints_the_stubbed_result(v2_page):
    """AL-12's OK path, also only ever cancelled until now.

    WHAT THIS PROVES: the mode radio really reaches the request — the
    non-default `replace` is selected here, so a build that hardcoded
    append_missing (or dropped the body entirely) goes red — and AL-13's
    console renders the backend's `output` on success.

    WHAT THIS DOES NOT PROVE: anything about the rules that would be written.
    The POST is fulfilled at the network boundary; config.py's
    apply_best_practices never runs and no monitoring rule is created,
    replaced or backed up."""
    page, base_url = v2_page
    _goto(page, base_url, R_OPS)
    labels = _labels(page)
    posted, handler = _stub_ok(page, "**/api/actions/best-practices",
                               {"ok": True, "output": "e2e-best-practices-output"})
    try:
        panel = page.locator('section[data-cov="AL-12"]')
        panel.locator('input[type="radio"][name="al-bp-mode"][value="replace"]').check()
        panel.get_by_role("button", name=labels["gui_load"], exact=True).click()
        modal = page.locator(".modal")
        modal.wait_for(state="visible")
        assert modal.locator("ul.impact li").count() >= 1
        modal.get_by_role("button", name=labels["gui_confirm"], exact=True).click()

        page.wait_for_function(
            "() => document.querySelector('[data-cov=AL-13] pre.console')"
            ".textContent.includes('e2e-best-practices-output')",
            timeout=SLOW,
        )
        assert posted == [{"mode": "replace"}], posted
    finally:
        page.unroute("**/api/actions/best-practices", handler)


def test_teardown_closes_surfaces_clears_callbacks_and_palette(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_RULES)
    labels = _labels(page)

    # Open a real stateful FilterBar drawer and an audit-openable surface.
    page.locator('section[data-cov="AL-01"]').get_by_role(
        "button", name=labels["gui_add_traffic"], exact=True
    ).click()
    page.locator("aside.drawer").wait_for(state="visible")
    assert page.locator("[data-role=filter-bar]").count() == 1
    assert "#/alerting/rules" in _palette_routes(page)

    _navigate(page, R_OPS)
    assert page.locator("aside.drawer").count() == 0
    assert "#/alerting/rules" not in _palette_routes(page)
    assert page.evaluate(
        "async () => { const m = await import('/static/js/v2/components/filter-bar.mjs'); "
        "return m._objfbHasBrowser(); }"
    ) is False
    assert page.evaluate("window.__openRuleDrawer === undefined")

    # Exercise the second mount's teardown independently.
    _open_all(page)
    assert page.locator(".modal").count() >= 1
    _navigate(page, R_SYSTEM_PCE)
    assert page.locator(".modal").count() == 0
    assert all(route != R_OPS for route in _palette_routes(page))


def test_rule_debug_error_console_keeps_backend_text(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_OPS)
    labels = _labels(page)
    panel = page.locator('section[data-cov="AL-09"]')
    mins = panel.locator('input[type="number"]').first
    mins.evaluate("(e) => { e.type = 'text'; e.value = 'not-a-number'; }")
    panel.get_by_role("button", name=labels["gui_run_debug"], exact=True).click()
    page.wait_for_selector('.toast[data-tone="crit"]')
    console = page.locator('[data-cov="AL-13"] pre.console')
    assert console.get_attribute("data-empty") == "false"
    assert labels["gui_err_invalid_number"] in console.inner_text()
