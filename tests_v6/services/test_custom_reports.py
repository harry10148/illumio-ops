"""Custom reports (P6e, spec §6.5.5): sections saved from the workbench without their period, made into the same
analysis segments the workbench runs when a report is made; bounded; not deleted while a schedule uses one."""
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from illumio_ops.domain.filter import EndpointFilter, FlowCondition
from illumio_ops.domain.segment import EventSegment, FlowSegment, GroupBy
from illumio_ops.domain.values import SegmentView
from illumio_ops.services import custom_reports as cr
from illumio_ops.services.workbench import EventRequest, FlowRequest
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)
COND = FlowCondition(dst=EndpointFilter(hrefs=("/orgs/1/workloads/db",)))


def _ranking(**kw):
    return FlowRequest(mode="flows", start=NOW - timedelta(days=1), end=NOW, view="ranking", condition=COND,
                       group_by=(GroupBy(dimension="src_host"),), **kw)


def _events():
    return EventRequest(mode="events", start=NOW - timedelta(days=1), end=NOW, view="detail",
                        event_types=("agent.tampering",))


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


def test_section_saved_without_its_period_and_remade(ctx):
    rep = cr.add_section(ctx, report_id=None, name="DB watch", title="Who reaches db", request=_ranking(), by="admin",
                         now=NOW)
    [sec] = rep.sections
    assert (rep.name, sec.title, sec.segment.mode, sec.segment.view) == ("DB watch", "Who reaches db", "flows", "ranking")
    start, end = NOW - timedelta(days=30), NOW
    seg = sec.segment.materialize(start, end)
    assert isinstance(seg, FlowSegment) and (seg.filter.start, seg.filter.end) == (start, end)
    assert seg.filter.dst.hrefs == ("/orgs/1/workloads/db",) and seg.group_by[0].dimension == "src_host"
    rep = cr.add_section(ctx, report_id=rep.id, name=None, title="Tampering", request=_events(), by="admin", now=NOW)
    ev = rep.sections[1].segment.materialize(start, end)
    assert isinstance(ev, EventSegment) and ev.filter.event_types == ("agent.tampering",)
    assert [r.name for r in cr.list_reports(ctx)] == ["DB watch"]


def test_limits_bounded_and_said(ctx):
    rep = cr.add_section(ctx, report_id=None, name="Big", title="t", request=_ranking(limit=1000), by="a", now=NOW)
    assert rep.sections[0].segment.limit == cr.RANKING_MAX
    with pytest.raises(ValueError):
        cr.add_section(ctx, report_id=None, name="x" * (cr.TITLE_MAX + 1), title="t", request=_ranking(), by="a",
                       now=NOW)
    for i in range(cr.SECTIONS_MAX - 1):
        cr.add_section(ctx, report_id=rep.id, name=None, title=f"s{i}", request=_ranking(), by="a", now=NOW)
    with pytest.raises(ValueError):
        cr.add_section(ctx, report_id=rep.id, name=None, title="one too many", request=_ranking(), by="a", now=NOW)


def test_predicted_view_not_saved(ctx):
    with pytest.raises((ValueError, ValidationError)):
        cr.CustomSegment(mode="flows", view=SegmentView.PREDICTED_BLOCK, limit=10)


def test_remove_rename_delete(ctx):
    rep = cr.add_section(ctx, report_id=None, name="R", title="a", request=_ranking(), by="a", now=NOW)
    rep = cr.add_section(ctx, report_id=rep.id, name=None, title="b", request=_events(), by="a", now=NOW)
    rep = cr.remove_section(ctx, rep.id, 0, now=NOW)
    assert [s.title for s in rep.sections] == ["b"]
    assert cr.rename(ctx, rep.id, "R2", now=NOW).name == "R2"
    cr.delete(ctx, rep.id)
    assert cr.list_reports(ctx) == [] and cr.get(ctx, rep.id) is None


