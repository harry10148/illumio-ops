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
from tests.services.collect.conftest import configured_ctx
from tests.services.reports.test_findings import decided_and_not, flow

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
    rows = {r[0]: (r[1], r[3]) for r in _table(doc, "decisions").rows}
    assert rows["Allowed (a rule allows it)"] == (2, 7) and rows["Potentially Blocked (blocked once enforcement starts)"] == (1, 5) and rows["Blocked"] == (1, 1)
    kpis = {k.key: k.value for k in doc.kpis}
    assert kpis["flows"] == 4 and kpis["connections"] == 13


def test_inbound_single_definition(ctx):
    # Into a managed host = the destination is managed, whoever started it (5.x had three definitions).
    _write(ctx, [flow(port=443, unmanaged_src=True), flow(port=443), flow(port=443, unmanaged_dst=True)])
    row = next(r for r in _table(_build(ctx), "decisions").rows if r[0] == "Allowed (a rule allows it)")
    assert row[4] == 2 and row[5] == "66.7%"


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
    first = doc.findings[0]
    assert first.title == "Ransomware Risk Port (High)" and "1 allowed flows" in first.what
    assert first.why == "These remote-access ports let someone outside keep control of a host."
    assert first.action_code == "narrow_rules" and first.action_short
    # a rule that fired is a finding, never a row of the closing section
    assert not any(r[0] == "B002" for s in doc.sections if s.id == "findings" for r in s.blocks[0].rows)


def test_every_rule_that_fired_is_a_finding_and_the_closing_section_holds_only_the_unevaluated(ctx):
    """Stage 3a: every rule that fired is a finding (6.6.0 showed the first five and listed the rest at the end);
    the closing section lists only the rules that could not be evaluated."""
    from illumio_ops.services.reports import findings, flowsections
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["reports"]["rule_thresholds"].update(
        unmanaged_connection=1, lateral_outbound_dst=1, cross_env_connection=1, discovery_protocol=1, pb_lateral=1))
    _write(ctx, [flow(port=5900), flow(port=445, src_env="Dev", dst_env="Prod"), flow(port=1433, unmanaged_src=True),
                 flow(port=22, decision="potentially_blocked"), flow(port=137, proto=17), flow(port=23, decision="blocked"),
                 flow(src="jump", dst="t1", port=22), flow(src="jump", dst="t2", port=22)])
    doc = _build(ctx)
    outcomes = findings.run_rules(ctx, flowsections.window(_inp(ctx)), ctx.settings.current().reports.rule_thresholds,
                                  Language.EN, now=NOW)
    fired = [o for o in outcomes if o.severity is not None]
    assert len(fired) > 5 and len(doc.findings) == len(fired)
    assert [f.severity for f in doc.findings] == [o.severity for o in fired]  # most severe first, as ranked
    rows = _table(doc, "findings").rows
    assert [r[0] for r in rows] == ["L006"]  # no exposure graph here: the one rule not evaluated
    assert not {r[1] for r in rows} & {f.title for f in doc.findings}


def test_no_closing_section_when_every_rule_was_evaluated(ctx):
    from illumio_ops.store.flowdb import analysis
    _write(ctx, [flow(port=5900)])
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "exposure", params={}, at=NOW, result={"hosts": []})
        conn.commit()
    doc = _build(ctx)
    assert len(doc.findings) == 1 and "findings" not in {s.id for s in doc.sections}


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
    assert doc.title and doc.findings[0].title == "勒索軟體高風險遠端存取 port"


def test_protocol_distribution(ctx):
    _write(ctx, [flow(port=443, conns=3), flow(port=22, conns=1), flow(port=53, proto=17, conns=6)])
    sec = _section(_build(ctx), "services")
    proto = next(b for b in sec.blocks if isinstance(b, TableBlock) and b.columns[0].key == "proto")
    rows = {r[0]: r[1:] for r in proto.rows}
    assert rows["UDP"][:2] == (1, 6) and rows["TCP"][:2] == (2, 4) and rows["UDP"][2] == "60.0%"
    assert proto.rows[0][0] == "UDP"  # most connections first


