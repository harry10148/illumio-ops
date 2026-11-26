"""The check on the schedules' reports (spec 2026-11-27 §1): each report of a schedule is judged once, when it is
over — not made, or made and not emailed."""
import json
from datetime import timedelta

import pytest

from illumio_ops.domain.values import (
    IngestSource,
    Language,
    ReportStatus,
    Severity,
    SystemCheck,
)
from illumio_ops.services.alerts.evaluate import evaluate_system
from illumio_ops.services.alerts.messages import AlertView, next_steps, summary
from illumio_ops.settings.schema import default_settings
from illumio_ops.settings.upgrade import upgrade
from illumio_ops.store import alerts as alert_store
from illumio_ops.store import reports as store
from illumio_ops.store.flowdb import ingest_state
from tests.services.collect.conftest import NOW, PCE, configured_ctx, minutes
from tests.services.reports.test_schedules import SID, sched
from tests.settings.conftest import HASH, KEY

RULE = "rule_system_report_failing"


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path)
    with c.flows().connect() as conn:
        ingest_state.mark_ok(conn, IngestSource.TRAFFIC, NOW - minutes(30), watermark=NOW - minutes(30), rows=0)
    c.settings.update(c.settings.current().revision,
                      lambda d: d["reports"].update(schedules=[sched(name="Weekly overview").model_dump(mode="json")]))
    return c


def _report(ctx, *, status=ReportStatus.QUEUED, schedule=SID, error_key=None):
    with ctx.db() as conn:
        return store.insert(conn, report_type="lateral_posture", params_json="{}", status=status,
                            trigger="schedule" if schedule else "manual", schedule_id=schedule, pce_label="p",
                            period_start=NOW, period_end=NOW, created_at=NOW, error_key=error_key)


def _done(ctx, rid, email=None, detail=None):
    with ctx.db() as conn:
        store.claim_next(conn, at=NOW)
        store.finish(conn, rid, status=ReportStatus.DONE, at=NOW, files=["a.html"], kpis=[])
        if email:
            store.set_email(conn, rid, status=email, detail=detail)


def _alerts(ctx):
    with ctx.db() as conn:
        rows, _ = alert_store.list_alerts(conn, pce_url=PCE["url"], org_id=PCE["org_id"],
                                          since=NOW - timedelta(days=30), limit=100, offset=0)
    return [{**dict(a), "params": json.loads(a["params_json"])} for a in rows
            if a["subject_key"].startswith("report_failing")]


def test_the_upgrade_marks_what_was_over_and_leaves_what_was_not(tmp_path, monkeypatch):
    """No alert for a failure from before the check existed; a report the upgrade stopped half-way is still judged,
    and has used one of its two starts."""
    from illumio_ops.store import db
    conn = db.connect(tmp_path / "old.sqlite")
    migrations = db._migrations()
    monkeypatch.setattr(db, "_migrations", lambda package=None: migrations[:21])
    assert db.migrate(conn) == 21
    for status, email in (("failed", None), ("done", "failed"), ("done", "sending"), ("running", None), ("queued", None)):
        conn.execute("INSERT INTO reports (report_type, params_json, status, trigger, schedule_id, pce_label, "
                     "period_start, period_end, created_at, email_status) VALUES ('audit', '{}', ?, 'schedule', ?, "
                     "'p', '2026-10-20', '2026-10-27', '2026-10-27', ?)", (status, SID, email))
    conn.commit()
    monkeypatch.undo()
    assert db.migrate(conn) == 22
    rows = [tuple(r) for r in conn.execute("SELECT status, email_status, alert_checked, attempts FROM reports ORDER BY id")]
    assert rows == [("failed", None, 1, 0), ("done", "failed", 1, 0), ("done", "sending", 0, 0),
                    ("running", None, 0, 1), ("queued", None, 0, 0)]


def test_a_report_running_at_the_first_evaluation_is_still_judged(ctx):
    """Codex review 2026-11-27: a watermark seeded at the newest report id skipped the one being made."""
    rid = _report(ctx)
    with ctx.db() as conn:
        store.claim_next(conn, at=NOW)
    assert evaluate_system(ctx, now=NOW).fired == 0
    with ctx.db() as conn:
        store.finish(conn, rid, status=ReportStatus.FAILED, at=NOW, files=[], kpis=[], error_key="rpt_err_internal")
    assert evaluate_system(ctx, now=NOW + minutes(1)).fired == 1


def test_a_report_given_a_deleted_reports_id_is_still_judged(ctx):
    """Codex review 2026-11-27: SQLite gives the id of a deleted newest row to the next one, which a watermark on
    the id would never look at."""
    first = _report(ctx, status=ReportStatus.FAILED, error_key="rpt_err_internal")
    assert evaluate_system(ctx, now=NOW).fired == 1
    with ctx.db() as conn:
        assert store.delete(conn, [first]) == [first]
    again = _report(ctx, status=ReportStatus.FAILED, error_key="rpt_err_ondemand_failed")
    assert again == first
    assert evaluate_system(ctx, now=NOW + timedelta(hours=3)).fired == 1


