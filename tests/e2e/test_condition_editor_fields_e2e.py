"""Round trips for every FlowCondition shape in the alert and report editors."""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from tests.e2e.conftest import sign_in


def _traffic_rule(condition: dict) -> dict:
    return {
        "id": uuid.uuid4().hex, "name": "Condition editor round trip", "pack_key": None, "enabled": True,
        "notify": True, "severity": "high", "cooldown_minutes": 0, "throttle": None, "type": "traffic",
        "window_minutes": 60, "threshold_connections": 25, "condition": condition,
    }


def _rules(live_app) -> dict[str, dict]:
    return {r.id: r.model_dump(mode="json") for r in live_app.ctx.settings.current().alerts.rules}


def _ports() -> list[dict]:
    return [
        {"port": 445, "to_port": None, "proto": None},
        {"port": 80, "to_port": None, "proto": 6},
        {"port": 53, "to_port": None, "proto": 17},
        {"port": 445, "to_port": None, "proto": 47},
        {"port": None, "to_port": None, "proto": 1},
        {"port": -1, "to_port": None, "proto": 1},
        {"port": 135, "to_port": 139, "proto": 6},
    ]


def _save_rule(page) -> None:
    form = page.locator("[data-role=rule-form]")
    if not form.count():
        form = page.locator("[data-role=rule-editor]")
    form.locator("button[type=submit]").click()
    page.wait_for_selector("[data-role=rules-event]")
    expect(page.locator("[data-role=rule-form]")).to_have_count(0)  # saved: the form has closed


def _rule_ports_case(page, live_app, append: bool) -> None:
    rule = _traffic_rule({"ports": _ports()})
    live_app.ctx.settings.update(live_app.ctx.settings.current().revision,
                                 lambda d: d["alerts"]["rules"].append(rule))
    page.goto(f"{live_app.url}/alert-rules?rule={rule['id']}")
    ports = page.locator("[data-role=rule-form] input[name=ports]")
    ports.focus()
    if append:
        ports.press("End")
        ports.fill(ports.input_value() + ", 8080")
    ports.blur()
    _save_rule(page)
    saved = _rules(live_app)[rule["id"]]["condition"]["ports"]
    expected = _ports() + ([{"port": 8080, "to_port": None, "proto": 6}] if append else [])
    assert saved == expected


