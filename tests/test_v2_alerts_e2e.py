"""v3.1 §3 — the alert list and the alert page.

Spec: docs/superpowers/specs/2026-09-04-ui-redesign-v3-1-workbench-design.md
§1.1 (routes), §3 (the alert page). Replaces
tests/test_v2_investigate_hub_e2e.py, which covered 3B's inbox-and-stepper
flow: the user ruled that flow out ("不需要收件匣與事件調查流程，只要能檢視最近
的告警"), so the inbox, the five-step stepper, the traffic page's context strip
and its per-row "see rules" button are gone, and with them IN-01..06.

What replaces them, and where each lives (design/v3/coverage.yaml):

  AT-01  the list at #/investigate/alerts — one row per alert, severity
         stripe, time, one sentence, status chip; the row opens the alert.
  AT-02  the status control on the alert page, and the PATCH behind it.
  AT-03  the alert page itself: a title that says what happened, then
         "what happened / who was talking / what to do".
  AT-04  the rule column — the page asks the PCE about the first N flows on
         load and fills each row in as the answer arrives.
  AT-05  the action row.

Runs against the in-process GUI with an isolated alert store. The PCE is
never reached, so every explain answers with its error path — which is
itself part of what AT-04 asserts: a flow the PCE could not answer for says
so, in its own row, and does not take the other rows down with it.

Flow rows come from design/v2/snapshots/traffic_search.json, the frozen
capture of a real PCE response. Hand-written flows would let the page pass
against a shape the product never produces (Global Constraints: 資料與文案
來自原始碼與快照; mockup／測試資料禁手寫).
"""
from __future__ import annotations

import json
import pathlib

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

pytest_plugins = ["tests.v2_e2e_utils"]

ROOT = pathlib.Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "design" / "v2" / "snapshots" / "traffic_search.json"

ALERTS = "#/investigate/alerts"
INBOX = "#/investigate/inbox"
TRAFFIC = "#/investigate/traffic"

# spec §3: the page asks the PCE about the first N flows. N is the product's
# own default; the seed carries exactly that many so "one chip per flow" and
# "one chip per asked flow" cannot be confused for one another.
EXPLAIN_N = 8

# The connection total the rule fired on — larger than the sum over the eight
# flows the payload keeps, exactly as a real alert's is.
FIRED_COUNT = 99999


def _flows(n=EXPLAIN_N):
    """`n` real flow rows from the frozen traffic capture."""
    rows = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["data"]
    assert len(rows) >= n, len(rows)
    return rows[:n]


def _seed(path, v2_app):
    """One traffic alert carrying real flows, and one event alert."""
    from src.alerts.store import AlertStore

    cm = v2_app.config["CM"]
    cm.config["rules"] = [{
        "id": "t1", "name": "SSH in", "type": "traffic", "enabled": True,
        "pd": "1", "threshold_window": "1440", "filters": {"port": "22"}, "dst_label": "role:db",
    }]
    cm.save()
    flows = _flows()
    st = AlertStore(path)
    traffic = st.insert(
        fired_at="2026-09-04T01:00:00Z", type="traffic", rule_id="t1", rule_name="SSH in",
        severity="warning", summary="SSH in · 24 flows", criteria="port 22",
        # count is DELIBERATELY larger than the flows sum: the analyzer keeps
        # only the top matches in raw_data but counts every matching flow into
        # `count`, so the two differ on any real alert with more than
        # TOP_MATCHES_LIMIT flows. The page must read the count.
        payload={"raw_data": flows, "count": str(FIRED_COUNT)},
        dispatch=[{"channel": "mail", "status": "success"}],
    )
    event = st.insert(
        fired_at="2026-09-04T01:01:00Z", type="event", rule_id="18", rule_name="Login failed",
        severity="critical", summary="Login failed · x",
        criteria="", payload={"parsed_data": [{
            "actor": "user@example.com", "action": "DELETE /rule_sets/669",
            "resource_name": "prod-ruleset", "event_type": "rule_set.delete",
        }]}, dispatch=[],
    )
    st.close()
    return traffic, event


def _open_list(page, base_url):
    page.goto(base_url + "/" + ALERTS)
    page.wait_for_selector('[data-cov="AT-01"]', timeout=20000)


