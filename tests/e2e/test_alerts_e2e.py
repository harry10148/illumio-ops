"""Alerts in a browser: the list with its delivery badges, the detail with the delivery state and notes, rules."""
from datetime import UTC, datetime

from playwright.sync_api import expect

from illumio_ops.domain.alerting import Confidence, Trigger
from illumio_ops.domain.values import AlertRuleType, DeliveryStatus, Severity
from illumio_ops.store import alerts as store
from tests.e2e.conftest import sign_in


def seed(ctx, *, channels=("line",), hold=None):
    now = datetime.now(UTC)
    t = Trigger(rule_id="a" * 32, rule_type=AlertRuleType.SYSTEM, subject_key="disk_low", severity=Severity.HIGH,
                first_seen=now, last_seen=now, late=False, message_key="alert_system_disk_low",
                params={"free": "1 GB", "warn": "10 GB"}, facts={}, evidence=None, confidence=Confidence())
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        return store.insert_alert(conn, pce_url=pce.url, org_id=pce.org_id, rule_name="", pack_key="rule_system_disk_low",
                                  trigger=t, at=now, channels=list(channels), hold=hold)


def test_alerts_nav_and_list(context, live_app):
    seed(live_app.ctx)
    seed(live_app.ctx, hold=DeliveryStatus.NOT_NOTIFIED)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.click("nav >> text=Alerts")
    table = page.locator("[data-role=alert-list]")
    expect(table.locator("[data-alert-id]")).to_have_count(2)
    expect(table).to_contain_text("Disk space is low: 1 GB left")
    expect(table.locator("[data-delivery=pending]")).to_have_text("LINE: waiting")
    expect(table.locator("[data-delivery=not_notified]")).to_have_text("recorded only (rule setting)")
    expect(page.locator("[data-role=alert-total]")).to_have_text("2 alerts")


def test_alert_detail_shows_delivery_status(context, live_app):
    a = seed(live_app.ctx)
    with live_app.ctx.db() as conn:
        ids = [d["id"] for d in store.deliveries(conn, [a])]
        store.mark_deliveries(conn, ids, status=DeliveryStatus.FAILED, attempts_add=3, next_attempt_at=None,
                              sent_at=None, error="status=401 rejected /v2/bot/... ")
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/{a}")
    d = page.locator("[data-role=deliveries]")
    expect(d.locator("[data-delivery=failed]")).to_contain_text("LINE: failed")
    expect(d).to_contain_text("3 attempt(s)")
    expect(d.locator("[data-role=delivery-error]")).to_contain_text("status=401")
    expect(page.locator("[data-role=alert-detail]")).to_contain_text("a system check")


def test_alert_note_persists(context, live_app):
    a = seed(live_app.ctx)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.click("nav >> text=Alerts")
    page.locator(f"[data-alert-id='{a}']").click()
    page.locator("[data-role=open-detail]").click()
    notes = page.locator("[data-role=notes]")
    notes.locator("textarea[name=note]").fill("Checked: the backup job filled the disk.")
    notes.get_by_role("button", name="Add note").click()
    expect(notes).to_contain_text("Checked: the backup job filled the disk.")
    page.reload()
    expect(page.locator("[data-role=notes]")).to_contain_text("Checked: the backup job filled the disk.")


