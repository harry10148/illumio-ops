"""What the rule checker cannot measure about buttons, tags and type (purpose-led UI spec §5.1–§5.3): where the
reason for an action goes, which values are set in monospace."""
from playwright.sync_api import expect

from tests.e2e import test_alerts_e2e as alerts_e2e
from tests.e2e import test_hosts_e2e as hosts_e2e
from tests.e2e.conftest import sign_in

MONO = "JetBrains Mono"


def _family(locator) -> str:
    return str(locator.evaluate("(e) => getComputedStyle(e).fontFamily"))


def test_why_quarantine_would_do_nothing_is_under_the_button_not_in_it(context, live_app):
    hosts_e2e._seed(live_app)  # db: a managed host in Visibility Only
    alerts_e2e._lateral(live_app.ctx, "new_process", subject=hosts_e2e.DB)
    page = context.new_page()
    sign_in(page, live_app.url)
    side = page.locator("[data-role=alert-side]")
    button = side.locator("[data-role=quarantine]")
    expect(button).to_have_text("Quarantine")
    note = side.locator("[data-role=action-note]")
    expect(note).to_contain_text("no effect")
    assert note.bounding_box()["y"] >= button.bounding_box()["y"] + button.bounding_box()["height"] - 1


def test_times_and_counts_are_in_the_reading_face(context, live_app):
    alerts_e2e.seed(live_app.ctx)
    page = context.new_page()
    sign_in(page, live_app.url)
    row = page.locator("[data-role=alert-list] tbody tr").first
    expect(row).to_be_visible()
    assert MONO not in _family(row.locator("td").first)
    assert MONO not in _family(page.locator(".kpi-value").first)
    assert MONO not in _family(page.locator("[data-role=alert-side] [data-role=timeline] li span").first)


def test_an_address_is_monospace_and_a_host_name_is_not(context, live_app):
    alerts_e2e._lateral(live_app.ctx, "new_process", subject="ip:10.0.0.9")  # names its source 10.0.0.9, its target db-01
    page = context.new_page()
    sign_in(page, live_app.url)
    ends = page.locator("[data-role=alert-list] tbody tr").first.locator("td").nth(3)
    expect(ends).to_contain_text("10.0.0.9")
    address = ends.locator("[data-role=address]")
    expect(address).to_have_text("10.0.0.9")
    assert MONO in _family(address)
    assert MONO not in _family(ends)


def test_recorded_only_is_said_in_words_not_as_a_tag(context, live_app):
    from illumio_ops.domain.values import DeliveryStatus
    alerts_e2e.seed(live_app.ctx, hold=DeliveryStatus.NOT_NOTIFIED)
    page = context.new_page()
    sign_in(page, live_app.url)
    cell = page.locator("[data-role=alert-list] [data-delivery=not_notified]")
    expect(cell).to_have_text("recorded only (rule setting)")
    expect(cell.locator(".tag")).to_have_count(0)
    assert page.locator("[data-role=alert-list] [data-delivery=not_notified].tag").count() == 0
