"""Shared in-process Playwright harness for Phase 2A `/v2` end-to-end tests.

## Why this file exists

The phase2a-gui plan's Global Constraints (and this task's own brief) said to
"reuse the existing in-process Playwright pattern" — citing
tests/test_gui_e2e_playwright.py's app fixture and an auth bypass
(`login_manager.session_protection=None` + `sess["_user_id"]`). Verified
before writing this file: that pattern does not exist anywhere in this repo.
All five existing Playwright test files (test_gui_e2e_playwright.py,
test_gui_e2e_filterbar_playwright.py, test_e2e_header_menu.py,
test_gui_settings_subtab_e2e.py, test_e2e_dashboard_story.py) are gated on
`ILLUMIO_OPS_E2E_BASE_URL` and skip the whole module when it's unset — none
of them contains an app fixture, and the cited auth bypass does not appear in
the codebase. So this module builds the harness the plan assumed already
existed, as a *shared* module — Tasks 3-10 each add their own
`test_v2_<area>_e2e.py` and must import fixtures from here rather than
re-implement this pattern per file.

## What it does

  - Builds a real Flask app via `src.gui.build_app` with
    `web_gui.enable_v2_preview = True`, `use_https=False` (so
    `SESSION_COOKIE_SECURE` stays False — see src/gui/__init__.py:179 — and a
    plain-HTTP local server can carry the session cookie), and
    `app.testing = True` (so Talisman's forced-HTTPS redirect is disabled —
    see src/gui/__init__.py:461-476, `_force_https_unless_testing`).
  - Serves it with `werkzeug.serving.make_server("127.0.0.1", 0, app,
    threaded=True)` on a background thread, using an OS-assigned port so
    tests never collide. `threaded=True` (Task 4 fix — the real production
    server runs cheroot's multi-thread pool, see
    src/gui/routes/dashboard.py:560-562's own comment) matters once a test
    drives two genuinely concurrent requests: a page that fires a slow
    PCE-backed background fetch (verified: label/IP-list/service resolution
    against an unreachable PCE can chain several ~6s DNS-retry failures
    before the request itself even starts, 30s+ total) and then, moments
    later, a fast foreground POST/GET — without `threaded=True` the dev
    server's single worker queues the fast request behind the slow one,
    which read as the fast request hanging (reproduced and confirmed: the
    save button's own request never even started listening until the slow
    one finished).
  - Logs in through the REAL `/api/login` endpoint via Playwright's
    `BrowserContext.request` (an APIRequestContext bound to the same browser
    context, so the session cookie it receives is sent by subsequent `page`
    navigations) — this is the real login flow, not a bypass, and is exactly
    the alternative the controlling ruling allowed ("drive the login page, or
    POST /api/login from the browser context").
  - Tears the server down cleanly at fixture teardown.

## How to use this from a new test_v2_<area>_e2e.py

`v2_page` depends on `v2_context` and `v2_server`, which in turn depend on
`v2_app` / `_v2_browser` / `_v2_playwright` — a plain
`from tests.v2_e2e_utils import v2_page` is NOT enough, because pytest only
resolves a fixture's own dependencies via conftest.py or the requesting
module's own plugin registration, not via a second module's globals. Register
the whole chain at once with `pytest_plugins`:

    import pytest
    pytest.importorskip("playwright.sync_api", exc_type=ImportError)

    pytest_plugins = ["tests.v2_e2e_utils"]

    def test_something(v2_page):
        page, base_url = v2_page
        ...

Both lines are required, IN THIS ORDER — this is not optional boilerplate:

  1. `pytest.importorskip(...)` MUST come first, in the consuming module
     itself, even though this file already guards its own import with the
     same call. If playwright is not installed and this module is loaded
     only via the `pytest_plugins` line below, pytest 9.0.3 raises
     `Skipped` while importing it as a plugin, and pytest silently swallows
     that into its internal `skipped_plugins` list *without registering any
     of this module's fixtures* — the consuming test module then fails with
     a confusing `fixture 'v2_page' not found` instead of skipping cleanly.
     Calling `importorskip` directly in the consuming module first makes
     pytest skip that whole module during collection, before it ever tries
     to load this one as a plugin, which is the clean outcome CI without
     browsers needs.
  2. `pytest_plugins = ["tests.v2_e2e_utils"]` — at test-module scope (as
     opposed to a non-rootdir conftest.py) this is fully supported by
     pytest 9.x, and is what actually registers `v2_page`'s dependency
     chain so it resolves.

`tests/test_v2_core_e2e.py` is the reference implementation of this pattern.
"""
from __future__ import annotations