def test_bandwidth_and_bytes_per_connection(ctx):
    """5.x mod11: Mbps where the flow's span is known (bytes over first to last detection, a lower bound), bytes per
    connection, and the data volume by app pair."""
    _write(ctx, [flow(dst="big", port=443, bytes_=50 * 1024 * 1024, conns=2),
                 flow(dst="small", port=443, bytes_=3000, conns=3, src_app="Batch"), flow(port=22, src_app="Quiet")])
    sec = _section(_build(ctx), "bytes")
    tables = {b.columns[-1].key: b for b in sec.blocks if isinstance(b, TableBlock)}
    rate = tables["mbps"]
    assert rate.rows[0][1] == "big" and rate.rows[0][-1] == "1.398" and rate.total_rows == 2
    per_conn = tables["per_conn"]
    assert [r[1] for r in per_conn.rows] == ["big", "small"] and per_conn.rows[1][-1] == 1000
    apps = next(b for b in sec.blocks if isinstance(b, TableBlock) and b.columns[0].key == "src_app")
    assert [r[:2] for r in apps.rows] == [("Web", "DB"), ("Batch", "DB")]  # no row for a pair without byte data
    text = " ".join(p for b in sec.blocks if isinstance(b, TextBlock) for p in b.paragraphs)
    assert "2 of 2" in text and "lower bound" in text and "highest here: 1.398 Mbps" in text


def test_undecided_flows_are_counted_under_the_table_and_days_are_drawn(ctx):
    """Stage 3b: the flows without a decision are no row of the table; a sentence under it says how many there are
    and where they are listed. A period seen on more than one day draws its connections per day (every connection,
    with or without a decision), which add up to the total."""
    from datetime import timedelta

    from illumio_ops.domain.report import BarBlock
    a, b = flow(port=443, conns=3), flow(port=22, decision="unknown", conns=2)
    object.__setattr__(b, "last_detected", b.last_detected + timedelta(days=1))
    _write(ctx, [a, b])
    doc = _build(ctx)
    sec = _section(doc, "decisions")
    words = " ".join(p for blk in sec.blocks if isinstance(blk, TextBlock) for p in blk.paragraphs)
    assert "Flows without one: 1 (connections: 2); see “Traffic that can only be watched”." in words
    named = [r[0] for r in _table(doc, "decisions").rows]
    assert named[0] == "Allowed (a rule allows it)" and "Unknown" not in named and len(named) == 3
    bars = next(blk for blk in sec.blocks if isinstance(blk, BarBlock))
    assert [v for _, v in bars.points] == [3, 2] and sum(v for _, v in bars.points) == 5


def test_one_day_of_traffic_draws_no_trend_and_no_unknown_note(ctx):
    from illumio_ops.domain.report import BarBlock
    _write(ctx, [flow(port=443)])
    sec = _section(_build(ctx), "decisions")
    assert not [b for b in sec.blocks if isinstance(b, (BarBlock, TextBlock))]


# ── stage 3b: a share counts only the flows the PCE gave a decision for ──────────────────────────────────────

NO_DECIDED = "No flow in this period carries a decision, so no share can be worked out."


def test_decision_table_is_the_three_decisions_with_their_share_of_the_decided_flows(ctx):
    _write(ctx, decided_and_not())
    doc = _build(ctx)
    table = _table(doc, "decisions")
    assert [c.key for c in table.columns] == ["decision", "flows", "share", "connections", "into_managed",
                                              "into_managed_pct"]
    assert [r[:4] for r in table.rows] == [
        ("Allowed (a rule allows it)", 3, "75.0%", 10),
        ("Potentially Blocked (blocked once enforcement starts)", 1, "25.0%", 30), ("Blocked", 0, "0.0%", 0)]
    assert sum(float(r[2].rstrip("%")) for r in table.rows) == 100.0
    words = " ".join(p for b in _section(doc, "decisions").blocks if isinstance(b, TextBlock) for p in b.paragraphs)
    assert words == ("Shares count only the flows with a decision. Flows without one: 2 (connections: 60); see "
                     "“Traffic that can only be watched”.")
    kpis = {k.key: k.value for k in doc.kpis}
    assert kpis["flows"] == 6 and kpis["connections"] == 100  # what was seen keeps the flows without a decision


def test_a_period_with_no_decided_flow_has_an_empty_decision_table_that_says_why(ctx):
    _write(ctx, [flow(port=443, decision="unknown", conns=5), flow(port=22, decision="unknown", conns=5)])
    doc = _build(ctx)
    table = _table(doc, "decisions")
    assert table.rows == () and table.empty_text == NO_DECIDED
    words = " ".join(p for b in _section(doc, "decisions").blocks if isinstance(b, TextBlock) for p in b.paragraphs)
    assert "Flows without one: 2 (connections: 10)" in words
    assert {k.key: k.value for k in doc.kpis}["flows"] == 2


def test_zh_decided_note(ctx):
    _write(ctx, decided_and_not())
    doc = _build(ctx, lang=Language.ZH_TW)
    words = " ".join(p for b in _section(doc, "decisions").blocks if isinstance(b, TextBlock) for p in b.paragraphs)
    assert words == "比例只算有判定的流量；沒有判定的 2 筆（60 次連線）見〈只能監看的流量〉。"
