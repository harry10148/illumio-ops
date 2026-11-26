"""Report reliability (spec 2026-11-27): what a restart leaves behind, the two lanes of the queue, the key numbers
kept apart from the reports, and a monthly schedule's calendar month."""
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from illumio_ops.domain.report import Kpi, ReportDocument
from illumio_ops.domain.values import Language, ReportStatus, ReportType
from illumio_ops.jobs import scheduler
from illumio_ops.services.reports import (
    generate,
    history,
    registry,
    retention,
    schedules,
)
from illumio_ops.services.reports.registry import BuildInput, ReportParams, ReportSpec
from illumio_ops.store import reports as store
from tests.services.collect.conftest import configured_ctx
from tests.services.reports.test_generate import FakeBuilder, _register, _row
from tests.services.reports.test_schedules import sched

NOW = datetime(2026, 10, 27, 1, 30, tzinfo=UTC)
LATERAL = ReportType.LATERAL_POSTURE
USAGE = ReportType.POLICY_USAGE


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path)
    c.settings.update(c.settings.current().revision, lambda d: d["display"].update(timezone="UTC"))
    return c


def _queue(ctx, report_type=LATERAL, **params):
    return generate.enqueue(ctx, ReportParams(report_type=report_type, **params), trigger="manual", schedule_id=None,
                            now=NOW)


# ── a restart ────────────────────────────────────────────────────────────────

def test_a_report_interrupted_twice_is_failed_not_started_a_third_time(ctx, monkeypatch):
    _register(monkeypatch, FakeBuilder())
    rid = _queue(ctx)
    with ctx.db() as conn:
        store.claim_next(conn, at=NOW)
    assert generate.recover(ctx, now=NOW)[:2] == (1, 0) and _row(ctx, rid).status is ReportStatus.QUEUED
    with ctx.db() as conn:
        store.claim_next(conn, at=NOW)
    assert generate.recover(ctx, now=NOW)[:2] == (0, 1)
    row = _row(ctx, rid)
    assert (row.status, row.error_key, row.finished_at) == (ReportStatus.FAILED, "rpt_err_interrupted", NOW)
    assert generate.run_queued(ctx, now=NOW) is None


def test_an_email_interrupted_by_a_restart_is_not_left_sending(ctx, monkeypatch):
    _register(monkeypatch, FakeBuilder())
    rid = _queue(ctx)
    generate.run_queued(ctx, now=NOW)
    with ctx.db() as conn:
        store.set_email(conn, rid, status="sending", detail=None)
    assert generate.recover(ctx, now=NOW) == (0, 0, 1)
    assert _row(ctx, rid).email_status == "interrupted" and _row(ctx, rid).status is ReportStatus.DONE


def test_the_scheduler_recovers_at_start_and_a_report_job_never_does(ctx, monkeypatch):
    """A lane's job queueing "running" reports again would queue the one the other lane is making."""
    _register(monkeypatch, FakeBuilder())
    rid = _queue(ctx)
    with ctx.db() as conn:
        store.claim_next(conn, at=NOW)  # left running by the stopped service
    scheduler.build_scheduler(ctx)
    assert _row(ctx, rid).status is ReportStatus.QUEUED
    with ctx.db() as conn:
        store.claim_next(conn, at=NOW)  # now being made by the other lane
    jobs = scheduler._collector_jobs(ctx)
    jobs["reports_run"]()
    jobs["reports_run_pce"]()
    assert _row(ctx, rid).status is ReportStatus.RUNNING


# ── two lanes ────────────────────────────────────────────────────────────────

def test_a_local_report_is_not_held_up_behind_a_pce_one(ctx, monkeypatch):
    made: list[ReportType] = []
    b = FakeBuilder(lambda inp: made.append(inp.params.report_type))
    reg = {t: ReportSpec(report_type=t, group="lateral", needs_traffic=False, build=b,
                         lane="pce" if t is USAGE else "local") for t in ReportType}
    monkeypatch.setattr(registry, "REGISTRY", reg)
    slow, fast = _queue(ctx, USAGE), _queue(ctx)
    assert generate.run_queued(ctx, now=NOW, lane="local") == fast and _row(ctx, slow).status is ReportStatus.QUEUED
    assert generate.run_queued(ctx, now=NOW, lane="local") is None
    assert generate.run_queued(ctx, now=NOW, lane="pce") == slow and generate.run_queued(ctx, now=NOW, lane="pce") is None
    assert made == [LATERAL, USAGE]