def test_not_deleted_while_scheduled(ctx):
    rep = cr.add_section(ctx, report_id=None, name="R", title="a", request=_ranking(), by="a", now=NOW)

    def add(d):
        d["reports"]["schedules"] = [*d["reports"]["schedules"], {
            "id": "a" * 32, "name": "Nightly R", "enabled": True, "report_type": "custom", "lookback_days": 7,
            "custom_id": rep.id, "frequency": "daily", "day_of_week": None, "day_of_month": None, "hour": 1,
            "minute": 0, "formats": ["html"], "email": False, "recipients": [], "lang": None, "keep": 5}]
    ctx.settings.update(ctx.settings.current().revision, add)
    with pytest.raises(cr.InUse) as exc:
        cr.delete(ctx, rep.id)
    assert exc.value.schedules == ["Nightly R"]


def test_needs_traffic_only_with_a_flow_section(ctx):
    rep = cr.add_section(ctx, report_id=None, name="Events", title="e", request=_events(), by="a", now=NOW)
    assert not cr.needs_traffic(ctx, rep.id)
    cr.add_section(ctx, report_id=rep.id, name=None, title="f", request=_ranking(), by="a", now=NOW)
    assert cr.needs_traffic(ctx, rep.id)


def test_workbench_request_for_a_section(ctx):
    rep = cr.add_section(ctx, report_id=None, name="R", title="a", request=_ranking(), by="a", now=NOW)
    seg = rep.sections[0].segment
    assert isinstance(seg.request(NOW - timedelta(days=7), NOW), FlowRequest)
    assert seg.request(NOW - timedelta(days=60), NOW) is None  # longer than the workbench's 30 days: no link


# ── the report ───────────────────────────────────────────────────────────────

def _flows_store(ctx):
    from illumio_ops.domain.values import DataOrigin
    from illumio_ops.store.flowdb.flows import upsert_flows
    from tests_v6.services.reports.test_findings import flow
    with ctx.flows().connect() as conn:
        upsert_flows(conn, [flow(src="adm", dst="db", port=3389), flow(src="bak", dst="db", port=445),
                            flow(src="adm", dst="db", port=22)], origin=DataOrigin.INGEST, now=NOW)
        conn.commit()


def _make(ctx, report_id, *, gui=""):
    from illumio_ops.domain.values import Language, ReportType
    from illumio_ops.services.reports.custom import build_custom
    from illumio_ops.services.reports.registry import BuildInput, ReportParams
    if gui:
        ctx.settings.update(ctx.settings.current().revision, lambda d: d["reports"].update(gui_external_url=gui))
    params = ReportParams(report_type=ReportType.CUSTOM, custom_id=report_id, lookback_days=7)
    return build_custom(BuildInput(ctx=ctx, params=params, start=datetime(2026, 10, 20, tzinfo=UTC),
                                   end=datetime(2026, 10, 27, tzinfo=UTC), lang=Language.EN, tz=None, now=NOW,
                                   pce_label="lab"))


def test_report_runs_each_section_on_its_period(ctx):
    _flows_store(ctx)
    cond = FlowCondition(dst=EndpointFilter(hrefs=("/orgs/1/workloads/db",)))
    req = FlowRequest(mode="flows", start=NOW - timedelta(days=1), end=NOW, view="ranking", condition=cond,
                      group_by=(GroupBy(dimension="src_host"),))
    rep = cr.add_section(ctx, report_id=None, name="DB watch", title="Who reaches db", request=req, by="a", now=NOW)
    rep = cr.add_section(ctx, report_id=rep.id, name=None, title="Connections", request=FlowRequest(
        mode="flows", start=NOW - timedelta(days=1), end=NOW, view="detail", condition=cond), by="a", now=NOW)
    rep = cr.add_section(ctx, report_id=rep.id, name=None, title="Tampering", request=_events(), by="a", now=NOW)
    doc = _make(ctx, rep.id, gui="https://ops.example")
    assert doc.title == "DB watch" and [s.title for s in doc.sections] == ["Who reaches db", "Connections", "Tampering"]
    from illumio_ops.domain.report import TableBlock
    ranking, detail, events = (next(b for b in s.blocks if isinstance(b, TableBlock)) for s in doc.sections)
    assert {r[0]: r[1] for r in ranking.rows} == {"adm": 2, "bak": 1}
    assert len(detail.rows) == 3 and events.rows == () and events.empty_text
    assert doc.sections[0].workbench_link.startswith("https://ops.example/investigate?q=")