import json
import threading

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

from playwright.sync_api import sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from src.config import ConfigManager, hash_password  # noqa: E402
from src.gui import build_app  # noqa: E402

V2_USERNAME = "admin"
V2_PASSWORD = "testpass"


def build_v2_app(temp_config_file: str, **web_gui_overrides):
    """Build a real Flask app with the v2 preview flag on, ready for a plain-HTTP server.

    Mirrors tests/conftest.py's app_persistent fixture (and
    tests/test_v2_scaffold.py's app_v2_enabled), only adding
    `enable_v2_preview: True` and building with `use_https=False`.
    """
    cm = ConfigManager(config_file=temp_config_file)
    cm.load()
    cm.config["web_gui"] = {
        "username": V2_USERNAME,
        "password": hash_password(V2_PASSWORD),
        "allowed_ips": ["127.0.0.1", "192.168.1.0/24"],
        "secret_key": "x" * 64,
        "enable_v2_preview": True,
        **web_gui_overrides,
    }
    cm.save()

    app = build_app(cm, persistent_mode=True, use_https=False)
    app.config.update({"TESTING": True})
    app.testing = True  # disables Talisman's forced-HTTPS redirect for this app
    return app, cm


class _LiveServer:
    """A real werkzeug HTTP server for `app`, running on a background thread."""

    def __init__(self, app):
        # threaded=True — see this module's docstring ("What it does") for
        # why a single-threaded dev server produces spurious hangs once a
        # test drives a slow background fetch concurrently with a fast
        # foreground one; the real production server is multi-threaded too.
        self._server = make_server("127.0.0.1", 0, app, threaded=True)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://127.0.0.1:{port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)


@pytest.fixture
def v2_app(temp_config_file):
    """A real Flask app with the v2 preview flag on. Not served — see v2_server."""
    app, _cm = build_v2_app(temp_config_file)
    return app


@pytest.fixture
def v2_server(v2_app):
    """base_url of a live server serving v2_app, torn down after the test."""
    server = _LiveServer(v2_app)
    server.start()
    try:
        yield server.base_url
    finally:
        server.stop()


@pytest.fixture(scope="session")
def _v2_playwright():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def _v2_browser(_v2_playwright):
    browser = _v2_playwright.chromium.launch()
    try:
        yield browser
    finally:
        browser.close()


@pytest.fixture
def v2_context(_v2_browser):
    ctx = _v2_browser.new_context(ignore_https_errors=True)
    try:
        yield ctx
    finally:
        ctx.close()


def v2_login(context, base_url: str, username: str = V2_USERNAME, password: str = V2_PASSWORD) -> None:
    """Log in through the real POST /api/login, from the browser context.

    Uses Playwright's APIRequestContext (`context.request`), which shares
    its cookie jar with `context` — so a `page.goto()` after this call
    carries the session cookie the login response set. This is the real
    login endpoint (the same one the production login page's JS calls),
    not an auth bypass.
    """
    resp = context.request.post(
        base_url + "/api/login",
        data=json.dumps({"username": username, "password": password}),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, f"login failed: {resp.status} {resp.text()}"
    body = resp.json()
    assert body.get("ok") is True, body


@pytest.fixture
def v2_page(v2_context, v2_server):
    """A logged-in Playwright page, plus the server's base_url, ready to visit /v2.

    Yields (page, base_url) so tests can `page.goto(base_url + "/v2#/overview")`.
    """
    v2_login(v2_context, v2_server)
    page = v2_context.new_page()
    page.set_default_timeout(10_000)
    try:
        yield page, v2_server
    finally:
        page.close()