def test_the_built_in_lanes_and_a_type_without_a_builder(ctx):
    assert generate.lane_types("pce") == {"policy_usage", "readiness"}
    with ctx.db() as conn:  # queued before an upgrade retired its type: the local lane gives it its failure
        rid = store.insert(conn, report_type="rule_hit_count", params_json='{"report_type": "rule_hit_count"}',
                           status=ReportStatus.QUEUED, trigger="manual", schedule_id=None, pce_label="p",
                           period_start=NOW, period_end=NOW, created_at=NOW,
                           pce_target=generate.pce_target(ctx.settings.current().pce))
    assert generate.run_queued(ctx, now=NOW, lane="pce") is None
    assert generate.run_queued(ctx, now=NOW, lane="local") == rid
    assert _row(ctx, rid).error_key == "rpt_err_rhc_merged"


# ── the previous period's numbers outlive the report ─────────────────────────

def _valued(value, previous=None):
    def build(inp: BuildInput) -> ReportDocument:
        return ReportDocument(report_type=inp.params.report_type, lang=inp.lang, title="T", period_start=inp.start,
                              period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label,
                              kpis=(Kpi(key="k", label="K", value=value, previous=previous),
                                    Kpi(key="none", label="N", value=None, previous=None)),
                              findings=(), data_quality=(), sections=())
    return build


def _make(ctx, monkeypatch, value, first, last, previous=None):
    reg = {t: ReportSpec(report_type=t, group="lateral", needs_traffic=False, build=_valued(value, previous))
           for t in ReportType}
    monkeypatch.setattr(registry, "REGISTRY", reg)
    rid = _queue(ctx, period_from=first, period_to=last)
    generate.run_queued(ctx, now=NOW)
    assert _row(ctx, rid).status is ReportStatus.DONE
    return rid


def test_the_previous_number_survives_deleting_the_report_it_came_from(ctx, monkeypatch):
    a = _make(ctx, monkeypatch, 5, date(2026, 10, 13), date(2026, 10, 19))
    assert retention.remove_report(ctx, a, by="t") == "removed"
    b = _make(ctx, monkeypatch, 8, date(2026, 10, 20), date(2026, 10, 26))
    kpis = {k["key"]: k for k in _row(ctx, b).kpis}
    assert kpis["k"]["previous"] == 5 and kpis["none"]["previous"] is None
    html = next((ctx.paths.reports_dir / str(b)).glob("*.html")).read_text(encoding="utf-8")
    assert "are those of the report made" in html  # the data note says where the previous numbers come from


def test_a_number_the_builder_computed_is_not_replaced(ctx, monkeypatch):
    _make(ctx, monkeypatch, 5, date(2026, 10, 13), date(2026, 10, 19))
    b = _make(ctx, monkeypatch, 8, date(2026, 10, 20), date(2026, 10, 26), previous=6)
    assert {k["key"]: k["previous"] for k in _row(ctx, b).kpis}["k"] == 6
    html = next((ctx.paths.reports_dir / str(b)).glob("*.html")).read_text(encoding="utf-8")
    assert "are those of the report made" not in html


def test_only_a_period_as_long_and_adjacent_is_the_previous_one(ctx, monkeypatch):
    _make(ctx, monkeypatch, 5, date(2026, 10, 17), date(2026, 10, 19))  # three days, ends where the next starts
    _make(ctx, monkeypatch, 4, date(2026, 10, 6), date(2026, 10, 12))  # a week, but not the week before
    b = _make(ctx, monkeypatch, 8, date(2026, 10, 20), date(2026, 10, 26))
    assert {k["key"]: k["previous"] for k in _row(ctx, b).kpis}["k"] is None


