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
from tests.services.collect.conftest import configured_ctx

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


def test_lightweight_mode_queues_flow_reports(tmp_path, monkeypatch):
    """A flow report in lightweight mode is queued like any other; the run pulls its period on demand."""
    ctx = configured_ctx(tmp_path, mode="lightweight")
    _register(monkeypatch, FakeBuilder())
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="schedule", schedule_id="s", now=NOW)
    assert _row(ctx, rid).status is ReportStatus.QUEUED


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


def _gaps(ctx, windows, *, covered=True):
    start, end = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
    with ctx.flows().connect() as conn:
        if covered:
            ingest_state.add_coverage(conn, IngestSource.TRAFFIC, start - timedelta(days=1), end + timedelta(hours=1))
        for a, b, kind in windows:
            ingest_state.record_gap(conn, IngestSource.TRAFFIC, a, b, kind=kind, detail="x", at=NOW)
    return start, end


def _at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def test_two_gaps_are_one_sentence_under_the_conclusion(ctx):
    start, end = _gaps(ctx, [(_at(22, 3), _at(22, 5), "failed"), (_at(24, 10), _at(24, 13, 30), "failed")])
    got = generate.coverage_text(ctx, start, end, Language.ZH_TW, now=NOW, tz=UTC)
    assert got.caveats == ("期間內有 2 段、共 5.5 小時沒有收集到資料；明細在最後的「資料註記」。",)
    assert got.lines == generate.coverage_note(ctx, start, end, Language.ZH_TW, now=NOW, tz=UTC)
    assert sum("缺口" in line for line in got.lines) == 2
    en = generate.coverage_text(ctx, start, end, Language.EN, now=NOW, tz=UTC)
    assert len(en.caveats) == 1 and "2" in en.caveats[0] and "5.5 hours" in en.caveats[0]


def test_the_sentence_counts_every_gap_though_the_notes_list_ten(ctx):
    start, end = _gaps(ctx, [(_at(22, h), _at(22, h, 30), "failed") for h in range(12)])
    got = generate.coverage_text(ctx, start, end, Language.EN, now=NOW, tz=UTC)
    assert len(got.caveats) == 1 and ": 12," in got.caveats[0] and "6.0 hours" in got.caveats[0]
    assert sum("numbers do not include that time" in line for line in got.lines) == generate.MAX_GAP_LINES
    assert got.lines[-1] == "…and 2 more gaps."


def test_hours_of_two_gaps_over_the_same_time_are_counted_once(ctx):
    start, end = _gaps(ctx, [(_at(22, 3), _at(22, 5), "failed"), (_at(22, 4), _at(22, 6), "truncated")])
    got = generate.coverage_text(ctx, start, end, Language.EN, now=NOW, tz=UTC)
    assert ": 2," in got.caveats[0] and "3.0 hours" in got.caveats[0]  # 03:00-06:00, not 2 + 2


def test_gaps_under_a_tenth_of_an_hour_are_not_said_as_zero_hours(ctx):
    start, end = _gaps(ctx, [(_at(22, 3), _at(22, 3, 2), "failed"), (_at(23, 3), _at(23, 3, 3), "failed")])
    zh = generate.coverage_text(ctx, start, end, Language.ZH_TW, now=NOW, tz=UTC)
    assert zh.caveats == ("期間內有 2 段、共不到 0.1 小時沒有收集到資料；明細在最後的「資料註記」。",)
    en = generate.coverage_text(ctx, start, end, Language.EN, now=NOW, tz=UTC)
    assert ": 2, less than 0.1 hours in all" in en.caveats[0] and "0.0" not in en.caveats[0]
    # six minutes is 0.1 hours: said as the number
    at = datetime(2026, 10, 22, 3, tzinfo=UTC)
    assert "0.1 hours" in generate.gap_caveats([(at, at + timedelta(minutes=6), "failed")], Language.EN)[0]
    assert "less than" in generate.gap_caveats([(at, at + timedelta(minutes=5), "failed")], Language.EN)[0]


def test_no_gap_no_sentence(ctx):
    start, end = _gaps(ctx, [])
    got = generate.coverage_text(ctx, start, end, Language.EN, now=NOW, tz=UTC)
    assert got.caveats == () and any("whole period" in line for line in got.lines)