def _open_alert(page, base_url, alert_id):
    page.goto(base_url + "/" + ALERTS + "?id=" + str(alert_id))
    page.wait_for_selector('[data-cov="AT-03"]', timeout=20000)


def _alert(page, base_url, alert_id):
    return page.request.get(f"{base_url}/api/alerts/{alert_id}").json()["alert"]


# ── AT-01 · the list ────────────────────────────────────────────────────────

def test_the_list_is_rows_not_a_table_and_each_row_opens_its_alert(v2_page, v2_app, _isolate_alert_store):
    traffic, event = _seed(_isolate_alert_store, v2_app)
    page, base_url = v2_page
    page.reload()
    _open_list(page, base_url)

    rows = page.locator('[data-cov="AT-01"] a.lrow')
    assert rows.count() == 2
    hrefs = [rows.nth(i).get_attribute("href") for i in range(2)]
    assert f"{ALERTS}?id={traffic}" in hrefs
    assert f"{ALERTS}?id={event}" in hrefs
    # §5.1: a severity stripe and a status chip on every row, not a column wall
    assert page.locator('[data-cov="AT-01"] a.lrow .stripe').count() == 2
    assert page.locator('[data-cov="AT-01"] a.lrow .chip').count() == 2
    # §5.1: the footer carries the count and a secondary link, not pagination
    # chrome pretending to be content
    assert page.locator('[data-cov="AT-01"] .lfoot').count() == 1

    page.locator(f'[data-cov="AT-01"] a.lrow[href="{ALERTS}?id={traffic}"]').click()
    page.wait_for_selector('[data-cov="AT-03"]')


# ── AT-03 · the alert page ──────────────────────────────────────────────────

def test_the_alert_page_headline_says_what_happened(v2_page, v2_app, _isolate_alert_store):
    traffic, _ = _seed(_isolate_alert_store, v2_app)
    page, base_url = v2_page
    page.reload()
    _open_alert(page, base_url, traffic)

    # spec §3: "{scope} {what}" — the headline carries the alert's own numbers,
    # not the word "Alert" and an id. The number is payload.count, the figure
    # the rule fired on, NOT the sum over the sample of flows the payload
    # keeps: raw_data is top_matches[:LIMIT] and understates the total.
    head = page.locator(".workarea .phead h2").inner_text()
    assert "SSH in" in head, head
    assert "99,999" in head or "99999" in head, head
    flow_sum = sum(f["num_connections"] for f in _flows())
    assert str(flow_sum) not in head, (head, flow_sum)
    # ...and the three sections the spec fixes the order of.
    assert page.locator('[data-cov="AT-03"] .sect').count() >= 3
    # the collapsed "more" block holds the dispatch record, not the page body
    assert page.locator('[data-cov="AT-03"] details.more').count() == 1
    assert "mail" in page.locator('[data-cov="AT-03"] details.more').text_content()


def test_an_event_alert_has_no_flow_table_and_lists_its_actor_and_action(v2_page, v2_app, _isolate_alert_store):
    _, event = _seed(_isolate_alert_store, v2_app)
    page, base_url = v2_page
    page.reload()
    _open_alert(page, base_url, event)

    assert page.locator('[data-cov="AT-04"]').count() == 0
    body = page.locator('[data-cov="AT-03"]').text_content()
    assert "user@example.com" in body
    assert "prod-ruleset" in body


# ── AT-04 · the rule column ─────────────────────────────────────────────────

def test_every_asked_flow_gets_a_verdict_even_when_the_pce_answers_none(v2_page, v2_app, _isolate_alert_store):
    """The PCE is unreachable here, so every explain fails.

    That is the case worth pinning: the verdicts are fetched in parallel and
    filled in per row, so one failure must not empty the table or stop the
    others — each row says the PCE did not answer, and the count still
    matches the number of flows asked about.
    """
    traffic, _ = _seed(_isolate_alert_store, v2_app)
    page, base_url = v2_page
    page.reload()
    _open_alert(page, base_url, traffic)

    table = page.locator('[data-cov="AT-04"]')
    assert table.count() == 1
    page.wait_for_function(
        "n => document.querySelectorAll('[data-cov=\"AT-04\"] tbody .chip').length === n",
        arg=EXPLAIN_N,
        timeout=30000,
    )
    assert table.locator("tbody tr").count() == EXPLAIN_N