def test_rule_create_traffic_with_condition(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/rules/new")
    form = page.locator("[data-role=rule-editor]")
    form.locator("select[name=type]").select_option("traffic")
    form.locator("input[name=name]").fill("SSH blocked")
    form.locator("input[name=ports]").fill("22")
    form.locator("input[name=ports]").blur()
    form.locator("input[name=decision_blocked]").check()
    form.get_by_role("button", name="Save").click()
    page.wait_for_selector("[data-role=rule-list]")
    expect(page.locator("[data-role=rule-list]")).to_contain_text("SSH blocked")
    mine = next(r for r in live_app.ctx.settings.current().alerts.rules if r.name == "SSH blocked")
    assert [p.port for p in mine.condition.ports] == [22] and [d.value for d in mine.condition.decisions] == ["blocked"]


def test_rule_traffic_exclusions_round_trip(context, live_app):
    """Task 9: each side can exclude addresses; saved, and shown again when the rule is opened (review: no
    control existed, and a migrated exclusion could not be seen)."""
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/rules/new")
    form = page.locator("[data-role=rule-editor]")
    form.locator("select[name=type]").select_option("traffic")
    form.locator("input[name=name]").fill("Blocked but not the scanner")
    form.locator("input[name=decision_blocked]").check()
    form.get_by_text("Exclusions").click()
    form.locator("input[name=src_exclude_ips]").fill("10.9.9.9")
    form.locator("input[name=src_exclude_ips]").blur()
    form.get_by_role("button", name="Save").click()
    page.wait_for_selector("[data-role=rule-list]")
    mine = next(r for r in live_app.ctx.settings.current().alerts.rules if r.name == "Blocked but not the scanner")
    assert mine.condition.src_exclude is not None and mine.condition.src_exclude.ips == ("10.9.9.9",)
    page.goto(f"{live_app.url}/alerts/rules/{mine.id}")
    expect(page.locator("input[name=src_exclude_ips]")).to_have_value("10.9.9.9")


def test_rule_lateral_exclusion_round_trip(context, live_app):
    """User 2026-10-31: a lateral rule leaves out the internet side by default, and an address or an IP list."""
    from datetime import UTC, datetime

    from illumio_ops.store.flowdb import ip_lists
    with live_app.ctx.flows().connect() as conn:
        ip_lists.replace_all(conn, [ip_lists.IpListRow("/orgs/1/sec_policy/active/ip_lists/7", "Scanners",
                                                       ("10.9.0.0/16",))], at=datetime(2026, 10, 31, tzinfo=UTC))
        conn.commit()
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/rules/new")
    form = page.locator("[data-role=rule-editor]")
    form.locator("select[name=type]").select_option("lateral")
    form.locator("input[name=name]").fill("Fan-out but not the scanner")
    side = form.locator("[data-side=exclude]")
    expect(side.locator("input[name=exclude_public]")).to_be_checked()
    expect(side).to_contain_text("does not alert")
    side.locator("input[name=exclude_ips]").fill("10.9.9.9")
    side.locator("input[name=exclude_ips]").blur()
    side.get_by_role("button", name="Add IP list").click()
    expect(side.locator("[data-ip-list]")).to_have_text("Scanners×")
    form.get_by_role("button", name="Save").click()
    page.wait_for_selector("[data-role=rule-list]")
    mine = next(r for r in live_app.ctx.settings.current().alerts.rules if r.name == "Fan-out but not the scanner")
    assert mine.exclude is not None and mine.exclude.public and mine.exclude.ips == ("10.9.9.9",)
    assert mine.exclude.ip_lists == ("/orgs/1/sec_policy/active/ip_lists/7",)
    page.goto(f"{live_app.url}/alerts/rules/{mine.id}")
    side = page.locator("[data-side=exclude]")
    expect(side.locator("input[name=exclude_ips]")).to_have_value("10.9.9.9")
    expect(side.locator("[data-ip-list]")).to_contain_text("Scanners")
    side.locator("[data-ip-list] button").click()
    side.locator("input[name=exclude_public]").uncheck()
    side.locator("input[name=exclude_ips]").fill("")
    side.locator("input[name=exclude_ips]").blur()
    page.locator("[data-role=rule-editor]").get_by_role("button", name="Save").click()
    page.wait_for_selector("[data-role=rule-list]")
    assert next(r for r in live_app.ctx.settings.current().alerts.rules if r.id == mine.id).exclude is None


def test_rule_event_match_fields_round_trip(context, live_app):
    """Task 9: an event rule's advanced field matches, one path=pattern per line (review: no control)."""
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/rules/new")
    form = page.locator("[data-role=rule-editor]")
    form.locator("input[name=name]").fill("Hard limit")
    form.locator("input[name=event_types]").fill("system_task.prune_old_log_events")
    form.get_by_text("Advanced: match event fields").click()
    form.locator("textarea[name=match_fields]").fill("notification_type=hard_limit.exceeded")
    form.locator("textarea[name=match_fields]").blur()
    form.get_by_role("button", name="Save").click()
    page.wait_for_selector("[data-role=rule-list]")
    mine = next(r for r in live_app.ctx.settings.current().alerts.rules if r.name == "Hard limit")
    assert dict(mine.match_fields) == {"notification_type": "hard_limit.exceeded"}
    page.goto(f"{live_app.url}/alerts/rules/{mine.id}")
    expect(page.locator("textarea[name=match_fields]")).to_have_value("notification_type=hard_limit.exceeded")


def test_rule_invalid_regex_field_error(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/rules/new")
    form = page.locator("[data-role=rule-editor]")
    form.locator("input[name=name]").fill("bad")
    form.locator("input[name=event_types]").fill("agent.(tampering")
    form.get_by_role("button", name="Save").click()
    err = form.locator(".form-error[data-field*=event_types]").first
    expect(err).to_be_visible()
    assert not [r for r in live_app.ctx.settings.current().alerts.rules if r.name == "bad"]


def test_pack_append_missing(context, live_app):
    from illumio_ops.domain.alertpack import pack_rule_id
    rid = pack_rule_id("rule_agent_clone")
    live_app.ctx.settings.update(live_app.ctx.settings.current().revision, lambda d: d["alerts"].__setitem__(
        "rules", [r for r in d["alerts"]["rules"] if r["id"] != rid]))
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/rules")
    pack = page.locator("[data-role=pack]")
    expect(pack).to_contain_text("1 built-in rule(s) were deleted.")
    pack.get_by_role("button", name="Add missing built-in rules").click()
    pack.get_by_role("button", name="Confirm").click()
    expect(page.locator(f"tr[data-rule-id='{rid}']")).to_contain_text("Agent Clone Detected")


def test_direct_link_detail_note(context, live_app):
    # An alert opened from a link (a notification, a bookmark) rather than from the list.
    a = seed(live_app.ctx)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/{a}")
    page.wait_for_load_state("networkidle")
    notes = page.locator("[data-role=notes]")
    notes.locator("textarea[name=note]").fill("Opened from a link.")
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/notes")) as resp:
        notes.get_by_role("button", name="Add note").click()
    assert resp.value.status == 200
    expect(notes).to_contain_text("Opened from a link.")


def test_lateral_alert_marked_known_then_removed(context, live_app):
    """Spec §6.5.8: mark a detection known from its alert; the mark is listed on the Lateral page and can be removed."""
    now = datetime.now(UTC)
    t = Trigger(rule_id="b" * 32, rule_type=AlertRuleType.LATERAL, subject_key="volume|/orgs/1/workloads/w1",
                severity=Severity.MEDIUM, first_seen=now, last_seen=now, late=False, message_key="focus_title_volume_surge",
                params={"detector": "volume_surge", "account": "/orgs/1/workloads/w1", "host": "w1",
                        "connections": 5000, "previous_max": 10}, facts={}, evidence=None, confidence=Confidence())
    pce = live_app.ctx.settings.current().pce
    with live_app.ctx.db() as conn:
        a = store.insert_alert(conn, pce_url=pce.url, org_id=pce.org_id, rule_name="", pack_key="rule_anomaly_volume",
                               trigger=t, at=now, channels=[], hold=None)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/{a}")
    form = page.locator("[data-role=mark-known]")
    form.locator("input[name=known_reason]").fill("Nightly backup host")
    form.get_by_label("Every detection of this kind about this host (or account)").check()
    form.get_by_role("button", name="Mark known").click()
    expect(form.locator(".form-ok")).to_have_text("Marked known.")
    page.click(".sidenav .nav-item[data-nav='/system']")
    page.click(".subnav >> a[href=\"/system/lateral\"]")
    known = page.locator("[data-role=known-detections]")
    expect(known).to_contain_text("Nightly backup host")
    expect(known).to_contain_text("every detection of this kind about /orgs/1/workloads/w1")
    known.get_by_role("button", name="Remove").click()
    expect(known).to_contain_text("No detection is marked known.")


# ── the alerts home page (UI redesign sample 01) ────────────────────────────

def _lateral(ctx, detector, *, subject="ip:10.0.0.9"):
    import json
    from datetime import timedelta

    from illumio_ops.store.flowdb import analysis
    from illumio_ops.store.flowdb.analysis import DetectionWrite
    now = datetime.now(UTC)
    with ctx.flows().connect() as conn:
        analysis.upsert_detections(conn, [DetectionWrite(
            detector=detector, fingerprint=f"{detector}|{subject}", subject_key=subject, severity="high",
            first_seen=now - timedelta(minutes=30), last_seen=now - timedelta(minutes=10), critical_asset=False,
            summary_json=json.dumps({"process": "psexesvc.exe", "port": 445, "target": "db-01"}),
            segment_json=json.dumps({"filter": {"start": (now - timedelta(hours=1)).isoformat(), "end": now.isoformat()},
                                     "view": "detail", "limit": 50}),
            confidence_json="{}")], dedup={detector: timedelta(hours=1)}, late=False, at=now)
        conn.commit()
        det = int(conn.execute("SELECT id FROM detections WHERE fingerprint = ?", (f"{detector}|{subject}",))
                  .fetchone()[0])
    t = Trigger(rule_id="b" * 32, rule_type=AlertRuleType.LATERAL, subject_key=f"{detector}|{subject}",
                severity=Severity.HIGH, first_seen=now, last_seen=now, late=False,
                message_key="focus_title_new_process",
                params={"detector": detector, "host": "10.0.0.9", "process": "psexesvc.exe", "port": 445,
                        "target": "db-01"},
                facts={"detection_id": det}, evidence=None, confidence=Confidence())
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        return store.insert_alert(conn, pce_url=pce.url, org_id=pce.org_id, rule_name="", pack_key=None, trigger=t,
                                  at=now, channels=["line"], hold=None)


def test_home_is_alerts(context, live_app):
    seed(live_app.ctx)
    page = context.new_page()
    sign_in(page, live_app.url)
    expect(page.locator("[data-role=alerts-home]")).to_have_count(1)
    expect(page.locator("[data-role=kpi-strip] [data-kpi=high] .kpi-value")).to_have_text("1")
    expect(page.locator("[data-role=alert-side] [data-role=alert-summary]")).to_contain_text("Disk space is low")


def test_old_alerts_url_redirects(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts?days=30")
    page.wait_for_url(f"{live_app.url}/?days=30")
    expect(page.locator("[data-role=alerts-home]")).to_have_count(1)


def test_category_filter(context, live_app):
    seed(live_app.ctx)
    _lateral(live_app.ctx, "new_process")
    page = context.new_page()
    sign_in(page, live_app.url)
    table = page.locator("[data-role=alert-list]")
    expect(table.locator("[data-alert-id]")).to_have_count(2)
    page.click("[data-category=anomaly]")
    expect(table.locator("[data-alert-id]")).to_have_count(1)
    expect(table).to_contain_text("Allowed-traffic anomaly")
    page.click("[data-category=system]")
    expect(table).to_contain_text("Disk space is low")


def test_no_quarantine_button_for_unmanaged(context, live_app):
    _lateral(live_app.ctx, "new_process", subject="ip:10.0.0.9")
    page = context.new_page()
    sign_in(page, live_app.url)
    side = page.locator("[data-role=alert-side]")
    expect(side.locator("[data-role=quarantine-reason]")).to_contain_text("not a managed host")
    expect(side.locator("[data-role=quarantine]")).to_have_count(0)
    expect(side.locator("[data-role=beyond]")).to_contain_text("psexesvc.exe")
    expect(side.locator("[data-role=timeline] li")).not_to_have_count(0)


def test_detail_below_list_at_760(narrow_context, live_app):
    from tests.e2e.conftest import no_horizontal_overflow
    seed(live_app.ctx)
    page = narrow_context.new_page()
    sign_in(page, live_app.url)
    side = page.locator("[data-role=alert-side]")
    side.wait_for()
    table_box = page.locator("[data-role=alert-list]").bounding_box()
    side_box = side.bounding_box()
    assert table_box and side_box and side_box["y"] > table_box["y"] + table_box["height"] - 1
    assert no_horizontal_overflow(page)


# ── alert rules and notifications (UI redesign sample 10) ───────────────────

def test_rules_tab_columns(context, live_app):
    seed(live_app.ctx)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.click(".sidenav .nav-item[data-nav='/alert-rules']")
    table = page.locator("[data-role=rule-list]")
    expect(table).to_contain_text("Triggers (7 days)")
    row = table.locator(f"tr[data-rule-id='{'a' * 32}'] [data-role=fired-7d]")
    expect(row).to_have_count(0)  # the seeded alert's rule id is not a configured rule
    expect(table.locator("[data-role=fired-7d]").first).to_have_text("0")


def test_rule_test_shows_matches(context, live_app):
    _lateral(live_app.ctx, "new_process")
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules")
    select = page.locator("select[name=rule_test_record]")
    select.locator("option").nth(1).wait_for(state="attached")
    value = select.locator("option").nth(1).get_attribute("value")
    select.select_option(value)
    panel = page.locator("[data-role=rule-test]")
    expect(panel.locator("[data-role=verdict]").first).to_be_visible()
    assert panel.locator("[data-role=verdict]").count() >= 1


def test_channels_tab(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?tab=channels")
    expect(page.locator("[data-role=channels]")).to_have_count(1)


def test_old_rule_and_channel_urls_redirect(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/rules")
    page.wait_for_url(f"{live_app.url}/alert-rules")
    page.goto(f"{live_app.url}/system/channels")
    page.wait_for_url(f"{live_app.url}/alert-rules?tab=channels")


def test_rules_no_overflow_760(narrow_context, live_app):
    from tests.e2e.conftest import no_horizontal_overflow
    page = narrow_context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules")
    page.locator("[data-role=rule-list]").wait_for()
    assert no_horizontal_overflow(page)


def test_late_detail_does_not_replace_the_selected_one(context, live_app, monkeypatch):
    """Codex review: a slow answer for the alert left behind must not overwrite the one now selected."""
    import time

    from illumio_ops.services.alerts import views
    seed(live_app.ctx)
    newer = _lateral(live_app.ctx, "new_process")
    real = views.alert_detail

    def slow(ctx, alert_id):
        if alert_id == newer:
            time.sleep(1.5)  # the first selected (newest) answers late; the server serves the others meanwhile
        return real(ctx, alert_id)
    monkeypatch.setattr("illumio_ops.web.routes.alerts.views.alert_detail", slow)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.locator("[data-alert-id]").nth(1).click()  # the disk alert, while the first is still loading
    side = page.locator("[data-role=alert-side] [data-role=alert-summary]")
    expect(side).to_contain_text("Disk space is low")
    page.wait_for_timeout(2500)
    expect(side).to_contain_text("Disk space is low", timeout=100)
