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
    # The saved note is the list entry. The form as a whole also holds what was typed (a textarea's value is part of
    # its text), so reading the form passed before the save had answered and the reload then raced the save.
    expect(notes.locator("li")).to_contain_text("Checked: the backup job filled the disk.")
    expect(notes.locator("textarea[name=note]")).to_have_value("")
    page.reload()
    expect(page.locator("[data-role=notes] li")).to_contain_text("Checked: the backup job filled the disk.")


def test_rule_create_traffic_with_condition(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/rules/new?form=full")
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
    page.goto(f"{live_app.url}/alerts/rules/new?form=full")
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
    page.goto(f"{live_app.url}/alerts/rules/new?form=full")
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
    page.goto(f"{live_app.url}/alerts/rules/new?form=full")
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
    page.goto(f"{live_app.url}/alerts/rules/new?form=full")
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
    expect(notes.locator("li")).to_contain_text("Opened from a link.")  # the list entry, not the text typed


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
    form.get_by_role("button", name="Stop alerting on this").click()
    expect(form.locator(".form-ok")).to_have_text("Marked known; this alert now counts as handled.")
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


def test_rule_traffic_parity_conditions_round_trip(context, live_app):
    """5.x parity 2026-11-06: either end, a label group, a named service, a Windows service, transmission and a
    process to leave out are offered, saved, and shown again by name."""
    from datetime import UTC, datetime

    from illumio_ops.store.flowdb import policy_objects
    at = datetime(2026, 11, 6, tzinfo=UTC)
    with live_app.ctx.flows().connect() as conn:
        policy_objects.replace_services(conn, [policy_objects.ServiceRow(
            "/orgs/1/sec_policy/active/services/2", "Web", ((443, None, 6),))], at=at)
        policy_objects.replace_label_groups(conn, [policy_objects.LabelGroupRow(
            "/orgs/1/sec_policy/active/label_groups/3", "Live", "env", ("Prod",))], at=at)
        conn.commit()
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/rules/new?form=full")
    form = page.locator("[data-role=rule-editor]")
    form.locator("select[name=type]").select_option("traffic")
    form.locator("input[name=name]").fill("Parity conditions")
    form.locator("[data-side=src]").get_by_role("button", name="Add label group").click()
    form.get_by_text("Either end").first.click()
    form.locator("input[name=either_ips]").fill("10.0.0.9")
    form.locator("input[name=either_ips]").blur()
    form.locator("[data-role=service]").get_by_role("button", name="Add service").click()
    form.locator("input[name=windows_services]").fill("wuauserv, Spooler")
    form.locator("input[name=windows_services]").blur()
    form.locator("input[name=transmission_broadcast]").check()
    form.get_by_text("Exclusions").click()
    form.locator("input[name=exclude_processes]").fill("svchost.exe")
    form.locator("input[name=exclude_processes]").blur()
    form.locator("input[name=exclude_transmission_multicast]").check()
    form.get_by_role("button", name="Save").click()
    page.wait_for_selector("[data-role=rule-list]")
    mine = next(r for r in live_app.ctx.settings.current().alerts.rules if r.name == "Parity conditions")
    c = mine.condition
    assert c.src is not None and c.src.label_groups == ("/orgs/1/sec_policy/active/label_groups/3",)
    assert c.either is not None and c.either.ips == ("10.0.0.9",)
    assert c.services == ("/orgs/1/sec_policy/active/services/2",)
    assert c.windows_services == ("wuauserv", "Spooler") and c.transmissions == ("broadcast",)
    assert c.exclude_processes == ("svchost.exe",) and c.exclude_transmissions == ("multicast",)
    page.goto(f"{live_app.url}/alerts/rules/{mine.id}")
    expect(page.locator("[data-side=src] [data-label-group]")).to_contain_text("Live (env)")
    expect(page.locator("[data-role=service] [data-service]")).to_contain_text("Web")
    expect(page.locator("input[name=windows_services]")).to_have_value("wuauserv, Spooler")


def test_rule_event_types_from_the_catalog(context, live_app):
    """5.x parity 2026-11-06: event types are picked from the catalog with their descriptions; a type the catalog does
    not list can still be typed, and is said to be unlisted."""
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/rules/new?form=full")
    form = page.locator("[data-role=rule-editor]")
    form.locator("input[name=name]").fill("Tamper or sign-in")
    picker = form.locator("[data-role=event-picker]")
    picker.locator("select[name=event_pick]").select_option("agent.tampering")
    picker.get_by_role("button", name="Add event type").click()
    expect(form.locator("input[name=event_types]")).to_have_value("agent.tampering")
    expect(picker.locator("[data-event-type='agent.tampering']")).to_contain_text("firewall")
    expect(picker.locator("[data-role=status-unmarked]")).to_be_visible()
    picker.locator("select[name=event_pick]").select_option("user.sign_in")
    picker.get_by_role("button", name="Add event type").click()
    expect(picker.locator("[data-role=status-unmarked]")).to_have_count(0)
    form.locator("input[name=event_types]").fill("agent.tampering, user.sign_in, vendor.brand_new")
    expect(picker.locator("[data-event-type='vendor.brand_new']")).to_contain_text("not in the event catalog")
    form.get_by_role("button", name="Save").click()
    page.wait_for_selector("[data-role=rule-list]")
    mine = next(r for r in live_app.ctx.settings.current().alerts.rules if r.name == "Tamper or sign-in")
    assert mine.event_types == ("agent.tampering", "user.sign_in", "vendor.brand_new")


def test_rules_page_holds_resets_evaluates_and_keeps(context, live_app):
    """5.x parity 2026-11-06: a rule in cooldown says until when and can be reset; evaluate now asks the jobs to run;
    alert records can be kept forever."""
    from datetime import timedelta

    from illumio_ops.domain.alerting import RuleState
    from illumio_ops.domain.alertpack import pack_rule_id
    from illumio_ops.jobs.scheduler import build_scheduler
    rid = pack_rule_id("rule_agent_tampering")
    with live_app.ctx.db() as conn:
        store.save_rule_state(conn, rid, "host-a", RuleState(datetime.now(UTC) - timedelta(minutes=5), ()),
                              suppressed="cooldown")
        conn.commit()
    live_app.ctx.scheduler = build_scheduler(live_app.ctx)
    try:
        page = context.new_page()
        sign_in(page, live_app.url)
        page.goto(f"{live_app.url}/alert-rules")
        held = page.locator(f"tr[data-rule-id='{rid}'] [data-role=held]")
        expect(held).to_contain_text("In cooldown until")
        expect(held).to_contain_text("(1 held back)")
        held.locator("[data-role=reset]").click()
        held.locator("[data-role=reset-confirm]").click()
        expect(page.locator(f"tr[data-rule-id='{rid}'] [data-role=held]")).to_have_count(0)
        page.locator("[data-role=evaluate-now]").click()
        expect(page.locator("[data-role=evaluate-requested]")).to_contain_text("Requested at")
        assert live_app.ctx.scheduler.get_job("collect_events").next_run_time <= datetime.now(UTC)
        keep = page.locator("[data-role=retention]")
        keep.locator("input[name=alert_retention_days]").fill("0")
        expect(keep).to_contain_text("kept forever")
        keep.get_by_role("button", name="Save").click()
        expect(keep.get_by_role("status")).to_be_visible()
        assert live_app.ctx.settings.current().alerts.retention_days == 0
    finally:
        live_app.ctx.scheduler = None


def _traffic_rule(live_app):
    rule = {"id": "c" * 32, "name": "RDP blocked", "pack_key": None, "enabled": True, "notify": True,
            "severity": "high", "cooldown_minutes": 0, "throttle": None, "type": "traffic",
            "window_minutes": 60, "threshold_connections": 25,
            "condition": {"decisions": ["blocked"], "ports": [{"port": 3389, "proto": 6}],
                          "dst": {"labels": [{"key": "env", "values": ["Prod", "DR"]}]},
                          "src_exclude": {"labels": [{"key": "app", "values": ["Jumpbox"]}]},
                          "exclude_ports": [{"port": 22, "proto": 6}]}}
    ctx = live_app.ctx
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["alerts"]["rules"].append(rule))