def _archive(missing):
    from illumio_ops.services import archive_read
    return archive_read.ArchiveResult(ctx=None, archived_days={}, missing_days=missing, rows=0, unreadable=0,
                                      unread_from=None)


def test_days_the_archive_lacks_are_a_second_sentence(ctx):
    res = _archive({"flows": ["2026-10-01", "2026-10-02"], "events": ["2026-10-02", "2026-10-03"]})
    got = generate.archive_caveats(("the gap sentence",), res, Language.ZH_TW)
    assert got == ("the gap sentence", "期間內有 3 天的封存讀不到；明細在最後的「資料註記」。")  # a day both lack is one day
    assert "3" in generate.archive_caveats((), res, Language.EN)[0]


def test_no_missing_day_no_sentence_and_never_a_third(ctx):
    assert generate.archive_caveats(("a",), _archive({"flows": []}), Language.EN) == ("a",)
    full = generate.archive_caveats(("a", "b"), _archive({"flows": ["2026-10-01"]}), Language.EN)
    assert full == ("a", "b")


def test_period_starts_at_display_midnight_across_dst():
    """Review: the start was the UTC end minus whole days, an hour off when the span crosses a DST change."""
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")  # DST starts 2026-03-08
    s, e = generate.period(datetime(2026, 3, 9, 12, tzinfo=UTC), 1, ny)
    assert s.astimezone(ny) == datetime(2026, 3, 8, tzinfo=ny) and e.astimezone(ny) == datetime(2026, 3, 9, tzinfo=ny)
    s7, _ = generate.period(datetime(2026, 3, 9, 12, tzinfo=UTC), 7, ny)
    assert s7.astimezone(ny).replace(tzinfo=None) == datetime(2026, 3, 2)


def test_previous_period_also_at_midnight():
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    s, e = generate.period(datetime(2026, 3, 9, 12, tzinfo=UTC), 1, ny)
    ps, pe = generate.previous_period(s, e, ny)
    assert pe == s and ps.astimezone(ny) == datetime(2026, 3, 7, tzinfo=ny)


def test_queued_report_fails_when_pce_changed_before_it_ran(ctx, monkeypatch):
    """Review: a report queued for PCE A and run after a switch to B read B's data under A's name."""
    _register(monkeypatch, FakeBuilder())
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="manual", schedule_id=None, now=NOW)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(url="https://other.example:8443"))
    generate.run_queued(ctx, now=NOW)
    row = _row(ctx, rid)
    assert row.status is ReportStatus.FAILED and row.error_key == "rpt_err_pce_switched"


def test_previous_covered_only_when_fully_collected(ctx):
    start, end = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
    assert generate.traffic_covered(ctx, start, end, now=NOW) is False  # nothing collected
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, start - timedelta(days=1), end)
    assert generate.traffic_covered(ctx, start, end, now=NOW) is True
    with ctx.flows().connect() as conn:
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, datetime(2026, 10, 22, tzinfo=UTC),
                                datetime(2026, 10, 22, 1, tzinfo=UTC), kind="failed", detail="x", at=NOW)
    assert generate.traffic_covered(ctx, start, end, now=NOW) is False


def test_report_without_pce_target_is_not_run(ctx, monkeypatch):
    """Re-review: a row queued before the column existed has pce_target '' and skipped the check."""
    _register(monkeypatch, FakeBuilder())
    with ctx.db() as conn:
        rid = store.insert(conn, report_type="lateral_posture", params_json='{"report_type": "lateral_posture"}',
                           status=ReportStatus.QUEUED, trigger="manual", schedule_id=None, pce_label="A",
                           period_start=NOW, period_end=NOW, created_at=NOW)
    generate.run_queued(ctx, now=NOW)
    assert _row(ctx, rid).error_key == "rpt_err_pce_switched"


def test_label_and_target_from_one_settings_snapshot(ctx, monkeypatch):
    """Re-review: label and target were read from two snapshots; a switch in between stored A's name with B."""
    _register(monkeypatch, FakeBuilder())
    real = ctx.settings.current
    first = real()
    other = first.model_copy(update={"pce": first.pce.model_copy(update={"url": "https://b.example:8443"})})
    calls = iter([first] + [other] * 50)
    monkeypatch.setattr(ctx.settings, "current", lambda: next(calls))
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="manual", schedule_id=None, now=NOW)
    row = _row(ctx, rid)
    assert "pce.example.com" in row.pce_label and "pce.example.com" in row.pce_target


