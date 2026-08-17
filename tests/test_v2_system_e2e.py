"""Phase 2A Task 9 — in-process Playwright e2e for the v2 system area.

Drives a real (headless) Chromium against a real Flask app + real backend
through tests.v2_e2e_utils's shared harness — see that module's docstring for
the harness itself.

Covers, per the task brief's T9 row:
  - every SY-01..SY-18 coverage anchor (design/v2/coverage.yaml's system
    subset), split across the eight sub-routes that own them. All 18 anchors
    are rendered STATICALLY on their page (no drawer/modal has to be opened
    to see them) — verified while writing src/static/js/v2/areas/system.mjs —
    so each coverage test also calls window.__openAllForAudit() and asserts
    it reports no errors, exercising every audit opener for real.
  - key flow 1 (dirty tracking / the Phase 1 defect fix): toggling the
    language radio on #/system/display marks the docked form dirty AND the
    live payload preview carries the NEW language, not the stale settings
    snapshot (test_display_language_change_enters_form_track).
  - key flow 2 (the required save-flow e2e): change ONE display setting
    (settings.timezone) -> Save -> reload -> re-GET /api/settings and verify
    it persisted -> change it back, confined to a `finally` so a failed
    assertion cannot leave the app's settings changed
    (test_display_save_flow_timezone_persists_and_reverts).
  - PCE profile CRUD: create a throwaway profile through the real drawer,
    verify it appears in the real list, delete it through the real confirm
    flow (test_pce_profile_crud_add_then_delete). `activate` is never
    clicked — see "Destructive-operation discipline" below.
  - SIEM destination CRUD: same shape, for a throwaway UDP destination
    (test_siem_destination_crud_add_then_delete).
  - TLS CSR generation: real and non-destructive (never touches the serving
    cert) — exercised for real (test_tls_csr_generation_is_real).
  - every destructive control this area holds renders its confirm and Cancel
    dismisses it with NO request ever sent
    (test_destructive_confirms_render_cancel_sends_nothing).
  - S2 teardown across two sub-routes (test_teardown_closes_surfaces_and_palette).
  - DLQ replay/purge are wired to the real endpoints, proven with a
    destination filter that matches nothing so the call is a real, harmless
    no-op (test_dlq_replay_and_purge_are_wired_for_real).

Task 12d added two more, for defects that survived because no test read a
write's answer:
  - SY-03 really POSTs /api/daemon/restart and tells 200/409/429/other apart
    (test_restart_monitor_posts_and_branches_on_the_status).
  - SY-10 replay/purge report what the server said, including the per-item
    failures replay's `ids` branch hides inside an HTTP 200
    (test_dlq_replay_and_purge_read_their_response).

## Destructive-operation discipline

This area can stop the GUI, regenerate TLS material and purge queued data.
Nothing here is triggered destructively:

  POST /api/pce-profiles {action:"activate", ...}  — NEVER called. Re-points
      the whole appliance's PCE target; the confirm renders, Cancel is
      clicked, Confirm never is.
  POST /api/cache/retention/run   — NEVER called for real. Purges cache rows;
      confirm renders + Cancel only.
  POST /api/daemon/restart        — the "restart monitor" confirm. Reached in
      exactly two safe ways: Cancel-only in the destructive sweep, and in
      test_restart_monitor_posts_and_branches_on_the_status, where the one
      unmocked Confirm hits this harness's own app — which never installed a
      restart hook, so the route answers 409 and restarts nothing. The 200 /
      429 / 500 branches are fulfilled responses, never a real restart.
      (An earlier version of this file claimed no such route existed at all;
      it does — src/gui/__init__.py:607.)
  POST /api/tls/renew             — NEVER called. Overwrites the serving
      self-signed cert in place with no backup; confirm renders + Cancel only.
  POST /api/tls/import-cert       — NEVER called. Overwrites the serving
      cert's config; confirm renders + Cancel only.
  POST /api/siem/dlq/purge        — NEVER reaches the backend through the
      UI's confirm. Cancel only in the destructive sweep; in
      test_dlq_replay_and_purge_read_their_response the Confirm IS clicked,
      but against a page.route-fulfilled response, so no request leaves the
      browser. Also exercised for real directly through api.post with a
      `dest` that matches no destination, so that call is a genuine, harmless
      no-op (asserts {removed: 0}) — proves the wiring without deleting
      anything.
  POST /api/shutdown              — NEVER called through the UI (Cancel
      only). This harness's app runs with persistent_mode=True regardless
      (tests/v2_e2e_utils.py), so even a real call would 403 rather than
      exit — the test still never risks it, per the task brief's explicit
      instruction not to trigger this control.
  POST /api/actions/test-alert    — NEVER called (per-channel test-send
      button on #/system/channels). A real external side effect (dispatches
      through the configured plugin), same caution as alerting.mjs's own
      run-once/test-alert; not one of this area's 18 coverage anchors'
      required interactions, so it is left unclicked entirely.
  POST /api/siem/destinations/<name>/test — NEVER called (dials the
      destination's real host:port).

Genuinely exercised for real, because they are either safe (no lasting/
external effect) or explicitly required by the task brief:
  POST /api/pce-profiles {action:"add"|"delete"}      — a throwaway, never-
      activated profile.
  POST/PUT/DELETE /api/siem/destinations[/<name>]     — a throwaway
      destination.
  POST /api/tls/generate-csr                          — writes a CSR+key
      file, never touches the serving cert.
  POST /api/settings (settings.timezone / settings.language)
  POST /api/siem/dlq/replay, POST /api/siem/dlq/purge  — called directly with
      a `dest` matching nothing.
"""
from __future__ import annotations

import json
import re

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

from playwright.sync_api import expect  # noqa: E402

# Registers v2_page and its fixture chain — see tests/v2_e2e_utils.py's
# docstring for why both this line and the importorskip above (in that exact
# order) are required.
pytest_plugins = ["tests.v2_e2e_utils"]

R_PCE = "#/system/pce"
R_CACHE = "#/system/cache"
R_SIEM = "#/system/siem"
R_TLS = "#/system/tls"
R_SECURITY = "#/system/security"
R_DISPLAY = "#/system/display"
R_CHANNELS = "#/system/channels"
R_LOGS = "#/system/logs"
SLOW = 45_000


def _goto(page, base_url, route, cov):
    page.set_default_timeout(SLOW)
    page.goto(base_url + "/" + route)
    page.wait_for_selector('body[data-booted="true"]')
    page.wait_for_selector('[data-route="%s"]' % route)
    page.wait_for_selector('[data-cov="%s"]' % cov)


