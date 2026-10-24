"""Browser tests against a real v6 server (werkzeug, HTTP) and a fake PCE."""
from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from werkzeug.serving import make_server

from illumio_ops.services.context import AppContext
from illumio_ops.web.app import DEFAULT_STATIC_DIR, create_app
from tests_v6.e2e.fake_pce import FakePce
from tests_v6.web.conftest import ADMIN_PASSWORD, make_ctx

sync_api = pytest.importorskip("playwright.sync_api")


@dataclass
class LiveApp:
    url: str
    ctx: AppContext


@pytest.fixture
def fake_pce() -> Iterator[FakePce]:
    pce = FakePce().start()
    yield pce
    pce.stop()


@pytest.fixture
def live_app(tmp_path, monkeypatch) -> Iterator[LiveApp]:
    assert (DEFAULT_STATIC_DIR / "index.html").is_file(), "build the frontend first"
    monkeypatch.setenv("ILLUMIO_OPS_RATELIMIT_URI", "memory://")
    ctx = make_ctx(tmp_path)
    app = create_app(ctx, use_https=False)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield LiveApp(f"http://127.0.0.1:{server.server_port}", ctx)
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def context(browser):
    ctx = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
    yield ctx
    ctx.close()


def sign_in(page, base_url: str) -> None:
    page.goto(base_url + "/")
    page.fill("input[autocomplete=username]", "illumio")
    page.fill("input[autocomplete=current-password]", ADMIN_PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_selector(".shell")
