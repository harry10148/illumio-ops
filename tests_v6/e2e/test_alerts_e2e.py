"""Alerts in a browser: the list with its delivery badges, the detail with the delivery state and notes, rules."""
from datetime import UTC, datetime

from playwright.sync_api import expect

from illumio_ops.domain.alerting import Confidence, Trigger
from illumio_ops.domain.values import AlertRuleType, DeliveryStatus, Severity
from illumio_ops.store import alerts as store
from tests_v6.e2e.conftest import sign_in


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
    expect(table.locator("tr[data-alert-id]")).to_have_count(2)
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
    page.locator(f"tr[data-alert-id='{a}'] a").click()
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
    page.click("nav >> a[href=\"/system/lateral\"]")
    known = page.locator("[data-role=known-detections]")
    expect(known).to_contain_text("Nightly backup host")
    expect(known).to_contain_text("every detection of this kind about /orgs/1/workloads/w1")
    known.get_by_role("button", name="Remove").click()
    expect(known).to_contain_text("No detection is marked known.")