def test_lookback_beyond_flow_retention_refused(ctx, monkeypatch):
    reg = {t: ReportSpec(report_type=t, group="analysis", needs_traffic=True, build=FakeBuilder(),
                         max_lookback=lambda s: s.collection.retention.flow_days) for t in ReportType}
    monkeypatch.setattr(registry, "REGISTRY", reg)
    ctx.settings.update(ctx.settings.current().revision,
                        lambda d: d["collection"].update(mode="alert", retention={**d["collection"]["retention"],
                                                                                    "flow_days": 3}))
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL, lookback_days=7), trigger="manual",
                           schedule_id=None, now=NOW)
    row = _row(ctx, rid)
    assert row.status is ReportStatus.FAILED and row.error_key == "rpt_err_lookback_beyond_retention"
    ok = generate.enqueue(ctx, ReportParams(report_type=LATERAL, lookback_days=3), trigger="manual",
                          schedule_id=None, now=NOW)
    assert _row(ctx, ok).status is ReportStatus.QUEUED


def test_app_required_for_app_reports(ctx, monkeypatch):
    from illumio_ops.domain.filter import EndpointFilter, FlowCondition, LabelCond
    reg = {t: ReportSpec(report_type=t, group="inventory", needs_traffic=True, build=FakeBuilder(),
                         requires_app=True, accepts_filter=True) for t in ReportType}
    monkeypatch.setattr(registry, "REGISTRY", reg)
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="manual", schedule_id=None, now=NOW)
    assert _row(ctx, rid).error_key == "rpt_err_app_required"
    cond = FlowCondition(dst=EndpointFilter(labels=(LabelCond(key="app", values=("Finance",)),)))
    rid2 = generate.enqueue(ctx, ReportParams(report_type=LATERAL, filter=cond), trigger="manual", schedule_id=None,
                            now=NOW)
    assert _row(ctx, rid2).status is ReportStatus.QUEUED


# stage 3a: the three lead numbers come first (finish), and the document knows where the console is
def _kpi_doc(report_type, keys):
    return ReportDocument(report_type=report_type, lang=Language.EN, title="T", period_start=NOW - timedelta(days=7),
                          period_end=NOW, generated_at=NOW, pce_label="pce",
                          kpis=tuple(Kpi(key=k, label=k, value=i, previous=None) for i, k in enumerate(keys)),
                          findings=(), data_quality=(), sections=())


def _finished_keys(report_type, keys):
    from illumio_ops.services.reports.finish import finish
    out = finish(_kpi_doc(report_type, keys))
    assert {k.key: k.value for k in out.kpis} == {k: i for i, k in enumerate(keys)}  # moved, never changed
    return [k.key for k in out.kpis]


def test_finish_puts_the_lead_numbers_first_and_keeps_the_rest_in_order():
    keys = ["allowed_pct", "pb_flows", "blocked_flows", "enforced_hosts_pct", "critical_high_findings", "maturity"]
    assert _finished_keys(ReportType.SECURITY_RISK, keys) == [
        "maturity", "enforced_hosts_pct", "pb_flows", "allowed_pct", "blocked_flows", "critical_high_findings"]


def test_finish_fills_a_missing_lead_number_from_the_ones_after():
    """A ransomware report with only its list has no 'priority': the first page still shows doc.kpis[:3]."""
    assert _finished_keys(ReportType.RANSOMWARE, ["org_percent", "rated_hosts", "suspicious", "safe_to_block"]) == [
        "rated_hosts", "safe_to_block", "org_percent", "suspicious"]
    assert _finished_keys(ReportType.RANSOMWARE, ["org_percent"]) == ["org_percent"]


@pytest.mark.parametrize("report_type", [ReportType.POLICY_RESOLVER, ReportType.CUSTOM])
def test_finish_leaves_the_order_of_a_type_without_lead_numbers(report_type):
    from illumio_ops.domain.conclusion import LEAD_KPIS
    assert report_type not in LEAD_KPIS
    assert _finished_keys(report_type, ["rows", "rules", "maturity", "total"]) == ["rows", "rules", "maturity", "total"]