def _navigate(page, route, cov):
    page.evaluate("location.hash = '%s'" % route)
    page.wait_for_selector('[data-route="%s"]' % route)
    page.wait_for_selector('[data-cov="%s"]' % cov)


def _covs(page):
    return set(page.eval_on_selector_all("[data-cov]", "els => els.map(e => e.dataset.cov)"))


def _missing_i18n(page):
    return page.evaluate(
        "async () => { const { i18n } = await import('/static/js/v2/core/i18n.mjs'); "
        "return i18n.missing(); }"
    )


def _labels(page):
    keys = [
        "gui_save", "gui_cancel", "gui_confirm", "gui_close", "gui_pce_add",
        "gui_pce_activate", "gui_pce_delete_profile", "gui_msg_confirm_delete",
        "gui_retention_now", "gui_it_restart_monitor", "gui_tls_renew",
        "gui_tls_import_btn", "gui_dlq_purge_selected", "gui_sy_stop_btn",
        "gui_siem_add", "gui_siem_delete", "gui_confirm_delete",
        "gui_tls_csr_generate", "gui_sy_discard", "gui_errcard_retry",
        "gui_dlq_replay", "gui_restart_success", "gui_daemon_external_restart_hint",
    ]
    return page.evaluate(
        "async (keys) => { const { t } = await import('/static/js/v2/core/i18n.mjs'); "
        "const out = {}; keys.forEach(k => { out[k] = t(k); }); return out; }",
        keys,
    )


def _palette_routes(page):
    return page.evaluate(
        "async () => { const { palette } = await import('/static/js/v2/components/palette.mjs'); "
        "return palette.list().map(c => c.route || null); }"
    )


def _open_all(page):
    result = page.evaluate("window.__openAllForAudit()")
    page.wait_for_timeout(250)
    return result


# Same rationale as test_v2_automation_e2e.py: POST/PUT/DELETE here is
# CSRF-protected, and api.mjs is what actually attaches/refreshes the
# X-CSRF-Token header. A page must already be on the app's origin for the
# dynamic import to resolve, so these only run after a real _goto()/_navigate().
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


# ══════════════════════════════════════════ coverage anchors + i18n ══════════

def test_pce_coverage_and_i18n(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_PCE, "SY-01")
    result = _open_all(page)
    assert result["errors"] == [], result
    assert {"SY-01", "SY-18"} - _covs(page) == set()
    assert _missing_i18n(page) == []


def test_cache_coverage_and_i18n(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_CACHE, "SY-02")
    result = _open_all(page)
    assert result["errors"] == [], result
    expected = {"SY-02", "SY-03", "SY-04", "SY-05", "SY-06", "SY-17"}
    assert expected - _covs(page) == set()
    assert _missing_i18n(page) == []
    # The two confirms audit-opened above must be dismissible with Cancel —
    # "never sends a request" is asserted separately, in the consolidated
    # test_destructive_confirms_render_cancel_sends_nothing.
    assert page.locator(".modal").count() >= 1
    # Escape, not a Cancel click: the audit sweep stacks two independent
    # confirms (retention + restart), and dom.mjs's dismissible() is
    # explicitly stack-aware — only the topmost dialog reacts to Escape,
    # closing one layer at a time. A Cancel-button click would need to guess
    # which of two visually-overlapping modals is actually on top.
    while page.locator(".modal").count():
        page.keyboard.press("Escape")
        page.wait_for_timeout(50)
    page.wait_for_selector(".modal", state="detached")


def test_siem_coverage_and_i18n(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_SIEM, "SY-07")
    result = _open_all(page)
    assert result["errors"] == [], result
    expected = {"SY-07", "SY-08", "SY-09", "SY-10"}
    assert expected - _covs(page) == set()
    assert _missing_i18n(page) == []
    # Escape, not a Cancel click — same reason as test_cache_coverage_and_i18n:
    # the audit sweep here stacks two drawers (sy-siem-dest, sy-siem-dlq) plus
    # the purge modal, and only dismissible()'s topmost entry reacts to Escape.
    while page.locator(".modal").count() or page.locator("aside.drawer").count():
        page.keyboard.press("Escape")
        page.wait_for_timeout(50)
    # DLQ is genuinely empty on a fresh temp_config_file — SY-10's table
    # shows the real "no data" empty state, not a fabricated row.
    dlq_panel = page.locator('section[data-cov="SY-10"]')
    assert dlq_panel.locator(".empty").count() == 1


def test_tls_coverage_and_i18n(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_TLS, "SY-11")
    result = _open_all(page)
    assert result["errors"] == [], result
    assert "SY-11" in _covs(page)
    assert _missing_i18n(page) == []
    labels = _labels(page)
    if page.locator(".modal").count():
        page.locator(".modal").first.get_by_role("button", name=labels["gui_cancel"], exact=True).click()
        page.wait_for_selector(".modal", state="detached")


def test_security_coverage_and_i18n(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_SECURITY, "SY-12")
    result = _open_all(page)
    assert result["errors"] == [], result
    assert {"SY-12", "SY-16"} - _covs(page) == set()
    assert _missing_i18n(page) == []
    labels = _labels(page)
    if page.locator(".modal").count():
        page.locator(".modal").first.get_by_role("button", name=labels["gui_cancel"], exact=True).click()
        page.wait_for_selector(".modal", state="detached")


def test_display_coverage_and_i18n(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_DISPLAY, "SY-13")
    assert {"SY-13", "XC-05", "XC-06"} - _covs(page) == set()
    assert _missing_i18n(page) == []


def test_channels_coverage_and_i18n(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_CHANNELS, "SY-14")
    assert "SY-14" in _covs(page)
    assert _missing_i18n(page) == []


def test_logs_coverage_and_i18n(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_LOGS, "SY-15")
    # SY-15's table paints asynchronously (a real, parameterised
    # module_log_sample fetch — header point 11) — wait for it before
    # opening the drawer, or the audit opener's handles.first is not set yet.
    # .sy-logs-body is empty until paint()'s fetch resolves (table.tbl on
    # success, a .note on a real fetch error) — unlike the panel's own
    # static notes below it, which render immediately.
    page.wait_for_selector(".sy-logs-body table.tbl, .sy-logs-body .note")
    result = _open_all(page)
    assert result["errors"] == [], result
    assert "SY-15" in _covs(page)
    assert _missing_i18n(page) == []


# ══════════════════════════════════════════ key flow: Phase 1 defect fix ═════

