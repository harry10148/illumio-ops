"""SIEM forwarding in a browser (P7): a destination added and tested against a local UDP receiver, its status row, the
HEC token never on the page, the lightweight notice, and the DLQ purge with an in-page confirmation."""
import socket
from datetime import UTC, datetime

import pytest
from playwright.sync_api import expect

from illumio_ops.store import siem as store
from tests.e2e.conftest import sign_in

DEST = "b" * 32


@pytest.fixture
def udp():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(5)
    yield s
    s.close()


def _set(live_app, mutate):
    live_app.ctx.settings.update(live_app.ctx.settings.current().revision, mutate)


def test_add_a_destination_test_it_and_see_its_status(context, live_app, udp):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.click("nav >> text=SIEM forwarding")
    expect(page.locator("[data-role=siem-off]")).to_be_visible()
    page.locator("[data-role=siem-add]").click()
    card = page.locator("[data-role=siem-destination]")
    card.locator("input[name=siem_name]").fill("local")
    card.locator("select[name=siem_transport]").select_option("udp")
    card.locator("input[name=siem_host]").fill("127.0.0.1")
    card.locator("input[name=siem_port]").fill(str(udp.getsockname()[1]))
    card.locator("select[name=siem_format]").select_option("json")
    card.locator("[data-role=siem-test]").click()
    expect(card.locator("[data-role=siem-test-result]")).to_have_class("form-ok")
    line = udp.recv(65535).decode()
    assert '"kind":"test"' in line and "illumio-ops" in line
    page.locator("input[name=siem_enabled]").check()
    page.get_by_role("button", name="Save").click()
    expect(page.locator("p.form-ok[role=status]")).to_have_text("Saved.")
    row = page.locator("[data-role=siem-status] tr[data-dest=local][data-source=audit]")
    expect(row).to_have_attribute("data-state", "ok")  # saving placed its cursor: nothing stored after it is skipped


def test_the_hec_token_is_never_on_the_page(context, live_app):
    _set(live_app, lambda d: d["siem"].update(enabled=True, destinations=[{
        "id": DEST, "name": "splunk", "enabled": True, "transport": "hec", "format": "json", "host": "splunk.example",
        "port": 8088, "framing": "lf", "verify_tls": True, "hec_token": "HEC-PAGE-SECRET", "batch_size": 100,
        "max_retries": 10, "sources": ["audit"], "new_connection_decisions": [], "new_connection_internal_only": True, "mask_pii": False}]))
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/siem")
    expect(page.locator("input[name=siem_hec_token]")).to_have_value("********")
    assert "HEC-PAGE-SECRET" not in page.content()


def test_lightweight_says_findings_need_alert_mode(context, live_app):
    _set(live_app, lambda d: d["collection"].update(mode="lightweight"))
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/siem")
    page.locator("[data-role=siem-add]").click()
    expect(page.locator("[data-role=siem-needs-alert-mode]")).to_have_count(0)
    page.locator("input[name=siem_source_findings]").check()
    expect(page.locator("[data-role=siem-needs-alert-mode]")).to_be_visible()


def test_dlq_purge_asks_on_the_page_first(context, live_app):
    now = datetime(2026, 10, 31, 8, 0, tzinfo=UTC)
    with live_app.ctx.db() as conn:
        for i in range(3):
            store.quarantine(conn, destination_id=DEST, source="audit", record_id=i, external_id=f"audit:{i}",
                             event_time=now, payload=f"line {i}", sent_as="[]", error="refused: 400", attempts=1,
                             at=now)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/siem/dlq")
    rows = page.locator("[data-role=dlq-rows] tbody tr")
    expect(rows).to_have_count(3)
    rows.first.locator("input[type=checkbox]").check()
    page.locator("[data-role=dlq-purge]").click()
    expect(page.locator("[data-role=dlq-confirm]")).to_be_visible()
    expect(rows).to_have_count(3)  # nothing removed before confirming
    page.locator("[data-role=dlq-confirm-yes]").click()
    expect(rows).to_have_count(2)
    expect(page.locator("[data-role=dlq-done]")).to_contain_text("Purged 1.")