def test_every_other_type_has_three_lead_numbers():
    from illumio_ops.domain.conclusion import LEAD_KPIS
    assert set(LEAD_KPIS) == set(ReportType) - {ReportType.POLICY_RESOLVER, ReportType.CUSTOM}
    assert all(len(keys) == 3 and len(set(keys)) == 3 for keys in LEAD_KPIS.values())


def test_finish_keeps_host_keys_only_for_the_columns_it_keeps():
    from illumio_ops.domain.report import Column, Section, TableBlock
    from illumio_ops.services.reports.finish import finish
    cols = (Column(key="src", label="S"), Column(key="blank", label="B"), Column(key="dst", label="D"))
    block = TableBlock(title="t", columns=cols, rows=(("a", "", "b"), ("c", None, "d")), total_rows=2, empty_text="-",
                       host_keys={"src": ("ka", "kc"), "blank": (None, None), "dst": ("kb", None)},
                       host_section="connections")
    doc = _kpi_doc(ReportType.TRAFFIC, []).model_copy(update={"sections": (Section(id="s", title="S", blocks=(block,)),)})
    out = finish(doc).sections[0].blocks[0]
    assert [c.key for c in out.columns] == ["src", "dst"]
    assert out.host_keys == {"src": ("ka", "kc"), "dst": ("kb", None)} and out.host_section == "connections"
    TableBlock.model_validate(out.model_dump())  # still a valid table


@pytest.mark.parametrize(("external", "base"), [("https://ops.example:5443/", "https://ops.example:5443"),
                                                ("https://ops.example/ops", "https://ops.example/ops"), ("", None)])
def test_the_document_carries_the_console_address(ctx, monkeypatch, external, base):
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["reports"].update(gui_external_url=external))
    _register(monkeypatch, FakeBuilder())
    seen = []
    real = generate._write
    monkeypatch.setattr(generate, "_write", lambda out_dir, doc, *a, **kw: (seen.append(doc), real(out_dir, doc, *a, **kw))[1])
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="manual", schedule_id=None, now=NOW)
    generate.run_queued(ctx, now=NOW)
    assert _row(ctx, rid).status is ReportStatus.DONE
    assert seen[0].gui_base == base
    assert seen[0].gui_link == (f"{base}/reports?id={rid}" if base else None)


@pytest.mark.parametrize(("external", "said"), [("", True), ("https://ops.example", False)])
def test_a_report_made_without_the_console_address_says_its_hosts_are_not_links(ctx, monkeypatch, external, said):
    """The address is on the document before finish() reads it: a report naming hosts says, in its data notes, why
    they are not links — and does not say it when they are."""
    from illumio_ops.domain.report import Column, Section, TableBlock
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["reports"].update(gui_external_url=external))
    hosts = TableBlock(title="Hosts", columns=(Column(key="host", label="Host", kind="host"),), rows=(("db",),),
                       total_rows=1, empty_text="-", host_keys={"host": ("/orgs/1/workloads/db",)}, host_section="status")

    def build(inp: BuildInput) -> ReportDocument:
        return _doc(inp).model_copy(update={"sections": (Section(id="hosts", title="Hosts", blocks=(hosts,)),)})
    _register(monkeypatch, build)
    seen = []
    real = generate._write
    monkeypatch.setattr(generate, "_write", lambda out_dir, doc, *a, **kw: (seen.append(doc), real(out_dir, doc, *a, **kw))[1])
    rid = generate.enqueue(ctx, ReportParams(report_type=LATERAL), trigger="manual", schedule_id=None, now=NOW)
    generate.run_queued(ctx, now=NOW)
    assert _row(ctx, rid).status is ReportStatus.DONE
    sentence = "The console's external address is not set, so the hosts named in this report are not links."
    assert (sentence in seen[0].data_quality) is said
    html = (ctx.paths.reports_dir / str(rid) / _row(ctx, rid).files[0]).read_text(encoding="utf-8")
    assert ('data-role="host-link" href="https://ops.example/hosts?key=%2Forgs%2F1%2Fworkloads%2Fdb#status"' in html) is not said
    assert (sentence.replace("'", "&#x27;") in html) is said  # the page escapes the apostrophe