def test_display_language_change_enters_form_track(v2_page):
    """The Phase 1 defect (task brief): before this fix, toggling the
    language radio mutated a client-side i18n.lang directly and the docked
    form's payload preview always re-sent the STALE settings snapshot's
    language — the ledger could claim a change Save would then silently fail
    to persist. Asserts both halves of the real fix: the radio flip enters
    the dirty ledger (fapi.track), and the live payload preview reflects the
    NEW value. A regression that reverts either half (dropping
    fapi.track("settings.language", ...) or reverting setBody's
    v["settings.language"] read back to the stale snapshot) turns this red."""
    page, base_url = v2_page
    _goto(page, base_url, R_DISPLAY, "XC-06")

    locale = page.locator('section[data-cov="XC-06"]')
    current = locale.locator('input[type="radio"][name="sy-lang"]:checked').get_attribute("value")
    other = "zh_TW" if current == "en" else "en"

    bar = page.locator(".savebar")
    assert bar.get_attribute("data-tone") == "neutral"
    locale.locator('input[type="radio"][name="sy-lang"][value="%s"]' % other).check()
    assert bar.get_attribute("data-tone") == "warn"
    assert bar.locator(".chg code", has_text="settings.language").count() == 1

    payload = page.locator(".codepane.tall").last.inner_text()
    assert ('"language": "%s"' % other) in payload, payload

    # Restore without saving — discard reverts the whole ledger, including
    # the radio's own checked state (writeCtl's __setValue branch).
    page.get_by_role("button", name=_labels(page)["gui_sy_discard"], exact=True).click()
    assert bar.get_attribute("data-tone") == "neutral"
    assert locale.locator('input[type="radio"][name="sy-lang"]:checked').get_attribute("value") == current


# ══════════════════════════════════════════ key flow: required save-flow e2e ═

def test_display_save_flow_timezone_persists_and_reverts(v2_page):
    """The task brief's required save-flow e2e: change ONE display setting
    -> Save -> reload -> re-GET /api/settings and verify it persisted ->
    change it back. Confined to settings.timezone (inert; no side effect on
    the running page, unlike settings.language). Restoration happens in a
    `finally` so a failed assertion above it cannot leave the app's settings
    changed — even the ORIGINAL value is re-read from the server rather than
    assumed, so this is correct regardless of what temp_config_file seeds."""
    page, base_url = v2_page
    _goto(page, base_url, R_DISPLAY, "XC-06")

    original = _api_get(page, "/api/settings")["settings"].get("timezone", "local")
    new_value = "UTC+8" if original != "UTC+8" else "UTC+7"
    try:
        tz_select = page.locator('select[data-field="settings.timezone"]')
        tz_select.select_option(new_value)
        bar = page.locator(".savebar")
        assert bar.get_attribute("data-tone") == "warn"

        with page.expect_request(
            lambda r: r.url.endswith("/api/settings") and r.method == "POST"
        ) as info:
            page.get_by_role("button", name=_labels(page)["gui_save"], exact=True).click()
        assert info.value.post_data_json["settings"]["timezone"] == new_value
        page.wait_for_selector('.toast[data-tone="ok"]')

        page.reload()
        page.wait_for_selector('body[data-booted="true"]')
        page.wait_for_selector('[data-route="%s"]' % R_DISPLAY)
        page.wait_for_selector('[data-cov="XC-06"]')
        reread = _api_get(page, "/api/settings")
        assert reread["settings"]["timezone"] == new_value, reread["settings"]
        assert page.locator('select[data-field="settings.timezone"]').input_value() == new_value
    finally:
        # Best-effort UI-driven restore first (proves the real Save path can
        # revert its own change), but never trusted alone: whatever happens
        # above, a direct POST through the real endpoint is the guaranteed
        # restore, and the final GET is what actually proves it worked. A
        # failure in the UI portion (page navigated away, button not found,
        # …) must not skip the guaranteed restore below.
        try:
            tz_select = page.locator('select[data-field="settings.timezone"]')
            if tz_select.count() and tz_select.input_value() != original:
                tz_select.select_option(original)
                with page.expect_request(
                    lambda r: r.url.endswith("/api/settings") and r.method == "POST"
                ):
                    page.get_by_role("button", name=_labels(page)["gui_save"], exact=True).click()
                page.wait_for_selector('.toast[data-tone="ok"]')
        except Exception as ui_exc:  # noqa: BLE001 — reported, restore still proceeds below
            print("[test_display_save_flow] UI-driven restore failed: %r" % ui_exc)
        current = _api_get(page, "/api/settings")["settings"].get("timezone")
        if current != original:
            _api_post(page, "/api/settings", {"settings": {"timezone": original}})
        final = _api_get(page, "/api/settings")["settings"].get("timezone")
        assert final == original, "settings.timezone was not restored: %r" % final


# ══════════════════════════════════════════════════════ real CRUD flows ══════

def test_pce_profile_crud_add_then_delete(v2_page):
    """SY-01: create a throwaway profile through the real drawer, verify it
    reconciles against the real list, delete it through the real confirm
    flow. `activate` is never clicked (header + module docstring)."""
    page, base_url = v2_page
    _goto(page, base_url, R_PCE, "SY-01")
    name = "e2e-sy-pce"
    labels = _labels(page)

    page.get_by_role("button", name=labels["gui_pce_add"], exact=True).first.click()
    drawer = page.locator("aside.drawer")
    drawer.wait_for(state="visible")
    drawer.locator('input[data-field="name"]').fill(name)
    drawer.locator('input[data-field="url"]').fill("https://pce.e2e.example:8443")
    drawer.locator('input[data-field="org_id"]').fill("1")

    with page.expect_request(
        lambda r: r.url.endswith("/api/pce-profiles") and r.method == "POST"
    ) as info:
        drawer.locator(".drawer-f button.btn.primary").click()
    body = info.value.post_data_json
    assert body["action"] == "add"
    assert body["name"] == name
    # expect_request only waits for the request to be SENT, not for the
    # response + refreshAndRemount() that follows (router.go() does not
    # await the new mount) — a bare .count() right after would race the
    # remount. expect(...).to_have_count() auto-retries until it settles.
    row = page.locator('section[data-cov="SY-01"] table.tbl tbody tr').filter(has_text=name)
    expect(row).to_have_count(1)

    row.get_by_role("button", name=labels["gui_pce_delete_profile"], exact=True).click()
    confirm = page.locator(".modal")
    confirm.wait_for(state="visible")
    with page.expect_request(
        lambda r: r.url.endswith("/api/pce-profiles") and r.method == "POST"
    ) as del_info:
        confirm.get_by_role("button", name=labels["gui_confirm"], exact=True).click()
    assert del_info.value.post_data_json["action"] == "delete"
    expect(page.locator('section[data-cov="SY-01"] table.tbl tbody tr').filter(has_text=name)).to_have_count(0)


