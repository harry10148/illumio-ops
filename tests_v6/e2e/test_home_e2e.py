"""Home focus list in a browser (P6b): items with their reason and where they lead; not computed is said."""
from datetime import UTC, datetime

from playwright.sync_api import expect

from illumio_ops.store.flowdb import analysis
from tests_v6.e2e.conftest import sign_in


def test_focus_not_computed_then_items(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/")
    expect(page.locator("[data-role=focus-not-computed]")).to_have_count(1)

    now = datetime.now(UTC)
    item = {"kind": "tamper", "fingerprint": "tamper|/orgs/1/workloads/w1", "severity": "high", "critical_asset": False,
            "confidence": "high", "title_key": "focus_title_tamper", "why_key": "focus_why_tamper",
            "params": {"host": "web01", "count": 4, "pattern": "burst"},
            "action": {"target": "host", "segment": None, "host_key": "/orgs/1/workloads/w1"}, "score": 3.0,
            "first_seen": now.isoformat(), "new_this_week": True, "weeks_persisting": 0}
    with live_app.ctx.flows().connect() as conn:
        analysis.write_result(conn, "focus", params={}, result={
            "computed_at": now.isoformat(), "items": [item], "sources_status": {"exposure": "error: Boom", "tamper": "ok"},
            "detections": {"total": 0, "considered": 0}, "traffic_computed_at": None}, at=now)
        conn.commit()
    page.reload()
    entry = page.locator(".focus-item[data-kind=tamper]")
    expect(entry).to_have_count(1)
    assert "web01" in entry.inner_text() and "(burst)" not in entry.inner_text()  # the pattern is words
    assert entry.locator("[data-role=focus-link]").get_attribute("href").startswith("/hosts?key=")
    expect(page.locator("[data-role=focus-sources] li")).to_have_count(1)  # the failed exposure source is said
