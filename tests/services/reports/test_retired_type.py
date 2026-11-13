"""Rule Hit Count is no longer a report of its own (UI redesign spec §9.2, stage 3b): its counts are a chapter of the
policy usage report. The type stays in ReportType so that what was made and scheduled before still reads; nothing
new is made of it. Every path that takes the type of a stored report or of a schedule and asks the registry about it
is walked here with an old report and a schedule of that type in place: none may raise."""
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.values import Language, ReportStatus, ReportType
from illumio_ops.i18n import translate
from illumio_ops.services.reports import generate, registry, retention, schedules, views
from illumio_ops.services.reports.registry import ReportParams, specs
from illumio_ops.store import reports as store
from tests.services.collect.conftest import configured_ctx

NOW = datetime(2026, 11, 13, 10, tzinfo=UTC)
RHC = ReportType.RULE_HIT_COUNT
SID = "c" * 32
SCHEDULE = {"id": SID, "name": "Weekly hits", "enabled": True, "report_type": "rule_hit_count", "lookback_days": 90,
            "frequency": "daily", "day_of_week": None, "day_of_month": None, "hour": 9, "minute": 30,
            "formats": ["html", "xlsx"], "email": False, "recipients": [], "lang": None, "keep": 1}


def test_every_type_but_this_one_is_generated():
    """Written out, not derived: a type that dropped out of the registry by mistake would otherwise go unseen."""
    assert set(specs()) == set(ReportType) - {RHC}
    assert registry.RETIRED == {RHC: "rpt_err_rhc_merged"}


@pytest.mark.parametrize("lang", list(Language))
def test_the_reason_names_the_report_it_joined(lang):
    assert translate(lang, "rpt_title_policy_usage", {}) in translate(lang, "rpt_err_rhc_merged", {})


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path)
    c.settings.update(c.settings.current().revision, lambda d: d["display"].update(timezone="UTC"))
    return c


def _row(ctx, rid):
    with ctx.db() as conn:
        return store.get(conn, rid)


def test_asking_for_one_is_refused_with_where_it_went(ctx):
    params = ReportParams(report_type=RHC)
    assert generate.refusal(ctx.settings.current(), params) == "rpt_err_rhc_merged"
    assert generate.REFUSAL_FIELDS["rpt_err_rhc_merged"] == "report_type"
    assert RHC not in generate.availability(ctx)
    rid = generate.enqueue(ctx, params, trigger="manual", schedule_id=None, now=NOW)
    row = _row(ctx, rid)
    assert (row.status, row.error_key, row.files) == (ReportStatus.FAILED, "rpt_err_rhc_merged", [])
    assert generate.run_queued(ctx, now=NOW) is None  # nothing was queued


def test_one_queued_before_the_upgrade_fails_with_where_it_went(ctx):
    settings = ctx.settings.current()
    with ctx.db() as conn:
        rid = store.insert(conn, report_type=RHC.value, params_json=ReportParams(report_type=RHC).model_dump_json(),
                           status=ReportStatus.QUEUED, trigger="schedule", schedule_id=SID,
                           pce_label=generate.pce_label(settings.pce), period_start=NOW - timedelta(days=7),
                           period_end=NOW, created_at=NOW, pce_target=generate.pce_target(settings.pce))
    assert generate.run_queued(ctx, now=NOW) == rid
    row = _row(ctx, rid)
    assert (row.status, row.error_key) == (ReportStatus.FAILED, "rpt_err_rhc_merged")
    assert not (ctx.paths.reports_dir / str(rid)).exists()