def test_siem_destination_crud_add_then_delete(v2_page):
    """SY-08: same shape, for a throwaway UDP destination — UDP so there is
    no TLS/HEC section to fill and no real network probe is ever dialled
    (the test button is never clicked).

    PRE-EXISTING BACKEND DEFECT found while writing this test (out of scope
    to fix — binding constraint forbids editing src/siem/web.py): GET
    /api/siem/destinations (list_destinations) reads through
    src/siem/web.py's _get_siem_cfg(), which constructs a BARE
    `ConfigManager()` — the class's default-arg config_file (CONFIG_FILE, the
    real production path) rather than current_app.config['CM'] (the
    request-scoped instance every other handler in the same file correctly
    uses, including add_destination/update_destination/delete_destination/
    get_forwarder/test_destination). In this harness (temp_config_file is a
    throwaway path, never CONFIG_FILE) that fresh instance loads a
    completely different, unrelated file, so a destination added through the
    real POST never appears in the real GET list — confirmed directly
    against the Flask test client outside Playwright before writing this
    comment: POST returns {"ok": true}, the very next GET still returns
    {"destinations": []}. This means the table can never show the row this
    test just created, so persistence is instead proven the way that does
    not depend on the broken read: a DIRECT DELETE by the exact name added
    succeeds (404 "not found" would mean it was never really persisted) —
    delete_destination uses current_app.config['CM'] correctly, so a
    successful delete is real, independent proof the add durably landed in
    the same config instance the rest of the app reads from everywhere else."""
    page, base_url = v2_page
    _goto(page, base_url, R_SIEM, "SY-08")
    name = "e2e-sy-dest"
    labels = _labels(page)

    page.get_by_role("button", name=labels["gui_siem_add"], exact=True).first.click()
    drawer = page.locator("aside.drawer")
    drawer.wait_for(state="visible")
    drawer.locator('input[data-field="name"]').fill(name)
    drawer.locator('input[data-field="host"]').fill("127.0.0.1")

    try:
        with page.expect_request(
            lambda r: r.url.endswith("/api/siem/destinations") and r.method == "POST"
        ) as info:
            drawer.locator(".drawer-f button.btn.primary").click()
        assert info.value.post_data_json["name"] == name
        assert info.value.response().status == 200
        page.wait_for_selector("aside.drawer", state="detached")
    finally:
        deleted = _api_del(page, "/api/siem/destinations/" + name)
        assert deleted and deleted.get("ok") is True, deleted


def test_tls_csr_generation_is_real(v2_page):
    """Header point 10: CSR generation is real and non-destructive — it
    never touches the serving cert config. The empty-CN client-side guard is
    asserted first (no request), then a real POST with a CN produces a real
    PEM in the pane."""
    page, base_url = v2_page
    _goto(page, base_url, R_TLS, "SY-11")
    labels = _labels(page)

    generate = page.get_by_role("button", name=labels["gui_tls_csr_generate"], exact=True)
    generate.click()
    page.wait_for_selector('.toast[data-tone="crit"]')

    page.locator('input[data-field="cn"]').fill("e2e.example.com")
    with page.expect_request(
        lambda r: r.url.endswith("/api/tls/generate-csr") and r.method == "POST"
    ) as info:
        generate.click()
    assert info.value.post_data_json["cn"] == "e2e.example.com"
    assert info.value.response().status == 200
    pem_pane = page.locator('.fld pre.codepane').last
    page.wait_for_function(
        "el => el.textContent.includes('BEGIN CERTIFICATE REQUEST')",
        arg=pem_pane.element_handle(),
    )


# ══════════════════════════════════ destructive controls: confirm, never OK ══

def test_destructive_confirms_render_cancel_sends_nothing(v2_page):
    """Every destructive control this area holds: the confirm renders and
    Cancel dismisses it with no request ever sent to its own endpoint. One
    consolidated test so the discipline is visibly exhaustive in one place."""
    page, base_url = v2_page
    # _labels()'s dynamic import needs the page already on the app's origin —
    # v2_page only logs in, it does not navigate.
    _goto(page, base_url, R_CACHE, "SY-04")
    labels = _labels(page)
    sent = {"hit": False}

    def _watch(pattern):
        sent["hit"] = False
        def _handler(route):
            if pattern in route.request.url:
                sent["hit"] = True
            route.continue_()
        return _handler

    def _confirm_cancel_only(route, cov, open_button_name, watch_url):
        """Every case asserts its own real endpoint was never called.
        (watch_url used to be None for "restart monitor", on the mistaken
        premise that no daemon-restart route existed; POST /api/daemon/restart
        does exist — src/gui/__init__.py:607 — and Task 12d wired the confirm
        to it, so Cancel now has a real endpoint to stay silent about.)"""
        page.evaluate("location.hash = '%s'" % route)
        page.wait_for_selector('[data-cov="%s"]' % cov)
        handler = _watch(watch_url or "/__never__")
        page.route("**/*", handler)
        try:
            # .last, not .first: #/system/cache's restart-monitor label is
            # shared by the (initially hidden) banner's own button and the
            # standalone one below it (mockup-inherited duplication — both
            # call the identical handles.restart) — the standalone one is
            # last in DOM order and is always visible.
            page.get_by_role("button", name=open_button_name, exact=True).last.click()
            modal = page.locator(".modal")
            modal.wait_for(state="visible")
            assert modal.locator("ul.impact li").count() >= 1
            modal.get_by_role("button", name=labels["gui_cancel"], exact=True).click()
            page.wait_for_selector(".modal", state="detached")
            page.wait_for_timeout(200)
            if watch_url:
                assert sent["hit"] is False, "%s must not have been called" % watch_url
        finally:
            page.unroute("**/*", handler)

    _confirm_cancel_only(R_CACHE, "SY-04", labels["gui_retention_now"], "/api/cache/retention/run")
    _confirm_cancel_only(R_CACHE, "SY-03", labels["gui_it_restart_monitor"], "/api/daemon/restart")
    _confirm_cancel_only(R_TLS, "SY-11", labels["gui_tls_renew"], "/api/tls/renew")
    _confirm_cancel_only(R_SECURITY, "SY-16", labels["gui_sy_stop_btn"], "/api/shutdown")

    # SIEM DLQ purge — needs a destination filter selected first, same shape.
    page.evaluate("location.hash = '%s'" % R_SIEM)
    page.wait_for_selector('[data-cov="SY-10"]')
    handler = _watch("/api/siem/dlq/purge")
    page.route("**/*", handler)
    try:
        page.get_by_role("button", name=labels["gui_dlq_purge_selected"], exact=True).click()
        modal = page.locator(".modal")
        modal.wait_for(state="visible")
        modal.get_by_role("button", name=labels["gui_cancel"], exact=True).click()
        page.wait_for_selector(".modal", state="detached")
        page.wait_for_timeout(200)
        assert sent["hit"] is False
    finally:
        page.unroute("**/*", handler)

    # PCE activate — needs a real profile row (activate is hidden for the
    # active one and absent from the empty state), so this creates and
    # cleans up a throwaway profile around the confirm/Cancel check.
    page.evaluate("location.hash = '%s'" % R_PCE)
    page.wait_for_selector('[data-cov="SY-01"]')
    created = _api_post(page, "/api/pce-profiles", {
        "action": "add", "name": "e2e-sy-pce-activate-guard", "url": "https://pce.e2e.example:8443",
        "org_id": "1", "key": "", "secret": "", "verify_ssl": True,
    })
    assert created.get("ok") is True, created
    try:
        page.evaluate("location.hash = '%s'" % R_PCE)
        page.reload()
        page.wait_for_selector('body[data-booted="true"]')
        page.wait_for_selector('[data-cov="SY-01"]')
        handler = _watch("/api/pce-profiles")
        page.route("**/*", handler)
        try:
            page.get_by_role("button", name=labels["gui_pce_activate"], exact=True).first.click()
            modal = page.locator(".modal")
            modal.wait_for(state="visible")
            modal.get_by_role("button", name=labels["gui_cancel"], exact=True).click()
            page.wait_for_selector(".modal", state="detached")
            page.wait_for_timeout(200)
            assert sent["hit"] is False
        finally:
            page.unroute("**/*", handler)
    finally:
        _api_post(page, "/api/pce-profiles", {"action": "delete", "id": created["profile"]["id"]})