def test_no_links_without_the_external_address(ctx):
    rep = cr.add_section(ctx, report_id=None, name="R", title="a", request=_events(), by="a", now=NOW)
    doc = _make(ctx, rep.id)
    assert doc.sections[0].workbench_link is None and doc.data_quality


def test_deleted_custom_report_fails_the_report(ctx):
    from illumio_ops.services.reports.registry import ReportFailed
    with pytest.raises(ReportFailed) as exc:
        _make(ctx, 999)
    assert exc.value.key == "rpt_err_custom_missing"


def test_refusals(ctx):
    from illumio_ops.domain.values import ReportType
    from illumio_ops.services.reports.generate import refusal
    from illumio_ops.services.reports.registry import ReportParams
    s = ctx.settings.current()
    assert refusal(s, ReportParams(report_type=ReportType.CUSTOM)) == "rpt_err_custom_required"
    assert refusal(s, ReportParams(report_type=ReportType.TRAFFIC, custom_id=1)) == "rpt_err_custom_not_supported"


def test_enqueue_refuses_an_unknown_custom_report(ctx):
    from illumio_ops.domain.values import ReportType
    from illumio_ops.services.reports import generate
    from illumio_ops.services.reports.registry import ReportParams
    from illumio_ops.store import reports as rstore
    rid = generate.enqueue(ctx, ReportParams(report_type=ReportType.CUSTOM, custom_id=42), trigger="manual",
                           schedule_id=None, now=NOW)
    with ctx.db() as conn:
        assert rstore.get(conn, rid).error_key == "rpt_err_custom_missing"


def test_event_only_report_pulls_nothing_in_lightweight(tmp_path):
    from illumio_ops.domain.values import ReportType
    from illumio_ops.services.reports.generate import pulls_on_demand
    from illumio_ops.services.reports.registry import ReportParams, specs
    light = configured_ctx(tmp_path, mode="lightweight")
    rep = cr.add_section(light, report_id=None, name="E", title="e", request=_events(), by="a", now=NOW)
    spec = specs()[ReportType.CUSTOM]
    assert not pulls_on_demand(light, spec, NOW - timedelta(days=7), NOW,
                               ReportParams(report_type=ReportType.CUSTOM, custom_id=rep.id))
    cr.add_section(light, report_id=rep.id, name=None, title="f", request=_ranking(), by="a", now=NOW)
    assert pulls_on_demand(light, spec, NOW - timedelta(days=7), NOW,
                           ReportParams(report_type=ReportType.CUSTOM, custom_id=rep.id))


def test_uncollected_period_is_not_said_as_nothing(ctx):
    """Lab acceptance 2026-10-31: an event section read "no events in the period" for a period no events were
    collected for; each section says where its data has gaps, and the report says the traffic's coverage."""
    from illumio_ops.domain.report import TextBlock
    rep = cr.add_section(ctx, report_id=None, name="R", title="Events", request=_events(), by="a", now=NOW)
    cr.add_section(ctx, report_id=rep.id, name=None, title="Flows", by="a", now=NOW,
                   request=FlowRequest(mode="flows", start=NOW - timedelta(days=1), end=NOW, view="detail"))
    doc = _make(ctx, rep.id)
    for sec in doc.sections:
        notes = [p for b in sec.blocks if isinstance(b, TextBlock) for p in b.paragraphs]
        assert notes, sec.title  # the gap is said beside the empty table
    assert any("traffic" in q.lower() or "flow" in q.lower() for q in doc.data_quality)


# ── final review (2026-10-31) ─────────────────────────────────────────────────