def test_another_filter_or_pce_is_not_compared(ctx, monkeypatch):
    _make(ctx, monkeypatch, 5, date(2026, 10, 13), date(2026, 10, 19))
    with ctx.db() as conn:
        conn.execute("UPDATE report_kpi_history SET pce_target = 'https://other#1'")
        conn.commit()
    b = _make(ctx, monkeypatch, 8, date(2026, 10, 20), date(2026, 10, 26))
    assert {k["key"]: k["previous"] for k in _row(ctx, b).kpis}["k"] is None


def test_reports_made_before_the_numbers_were_kept_are_recorded_at_start(ctx, monkeypatch):
    a = _make(ctx, monkeypatch, 5, date(2026, 10, 13), date(2026, 10, 19))
    with ctx.db() as conn:
        conn.execute("DELETE FROM report_kpi_history")
        conn.commit()
    generate.recover(ctx, now=NOW)
    generate.recover(ctx, now=NOW)  # twice: nothing is recorded twice
    with ctx.db() as conn:
        assert [tuple(r) for r in conn.execute("SELECT complete FROM report_kpi_history")] == [(None,)]
    retention.remove_report(ctx, a, by="t")
    # Whether that report read its whole period was not recorded: a report that states a condition at the time it
    # ran compares with it (history.previous_values); one that counts a period does not take it for its previous.
    inp = BuildInput(ctx=ctx, params=ReportParams(report_type=LATERAL), start=datetime(2026, 10, 20, tzinfo=UTC),
                     end=datetime(2026, 10, 27, tzinfo=UTC), lang=Language.EN, tz=UTC, now=NOW, pce_label="p")
    assert history.previous_values(inp) == {"k": 5, "none": None}
    b = _make(ctx, monkeypatch, 8, date(2026, 10, 20), date(2026, 10, 26))
    assert {k["key"]: k["previous"] for k in _row(ctx, b).kpis}["k"] is None


def test_numbers_of_a_report_with_time_missing_are_not_the_next_ones_previous(ctx, monkeypatch):
    """Codex review 2026-11-27: a count over a period with a collection gap, kept and compared with a whole period,
    would show as growth."""
    def gappy(inp: BuildInput) -> ReportDocument:
        gap = (inp.start, inp.start + timedelta(hours=5), "ingest_failed")
        return _valued(10)(inp).model_copy(update={"caveats": generate.gap_caveats([gap], inp.lang)})
    reg = {t: ReportSpec(report_type=t, group="lateral", needs_traffic=False, build=gappy) for t in ReportType}
    monkeypatch.setattr(registry, "REGISTRY", reg)
    _queue(ctx, period_from=date(2026, 10, 13), period_to=date(2026, 10, 19))
    generate.run_queued(ctx, now=NOW)
    with ctx.db() as conn:
        assert [tuple(r) for r in conn.execute("SELECT complete FROM report_kpi_history")] == [(0,)]
    b = _make(ctx, monkeypatch, 100, date(2026, 10, 20), date(2026, 10, 26))
    assert {k["key"]: k["previous"] for k in _row(ctx, b).kpis}["k"] is None
    with ctx.db() as conn:  # and a whole report after a gappy one starts clean: the flag is each report's own
        assert sorted(tuple(r) for r in conn.execute("SELECT complete FROM report_kpi_history")) == [(0,), (1,)]


def test_a_report_to_be_emailed_is_never_seen_finished_without_its_email_going_out(ctx, monkeypatch):
    """Codex review 2026-11-27: "done" and "sending" were two changes; the check on the schedules' reports reading
    in between took the report for one that is over, and a failed send then raised no alert."""
    _register(monkeypatch, FakeBuilder())
    seen = []

    def deliver(c, report_id, doc, params, files, *, tz):
        with c.db() as conn:
            seen.append((store.get(conn, report_id).email_status, [r.id for r in store.unchecked_schedule_reports(conn)]))
            store.set_email(conn, report_id, status="failed", detail="x")
    monkeypatch.setattr(generate, "deliver", deliver)
    real = store.record_kpis

    def between(conn, **kw):  # what runs between "done" and the send
        seen.append((store.get(conn, rid).email_status, [r.id for r in store.unchecked_schedule_reports(conn)]))
        real(conn, **kw)
    monkeypatch.setattr(store, "record_kpis", between)
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL, email=True), trigger="schedule", schedule_id="s1",
                           now=NOW)
    generate.run_queued(ctx, now=NOW)
    assert seen == [("sending", []), ("sending", [])]
    with ctx.db() as conn:
        assert [r.id for r in store.unchecked_schedule_reports(conn)] == [rid]