# ═════════════════════════════ degraded telemetry keeps the controls ════════

def _fail_with_503(page, pattern, message):
    """Answer `pattern` with the real 503 shape these endpoints already use.

    The failure is injected at the network boundary rather than by breaking
    the cache DB, because the FRONTEND's degradation is what is under test:
    GET /api/cache/{status,lag,throughput,health} really do answer 503 with
    {"ok": false, "error": ...} whenever _get_sf() cannot open the cache
    (src/pce_cache/web.py) — an ordinary operational condition. Everything
    else on the page keeps talking to the real backend."""
    def handler(route):
        route.fulfill(
            status=503,
            content_type="application/json",
            body='{"ok": false, "error": "%s"}' % message,
        )
    page.route(pattern, handler)
    return handler


def test_cache_telemetry_failure_keeps_the_configuration_panels(v2_page):
    """Finding 3: a routine telemetry failure must not take away the controls
    an operator needs to fix it.

    Every #/system/cache snapshot used to load in one strict Promise.all, so a
    503 from GET /api/cache/status — the cache DB being unreachable, i.e. the
    exact condition this page exists to correct — replaced the whole mixed
    configuration/telemetry page with an error card: no settings form, no
    retention control, no restart banner.

    RED against the pre-fix system.mjs: `.errcard` is the only thing on the
    board and every SY-02..SY-06 assertion below fails. The panel-level
    assertions keep it honest in the other direction too — the fix must still
    SHOW the real failure (the server's own error text) and offer a retry,
    not swallow the 503 into a page that looks healthy."""
    page, base_url = v2_page
    message = "e2e-cache-status-unavailable"
    handler = _fail_with_503(page, "**/api/cache/status", message)
    try:
        _goto(page, base_url, R_CACHE, "SY-02")

        # The page is NOT an error card: every configuration anchor is here.
        assert page.locator(".board .errcard").count() == 0
        assert {"SY-02", "SY-03", "SY-04", "SY-05", "SY-06"} - _covs(page) == set()
        assert page.locator('input[data-field="db_path"]').count() == 1
        assert page.get_by_role(
            "button", name=_labels(page)["gui_retention_now"], exact=True
        ).count() >= 1
        # ...and the docked save row is still usable.
        assert page.locator(".savebar").count() == 1

        # The failure is reported where it happened, with the server's own
        # text, and a real retry sits next to it.
        stat = page.locator('section[data-cov="SY-17"]')
        assert stat.count() == 1
        assert message in stat.inner_text(), stat.inner_text()
        assert stat.get_attribute("data-tone") == "crit"
        retry = stat.get_by_role("button", name=_labels(page)["gui_errcard_retry"], exact=True)
        assert retry.count() == 1
    finally:
        page.unroute("**/api/cache/status", handler)

    # The retry really re-fetches: with the interception gone the panel
    # recovers in place, without a remount (the settings form's own state is
    # untouched — a full page remount would discard unsaved edits).
    page.locator('input[data-field="db_path"]').fill("/e2e/unsaved-edit.db")
    stat = page.locator('section[data-cov="SY-17"]')
    retry = stat.get_by_role("button", name=_labels(page)["gui_errcard_retry"], exact=True)
    retry.click()
    # The repaint is asynchronous (a real re-fetch of all four telemetry ids),
    # so wait for the panel to leave its failed state rather than reading it
    # straight after the click.
    expect(retry).to_have_count(0)
    assert message not in stat.inner_text()
    # The healthy content is really back — the lag strip only renders on the
    # success branch.
    assert stat.locator(".strip").count() == 1
    assert page.locator('input[data-field="db_path"]').input_value() == "/e2e/unsaved-edit.db"


def test_siem_status_failure_keeps_the_forwarder_and_destination_controls(v2_page):
    """Finding 3, the same shape on #/system/siem: GET /api/siem/status is
    telemetry (per-destination counters); the forwarder form and the
    destination list are configuration. A 503 from the former must not remove
    the latter, and the per-destination status badge must say "unknown"
    rather than reporting healthy on counters it never received."""
    page, base_url = v2_page
    message = "e2e-siem-status-unavailable"
    handler = _fail_with_503(page, "**/api/siem/status", message)
    try:
        _goto(page, base_url, R_SIEM, "SY-07")

        assert page.locator(".board .errcard").count() == 0
        assert {"SY-07", "SY-08", "SY-09", "SY-10"} - _covs(page) == set()
        assert page.locator('input[data-field="dispatch_tick_seconds"]').count() == 1
        assert page.get_by_role(
            "button", name=_labels(page)["gui_siem_add"], exact=True
        ).count() >= 1

        strip = page.locator(".sy-siem-telemetry")
        assert strip.count() == 1
        assert message in strip.inner_text(), strip.inner_text()
        assert strip.get_by_role(
            "button", name=_labels(page)["gui_errcard_retry"], exact=True
        ).count() == 1
    finally:
        page.unroute("**/api/siem/status", handler)


