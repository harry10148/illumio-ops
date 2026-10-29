"""The traffic report (P5b-1 Task 3): flows and connections by decision, rankings by label, service and bytes,
the unmanaged summary and the rule engine's findings — every number from the flow store's primary rows."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.filter import EndpointFilter, FlowCondition, LabelCond
from illumio_ops.domain.report import TableBlock, TextBlock
from illumio_ops.domain.values import DataOrigin, IngestSource, Language, ReportType
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.services.collect.conftest import configured_ctx
from tests_v6.services.reports.test_findings import flow

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)


def _inp(ctx, *, cond=None, lang=Language.EN):
    return BuildInput(ctx=ctx, params=ReportParams(report_type=ReportType.TRAFFIC, filter=cond), start=START,
                      end=END, lang=lang, tz=UTC, now=NOW, pce_label="pce")


def _build(ctx, **kw):
    return specs()[ReportType.TRAFFIC].build(_inp(ctx, **kw))


def _write(ctx, flows):
    with ctx.flows().connect() as conn:
        upsert_flows(conn, flows, origin=DataOrigin.INGEST, now=NOW)


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _table(doc, sid, i=0):
    return [b for b in _section(doc, sid).blocks if isinstance(b, TableBlock)][i]


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


def test_decision_table_flows_and_connections(ctx):
    _write(ctx, [flow(port=443, conns=3), flow(port=443, conns=4), flow(port=22, decision="potentially_blocked", conns=5),
                 flow(port=23, decision="blocked", conns=1)])
    doc = _build(ctx)
    rows = {r[0]: r[1:3] for r in _table(doc, "decisions").rows}
    assert rows["Allowed"] == (2, 7) and rows["Potentially blocked"] == (1, 5) and rows["Blocked"] == (1, 1)
    kpis = {k.key: k.value for k in doc.kpis}
    assert kpis["flows"] == 4 and kpis["connections"] == 13


def test_inbound_single_definition(ctx):
    # Into a managed host = the destination is managed, whoever started it (5.x had three definitions).
    _write(ctx, [flow(port=443, unmanaged_src=True), flow(port=443), flow(port=443, unmanaged_dst=True)])
    row = next(r for r in _table(_build(ctx), "decisions").rows if r[0] == "Allowed")
    assert row[3] == 2 and row[4] == "66.7%"


def test_bytes_section_states_coverage(tmp_path):
    a = configured_ctx(tmp_path / "a")
    _write(a, [flow(dst="big", port=443, bytes_=5000), flow(port=443)])
    sec = _section(_build(a), "bytes")
    assert "50.0%" in sec.intro and next(b for b in sec.blocks if isinstance(b, TableBlock)).rows
    b = configured_ctx(tmp_path / "b")
    _write(b, [flow(port=443)])
    sec = _section(_build(b), "bytes")
    assert not any(isinstance(x, TableBlock) for x in sec.blocks)
    assert any(isinstance(x, TextBlock) and "byte" in x.paragraphs[0].lower() for x in sec.blocks)


def test_findings_from_rules(ctx):
    _write(ctx, [flow(port=5900)])
    doc = _build(ctx)
    assert doc.findings[0].title == "Ransomware Risk Port (High)" and "1 allowed flows" in doc.findings[0].why
    assert any("B002" in str(r[0]) for r in _table(doc, "findings").rows)


def test_rule_error_shown_as_not_evaluated(ctx, monkeypatch):
    from illumio_ops.services.reports import findings

    def boom(*a, **k):
        raise RuntimeError("bad rule")
    monkeypatch.setitem(findings.RULE_FUNCTIONS, "B005", boom)
    _write(ctx, [flow(port=443)])
    rows = _table(_build(ctx), "findings").rows
    assert any(r[0] == "B005" and "RuntimeError: bad rule" in " ".join(map(str, r)) for r in rows)


def test_previous_none_without_collection(ctx):
    _write(ctx, [flow(port=443)])
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, START, END)
        conn.commit()
    assert all(k.previous is None for k in _build(ctx).kpis)
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, START - (END - START), START)
        conn.commit()
    assert {k.key: k.previous for k in _build(ctx).kpis}["flows"] == 0


def test_filter_with_no_flows_says_so(ctx):
    _write(ctx, [flow(port=443)])
    cond = FlowCondition(dst=EndpointFilter(labels=(LabelCond(key="app", values=("Nope",)),)))
    doc = _build(ctx, cond=cond)
    assert all(k.value is None and k.note for k in doc.kpis)
    assert any("Destination app = Nope" in q for q in doc.data_quality)
    assert "filter" in _table(doc, "services").empty_text.lower()


def test_unmanaged_summary(ctx):
    _write(ctx, [flow(port=443, unmanaged_src=True), flow(port=443, unmanaged_dst=True), flow(port=443)])
    text = " ".join(p for b in _section(_build(ctx), "unmanaged").blocks if isinstance(b, TextBlock)
                    for p in b.paragraphs)
    assert "Of 3 flows, 1 came from" in text and "1 went to" in text


def test_lookback_reaches_the_ondemand_limit(ctx):
    """Past the kept 35 days the period is pulled from the PCE (spec §6.4): 90 days, the request's own limit."""
    assert specs()[ReportType.TRAFFIC].max_lookback(ctx.settings.current()) == 90


def test_zh_tw_builds(ctx):
    _write(ctx, [flow(port=5900)])
    doc = _build(ctx, lang=Language.ZH_TW)
    assert doc.title and doc.findings[0].title == "勒索軟體高風險遠端存取 Port"
