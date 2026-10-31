"""5.x report settings and report schedules → v6 (P5c-5, spec §7): every schedule carried, rewritten, paused or
skipped — and said; never widened silently (a filter or cron v6 cannot hold pauses the schedule)."""
import copy
import json
from pathlib import Path

from illumio_ops.migrate.v5 import migrate_v5

FIXTURES = Path(__file__).parent / "fixtures"


def _raw(**report):
    raw = json.loads((FIXTURES / "v5_2_x_config_106_redacted.json").read_text())
    raw = copy.deepcopy(raw)
    raw["report_schedules"] = report.pop("schedules", [])
    raw["report"].update(report)
    return raw


def _sched(**kw):
    base = {"id": 1, "name": "Weekly", "cron_expr": None, "timezone": "local", "report_type": "traffic",
            "schedule_type": "weekly", "day_of_week": "monday", "day_of_month": 1, "hour": 8, "minute": 30,
            "lookback_days": 7, "max_reports": 30, "format": ["html"], "email_report": False, "email_recipients": [],
            "enabled": True}
    return {**base, **kw}


def _run(raw):
    res = migrate_v5(raw)
    assert res.settings is not None, res.blocking
    return res.settings.reports, {i.source: i for i in res.report.items}


def test_schedule_carried():
    reports, items = _run(_raw(schedules=[_sched()]))
    [s] = reports.schedules
    assert (s.report_type.value, s.frequency, s.day_of_week, s.hour, s.minute, s.lookback_days, s.keep, s.enabled) == \
        ("traffic", "weekly", 0, 8, 30, 7, 30, True)
    assert s.formats == ("html",) and len(s.id) == 32
    assert items["report_schedules[0] Weekly"].action == "carried"


def test_schedules_5x_never_ran_are_paused():
    """The .106 config's schedule: audit_summary (a type 5.x did not know) and "mon" (5.x compared full weekday
    names, so it never fired — 5.x's own comment says so). Carried with the intent, paused: v6 does not start
    sending what 5.x never did."""
    reports, items = _run(_raw(schedules=[_sched(report_type="audit_summary"), _sched(id=2, name="Mon", day_of_week="mon")]))
    a, m = reports.schedules
    assert (a.report_type.value, a.enabled, m.day_of_week, m.enabled) == ("audit", False, 0, False)
    assert {items["report_schedules[0] Weekly"].reason_key, items["report_schedules[1] Mon"].reason_key} == \
        {"migrate_schedule_never_ran"}


def test_cron_and_filters_pause():
    reports, items = _run(_raw(schedules=[_sched(cron_expr="0 8 * * MON-FRI"),
                                          _sched(id=2, name="Filtered", filters={"src_labels": ["app:Web"]})]))
    assert [s.enabled for s in reports.schedules] == [False, False]
    assert items["report_schedules[0] Weekly"].reason_key == "migrate_schedule_cron_paused"
    assert items["report_schedules[1] Filtered"].reason_key == "migrate_schedule_filter_paused"


def test_unknown_type_skipped():
    reports, items = _run(_raw(schedules=[_sched(report_type="executive_pdf")]))
    assert reports.schedules == () and items["report_schedules[0] Weekly"].action == "unsupported"


def test_app_summary_needs_app():
    reports, items = _run(_raw(schedules=[_sched(report_type="app_summary", app="Billing", env="Prod"),
                                          _sched(id=2, name="NoApp", report_type="app_summary")]))
    [s] = reports.schedules
    labels = {(lc.key, lc.values) for lc in s.filter.dst.labels}
    assert labels == {("app", ("Billing",)), ("env", ("Prod",))}
    assert items["report_schedules[1] NoApp"].action == "unsupported"


def test_formats_and_lookback_per_type():
    reports, _ = _run(_raw(schedules=[_sched(format=["csv", "all"]), _sched(id=2, report_type="policy_resolver"),
                                      _sched(id=3, report_type="policy_usage", lookback_days=60)]))
    t, r, u = reports.schedules
    assert t.formats == ("html", "xlsx")
    assert r.formats == ("json", "csv") and r.lookback_days == 1
    assert u.lookback_days == 30


def test_recipients_and_keep():
    reports, items = _run(_raw(schedules=[_sched(email_report=True, email_recipients=["a@x.com", "bad", "b@x.com"],
                                                 max_reports=999)]))
    s = reports.schedules[0]
    assert s.email and s.recipients == ("a@x.com", "b@x.com") and s.keep == 365
    assert items["report_schedules[0] Weekly"].action == "rewritten"


def test_schedule_time_zone_disclosed():
    """v6 runs schedules in the display time zone."""
    _, items = _run(_raw(schedules=[_sched(timezone="America/New_York")]))
    assert items["report_schedules[0] Weekly"].reason_key == "migrate_schedule_rewritten"
    assert "time zone" in items["report_schedules[0] Weekly"].params["what"]


def test_report_section():
    raw = _raw(retention_days=45)
    raw["web_gui"]["public_url"] = "https://ops.example.com:5443/"
    reports, items = _run(raw)
    assert reports.retention_days == 45 and reports.gui_external_url == "https://ops.example.com:5443"
    assert items["report.retention_days"].action == "carried" and items["report.output_dir"].action == "dropped"
    assert items["web_gui.public_url"].target == "reports.gui_external_url"
    assert items["report.max_top_n"].reason_key == "migrate_not_in_v6"