def test_status_snapshot_failure_keeps_the_display_settings(v2_page):
    """Finding 3, /api/status on #/system/display. It is the only snapshot on
    that page that is not configuration, and its failure used to blank the
    whole page. The language radio must fall back to the SAVED language from
    the settings snapshot rather than defaulting to "en" — a wrong default
    here would enter the dirty ledger and let Save switch the appliance's
    language as a side effect of a status outage."""
    page, base_url = v2_page
    handler = _fail_with_503(page, "**/api/status", "e2e-status-unavailable")
    try:
        _goto(page, base_url, R_DISPLAY, "SY-13")

        assert page.locator(".board .errcard").count() == 0
        assert {"SY-13", "XC-05", "XC-06"} - _covs(page) == set()
        assert page.locator('select[data-field="settings.timezone"]').count() == 1

        saved = _api_get(page, "/api/settings")["settings"].get("language", "en")
        checked = page.locator(
            'input[type="radio"][name="sy-lang"]:checked'
        ).get_attribute("value")
        assert checked == saved, (checked, saved)
        # Nothing is dirty, so nothing can be saved by accident.
        assert page.locator(".savebar").get_attribute("data-tone") == "neutral"
    finally:
        page.unroute("**/api/status", handler)


# ══════════════════════════════════ secrets must not reach the preview ══════

# A value no seeded config, catalogue string or endpoint path can produce, so
# finding it anywhere in a preview is unambiguous evidence of a leak.
SENTINEL = "E2E-SECRET-SENTINEL-9137"
# system.mjs's SECRET_MASK — what the preview must show INSTEAD of the value.
MASK = "•" * 8


def _preview_text(scope):
    """The concatenated text of every request-preview <pre> inside `scope`."""
    panes = scope.locator("pre.codepane")
    return "\n".join(panes.nth(i).inner_text() for i in range(panes.count()))


def test_pce_secrets_never_reach_the_request_preview(v2_page):
    """Finding 1 (security): the docked save row's request preview is a
    VISIBLE <pre> in the DOM, and it used to serialize the raw request body —
    so an operator typing a PCE API key had that key sitting in plaintext on
    screen (and in any screenshot, screen share or DOM dump) until the page
    was left. Covers both PCE forms: the connection panel's docked preview
    and the add-profile drawer's own preview.

    RED against the pre-fix system.mjs: the sentinel appears verbatim in both
    previews. The mask assertions keep this from being a vacuous
    "not-in-string" check (B1) — they prove the key is genuinely IN the body
    being previewed, just redacted, rather than the whole panel having
    disappeared."""
    page, base_url = v2_page
    _goto(page, base_url, R_PCE, "SY-01")

    board = page.locator(".board")
    page.locator('.board input[data-field="key"]').fill(SENTINEL)
    page.locator('.board input[data-field="secret"]').fill(SENTINEL)
    preview = _preview_text(board)
    assert SENTINEL not in preview, preview
    assert '"key": "%s"' % MASK in preview, preview
    assert '"secret": "%s"' % MASK in preview, preview

    page.get_by_role("button", name=_labels(page)["gui_pce_add"], exact=True).first.click()
    drawer = page.locator("aside.drawer")
    drawer.wait_for(state="visible")
    drawer.locator('input[data-field="name"]').fill("e2e-sy-preview")
    drawer.locator('input[data-field="key"]').fill(SENTINEL)
    drawer.locator('input[data-field="secret"]').fill(SENTINEL)
    drawer_preview = _preview_text(drawer)
    assert SENTINEL not in drawer_preview, drawer_preview
    assert '"key": "%s"' % MASK in drawer_preview, drawer_preview
    assert '"secret": "%s"' % MASK in drawer_preview, drawer_preview

    # The dirty ledger has always masked; assert it stays that way so a fix
    # applied in the wrong place cannot regress it.
    assert SENTINEL not in page.locator(".savebar").inner_text()
    # Nothing is saved: the drawer is dismissed without touching the backend.
    page.keyboard.press("Escape")
    page.wait_for_selector("aside.drawer", state="detached")


def test_siem_hec_token_never_reaches_the_request_preview(v2_page):
    """Finding 1, the SIEM destination drawer's hec_token (system.mjs's
    destDrawer). transport=hec is selected first because the HEC section —
    and therefore the token in the body — only exists for that transport.
    Nothing is saved: the drawer is dismissed with Escape."""
    page, base_url = v2_page
    _goto(page, base_url, R_SIEM, "SY-08")

    page.get_by_role("button", name=_labels(page)["gui_siem_add"], exact=True).first.click()
    drawer = page.locator("aside.drawer")
    drawer.wait_for(state="visible")
    drawer.locator('input[data-field="name"]').fill("e2e-sy-preview-hec")
    drawer.locator('select[data-field="transport"]').select_option("hec")
    drawer.locator('input[data-field="hec_token"]').fill(SENTINEL)

    preview = _preview_text(drawer)
    assert SENTINEL not in preview, preview
    assert '"hec_token": "%s"' % MASK in preview, preview

    page.keyboard.press("Escape")
    page.wait_for_selector("aside.drawer", state="detached")


def test_security_new_password_never_reaches_the_request_preview(v2_page):
    """Finding 1, SY-12's new-password boxes. A typed replacement password is
    the most sensitive value this area handles and it was serialized straight
    into the visible preview. Never saved — the form is only typed into."""
    page, base_url = v2_page
    _goto(page, base_url, R_SECURITY, "SY-12")

    page.locator('input[data-field="new_password"]').fill(SENTINEL)
    page.locator('input[data-field="confirm_password"]').fill(SENTINEL)

    preview = _preview_text(page.locator(".board"))
    assert SENTINEL not in preview, preview
    assert '"new_password": "%s"' % MASK in preview, preview
    assert SENTINEL not in page.locator(".savebar").inner_text()