def _hec(**kw):
    base = {"id": DEST, "name": "splunk", "enabled": True, "transport": "hec", "format": "json",
            "host": "splunk.example", "port": 8088, "framing": "lf", "verify_tls": True, "hec_token": "HEC-TOKEN",
            "batch_size": 100, "max_retries": 10, "sources": ["audit"], "new_connection_decisions": [],
            "new_connection_internal_only": True, "mask_pii": False}
    base.update(kw)
    return base


def test_turning_certificate_verification_off_asks_and_then_warns(context, live_app):
    _set(live_app, lambda d: d["siem"].update(enabled=True, destinations=[_hec(transport="tls", port=6514,
                                                                                  hec_token="")]))
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/siem")
    card = page.locator("[data-role=siem-destination]")
    expect(card.locator("[data-role=siem-tls-warning]")).to_have_count(0)
    card.locator("input[name=siem_verify_tls]").uncheck()
    expect(card.locator("[data-role=siem-tls-warning]")).to_be_visible()
    page.get_by_role("button", name="Save").click()
    expect(page.locator("p.form-error")).to_contain_text("Certificate verification is off for splunk")
    assert live_app.ctx.settings.current().siem.destinations[0].verify_tls is True  # not saved yet
    page.locator("[data-role=siem-save-anyway]").click()
    expect(page.locator("p.form-ok[role=status]")).to_have_text("Saved.")
    assert live_app.ctx.settings.current().siem.destinations[0].verify_tls is False
    expect(page.locator("[data-role=siem-status] [data-role=siem-tls-unverified]")).to_be_visible()


def test_the_status_shows_the_last_day_and_week(context, live_app):
    from datetime import timedelta
    _set(live_app, lambda d: d["siem"].update(enabled=True, destinations=[_hec()]))
    now = datetime.now(UTC)
    with live_app.ctx.db() as conn:
        store.record_sends(conn, DEST, now - timedelta(minutes=5), sent=9, failed=1)
        store.record_sends(conn, DEST, now - timedelta(days=3), sent=1200)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/siem")
    status = page.locator("[data-role=siem-status]")
    expect(status.locator("[data-role=siem-rate-1h]")).to_have_text("Last hour: 90% went through (9 of 10 attempts)")
    expect(status.locator("[data-role=siem-sends-24h]")).to_have_text("Last 24 hours: sent 9, failed 1")
    expect(status.locator("[data-role=siem-sends-7d]")).to_have_text("Last 7 days: sent 1,209, failed 1")


def test_a_dlq_line_in_full_by_error_and_purged_by_age(context, live_app):
    from datetime import timedelta
    now = datetime.now(UTC)
    long_line = "y" * 900 + "TAIL"
    with live_app.ctx.db() as conn:
        for i, (error, days, payload) in enumerate([("refused: 413 too large", 40, long_line),
                                                    ("format: bad", 1, "short"), ("refused: 400", 2, "other")]):
            store.quarantine(conn, destination_id=DEST, source="audit", record_id=i, external_id=f"audit:{i}",
                             event_time=now, payload=payload, sent_as="[]", error=error, attempts=1,
                             at=now - timedelta(days=days))
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/siem/dlq")
    rows = page.locator("[data-role=dlq-rows] tbody tr")
    expect(rows).to_have_count(3)
    page.locator("input[name=dlq_error]").fill("413")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("first 300 of 904 characters")
    assert "error=413" in page.locator("[data-role=dlq-export]").get_attribute("href")
    rows.first.locator("[data-role=dlq-show]").click()
    expect(page.locator("[data-role=dlq-payload]")).to_have_text(long_line)
    page.locator("input[name=dlq_error]").fill("")
    expect(rows).to_have_count(3)
    page.locator("input[name=dlq_older_days]").fill("30")
    page.locator("[data-role=dlq-purge-older]").click()
    expect(page.locator("[data-role=dlq-confirm]")).to_contain_text("more than 30 days ago")
    page.locator("[data-role=dlq-confirm-yes]").click()
    expect(rows).to_have_count(2)
    expect(page.locator("[data-role=dlq-done]")).to_contain_text("Purged 1.")