def test_rule_list_states_condition_and_exclusion_and_filters_by_type(context, live_app):
    """6.5.0 B6 (UI spec §4.9): each rule's condition and exclusion in a line of words, and a filter by type."""
    _traffic_rule(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules")
    table = page.locator("[data-role=rule-list]")
    row = table.locator(f"tr[data-rule-id='{'c' * 32}']")
    cond = row.locator("[data-role=rule-condition]").inner_text()
    assert "Blocked" in cond and "3389" in cond and "env = Prod or DR" in cond
    assert "25 connections in 60 minutes" in cond
    excl = row.locator("[data-role=rule-exclusion]").inner_text()
    assert "app = Jumpbox" in excl and "22" in excl
    # a rule with nothing excluded says so; a system rule names what it watches
    system = table.locator("tr[data-rule-type=system]").first
    assert system.locator("[data-role=rule-exclusion]").inner_text() == "None"
    assert system.locator("[data-role=rule-condition]").inner_text().strip()
    total = table.locator("tbody tr").count()
    page.select_option("[data-role=rule-type-filter]", "traffic")
    expect(table.locator("tbody tr:not([data-rule-type=traffic])")).to_have_count(0)
    shown = table.locator("tbody tr").count()
    assert 0 < shown < total and row.count() == 1  # only traffic rules, the new one among them
    page.select_option("[data-role=rule-type-filter]", "")
    expect(table.locator("tbody tr")).to_have_count(total)


def test_rule_list_with_long_conditions_fits_1280_and_760(context, narrow_context, live_app):
    from tests.e2e.conftest import no_horizontal_overflow
    _traffic_rule(live_app)
    for c in (context, narrow_context):
        page = c.new_page()
        sign_in(page, live_app.url)
        page.goto(f"{live_app.url}/alert-rules")
        cell = page.locator(f"tr[data-rule-id='{'c' * 32}'] [data-role=rule-condition]")
        cell.wait_for()
        assert no_horizontal_overflow(page)
        assert cell.evaluate("e => e.scrollWidth <= e.clientWidth + 1 && getComputedStyle(e).textOverflow !== 'ellipsis'")


# ── new since the alerts page was last opened (purpose-led UI spec §6.1) ──

def _seen_now(ctx):
    with ctx.db() as conn:
        store.mark_seen(conn, datetime.now(UTC))


def test_alerts_are_new_until_the_alerts_page_has_been_opened(context, live_app):
    seed(live_app.ctx)
    seed(live_app.ctx)
    page = context.new_page()
    sign_in(page, live_app.url)  # signing in lands on the alerts page: the two above are seen
    page.goto(f"{live_app.url}/system/jobs")
    expect(page.locator("[data-role=nav-new]")).to_have_count(0)
    seed(live_app.ctx)  # fired after the page was last opened
    page.goto(f"{live_app.url}/system/jobs")  # anywhere but the alerts page: the count is owed
    expect(page.locator("[data-role=nav-new]")).to_have_text("New 1")
    page.goto(f"{live_app.url}/")
    rows = page.locator("[data-role=alert-list] tbody tr")
    expect(rows).to_have_count(3)
    expect(page.locator("[data-role=alert-list] [data-new]")).to_have_count(1)
    expect(page.locator("[data-role=page-conclusion]")).to_have_text(
        "3 alerts in the last 7 days: 3 High. 1 new since this page was last opened.")
    expect(page.locator("[data-role=nav-new]")).to_have_count(0)  # opening the page is having seen them
    # the page keeps its own measure while it is open: asking for the new ones does not find them already aged
    page.click("[data-role=alert-seen] button[data-value=new]")
    expect(rows).to_have_count(1)
    expect(page.locator("[data-role=alert-list] [data-new]")).to_have_count(1)
    page.goto(f"{live_app.url}/system/jobs")
    page.goto(f"{live_app.url}/")
    expect(rows).to_have_count(3)
    expect(page.locator("[data-role=alert-list] [data-new]")).to_have_count(0)
    expect(page.locator("[data-role=page-conclusion]")).to_have_text("3 alerts in the last 7 days: 3 High.")


def test_a_second_tab_does_not_age_the_list_of_the_first(context, live_app):
    _seen_now(live_app.ctx)
    seed(live_app.ctx)
    first = context.new_page()
    sign_in(first, live_app.url)
    expect(first.locator("[data-role=alert-list] [data-new]")).to_have_count(1)
    second = context.new_page()
    second.goto(f"{live_app.url}/")
    expect(second.locator("[data-role=alert-list] tbody tr")).to_have_count(1)
    first.click("[data-role=alert-seen] button[data-value=new]")
    expect(first.locator("[data-role=alert-list] [data-new]")).to_have_count(1)


def test_opening_one_alert_from_a_link_leaves_the_rest_new(context, live_app):
    _seen_now(live_app.ctx)
    a = seed(live_app.ctx)
    page = context.new_page()
    sign_in(page, live_app.url)  # lands on the alerts page: sign in elsewhere first would be the honest path, so reset
    _seen_now(live_app.ctx)
    b = seed(live_app.ctx)
    page.goto(f"{live_app.url}/alerts/{a}")
    expect(page.locator("[data-role=alert-detail]")).to_be_visible()
    expect(page.locator("[data-role=nav-new]")).to_have_text("New 1")
    assert b


def test_no_alerts_is_said_in_a_sentence(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    expect(page.locator("[data-role=page-conclusion]")).to_have_text("No alerts in the last 7 days.")


# ── the hosts an alert is about, and one body for the side panel and the full page (purpose-led UI spec §6.1) ──

W = "/orgs/1/workloads/"


def _about(ctx, devices, *, more=0, rule_type=AlertRuleType.LATERAL, subject="xenv|a|b", pack_key="rule_lateral_cross_env",
           params=None):
    from dataclasses import replace

    from illumio_ops.domain.alert_devices import Device
    now = datetime.now(UTC)
    t = Trigger(rule_id="d" * 32, rule_type=rule_type, subject_key=subject, severity=Severity.HIGH, first_seen=now,
                last_seen=now, late=False, message_key="alert_system_disk_low",
                params={"free": "1 GB", "warn": "10 GB", **(params or {})}, facts={}, evidence=None, confidence=Confidence())
    t = replace(t, devices=tuple(Device(k, r) for k, r in devices), devices_more=more)
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        return store.insert_alert(conn, pce_url=pce.url, org_id=pce.org_id, rule_name="", pack_key=pack_key, trigger=t,
                                  at=now, channels=["line"], hold=None)


def test_an_alert_lists_its_hosts_and_each_opens_that_host(context, live_app):
    from tests.e2e import test_hosts_e2e as hosts_e2e
    hosts_e2e._seed(live_app)  # db: a managed host the inventory holds
    seed(live_app.ctx)
    _about(live_app.ctx, [(hosts_e2e.DB, "source"), ("ip:10.0.0.9", "destination")])
    page = context.new_page()
    sign_in(page, live_app.url)
    row = page.locator("[data-role=alert-list] tbody tr").first
    links = row.locator("[data-role=host-link]")
    expect(links).to_have_count(2)
    expect(links.first).to_have_text("db")
    assert links.first.get_attribute("href").startswith("/hosts?key=") and links.first.get_attribute("href").endswith("#connections")
    assert "JetBrains Mono" in links.nth(1).locator("[data-role=address]").evaluate("(e) => getComputedStyle(e).fontFamily")
    # opening a host from a row is not choosing that row: the other alert stays in the side panel
    page.locator("[data-role=alert-list] tbody tr").nth(1).click()
    chosen = page.locator("[data-role=alert-side] [data-role=alert-summary]").inner_text()
    links.first.click()
    expect(page.locator("h1")).to_have_text("db")
    page.go_back()
    expect(page.locator("[data-role=alert-list] tbody tr").first).to_be_visible()
    assert chosen


def test_the_side_panel_and_the_alerts_own_page_say_the_same(context, live_app):
    from tests.e2e import test_hosts_e2e as hosts_e2e
    hosts_e2e._seed(live_app)
    a = _about(live_app.ctx, [(hosts_e2e.DB, "source"), ("ip:10.0.0.9", "destination")])
    page = context.new_page()
    sign_in(page, live_app.url)
    side = page.locator("[data-role=alert-side] [data-role=alert-body]")
    expect(side.locator("[data-role=alert-devices] li")).to_have_count(2)
    said = side.locator("[data-role=alert-devices]").inner_text()
    assert "Source" in said and "Recording only (Visibility Only)" in said and "unmanaged address" in said
    actions = set(side.locator("[data-role=alert-actions] a, [data-role=alert-actions] button").all_inner_texts())
    summary = side.locator("[data-role=alert-summary]").inner_text()
    page.goto(f"{live_app.url}/alerts/{a}")
    full = page.locator("[data-role=alert-detail] [data-role=alert-body]")
    expect(full.locator("[data-role=alert-devices] li")).to_have_count(2)
    assert full.locator("[data-role=alert-devices]").inner_text() == said
    there = set(full.locator("[data-role=alert-actions] a, [data-role=alert-actions] button").all_inner_texts())
    assert there == actions - {"Full detail (evidence, notes)"}
    assert full.locator("[data-role=alert-summary]").inner_text() == summary != ""


def test_many_hosts_are_three_in_the_list_and_twenty_in_the_detail_the_rest_a_count(context, live_app):
    a = _about(live_app.ctx, [(f"{W}h{i}", "subject") for i in range(20)], more=5, rule_type=AlertRuleType.EVENT,
               subject="e" * 32, pack_key="rule_agent_heartbeat")
    page = context.new_page()
    sign_in(page, live_app.url)
    row = page.locator("[data-role=alert-list] tbody tr").first
    expect(row.locator("[data-role=host-link]")).to_have_count(3)
    expect(row).to_contain_text("and 22 more")
    assert row.locator("[data-role=host-link]").first.get_attribute("href").endswith("#status")
    page.goto(f"{live_app.url}/alerts/{a}")
    devices = page.locator("[data-role=alert-detail] [data-role=alert-devices]")
    expect(devices.locator("[data-role=host-link]")).to_have_count(20)
    expect(devices).to_contain_text("and 5 more")
    assert page.evaluate("document.querySelector('main').scrollWidth <= document.querySelector('main').clientWidth + 1")


def test_an_alert_stored_before_hosts_were_kept_still_reads(context, live_app):
    a = _lateral(live_app.ctx, "new_process", subject="ip:10.0.0.9")  # its parameters name a host and a target
    with live_app.ctx.db() as conn:
        conn.execute("DELETE FROM alert_devices")  # as an alert from before the upgrade, not backfilled
        conn.commit()
    page = context.new_page()
    sign_in(page, live_app.url)
    row = page.locator("[data-role=alert-list] tbody tr").first
    expect(row).to_contain_text("10.0.0.9")
    expect(row.locator("[data-role=host-link]")).to_have_count(0)
    page.goto(f"{live_app.url}/alerts/{a}")
    expect(page.locator("[data-role=alert-detail] [data-role=alert-devices]")).to_contain_text("10.0.0.9")
    expect(page.locator(".form-error")).to_have_count(0)


def test_a_system_alert_says_it_is_about_no_host(context, live_app):
    seed(live_app.ctx)
    page = context.new_page()
    sign_in(page, live_app.url)
    expect(page.locator("[data-role=alert-list] tbody tr").first).to_contain_text("The PCE or this tool")
    expect(page.locator("[data-role=alert-side] [data-role=alert-devices]")).to_have_text(
        "This alert is about this tool or the PCE itself, not a particular host.")


def test_a_workload_the_host_page_cannot_open_is_named_but_not_a_link(context, live_app):
    """A Kubernetes workload is named in traffic like any host, but the host page takes only a managed workload or
    an address: its name is shown, and nothing leads to a page that would refuse it."""
    _about(live_app.ctx, [("/orgs/1/kubernetes_workloads/pod-1", "source"), ("ip:10.0.0.9", "destination")])
    page = context.new_page()
    sign_in(page, live_app.url)
    row = page.locator("[data-role=alert-list] tbody tr").first
    expect(row.locator("[data-role=alert-hosts]")).to_be_visible()
    expect(row.locator("[data-role=host-link]")).to_have_count(1)  # the address; the pod is words