def test_alert_channel_secrets_never_reach_the_request_preview(v2_page):
    """Finding 1, SY-14's alert-plugin secret fields (SMTP password, bot
    tokens — whichever the real plugin catalogue declares). Every declared
    secret box is filled, so this covers the catalogue as it actually is
    rather than one hardcoded plugin; the count assertion keeps the test from
    passing vacuously if the catalogue ever stops declaring any secret."""
    page, base_url = v2_page
    _goto(page, base_url, R_CHANNELS, "SY-14")

    boxes = page.locator('section[data-cov="SY-14"] input[type="password"]')
    total = boxes.count()
    assert total >= 1, "no secret field rendered — nothing to prove"
    for i in range(total):
        boxes.nth(i).fill(SENTINEL)

    preview = _preview_text(page.locator(".board"))
    assert SENTINEL not in preview, preview
    assert preview.count(MASK) >= total, preview
    assert SENTINEL not in page.locator(".savebar").inner_text()


# ══════════════════════════════════════════ real, harmless DLQ wiring ════════

def test_dlq_replay_and_purge_are_wired_for_real(v2_page):
    """SY-10: replay and purge are real endpoints. Called directly with a
    `dest` matching no configured destination, so the call is a genuine,
    harmless no-op — proves the wiring without touching real DLQ data."""
    page, base_url = v2_page
    _goto(page, base_url, R_SIEM, "SY-10")

    replayed = _api_post(page, "/api/siem/dlq/replay", {"dest": "e2e-sy-no-such-dest", "limit": 10})
    assert replayed == {"status": "ok", "requeued": 0}, replayed

    purged = _api_post(page, "/api/siem/dlq/purge", {"dest": "e2e-sy-no-such-dest", "older_than_days": 999})
    assert purged == {"status": "ok", "removed": 0}, purged


# ═══════════════════════════ responses the UI has to read, not assume ════════
#
# Task 12d F1/F2. Both defects survived because nothing here ever inspected a
# write's answer: SY-03's confirm sent no request at all, and SY-10's
# replay/purge painted a green toast whatever came back.

def _fulfill(page, pattern, status, body):
    """Answer `pattern` with a fixed status+JSON body. Returns the handler so
    the caller can page.unroute() it again.

    The failure/rate-limit/success branches under test are ordinary HTTP
    statuses this app really produces (409/429 from src/gui/__init__.py's
    api_daemon_restart and its 429 errorhandler; the {status:"ok"} /
    {ok:false,error} pair from src/siem/web.py) — injecting them at the
    network boundary is how the other v2 e2e files exercise a response shape
    without needing the real precondition, and for the DLQ it is also what
    keeps this file's destructive-operation discipline: the purge Confirm is
    clicked against a fulfilled response, so no real purge is ever issued."""
    def handler(route):
        route.fulfill(status=status, content_type="application/json", body=body)
    page.route(pattern, handler)
    return handler


def _toast_text(page, tone):
    node = page.locator('.toast[data-tone="%s"]' % tone).first
    node.wait_for(state="visible")
    return node.inner_text()


def _clear_toasts(page):
    """Toasts live ~4s and stack; drop them so the next step reads its own."""
    page.evaluate("() => document.querySelectorAll('.toast').forEach(n => n.remove())")


def _confirm_restart(page, labels):
    """Open the SY-03 restart confirm and click Confirm.

    `.last` for the reason test_destructive_confirms_render_cancel_sends_nothing
    already documents: the label is shared by the (initially hidden) banner
    button and the standalone one below it."""
    page.get_by_role("button", name=labels["gui_it_restart_monitor"], exact=True).last.click()
    box = page.locator(".modal")
    box.wait_for(state="visible")
    box.get_by_role("button", name=labels["gui_confirm"], exact=True).click()
    return box


def test_restart_monitor_posts_and_branches_on_the_status(v2_page):
    """F1: SY-03 must actually call POST /api/daemon/restart and tell the four
    outcomes apart.

    RED against the pre-fix system.mjs: the confirm performed no request at
    all, so `expect_request` below times out — it only ever showed the
    "managed externally" line, which is a lie under the standard
    systemd/`--monitor-gui` deployment where the restart really works."""
    page, base_url = v2_page
    _goto(page, base_url, R_CACHE, "SY-03")
    labels = _labels(page)

    # 409, against the REAL backend: this harness builds the app through
    # build_app() without src/cli/_runtime.py's run_daemon_with_gui, so
    # _GUI_OWNS_DAEMON stays False and api_daemon_restart really answers
    # 409 {ok:false, error:<localised>} — the one case the old
    # acknowledgment-only confirm happened to describe correctly.
    with page.expect_request(
        lambda r: r.url.endswith("/api/daemon/restart") and r.method == "POST"
    ) as info:
        _confirm_restart(page, labels)
    assert info.value.response().status == 409
    assert _toast_text(page, "info") == labels["gui_daemon_external_restart_hint"]
    page.wait_for_selector(".modal", state="detached")
    _clear_toasts(page)

    # 200 — the standard deployment's outcome.
    handler = _fulfill(page, "**/api/daemon/restart", 200, '{"ok": true}')
    try:
        _confirm_restart(page, labels)
        assert _toast_text(page, "ok") == labels["gui_restart_success"]
        page.wait_for_selector(".modal", state="detached")
    finally:
        page.unroute("**/api/daemon/restart", handler)
    _clear_toasts(page)

    # 429 — five per hour is a limit an operator can genuinely reach while
    # tuning cache settings, so it gets its own sentence rather than the raw
    # error code, and its own (transient) tone.
    handler = _fulfill(
        page, "**/api/daemon/restart", 429,
        '{"ok": false, "error": "rate_limit_exceeded", "description": "5 per 1 hour"}',
    )
    try:
        _confirm_restart(page, labels)
        text = _toast_text(page, "warn")
        assert "5 per 1 hour" in text, text
        assert "rate_limit_exceeded" not in text, text
        # A failure keeps the confirm open (SY-04 retention's own shape), so
        # the operator can retry without reopening it.
        page.locator(".modal").get_by_role("button", name=labels["gui_cancel"], exact=True).click()
        page.wait_for_selector(".modal", state="detached")
    finally:
        page.unroute("**/api/daemon/restart", handler)
    _clear_toasts(page)

    # anything else — the server's own error text, never a success toast.
    handler = _fulfill(page, "**/api/daemon/restart", 500, '{"ok": false, "error": "e2e-restart-boom"}')
    try:
        _confirm_restart(page, labels)
        assert "e2e-restart-boom" in _toast_text(page, "crit")
        assert page.locator('.toast[data-tone="ok"]').count() == 0
        page.locator(".modal").get_by_role("button", name=labels["gui_cancel"], exact=True).click()
        page.wait_for_selector(".modal", state="detached")
    finally:
        page.unroute("**/api/daemon/restart", handler)

    # Every branch's message came out of the real catalogue.
    assert _missing_i18n(page) == []