def test_a_moved_pce_keeps_its_numbers(ctx, monkeypatch):
    _make(ctx, monkeypatch, 5, date(2026, 10, 13), date(2026, 10, 19))
    old = generate.pce_target(ctx.settings.current().pce)
    with ctx.db() as conn:
        store.move_pce(conn, old_target=old, new_target="https://new#1")
        conn.commit()
        assert [r[0] for r in conn.execute("SELECT pce_target FROM report_kpi_history")] == ["https://new#1"]


# ── calendar months ──────────────────────────────────────────────────────────

PLUS8 = timezone(timedelta(hours=8))


def test_a_whole_month_compares_with_the_month_before():
    oct_ = (datetime(2026, 9, 30, 16, tzinfo=UTC), datetime(2026, 10, 31, 16, tzinfo=UTC))  # October in +08:00
    assert generate.whole_month(*oct_, PLUS8) and not generate.whole_month(*oct_, UTC)
    assert generate.previous_period(*oct_, PLUS8) == (datetime(2026, 8, 31, 16, tzinfo=UTC), oct_[0])  # September
    week = (datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC))
    assert generate.previous_period(*week, UTC) == (datetime(2026, 10, 13, tzinfo=UTC), week[0])
    sep = generate.previous_period(*oct_, PLUS8)
    assert generate.comparable(*sep, *oct_, PLUS8)  # 30 days before 31: the month before
    assert not generate.comparable(oct_[0] - timedelta(days=31), oct_[0], *oct_, PLUS8)  # 31 days that are no month
    # 1–30 May is 30 days, not a month: its previous period is the 30 days before, which April happens to be
    may = (datetime(2026, 5, 1, tzinfo=UTC), datetime(2026, 5, 31, tzinfo=UTC))
    assert generate.comparable(datetime(2026, 4, 1, tzinfo=UTC), may[0], *may, UTC)


def test_a_previous_month_schedule_covers_the_month_before_the_one_it_was_due_in(ctx, monkeypatch):
    _register(monkeypatch, FakeBuilder())
    s = sched(frequency="monthly", day_of_month=1, hour=9, minute=30, period="previous_month")
    ctx.settings.update(ctx.settings.current().revision,
                        lambda d: d["reports"].update(schedules=[s.model_dump(mode="json")]))
    schedules.tick_schedules(ctx, now=datetime(2026, 10, 20, tzinfo=UTC))  # first sight: counts from here
    (rid,) = schedules.tick_schedules(ctx, now=datetime(2026, 11, 1, 9, 31, tzinfo=UTC))
    row = _row(ctx, rid)
    assert (row.period_start, row.period_end) == (datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC))
    assert row.status is ReportStatus.QUEUED


def test_the_month_is_decided_by_the_due_time_not_by_when_the_run_is_made(ctx):
    late = sched(frequency="monthly", day_of_month=31, hour=23, minute=59, period="previous_month")
    due = datetime(2026, 10, 31, 23, 59, tzinfo=UTC)  # picked up after midnight, on 1 November
    p = schedules.params_of(late, due=due, tz=UTC)
    assert (p.period_from, p.period_to) == (date(2026, 9, 1), date(2026, 9, 30))
    days = schedules.params_of(sched(), due=due, tz=UTC)
    assert days.period_from is None and days.lookback_days == 7


def test_the_previous_month_is_a_monthly_schedules_period():
    with pytest.raises(ValidationError):
        sched(period="previous_month")  # daily
    assert sched().period == "days"  # a schedule saved before the field existed


