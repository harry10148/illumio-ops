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

## Destructive-operation discipline

This area can stop the GUI, regenerate TLS material and purge queued data.
Nothing here is triggered destructively:

  POST /api/pce-profiles {action:"activate", ...}  — NEVER called. Re-points
      the whole appliance's PCE target; the confirm renders, Cancel is
      clicked, Confirm never is.
  POST /api/cache/retention/run   — NEVER called for real. Purges cache rows;
      confirm renders + Cancel only.
  The "restart monitor" confirm    — has no backend route to call in the
      first place (verified while writing the port — no daemon-restart
      endpoint exists anywhere in this repo); still confirm renders + Cancel
      only, matching the task brief's explicit list.
  POST /api/tls/renew             — NEVER called. Overwrites the serving
      self-signed cert in place with no backup; confirm renders + Cancel only.
  POST /api/tls/import-cert       — NEVER called. Overwrites the serving
      cert's config; confirm renders + Cancel only.
  POST /api/siem/dlq/purge        — NEVER called through the UI's confirm
      (Cancel only). Exercised directly through api.post with a `dest` that
      matches no destination, so the real call is a genuine, harmless no-op
      (asserts {removed: 0}) — proves the wiring without deleting anything.
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
    page.wait_for_selector("code:text-is('%s')" % route)
    page.wait_for_selector('[data-cov="%s"]' % cov)


def _navigate(page, route, cov):
    page.evaluate("location.hash = '%s'" % route)
    page.wait_for_selector("code:text-is('%s')" % route)
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
        "gui_tls_csr_generate", "gui_sy_discard",
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
        page.wait_for_selector("code:text-is('%s')" % R_DISPLAY)
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
        """watch_url=None (the "restart monitor" case): there is no backend
        route to watch at all (verified while writing the port — no
        daemon-restart endpoint exists anywhere in this repo), so only
        render + Cancel-dismiss is asserted there; every other case also
        asserts its own real endpoint was never called."""
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
    _confirm_cancel_only(R_CACHE, "SY-03", labels["gui_it_restart_monitor"], None)
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