def test_mixed_report_reads_events_from_the_install(ctx):
    """#1: in lightweight mode a report with a flow section is built on the pulled store, which holds no events:
    the event sections read the install's events."""
    import dataclasses
    import tempfile
    from pathlib import Path

    from illumio_ops.domain.events import normalize_event
    from illumio_ops.domain.report import TableBlock
    from illumio_ops.domain.values import DataOrigin, Language, ReportType
    from illumio_ops.services.reports.custom import build_custom
    from illumio_ops.services.reports.registry import BuildInput, ReportParams
    from illumio_ops.store.flowdb.events import upsert_events
    from tests_v6.services.analysis.test_tamper import _tamper
    with ctx.flows().connect() as conn:
        upsert_events(conn, [normalize_event(_tamper(0, datetime(2026, 10, 22, tzinfo=UTC)))], origin=DataOrigin.INGEST,
                      now=NOW)
        conn.commit()
    rep = cr.add_section(ctx, report_id=None, name="R", title="Tampering", request=_events(), by="a", now=NOW)
    cr.add_section(ctx, report_id=rep.id, name=None, title="Flows", request=_ranking(), by="a", now=NOW)
    other = configured_ctx(Path(tempfile.mkdtemp()))
    pulled = dataclasses.replace(ctx, flowdb=other.flows(), ondemand=True)  # as ondemand makes it: no events
    params = ReportParams(report_type=ReportType.CUSTOM, custom_id=rep.id, lookback_days=7)
    doc = build_custom(BuildInput(ctx=pulled, params=params, start=datetime(2026, 10, 20, tzinfo=UTC),
                                  end=datetime(2026, 10, 27, tzinfo=UTC), lang=Language.EN, tz=None, now=NOW,
                                  pce_label="lab", install=ctx))
    events = next(b for b in doc.sections[0].blocks if isinstance(b, TableBlock))
    assert len(events.rows) == 1


def test_a_deleted_reports_id_is_not_reused(ctx):
    """#2: a queued request for a deleted custom report must not make the next one created."""
    a = cr.add_section(ctx, report_id=None, name="A", title="a", request=_events(), by="a", now=NOW)
    cr.delete(ctx, a.id)
    b = cr.add_section(ctx, report_id=None, name="B", title="b", request=_events(), by="a", now=NOW)
    assert b.id != a.id


def test_concurrent_saves_both_kept(ctx, monkeypatch):
    """#3: two saves into the same report at once both keep their section."""
    import threading
    import time as _time
    rep = cr.add_section(ctx, report_id=None, name="R", title="first", request=_events(), by="a", now=NOW)
    real_get = cr.store.get
    slow = threading.Event()

    def get(conn, report_id):
        row = real_get(conn, report_id)
        if threading.current_thread().name == "slow":
            slow.set()
            _time.sleep(0.4)  # another save comes in while this one holds what it read
        return row
    monkeypatch.setattr(cr.store, "get", get)
    t = threading.Thread(name="slow", target=lambda: cr.add_section(
        ctx, report_id=rep.id, name=None, title="A", request=_events(), by="a", now=NOW))
    t.start()
    assert slow.wait(5)
    cr.add_section(ctx, report_id=rep.id, name=None, title="B", request=_events(), by="a", now=NOW)
    t.join(5)
    assert sorted(s.title for s in cr.get(ctx, rep.id).sections) == ["A", "B", "first"]


def test_bytes_unknown_not_shown_as_zero(ctx):
    """#4: a bytes ranking over flows that report no bytes says the bytes are unknown, not 0."""
    from illumio_ops.domain.report import TextBlock
    _flows_store(ctx)
    req = FlowRequest(mode="flows", start=NOW - timedelta(days=1), end=NOW, view="ranking", metric="bytes",
                      group_by=(GroupBy(dimension="src_host"),))
    rep = cr.add_section(ctx, report_id=None, name="R", title="Bytes", request=req, by="a", now=NOW)
    doc = _make(ctx, rep.id)
    notes = " ".join(p for b in doc.sections[0].blocks if isinstance(b, TextBlock) for p in b.paragraphs)
    assert "byte" in notes.lower()