DLQ_ENTRY = {
    "id": 4242,
    "destination": "e2e-sy-dlq-dest",
    "source_id": "evt-e2e-1",
    "last_error": "e2e-dlq-reason",
    "quarantined_at": "2026-08-14T00:00:00Z",
    "retries": 2,
}


def _stub_dlq_list(page):
    """One DLQ row to act on. GET /api/siem/dlq is answered from a real,
    empty cache DB in this harness, and a row is the precondition for the
    replay button existing at all — so only the listing is stubbed; the
    replay/purge calls under test still travel the app's real api.post()."""
    body = json.dumps({"entries": [DLQ_ENTRY], "total": 1})

    def handler(route):
        route.fulfill(status=200, content_type="application/json", body=body)
    # Only the listing itself: /dlq and /dlq?..., never /dlq/replay|purge.
    page.route(re.compile(r"/api/siem/dlq(\?|$)"), handler)
    return handler


def test_dlq_replay_and_purge_read_their_response(v2_page):
    """F2: SY-10's replay and purge must report what the server actually said.

    The trap this guards (lesson A3): these two endpoints carry NO `ok` field
    when they succeed — src/siem/web.py answers {"status":"ok","requeued":N} /
    {"status":"ok","removed":N}, and only a FAILURE produces {ok:false,error}.
    A `res.ok !== true` check would therefore call every success a failure;
    `res.error` is the field that separates them.

    RED against the pre-fix system.mjs, which inspected neither: the failure
    halves below saw a green toast reporting 0, and purge additionally
    returned true so the confirm closed as if it had worked."""
    page, base_url = v2_page
    listing = _stub_dlq_list(page)
    try:
        _goto(page, base_url, R_SIEM, "SY-10")
        labels = _labels(page)
        row_replay = page.get_by_role("button", name=labels["gui_dlq_replay"], exact=True).first
        row_replay.wait_for(state="visible")

        # replay, success. The row button posts {ids:[...]}, and THAT branch of
        # replay_dlq answers `requeued` as replay_ids' per-item result list
        # (src/siem/dlq.py:52-74), not a count — transcribed here rather than
        # assumed, because the pre-fix code printed the list straight into the
        # toast's {n} ("[object Object] requeued for delivery").
        handler = _fulfill(page, "**/api/siem/dlq/replay", 200,
                           '{"status": "ok", "requeued": [{"id": 4242, "ok": true}]}')
        try:
            row_replay.click()
            text = _toast_text(page, "ok")
            assert "1" in text, text
            assert "object" not in text, text
        finally:
            page.unroute("**/api/siem/dlq/replay", handler)
        _clear_toasts(page)

        # replay, per-item failure inside an HTTP 200: an id already gone comes
        # back {ok:false,error} in that same list, with nothing wrong at the
        # top level. It is still not a success.
        handler = _fulfill(page, "**/api/siem/dlq/replay", 200,
                           '{"status": "ok", "requeued": [{"id": 4242, "ok": false, "error": "e2e-gone"}]}')
        try:
            row_replay.click()
            assert "e2e-gone" in _toast_text(page, "crit")
            assert page.locator('.toast[data-tone="ok"]').count() == 0
        finally:
            page.unroute("**/api/siem/dlq/replay", handler)
        _clear_toasts(page)

        # replay, transport/HTTP failure: the server's error, no success toast.
        handler = _fulfill(page, "**/api/siem/dlq/replay", 500,
                           '{"ok": false, "error": "e2e-replay-boom"}')
        try:
            row_replay.click()
            assert "e2e-replay-boom" in _toast_text(page, "crit")
            assert page.locator('.toast[data-tone="ok"]').count() == 0
        finally:
            page.unroute("**/api/siem/dlq/replay", handler)
        _clear_toasts(page)

        # purge, success: the real removed count.
        purge_btn = page.get_by_role("button", name=labels["gui_dlq_purge_selected"], exact=True)
        handler = _fulfill(page, "**/api/siem/dlq/purge", 200, '{"status": "ok", "removed": 7}')
        try:
            purge_btn.click()
            box = page.locator(".modal")
            box.wait_for(state="visible")
            box.get_by_role("button", name=labels["gui_confirm"], exact=True).click()
            assert "7" in _toast_text(page, "ok")
            page.wait_for_selector(".modal", state="detached")
        finally:
            page.unroute("**/api/siem/dlq/purge", handler)
        _clear_toasts(page)

        # purge, failure: the confirm stays open and says so.
        handler = _fulfill(page, "**/api/siem/dlq/purge", 500,
                           '{"ok": false, "error": "e2e-purge-boom"}')
        try:
            purge_btn.click()
            box = page.locator(".modal")
            box.wait_for(state="visible")
            box.get_by_role("button", name=labels["gui_confirm"], exact=True).click()
            assert "e2e-purge-boom" in _toast_text(page, "crit")
            assert page.locator('.toast[data-tone="ok"]').count() == 0
            expect(box).to_be_visible()
            box.get_by_role("button", name=labels["gui_cancel"], exact=True).click()
            page.wait_for_selector(".modal", state="detached")
        finally:
            page.unroute("**/api/siem/dlq/purge", handler)
    finally:
        page.unroute(re.compile(r"/api/siem/dlq(\?|$)"), listing)


# ══════════════════════════════════════════════════════════════ teardown ═════

def test_teardown_closes_surfaces_and_palette(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_PCE, "SY-01")

    page.evaluate(
        "async () => { const { drawer } = await import('/static/js/v2/components/drawer.mjs'); "
        "const { palette } = await import('/static/js/v2/components/palette.mjs'); "
        "palette.list().find(c => c.id === 'sy:pce-add').run(); }"
    )
    page.locator("aside.drawer").wait_for(state="visible")
    assert R_PCE in _palette_routes(page)

    _navigate(page, R_CACHE, "SY-02")
    assert page.locator("aside.drawer").count() == 0
    assert R_PCE not in _palette_routes(page)

    _open_all(page)
    assert page.locator(".modal").count() >= 1
    _navigate(page, R_SIEM, "SY-07")
    assert page.locator(".modal").count() == 0
    assert all(route != R_CACHE for route in _palette_routes(page))