def test_a_schedules_failed_report_is_reported_once_and_a_manual_one_never(ctx):
    evaluate_system(ctx, now=NOW)
    _report(ctx, status=ReportStatus.FAILED, schedule=None, error_key="rpt_err_internal")  # the operator saw it fail
    rid = _report(ctx, status=ReportStatus.FAILED, error_key="rpt_err_ondemand_failed")  # refused or failed
    assert evaluate_system(ctx, now=NOW + minutes(1)).fired == 1
    (a,) = _alerts(ctx)
    assert a["subject_key"] == f"report_failing:{SID}" and a["severity"] == Severity.MEDIUM.value
    assert a["params"]["report_id"] == rid and a["params"]["problem"] == "not_made"
    assert evaluate_system(ctx, now=NOW + timedelta(hours=3)).fired == 0  # looked at once


def test_a_report_made_and_emailed_says_nothing_and_one_not_emailed_does(ctx):
    evaluate_system(ctx, now=NOW)
    _done(ctx, _report(ctx), email="sent")
    assert evaluate_system(ctx, now=NOW + minutes(1)).fired == 0
    _done(ctx, _report(ctx), email="failed", detail="535 authentication failed")
    assert evaluate_system(ctx, now=NOW + timedelta(hours=2)).fired == 1
    assert _alerts(ctx)[0]["params"]["problem"] == "mail_failed"
    _done(ctx, _report(ctx), email="skipped_no_smtp")
    assert evaluate_system(ctx, now=NOW + timedelta(hours=4)).fired == 1
    _done(ctx, _report(ctx), email="interrupted")
    assert evaluate_system(ctx, now=NOW + timedelta(hours=6)).fired == 1
    assert {a["params"]["problem"] for a in _alerts(ctx)} == {"mail_failed", "mail_no_smtp", "mail_interrupted"}


def test_a_report_that_is_not_over_is_waited_for_not_skipped(ctx):
    evaluate_system(ctx, now=NOW)
    first = _report(ctx)  # queued: not over
    assert evaluate_system(ctx, now=NOW + minutes(1)).fired == 0
    _done(ctx, first, email="sending")  # made, its email still going out
    assert evaluate_system(ctx, now=NOW + minutes(2)).fired == 0
    with ctx.db() as conn:
        store.set_email(conn, first, status="failed", detail="timed out")
    assert evaluate_system(ctx, now=NOW + minutes(3)).fired == 1
    assert [a["params"]["report_id"] for a in _alerts(ctx)] == [first]
    assert evaluate_system(ctx, now=NOW + timedelta(hours=3)).fired == 0


def test_a_rule_turned_on_later_speaks_of_the_reports_after_that(ctx):
    def off(d):
        for r in d["alerts"]["rules"]:
            if r.get("pack_key") == RULE:
                r["enabled"] = not r["enabled"]
    ctx.settings.update(ctx.settings.current().revision, off)
    evaluate_system(ctx, now=NOW)
    _report(ctx, status=ReportStatus.FAILED, error_key="rpt_err_internal")
    assert evaluate_system(ctx, now=NOW + minutes(1)).fired == 0
    ctx.settings.update(ctx.settings.current().revision, off)  # on again
    assert evaluate_system(ctx, now=NOW + minutes(2)).fired == 0
    _report(ctx, status=ReportStatus.FAILED, error_key="rpt_err_internal")
    assert evaluate_system(ctx, now=NOW + minutes(3)).fired == 1


def test_a_run_of_another_check_does_not_look_at_the_reports(ctx):
    evaluate_system(ctx, now=NOW)
    _report(ctx, status=ReportStatus.FAILED, error_key="rpt_err_internal")
    evaluate_system(ctx, now=NOW + minutes(1), checks={SystemCheck.PCE_HEALTH})
    assert evaluate_system(ctx, now=NOW + minutes(2)).fired == 1


def _view(**params):
    base = {"schedule": "Weekly overview", "schedule_id": SID, "report_id": 7, "report_type": "weekly_overview",
            "error_key": "", "detail": ""}
    return AlertView(id=1, rule_name="", pack_key=RULE, severity=Severity.MEDIUM, subject_key=f"report_failing:{SID}",
                     fired_at=NOW, late=False, message_key="alert_system_report_failing", params={**base, **params},
                     facts={}, confidence={})


def test_the_alert_says_which_report_and_what_went_wrong():
    zh = summary(_view(problem="not_made", error_key="rpt_err_ondemand_failed", detail="PceTimeout: 900s"),
                 Language.ZH_TW)
    assert "「Weekly overview」" in zh and "#7" in zh and "報表沒有產出" in zh and "PceTimeout: 900s" in zh
    assert "rpt_err_ondemand_failed" not in zh  # the report's reason in words, not its key
    en = summary(_view(problem="mail_failed", detail="535 authentication failed"), Language.EN)
    assert "its email was not sent: 535 authentication failed" in en
    assert "SMTP" in summary(_view(problem="mail_no_smtp"), Language.EN)
    assert "不確定" in summary(_view(problem="mail_interrupted"), Language.ZH_TW) or \
        "無法確定" in summary(_view(problem="mail_interrupted"), Language.ZH_TW)
    assert next_steps(_view(problem="not_made"), Language.EN)


def test_an_upgraded_file_gets_the_report_check_once():
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 15
    d["alerts"]["rules"] = [r for r in d["alerts"]["rules"] if r.get("pack_key") != RULE]
    out = upgrade(d)
    assert sum(r.get("pack_key") == RULE for r in out["alerts"]["rules"]) == 1
    again = upgrade({**out, "schema_version": 15})
    assert sum(r.get("pack_key") == RULE for r in again["alerts"]["rules"]) == 1
