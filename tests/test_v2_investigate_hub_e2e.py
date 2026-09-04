"""Phase 3B Task 6 — the investigate hub (spec §3).

Alert inbox (IN-01), status toggle (IN-02), alert detail (IN-03), the
alert-scoped traffic page with its context strip (IN-04), the rule panel
(IN-05) and its action row (IN-06). Runs against the in-process GUI with an
isolated alert store; the PCE is never reached (rule explain falls back to
its error path, which still renders the panel and actions).
"""
import pytest

pytest_plugins = ["tests.v2_e2e_utils"]

INBOX = "#/investigate/inbox"
TRAFFIC = "#/investigate/traffic"


def _goto(page, base_url, route, cov):
    page.goto(base_url + "/" + route)
    page.wait_for_selector(f'[data-cov="{cov}"]', timeout=15000)


def _seed(path, v2_app):
    """One traffic alert whose rule still exists, one event alert."""
    from src.alerts.store import AlertStore
    cm = v2_app.config["CM"]
    cm.config["rules"] = [{
        "id": "t1", "name": "SSH in", "type": "traffic", "enabled": True,
        "pd": "1", "threshold_window": "1440", "filters": {"port": "22"}, "dst_label": "role:db",
    }]
    cm.save()
    st = AlertStore(path)
    a = st.insert(fired_at="2026-09-04T01:00:00Z", type="traffic", rule_id="t1", rule_name="SSH in",
                  severity="warning", summary="SSH in · 24 flows", criteria="port 22",
                  payload={"raw_data": [{"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 22}]},
                  dispatch=[{"channel": "mail", "status": "success"}])
    b = st.insert(fired_at="2026-09-04T01:01:00Z", type="event", rule_id="18", rule_name="Login failed",
                  severity="critical", summary="Login failed · x", criteria="", payload={}, dispatch=[])
    st.close()
    return a, b


def _alert(page, base_url, alert_id):
    return page.request.get(f"{base_url}/api/alerts/{alert_id}").json()["alert"]


def test_inbox_lists_alerts_opens_detail_and_toggles_status(v2_page, v2_app, _isolate_alert_store):
    a, b = _seed(_isolate_alert_store, v2_app)
    page, base_url = v2_page
    page.reload()
    _goto(page, base_url, INBOX, "IN-01")
    links = page.locator(f'[data-cov="IN-01"] a[href="{INBOX}?id={a}"]')
    assert links.count() >= 1
    assert page.locator(f'[data-cov="IN-01"] a[href="{INBOX}?id={b}"]').count() >= 1
    links.first.click()
    page.wait_for_selector('[data-cov="IN-03"]')
    detail = page.locator('[data-cov="IN-03"]')
    assert "SSH in" in detail.text_content()
    assert "port 22" in detail.text_content()
    assert "mail" in detail.text_content()
    # IN-02: the middle segment is "ack"; the PATCH lands in the store
    page.locator('[data-cov="IN-02"] .hubseg button').nth(1).click()
    page.wait_for_selector('[data-cov="IN-02"] .hubseg button:nth-child(2)[aria-pressed="true"]')
    assert _alert(page, base_url, a)["status"] == "ack"


def test_see_traffic_scopes_the_traffic_page_and_prefills_the_query(v2_page, v2_app, _isolate_alert_store):
    a, _ = _seed(_isolate_alert_store, v2_app)
    page, base_url = v2_page
    page.reload()
    _goto(page, base_url, f"{INBOX}?id={a}", "IN-03")
    with page.expect_request("**/api/quarantine/search") as req:
        page.locator('[data-cov="IN-03"] .hubactions .btn.primary').click()
    page.wait_for_selector('[data-cov="IN-04"]')
    assert f"{TRAFFIC}?alert={a}" in page.url
    strip = page.locator('[data-cov="IN-04"]')
    assert "SSH in" in strip.text_content()
    assert "3" in strip.locator('.stepper li[data-active="true"]').text_content()
    body = req.value.post_data_json
    assert body["policy_decision"] == "1"
    assert body["mins"] == 1440
    assert body["sort_by"] == "connections"
    assert "22" in req.value.post_data and "role:db" in req.value.post_data
    strip.locator("a.back").click()
    page.wait_for_selector('[data-cov="IN-03"]')


def test_event_alert_on_traffic_page_explains_why_nothing_is_prefilled(v2_page, v2_app, _isolate_alert_store):
    _, b = _seed(_isolate_alert_store, v2_app)
    page, base_url = v2_page
    page.reload()
    _goto(page, base_url, f"{TRAFFIC}?alert={b}", "IN-04")
    reason = page.locator('[data-cov="IN-04"] .meta[data-tone="warn"]')
    assert reason.is_visible()
    assert "Login failed" in page.locator('[data-cov="IN-04"]').text_content()


def test_rule_panel_opens_with_actions_and_marks_the_alert_done(v2_page, v2_app, _isolate_alert_store):
    a, _ = _seed(_isolate_alert_store, v2_app)
    page, base_url = v2_page
    page.reload()
    _goto(page, base_url, f"{TRAFFIC}?alert={a}", "IN-04")
    # the strip paints before the traffic board; the explain opener is only
    # wired once the board (and its rankings row) is up
    page.wait_for_selector('[data-cov="OV-04"]')
    # the coverage gate's opener explains a synthetic flow; same path a row's
    # "Rules" button takes
    page.evaluate("window.__openAllForAudit()")
    page.wait_for_selector('[data-cov="IN-05"]')
    page.wait_for_selector('[data-cov="IN-06"]')
    actions = page.locator('[data-cov="IN-06"]')
    assert actions.locator("button").count() >= 1
    # the audit opener also opened every drawer; click through the DOM instead
    actions.locator("button").last.evaluate("b => b.click()")
    page.wait_for_function(
        "() => document.querySelector('[data-cov=\"IN-04\"]').textContent.toLowerCase().includes('done')")
    assert _alert(page, base_url, a)["status"] == "done"
    # the detail page must not serve the cached "new" record
    page.locator('[data-cov="IN-04"] a.back').evaluate("a => a.click()")
    page.wait_for_selector('[data-cov="IN-02"] .hubseg button:nth-child(3)[aria-pressed="true"]')


def test_f_link_prefills_the_query_without_an_alert(v2_page):
    """spec §3: #/investigate/traffic?f=<urlsafe-base64 JSON> is the general
    hand-off into a scoped traffic query."""
    import base64, json
    page, base_url = v2_page
    f = base64.urlsafe_b64encode(json.dumps({"pd": "0", "threshold_window": "1440", "filters": {"port": "3389"}}).encode()).decode().rstrip("=")
    with page.expect_request("**/api/quarantine/search") as req:
        _goto(page, base_url, f"{TRAFFIC}?f={f}", "IN-04")
    body = req.value.post_data_json
    assert body["policy_decision"] == "0" and body["mins"] == 1440
    assert "3389" in req.value.post_data
    assert page.locator('[data-cov="IN-04"] .stepper').count() == 0