def _old_report(ctx, created, *, schedule_id=SID):
    """A Rule Hit Count report as 6.9 left it: done, with its files."""
    with ctx.db() as conn:
        rid = store.insert(conn, report_type=RHC.value,
                           params_json=ReportParams(report_type=RHC, lookback_days=90).model_dump_json(),
                           status=ReportStatus.QUEUED, trigger="schedule", schedule_id=schedule_id, pce_label="pce",
                           period_start=created - timedelta(days=90), period_end=created, created_at=created,
                           pce_target=generate.pce_target(ctx.settings.current().pce))
        name = f"rule_hit_count-20261101-{rid}.html"
        store.finish(conn, rid, status=ReportStatus.DONE, at=created, files=[name],
                     kpis=[{"key": "rules", "label": "Provisioned rules (enabled)", "value": 4, "previous": None}],
                     conclusion="Provisioned enabled rules: 4.")
    out = ctx.paths.reports_dir / str(rid)
    out.mkdir(parents=True)
    (out / name).write_text("<html>old</html>", encoding="utf-8")
    return rid, name


@pytest.fixture
def old(ctx):
    """Two old reports of the type under a schedule of the type (a file written by hand: an upgraded one has none
    left, the upgrade turns each into a policy usage schedule)."""
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["reports"].update(schedules=[SCHEDULE]))
    first = _old_report(ctx, NOW - timedelta(days=9))
    second = _old_report(ctx, NOW - timedelta(days=2))
    return ctx, first, second


def test_the_catalog_lists_no_card_for_it_and_does_not_stumble_on_its_schedule(old):
    ctx, _, _ = old
    cat = views.catalog(ctx)
    assert RHC not in {e.report_type for e in cat.entries} and len(cat.entries) == len(ReportType) - 1
    assert all(e.available and e.reason_key is None for e in cat.entries)
    usage = next(e for e in cat.entries if e.report_type is ReportType.POLICY_USAGE)
    assert (usage.schedules, usage.copies) == (0, 0)  # the old type's schedule and copies are not this card's


def test_its_old_reports_are_listed_read_opened_and_deleted(old):
    ctx, (first, name), (second, _) = old
    page = views.list_reports(ctx, page=1)
    assert [(i.id, i.report_type, i.status, i.schedule_name) for i in page.items] == [
        (second, "rule_hit_count", ReportStatus.DONE, "Weekly hits"),
        (first, "rule_hit_count", ReportStatus.DONE, "Weekly hits")]
    item = views.get_report(ctx, first)
    assert item is not None and item.files == [name] and item.conclusion == "Provisioned enabled rules: 4."
    path = views.report_file(ctx, first, name)
    assert path is not None and path.read_text(encoding="utf-8") == "<html>old</html>"
    assert retention.remove_report(ctx, first) == "removed"
    assert not (ctx.paths.reports_dir / str(first)).exists() and views.get_report(ctx, first) is None


def test_retention_keeps_as_many_as_its_schedule_says(old):
    ctx, (first, _), (second, _) = old
    assert retention.run_report_retention(ctx, now=NOW) == 1  # keep 1: the older goes
    assert views.get_report(ctx, first) is None and views.get_report(ctx, second) is not None
    assert retention.run_report_retention(ctx, now=NOW + timedelta(days=200)) == 1  # past reports.retention_days


def test_its_schedule_is_listed_and_a_run_fails_with_where_it_went(old):
    ctx, _, (second, _) = old
    status = schedules.schedule_status(ctx, now=NOW)[SID]
    assert (status.last_report_id, status.last_status, status.consecutive_failures) == (second, ReportStatus.DONE, 0)
    assert status.next_run == datetime(2026, 11, 14, 9, 30, tzinfo=UTC)
    rid = schedules.run_now(ctx, SID, now=NOW)
    assert rid is not None
    row = _row(ctx, rid)
    assert (row.status, row.error_key, row.schedule_id) == (ReportStatus.FAILED, "rpt_err_rhc_merged", SID)
    assert views.get_report(ctx, rid).report_type == "rule_hit_count"


def test_its_schedule_coming_due_makes_a_failed_report_not_an_error(old):
    ctx, _, _ = old
    assert schedules.tick_schedules(ctx, now=NOW) == []  # first seen: counts from now
    [rid] = schedules.tick_schedules(ctx, now=NOW + timedelta(days=1))
    assert _row(ctx, rid).error_key == "rpt_err_rhc_merged"
    assert schedules.schedule_status(ctx, now=NOW + timedelta(days=1))[SID].last_status is ReportStatus.FAILED
