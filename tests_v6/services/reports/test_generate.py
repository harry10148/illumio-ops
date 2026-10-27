"""The one report generation path (P5a Task 2): queued runs, failure semantics, files, coverage notes."""
from datetime import UTC, datetime, timedelta, timezone

import pytest

from illumio_ops.domain.report import Kpi, ReportDocument
from illumio_ops.domain.values import IngestSource, Language, ReportStatus, ReportType
from illumio_ops.services.reports import generate, registry
from illumio_ops.services.reports.registry import BuildInput, ReportParams, ReportSpec
from illumio_ops.store import reports as store
from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.db import StaleGeneration
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 27, 1, 30, tzinfo=UTC)
LATERAL = ReportType.LATERAL_POSTURE


def _doc(inp: BuildInput) -> ReportDocument:
    return ReportDocument(report_type=inp.params.report_type, lang=inp.lang, title="T", period_start=inp.start,
                          period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label,
                          kpis=(Kpi(key="k", label="K", value=1, previous=None),), findings=(), data_quality=(),
                          sections=())


class FakeBuilder:
    def __init__(self, action=None):
        self.calls: list[BuildInput] = []
        self.action = action

    def __call__(self, inp: BuildInput) -> ReportDocument:
        self.calls.append(inp)
        if self.action:
            self.action(inp)
        return _doc(inp)


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


def _register(monkeypatch, builder, *, needs_traffic=True):
    reg = {t: ReportSpec(report_type=t, group="lateral", needs_traffic=needs_traffic, build=builder)
           for t in ReportType}
    monkeypatch.setattr(registry, "REGISTRY", reg)


def _row(ctx, rid):
    with ctx.db() as conn:
        return store.get(conn, rid)


def test_manual_and_schedule_share_one_path(ctx, monkeypatch):
    b = FakeBuilder()
    _register(monkeypatch, b)
    a = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="manual", schedule_id=None, now=NOW)
    c = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="schedule", schedule_id="s1", now=NOW)
    assert generate.run_queued(ctx, now=NOW) == a
    assert generate.run_queued(ctx, now=NOW) == c
    assert generate.run_queued(ctx, now=NOW) is None
    assert len(b.calls) == 2
    row = _row(ctx, a)
    assert row.status is ReportStatus.DONE and {f.split(".")[-1] for f in row.files} == {"html", "xlsx"}
    for name in row.files:
        path = ctx.paths.reports_dir / str(a) / name
        assert path.is_file() and (path.stat().st_mode & 0o777) == 0o600
    assert row.kpis == [{"key": "k", "label": "K", "value": 1, "previous": None}]


def test_formats_respected(ctx, monkeypatch):
    _register(monkeypatch, FakeBuilder())
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL, formats=("xlsx",)), trigger="manual",
                           schedule_id=None, now=NOW)
    generate.run_queued(ctx, now=NOW)
    assert [f.rsplit(".", 1)[1] for f in _row(ctx, rid).files] == ["xlsx"]


def test_events_only_mode_fails_with_reason(tmp_path, monkeypatch):
    ctx = configured_ctx(tmp_path, mode="events_only")
    b = FakeBuilder()
    _register(monkeypatch, b)
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="schedule", schedule_id="s", now=NOW)
    row = _row(ctx, rid)
    assert row.status is ReportStatus.FAILED and row.error_key == "rpt_unavailable_events_only" and row.files == []
    assert generate.run_queued(ctx, now=NOW) is None and b.calls == []


def test_availability_lists_the_reason(tmp_path, monkeypatch):
    _register(monkeypatch, FakeBuilder())
    assert generate.availability(configured_ctx(tmp_path, mode="events_only"))[LATERAL] == \
        "rpt_unavailable_events_only"
    assert generate.availability(configured_ctx(tmp_path / "b"))[LATERAL] is None