def test_an_email_that_breaks_while_sending_is_recorded_failed_not_left_sending(ctx, monkeypatch):
    """Left at "sending", the report would wait for the next restart and the check on the schedules' reports for
    an email that is not going out."""
    _register(monkeypatch, FakeBuilder())

    def broken(*a, **kw):
        raise OSError("report file vanished")
    monkeypatch.setattr(generate, "deliver", broken)
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL, email=True), trigger="schedule", schedule_id="s1",
                           now=NOW)
    assert generate.run_queued(ctx, now=NOW) == rid  # the job does not fail for it
    row = _row(ctx, rid)
    assert (row.status, row.email_status) == (ReportStatus.DONE, "failed") and "report file vanished" in row.email_detail
    with ctx.db() as conn:
        assert [r.id for r in store.unchecked_schedule_reports(conn)] == [rid]


def test_a_builder_can_say_its_answer_is_a_part(ctx, monkeypatch):
    """A PCE answer that stopped at its row limit (policy usage, readiness): a floor is not kept to compare with."""
    def floor(inp: BuildInput) -> ReportDocument:
        generate.part_missing()
        return _valued(10)(inp)
    reg = {t: ReportSpec(report_type=t, group="lateral", needs_traffic=False, build=floor) for t in ReportType}
    monkeypatch.setattr(registry, "REGISTRY", reg)
    _queue(ctx, period_from=date(2026, 10, 13), period_to=date(2026, 10, 19))
    generate.run_queued(ctx, now=NOW)
    b = _make(ctx, monkeypatch, 100, date(2026, 10, 20), date(2026, 10, 26))
    assert {k["key"]: k["previous"] for k in _row(ctx, b).kpis}["k"] is None


# ── second review round (Codex, 2026-11-27) ──────────────────────────────────

def test_marking_a_report_looked_at_does_not_mark_one_that_took_its_id_since(ctx):
    with ctx.db() as conn:
        old = store.insert(conn, report_type="audit", params_json="{}", status=ReportStatus.FAILED, trigger="schedule",
                           schedule_id="s1", pce_label="p", period_start=NOW, period_end=NOW, created_at=NOW)
        looked_at = [(r.id, r.created_at) for r in store.unchecked_schedule_reports(conn)]
        store.delete(conn, [old])
        new = store.insert(conn, report_type="audit", params_json="{}", status=ReportStatus.FAILED,
                           trigger="schedule", schedule_id="s1", pce_label="p", period_start=NOW, period_end=NOW,
                           created_at=NOW + timedelta(seconds=30))
        assert new == old  # SQLite gave the deleted report's id to the next one
        store.mark_checked(conn, looked_at)
        assert [r.id for r in store.unchecked_schedule_reports(conn)] == [new]
        store.mark_checked(conn, [(new, NOW + timedelta(seconds=30))])
        assert store.unchecked_schedule_reports(conn) == []


def test_key_numbers_that_cannot_be_kept_do_not_stop_the_email(ctx, monkeypatch):
    _register(monkeypatch, FakeBuilder())
    sent = []
    monkeypatch.setattr(generate, "deliver", lambda c, rid, *a, **kw: sent.append(rid))

    def locked(conn, **kw):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(store, "record_kpis", locked)
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL, email=True), trigger="schedule", schedule_id="s1",
                           now=NOW)
    assert generate.run_queued(ctx, now=NOW) == rid and sent == [rid]
    assert _row(ctx, rid).status is ReportStatus.DONE


def test_a_report_of_a_state_does_not_compare_with_a_number_known_to_be_a_part(ctx):
    target = generate.pce_target(ctx.settings.current().pce)
    inp = BuildInput(ctx=ctx, params=ReportParams(report_type=ReportType.READINESS),
                     start=datetime(2026, 10, 20, tzinfo=UTC), end=datetime(2026, 10, 27, tzinfo=UTC), lang=Language.EN,
                     tz=UTC, now=NOW, pce_label="p")
    for complete, expected in ((False, None), (None, {"predicted_blocked": 100}), (True, {"predicted_blocked": 100})):
        with ctx.db() as conn:
            store.record_kpis(conn, report_type="readiness", pce_target=target,
                              match_json=history.match_key(inp.params.model_dump(mode="json")),
                              period_start=datetime(2026, 10, 13, tzinfo=UTC), period_end=inp.start,
                              kpis=[{"key": "predicted_blocked", "value": 100}], at=NOW, complete=complete)
        assert history.previous_values(inp) == expected, complete
