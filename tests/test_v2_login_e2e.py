"""Phase 2A Task 10 — in-process Playwright e2e for the v2 login page.

Drives a real (headless) Chromium against a real Flask app + the real
POST /api/login / POST /api/security endpoints (no snapshots, no mocks)
through tests.v2_e2e_utils's shared harness — see that module's docstring
for the harness itself.

Covers exactly the brief's three scenarios:
  - wrong password -> the real 401's error message renders inline, no
    navigation away from /v2/login.
  - correct password -> lands on the real /v2 shell (not just "some URL
    starting with /v2" — asserted via a shell-only DOM marker).
  - the first-login branch: a fixture sets a REAL must_change_password=True
    in the backend config (not a stubbed response), the inline
    change-password form that appears submits for real to POST
    /api/security, and the test asserts the backend's actual persisted
    state changed (must_change_password cleared, password hash rotated) —
    not just that a success message appeared on screen.

None of this weakens or bypasses authentication: every login here goes
through the real POST /api/login (or, for the wrong-password case,
deliberately fails it) exactly as tests.v2_e2e_utils.v2_login() does for
every other v2 e2e suite.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

from src.config import verify_password  # noqa: E402

# Registers v2_page/v2_context/v2_server/v2_app/_v2_browser/_v2_playwright —
# see tests/v2_e2e_utils.py's module docstring for why both this line and the
# importorskip above (in THIS module, not just there) are required, in order.
pytest_plugins = ["tests.v2_e2e_utils"]

from tests.v2_e2e_utils import (  # noqa: E402
    V2_PASSWORD,
    V2_USERNAME,
    _bounded_close,
    _LiveServer,
    build_v2_app,
)


# ── fixtures specific to this file ──────────────────────────────────────────
#
# v2_page (v2_e2e_utils) logs in via the real /api/login before handing back
# a page — exactly the wrong starting point for a login test, and not
# something to weaken: instead of touching it, this file adds its own
# logged-out page fixture on top of the same v2_context/v2_server building
# blocks v2_page itself is built from, so every other suite's v2_page keeps
# working unchanged.

@pytest.fixture
def v2_login_page(v2_context, v2_server):
    """A logged-OUT Playwright page, plus the server's base_url."""
    page = v2_context.new_page()
    page.set_default_timeout(10_000)
    try:
        yield page, v2_server
    finally:
        _bounded_close("v2_login_page", page.close)


@pytest.fixture
def v2_first_login_app(temp_config_file):
    """A real app whose backend config already has must_change_password set.

    This is the fixture the brief requires: must_change_password is real
    persisted backend state (config.json, via ConfigManager), not a stubbed
    /api/login response — auth.py's real handler reads it off gui_cfg and
    echoes it back honestly.

    Isolation/restoration: temp_config_file (tests/conftest.py) hands out a
    fresh tmpdir per test function and rmtree's it in its own teardown, so
    this fixture's must_change_password=True and the password rotation the
    test below performs against it are both confined to a private, disposable
    config file — nothing here is shared state that could leak into another
    test or leave a real account unusable, whether or not the test that used
    it passes.

    settings.language is pinned to zh_TW (not left at the "en" default) to
    prove login.mjs's fallback behaviour holds regardless of the configured
    install language — LG-02 must still read the plain English t()-fallback
    text (see login.mjs header note 5: it deliberately never re-queries the
    catalogue while must_change_password is pending), not a raw/unresolved
    key literal, and not some accidental match that only happens to work
    because "en" was already the configured language.
    """
    app, cm = build_v2_app(temp_config_file, must_change_password=True)
    cm.config["settings"] = {"language": "zh_TW"}
    cm.save()
    return app, cm


@pytest.fixture
def v2_first_login_page(_v2_browser, v2_first_login_app):
    app, cm = v2_first_login_app
    server = _LiveServer(app)
    server.start()
    ctx = _v2_browser.new_context(ignore_https_errors=True)
    page = ctx.new_page()
    page.set_default_timeout(10_000)
    try:
        yield page, server.base_url, cm
    finally:
        _bounded_close("v2_first_login_page.page", page.close)
        _bounded_close("v2_first_login_page.ctx", ctx.close)
        server.stop()


def _goto_login(page, base_url):
    page.goto(base_url + "/v2/login")
    page.wait_for_selector('body[data-booted="true"]')


# ── LG-01: wrong password ───────────────────────────────────────────────────