# ── AT-02 / AT-05 · status and actions ──────────────────────────────────────

def test_marking_the_alert_done_reaches_the_store_and_survives_a_reopen(v2_page, v2_app, _isolate_alert_store):
    """The PATCH lands, the page reflects it, and coming back does not serve
    the cached "new" record.

    That last clause is a real regression, found once already in 3B: api.load
    caches per (id, params), so a status write that does not invalidate the
    alert's own entry leaves the next visit showing the old status.
    """
    traffic, _ = _seed(_isolate_alert_store, v2_app)
    page, base_url = v2_page
    page.reload()
    _open_alert(page, base_url, traffic)

    actions = page.locator('[data-cov="AT-05"]')
    assert actions.locator("button").count() >= 2

    page.locator('[data-cov="AT-02"] button[data-status="done"]').click()
    page.wait_for_selector('[data-cov="AT-02"] button[data-status="done"][aria-pressed="true"]')
    assert _alert(page, base_url, traffic)["status"] == "done"

    _open_list(page, base_url)
    _open_alert(page, base_url, traffic)
    assert page.locator('[data-cov="AT-02"] button[data-status="done"]').get_attribute("aria-pressed") == "true"


# ── §1.1 · routing ──────────────────────────────────────────────────────────

def test_the_old_inbox_hash_redirects_and_keeps_its_query(v2_page, v2_app, _isolate_alert_store):
    traffic, _ = _seed(_isolate_alert_store, v2_app)
    page, base_url = v2_page
    page.reload()
    page.goto(f"{base_url}/{INBOX}?id={traffic}")
    page.wait_for_function(
        "want => location.hash.indexOf(want) === 0",
        arg=ALERTS,
        timeout=20000,
    )
    assert f"id={traffic}" in page.url
    page.wait_for_selector('[data-cov="AT-03"]')


def test_the_traffic_page_still_prefills_from_an_alert_without_a_context_strip(v2_page, v2_app, _isolate_alert_store):
    """§1.1: `?alert=` survives as "open this query in traffic search".

    What is gone is the strip, the stepper and the flow back into an
    investigation. The page says in one line where its filters came from and
    links back to the alert, and it still runs the query.
    """
    traffic, _ = _seed(_isolate_alert_store, v2_app)
    page, base_url = v2_page
    page.reload()
    with page.expect_request("**/api/quarantine/search") as req:
        page.goto(f"{base_url}/{TRAFFIC}?alert={traffic}")
        page.wait_for_selector('.workarea .phead[data-route="%s"] h2' % TRAFFIC, timeout=20000)

    assert page.locator(".ctxstrip, .stepper").count() == 0
    sub = page.locator(".workarea .phead p").inner_text()
    assert "SSH in" in sub, sub
    assert page.locator('.workarea .phead a[href^="%s?id=%s"]' % (ALERTS, traffic)).count() == 1

    body = req.value.post_data_json
    assert body["policy_decision"] == "1"
    assert body["mins"] == 1440
    assert "22" in req.value.post_data and "role:db" in req.value.post_data


def test_an_f_link_still_prefills_the_query_without_an_alert(v2_page):
    """§1.1: `?f=<urlsafe-base64 JSON>` is the general hand-off, alert or not."""
    import base64

    page, base_url = v2_page
    f = base64.urlsafe_b64encode(json.dumps(
        {"pd": "0", "threshold_window": "1440", "filters": {"port": "3389"}}
    ).encode()).decode().rstrip("=")
    with page.expect_request("**/api/quarantine/search") as req:
        page.goto(f"{base_url}/{TRAFFIC}?f={f}")
        page.wait_for_selector('.workarea .phead[data-route="%s"] h2' % TRAFFIC, timeout=20000)

    body = req.value.post_data_json
    assert body["policy_decision"] == "0" and body["mins"] == 1440
    assert "3389" in req.value.post_data
    assert page.locator(".stepper").count() == 0