def test_generation_change_fails_report(ctx, monkeypatch):
    def switch(inp):
        inp.ctx.flows().generation += 1
    _register(monkeypatch, FakeBuilder(switch))
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="manual", schedule_id=None, now=NOW)
    generate.run_queued(ctx, now=NOW)
    row = _row(ctx, rid)
    assert row.status is ReportStatus.FAILED and row.error_key == "rpt_err_pce_switched"
    assert not list((ctx.paths.reports_dir / str(rid)).glob("*"))


def test_stale_read_inside_builder_fails_report(ctx, monkeypatch):
    def stale(inp):
        raise StaleGeneration
    _register(monkeypatch, FakeBuilder(stale))
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="manual", schedule_id=None, now=NOW)
    generate.run_queued(ctx, now=NOW)
    assert _row(ctx, rid).error_key == "rpt_err_pce_switched"


def test_builder_error_leaves_no_files(ctx, monkeypatch):
    def boom(inp):
        raise RuntimeError("disk on fire " + "x" * 900)
    _register(monkeypatch, FakeBuilder(boom))
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="manual", schedule_id=None, now=NOW)
    generate.run_queued(ctx, now=NOW)
    row = _row(ctx, rid)
    assert row.status is ReportStatus.FAILED and row.error_key == "rpt_err_internal"
    assert row.error_detail.startswith("RuntimeError: disk on fire") and len(row.error_detail) <= 500
    assert not (ctx.paths.reports_dir / str(rid)).exists() or not list((ctx.paths.reports_dir / str(rid)).iterdir())


def test_running_rows_requeued_after_restart(ctx, monkeypatch):
    _register(monkeypatch, FakeBuilder())
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="manual", schedule_id=None, now=NOW)
    with ctx.db() as conn:
        store.claim_next(conn, at=NOW)
    assert _row(ctx, rid).status is ReportStatus.RUNNING
    assert generate.recover_running(ctx) == 1
    assert generate.run_queued(ctx, now=NOW) == rid and _row(ctx, rid).status is ReportStatus.DONE


def test_lang_defaults_to_display_language(ctx, monkeypatch):
    b = FakeBuilder()
    _register(monkeypatch, b)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["display"].update(language="zh_TW"))
    generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="manual", schedule_id=None, now=NOW)
    generate.enqueue(ctx, ReportParams(report_type=LATERAL, lang=Language.EN), trigger="manual", schedule_id=None,
                     now=NOW)
    generate.run_queued(ctx, now=NOW)
    generate.run_queued(ctx, now=NOW)
    assert [c.lang for c in b.calls] == [Language.ZH_TW, Language.EN]


def test_period_uses_display_day_boundaries():
    s, e = generate.period(datetime(2026, 10, 27, 1, 0, tzinfo=UTC), 7, timezone(timedelta(hours=8)))
    assert e == datetime(2026, 10, 26, 16, 0, tzinfo=UTC) and s == e - timedelta(days=7)


def test_period_in_utc():
    s, e = generate.period(NOW, 1, UTC)
    assert (s, e) == (datetime(2026, 10, 26, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC))


def test_coverage_note_names_gap(ctx):
    start, end = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, start - timedelta(days=1), end)
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, datetime(2026, 10, 22, 3, tzinfo=UTC),
                                datetime(2026, 10, 22, 5, tzinfo=UTC), kind="failed", detail="x", at=NOW)
    notes = generate.coverage_note(ctx, start, end, Language.ZH_TW, now=NOW, tz=UTC)
    assert any("缺口" in n and "2026-10-22 03:00" in n for n in notes)


def test_coverage_note_partial_coverage(ctx):
    start, end = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, datetime(2026, 10, 25, tzinfo=UTC), end)
    notes = generate.coverage_note(ctx, start, end, Language.EN, now=NOW, tz=UTC)
    assert any("2026-10-25" in n for n in notes) and not any("whole period" in n for n in notes)


def test_coverage_note_whole_period(ctx):
    start, end = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, start - timedelta(days=3), end + timedelta(hours=1))
    notes = generate.coverage_note(ctx, start, end, Language.EN, now=NOW, tz=UTC)
    assert any("whole period" in n for n in notes)
