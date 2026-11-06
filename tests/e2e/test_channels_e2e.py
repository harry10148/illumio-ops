"""Settings › Notification channels in a browser: a test reaches a local receiver; secrets come back masked."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from playwright.sync_api import expect

from illumio_ops.services.alerts import channels
from tests.e2e.conftest import sign_in


class _Receiver(BaseHTTPRequestHandler):
    got: list = []  # noqa: RUF012 - one receiver per test

    def do_POST(self):
        _Receiver.got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def receiver(monkeypatch):
    """Settings accept only https webhook URLs, so the page uses one; the send goes to a local plain-HTTP receiver."""
    _Receiver.got = []
    srv = HTTPServer(("127.0.0.1", 0), _Receiver)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    local = f"http://127.0.0.1:{srv.server_address[1]}/hook"
    real_post = channels._post
    monkeypatch.setattr(channels, "_post", lambda url, body, **kw: real_post(
        url.replace("https://hook.example/in", local), body, **kw))
    yield "https://hook.example/in/SECRET-PATH"
    srv.shutdown()


def test_channels_mask_and_test_webhook(context, live_app, receiver):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.click(".sidenav .nav-item[data-nav='/alert-rules']")
    page.click("[data-tab=channels]")
    card = page.locator("[data-channel=webhook]")
    card.locator("input[name=webhook_url]").fill(receiver)
    card.get_by_role("button", name="Send a test").click()
    expect(card.locator("[data-role=test-result]")).to_have_text("Sent. Check that it arrived.")
    assert _Receiver.got and _Receiver.got[0]["alerts"][0]["rule"] == "Test message"
    card.locator("input[name=webhook_enabled]").check()
    page.get_by_role("button", name="Save").click()
    expect(page.locator("p.form-ok[role=status]")).to_have_text("Saved.")
    page.reload()
    value = page.locator("[data-channel=webhook] input[name=webhook_url]").input_value()
    assert value == "********" and "SECRET-PATH" not in page.content()
    assert live_app.ctx.settings.current().alerts.channels.webhook.url == "https://hook.example/in/SECRET-PATH"


def test_test_every_enabled_channel(context, live_app, receiver):
    """5.x parity 2026-11-06: one button tests every enabled channel; none enabled is said so."""
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?tab=channels")
    page.locator("[data-role=test-all]").click()
    expect(page.locator("[data-role=test-all-none]")).to_have_text("No channel is enabled on this page.")
    card = page.locator("[data-channel=webhook]")
    card.locator("input[name=webhook_url]").fill(receiver)
    card.locator("input[name=webhook_enabled]").check()
    page.locator("[data-role=test-all]").click()
    expect(card.locator("[data-role=test-result]")).to_have_text("Sent. Check that it arrived.")
    expect(page.locator("[data-channel=line] [data-role=test-result]")).to_have_count(0)
    expect(page.locator("[data-role=test-all-none]")).to_have_count(0)
    assert len(_Receiver.got) == 1