def test_alert_ports_keep_every_protocol_and_append_bare_tcp(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    _rule_ports_case(page, live_app, append=False)
    _rule_ports_case(page, live_app, append=True)


def _schedule(live_app, condition: dict) -> str:
    sid = uuid.uuid4().hex
    schedule = {"id": sid, "name": "Port round trip", "enabled": True, "report_type": "traffic",
                "lookback_days": 7, "frequency": "daily", "day_of_week": None, "day_of_month": None,
                "hour": 8, "minute": 0, "formats": ["html"], "email": False, "recipients": [], "lang": None,
                "keep": 30, "filter": condition}
    live_app.ctx.settings.update(live_app.ctx.settings.current().revision,
                                 lambda d: d["reports"]["schedules"].append(schedule))
    return sid


def _report_ports_case(page, live_app, append: bool) -> None:
    sid = _schedule(live_app, {"ports": _ports()})
    page.goto(f"{live_app.url}/reports")
    page.wait_for_selector("[data-role=report-catalog]")
    page.get_by_role("tab", name="Schedules").click()
    page.locator(f"[data-role=schedule-list] tr[data-schedule-id='{sid}']").get_by_role("button", name="Edit").click()
    editor = page.locator("[data-role=schedule-editor]")
    ports = editor.locator("input[name=ports]")
    ports.focus()
    if append:
        ports.fill(ports.input_value() + ", 8080")
    ports.blur()
    editor.get_by_role("button", name="Save").click()
    # the list is drawn again from the saved schedule: its filter line shows the port once the save is through
    row = page.locator(f"[data-role=schedule-list] tr[data-schedule-id='{sid}']")
    expect(row.locator("[data-role=schedule-filter]")).to_contain_text("8080" if append else "445")
    expect(editor).to_have_count(0)
    saved = next(s for s in live_app.ctx.settings.current().reports.schedules if s.id == sid)
    got = [p.model_dump(mode="json") for p in saved.filter.ports]
    assert got == _ports() + ([{"port": 8080, "to_port": None, "proto": 6}] if append else [])


def test_report_filter_ports_keep_every_protocol_and_append_bare_tcp(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    _report_ports_case(page, live_app, append=False)
    _report_ports_case(page, live_app, append=True)


def test_alert_full_condition_fields_are_editable_and_saved(context, live_app):
    hrefs = ["/orgs/1/workloads/source-one", "/orgs/1/workloads/source-two"]
    condition = {
        "service_process": "old-service.exe", "service_user": "old-service-user", "text": "old search",
        "initiator_processes": ["old-init.exe", "legacy-init.exe"],
        "initiator_users": ["old-init-user", "legacy-init-user"],
        "service_processes": ["old-svc.exe", "legacy-svc.exe"],
        "service_users": ["old-svc-user", "legacy-svc-user"],
        "src": {"hrefs": hrefs, "labels": [{"key": "env", "values": ["Prod"]}], "ips": ["10.0.0.1"], "match": "all"},
    }
    rule = _traffic_rule(condition)
    live_app.ctx.settings.update(live_app.ctx.settings.current().revision,
                                 lambda d: d["alerts"]["rules"].append(rule))
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?rule={rule['id']}")
    form = page.locator("[data-role=rule-form]")
    text_values = {
        "service_process": ("old-service.exe", "new-service.exe"),
        "service_user": ("old-service-user", "new-service-user"),
        "text": ("old search", "new search"),
    }
    for name, (before, after) in text_values.items():
        control = form.locator(f"input[name={name}]")
        expect(control).to_be_visible()
        expect(control).to_have_value(before)
        control.fill(after)
    list_values = {
        "initiator_processes": (["old-init.exe", "legacy-init.exe"], ["new-init.exe", "second-init.exe"]),
        "initiator_users": (["old-init-user", "legacy-init-user"], ["new-init-user", "second-init-user"]),
        "service_processes": (["old-svc.exe", "legacy-svc.exe"], ["new-svc.exe", "second-svc.exe"]),
        "service_users": (["old-svc-user", "legacy-svc-user"], ["new-svc-user", "second-svc-user"]),
    }
    for name, (before, after) in list_values.items():
        control = form.locator(f"textarea[name={name}]")
        expect(control).to_be_visible()
        expect(control).to_have_value("\n".join(before))
        control.fill("\n".join(after))
        control.blur()
    side = form.locator("[data-role=src-advanced]")
    match = side.locator("select[name=src_match]")
    expect(match).to_be_visible()
    expect(match).to_have_value("all")
    match.select_option("any")
    chips = side.locator("[data-href]")
    expect(chips).to_have_count(2)
    expect(chips.nth(0)).to_contain_text(hrefs[0])
    expect(chips.nth(1)).to_contain_text(hrefs[1])
    chips.nth(0).get_by_role("button").click()
    _save_rule(page)
    saved = _rules(live_app)[rule["id"]]["condition"]
    for name, (_, after) in text_values.items():
        assert saved[name] == after
    for name, (_, after) in list_values.items():
        assert saved[name] == after
    assert saved["src"]["match"] == "any"
    assert saved["src"]["hrefs"] == [hrefs[1]]
    page.close()


def test_report_filter_does_not_show_alert_only_fields(context, live_app):
    _schedule(live_app, {"service_process": "kept", "initiator_processes": ["kept.exe"],
                         "src": {"hrefs": ["/orgs/1/workloads/report-only"]}})
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/reports")
    page.wait_for_selector("[data-role=report-catalog]")
    page.get_by_role("tab", name="Schedules").click()
    page.locator("[data-role=schedule-list] tbody tr").first.get_by_role("button", name="Edit").click()
    editor = page.locator("[data-role=schedule-editor]")
    expect(editor.locator("input[name=service_process]")).to_have_count(0)
    expect(editor.locator("textarea[name=initiator_processes]")).to_have_count(0)
    expect(editor.locator("select[name=src_match]")).to_have_count(0)
    expect(editor.locator("[data-href]")).to_have_count(0)
    page.close()