def test_wrong_password_shows_error_and_stays_on_login(v2_login_page):
    page, base_url = v2_login_page
    _goto_login(page, base_url)

    page.fill('[data-cov="LG-01"] input[data-field="username"]', V2_USERNAME)
    page.fill('[data-cov="LG-01"] input[data-field="password"]', "definitely-not-the-password")
    page.click('[data-cov="LG-01"] button.btn.primary')

    err = page.locator('[data-cov="LG-01"] input[data-field="password"] + .fld-err')
    err.wait_for(state="visible")
    # The exact live server string (auth.py's real 401 body, gui_err_invalid_auth
    # at settings.language's "en" default) — not just "some text appeared". A
    # server-side wording change, a client mis-parse of r.error, or a client
    # bug that shows the generic gui_err_generic message instead all turn
    # this red.
    assert err.inner_text() == "Invalid username or password."
    # Real production behaviour: no navigation on a failed login.
    assert "/v2/login" in page.url


# ── LG-01: correct password ─────────────────────────────────────────────────

def test_correct_password_lands_on_v2_shell(v2_login_page):
    page, base_url = v2_login_page
    _goto_login(page, base_url)

    page.fill('[data-cov="LG-01"] input[data-field="username"]', V2_USERNAME)
    page.fill('[data-cov="LG-01"] input[data-field="password"]', V2_PASSWORD)
    page.click('[data-cov="LG-01"] button.btn.primary')

    page.wait_for_url(base_url + "/v2*")
    page.wait_for_selector('body[data-booted="true"]')
    # Prove this is the real /v2 SPA shell (base.html's #area-root), not just
    # a URL that happens to start with /v2 — e.g. a broken redirect back to
    # this same login page would also satisfy a bare URL-prefix check.
    assert page.locator("#area-root").count() == 1
    assert page.locator("#login-root").count() == 0


# ── LG-02: first-login password change, real backend state ─────────────────

def test_first_login_change_password_flow_hits_real_backend(v2_first_login_page):
    page, base_url, cm = v2_first_login_page
    _goto_login(page, base_url)

    # Pre-auth: the catalogue fetch (GET /api/ui_translations) 401s for an
    # anonymous request (same before_request gate as every other /api/*
    # route), so LG-01 renders in its English t()-fallback text regardless of
    # settings.language=zh_TW — see login.mjs header note 5. Asserted here so
    # the later post-auth assertion below is a real before/after contrast,
    # not a coincidence.
    assert page.locator('[data-cov="LG-01"] h1').inner_text() == "PCE Ops"

    page.fill('[data-cov="LG-01"] input[data-field="username"]', V2_USERNAME)
    page.fill('[data-cov="LG-01"] input[data-field="password"]', V2_PASSWORD)
    page.click('[data-cov="LG-01"] button.btn.primary')

    # The real /api/login response (must_change_password=True, set by the
    # v2_first_login_app fixture above) drives the branch — not a picked
    # demo outcome.
    page.wait_for_selector('[data-cov="LG-02"]:not([hidden])')
    assert page.get_attribute('[data-cov="LG-01"]', "hidden") is not None

    # LG-02 stays on the same t()-fallback text as LG-01, even though this
    # fixture configures settings.language=zh_TW: login.mjs deliberately
    # never re-queries GET /api/ui_translations once authenticated but still
    # must_change_password-gated (header note 5 — that call would 423 and
    # api.mjs would navigate the whole page away to /login). If a future
    # change ever raced the catalogue fetch back in and something derailed
    # the fallback (e.g. a raw, unresolved key literal leaking to the
    # screen), this would stop reading "PCE Ops".
    assert page.locator('[data-cov="LG-02"] h1').inner_text() == "PCE Ops"

    new_password = "a genuinely new v2 login password"
    page.fill('[data-cov="LG-02"] input[data-field="new_password"]', new_password)
    page.fill('[data-cov="LG-02"] input[data-field="confirm_password"]', new_password)
    page.click('[data-cov="LG-02"] button.btn.primary')

    page.wait_for_url(base_url + "/v2*")
    page.wait_for_selector('body[data-booted="true"]')
    assert page.locator("#area-root").count() == 1

    # The real backend state changed via the real POST /api/security handler
    # (src/gui/routes/config.py:api_security_post) — not a stubbed 200. A
    # regression that accepted the form but silently no-opped the backend
    # write, or that left must_change_password set, turns this red.
    cm.load()
    gui_cfg = cm.config.get("web_gui", {})
    assert not gui_cfg.get("must_change_password")
    assert verify_password(new_password, gui_cfg.get("password", ""))
    assert not verify_password(V2_PASSWORD, gui_cfg.get("password", ""))
