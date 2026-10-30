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


def test_long_list_shows_the_top_first(context, live_app):
    """Lab acceptance 2026-10-30: 117 items (102 detections) listed at once; the top 10 come first, the rest on
    request, and the page says how many there are."""
    now = datetime.now(UTC)
    items = [{"kind": "detection", "fingerprint": f"det|{i}", "severity": "medium", "critical_asset": False,
              "confidence": "high", "title_key": "focus_title_fanout", "why_key": "focus_why_detection",
              "params": {"host": f"h{i}", "minutes": 10, "targets": 5},
              "action": {"target": "alerts", "segment": None, "host_key": None}, "score": 1.0,
              "first_seen": now.isoformat(), "new_this_week": True, "weeks_persisting": 0} for i in range(12)]
    with live_app.ctx.flows().connect() as conn:
        analysis.write_result(conn, "focus", params={}, result={
            "computed_at": now.isoformat(), "items": items, "sources_status": {},
            "detections": {"total": 12, "considered": 12}, "traffic_computed_at": None}, at=now)
        conn.commit()
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/")
    expect(page.locator(".focus-item")).to_have_count(10)
    page.click("[data-role=focus-more]")
    expect(page.locator(".focus-item")).to_have_count(12)


def _write(live_app, *, at, items=(), detections=None):
    with live_app.ctx.flows().connect() as conn:
        analysis.write_result(conn, "focus", params={}, result={
            "computed_at": at.isoformat(), "items": list(items), "sources_status": {},
            "detections": detections or {"total": 0, "considered": 0}, "traffic_computed_at": None}, at=at)
        conn.commit()


def test_stale_empty_list_is_not_all_clear(context, live_app):
    """Final review #6: an empty list the hourly run stopped updating is not "nothing to look at"."""
    from datetime import timedelta
    _write(live_app, at=datetime.now(UTC) - timedelta(hours=3), detections={"total": 600, "considered": 500})
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/")
    expect(page.locator("[data-role=focus-detections-capped]")).to_have_count(1)  # final review #7
    expect(page.locator("[data-role=focus] p.muted")).to_have_count(0)


def test_page_mounted_once_when_languages_differ(context, live_app):
    """Lab acceptance 2026-10-30 (P6c): with the browser in English and the display language Chinese, the shell drew
    the page in English and mounted it again once the Chinese words arrived — every first query ran twice, and an
    action started on the first mount (the lateral page's compute) lost its answer."""
    live_app.ctx.settings.update(live_app.ctx.settings.current().revision,
                                 lambda d: d["display"].update(language="zh_TW"))
    page = context.new_page()
    sign_in(page, live_app.url)
    asked = []
    page.on("request", lambda r: asked.append(r.url) if r.url.endswith("/api/lateral") else None)
    page.goto(f"{live_app.url}/lateral")
    expect(page.locator("h1")).to_have_text("橫向移動")
    page.wait_for_timeout(1000)
    assert len(asked) == 1
