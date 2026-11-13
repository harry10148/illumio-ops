"""Report filters and the flow-ranking sections every traffic report is built from (P5b-1 Task 1)."""
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.filter import EndpointFilter, FlowCondition, LabelCond
from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.report import Column
from illumio_ops.domain.segment import GroupBy
from illumio_ops.domain.values import (
    DataOrigin,
    Language,
    ReportType,
    SegmentDimension,
    SegmentMetric,
)
from illumio_ops.services.reports import flowsections
from illumio_ops.services.reports.registry import BuildInput, ReportParams
from illumio_ops.store.flowdb.flows import upsert_flows
from tests.services.collect.conftest import configured_ctx, raw_flow

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
APP_FIN = FlowCondition(dst=EndpointFilter(labels=(LabelCond(key="app", values=("Finance",)),)))


def _flow(i, *, app="Finance", port=445, conns=1, day=22):
    first = datetime(2026, 10, day, 3, tzinfo=UTC)
    raw = raw_flow(i, first, first + timedelta(minutes=5), port=port)
    raw["dst"]["workload"]["labels"] = [{"key": "app", "value": app}]
    raw["num_connections"] = conns
    return normalize_flow(raw)


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path)
    with c.flows().connect() as conn:
        upsert_flows(conn, [_flow(1, conns=5), _flow(2, port=22, conns=3), _flow(3, app="HR", conns=7)],
                     origin=DataOrigin.INGEST, now=NOW)
    return c


def _inp(ctx, *, cond=None, lang=Language.EN):
    return BuildInput(ctx=ctx, params=ReportParams(report_type=ReportType.LATERAL_POSTURE, filter=cond), start=START,
                      end=END, lang=lang, tz=UTC, now=NOW, pce_label="pce")


COLS = (Column(key="svc", label="Service"), Column(key="n", label="Connections", kind="number"))


def test_filter_carried_into_segments(ctx):
    t = flowsections.ranking(_inp(ctx, cond=APP_FIN), title="By port", columns=COLS,
                             group_by=(GroupBy(dimension=SegmentDimension.SERVICE),), metric=SegmentMetric.CONNECTIONS)
    assert {r[0]: r[1] for r in t.rows} == {"445/TCP": 5, "22/TCP": 3}  # HR's 7 left out by the filter


def test_ranking_limit_disclosed(ctx):
    t = flowsections.ranking(_inp(ctx), title="By port", columns=COLS, limit=1,
                             group_by=(GroupBy(dimension=SegmentDimension.SERVICE),), metric=SegmentMetric.CONNECTIONS)
    assert len(t.rows) == 1 and t.rows[0] == ("445/TCP", 12) and t.limit_note


def test_ranking_empty_says_why(ctx):
    cond = FlowCondition(dst=EndpointFilter(labels=(LabelCond(key="app", values=("Nope",)),)))
    t = flowsections.ranking(_inp(ctx, cond=cond), title="By port", columns=COLS,
                             group_by=(GroupBy(dimension=SegmentDimension.SERVICE),), metric=SegmentMetric.CONNECTIONS)
    assert t.rows == () and "filter" in t.empty_text.lower()


def test_ranking_host_names_and_labels(ctx):
    cols = (Column(key="h", label="Host"), Column(key="n", label="Flows", kind="number"))
    t = flowsections.ranking(_inp(ctx), title="By source", columns=cols,
                             group_by=(GroupBy(dimension=SegmentDimension.SRC_HOST),), metric=SegmentMetric.FLOWS)
    assert {r[0] for r in t.rows} == {"s1", "s2", "s3"}
    t2 = flowsections.ranking(_inp(ctx), title="By app", columns=cols, metric=SegmentMetric.CONNECTIONS,
                              group_by=(GroupBy(dimension=SegmentDimension.DST_LABEL, label_key="app"),))
    assert dict(t2.rows) == {"HR": 7, "Finance": 8}


def test_unlabeled_shown_in_words(ctx):
    cols = (Column(key="a", label="App"), Column(key="n", label="Connections", kind="number"))
    t = flowsections.ranking(_inp(ctx), title="By source app", columns=cols, metric=SegmentMetric.CONNECTIONS,
                             group_by=(GroupBy(dimension=SegmentDimension.SRC_LABEL, label_key="app"),))
    assert dict(t.rows) == {"(no label)": 15}


def test_filter_text_lists_labels():
    assert flowsections.filter_text(APP_FIN, Language.EN) == "Destination app = Finance"
    assert flowsections.filter_text(None, Language.EN) is None
    two = FlowCondition(src=EndpointFilter(labels=(LabelCond(key="env", values=("Prod", "QA")),)),
                        dst=EndpointFilter(labels=(LabelCond(key="app", values=("Finance",)),)))
    assert flowsections.filter_text(two, Language.EN) == "Source env = Prod or QA; Destination app = Finance"


def test_report_params_carry_filter():
    p = ReportParams.model_validate({"report_type": "lateral_posture", "filter": APP_FIN.model_dump(mode="json")})
    assert p.filter == APP_FIN


def test_filter_text_names_every_condition_the_filter_holds():
    """5.x parity 2026-11-06: the reports filter offers the whole condition; the cover says all of it, never a part."""
    from illumio_ops.domain.filter import PortProto
    cond = FlowCondition(
        src_exclude=EndpointFilter(labels=(LabelCond(key="env", values=("Dev",)),)),
        either=EndpointFilter(ips=("10.0.0.9",), label_groups=("/lg/1",)),
        dst=EndpointFilter(ip_lists=("/ipl/1", "/ipl/2"), public=True),
        services=("/svc/1",), exclude_ports=(PortProto(port=53, proto=17),), windows_services=("wuauserv",),
        transmissions=("broadcast",), exclude_processes=("svchost.exe",), initiator_user="alice",
        exclude_system_accounts=True)
    text = flowsections.filter_text(cond, Language.EN)
    for part in ("Source is not env = Dev", "Either end: 1 hosts", "Either end: 1 label groups",
                 "Destination: 2 IP lists", "Destination: Public addresses", "Service: 1", "Port is not: 53/UDP",
                 "Windows service: wuauserv", "Transmission: Broadcast", "Process is not: svchost.exe",
                 "Initiating user: alice", "Without system accounts"):
        assert part in text, (part, text)


def test_host_in_scope_reads_label_groups_and_either_end():
    from illumio_ops.domain.lateral import HostInfo
    host = HostInfo(key="/w/1", href="/w/1", hostname="h", managed=True, labels={"env": "Prod"}, enforcement_mode="full",
                    visibility_level=None, os_id=None, ven_href=None, critical=False, admin_group=False)
    groups = {"/lg/1": ("env", frozenset({"Prod"}))}
    by_group = FlowCondition(dst=EndpointFilter(label_groups=("/lg/1",)))
    assert flowsections.host_in_scope(host, by_group, label_groups=groups)
    assert not flowsections.host_in_scope(host, by_group, label_groups={})
    either = FlowCondition(either=EndpointFilter(labels=(LabelCond(key="env", values=("Prod",)),)))
    assert flowsections.host_in_scope(host, either, label_groups={})
    assert not flowsections.host_in_scope(host, FlowCondition(either_exclude=either.either), label_groups={})


def test_an_app_report_refuses_what_it_cannot_honour():
    from illumio_ops.services.reports.registry import app_filter_ok
    assert app_filter_ok(APP_FIN)
    assert not app_filter_ok(APP_FIN.model_copy(update={"either": EndpointFilter(ips=("10.0.0.1",))}))
    assert not app_filter_ok(APP_FIN.model_copy(update={"either_exclude": EndpointFilter(ips=("10.0.0.1",))}))
    side = APP_FIN.dst.model_copy(update={"label_groups": ("/lg/1",)})
    assert not app_filter_ok(APP_FIN.model_copy(update={"dst": side}))


# ── stage 3b: the flows without a decision have a chapter of their own, and one sentence on the first page ───

def _monitor(ctx, lang=Language.EN):
    """(the period's totals, the chapter) as a flow report builds them."""
    from illumio_ops.services.analysis.context import load_lateral_context
    from illumio_ops.services.flowsource import flow_totals
    inp = BuildInput(ctx=ctx, params=ReportParams(report_type=ReportType.TRAFFIC), start=START, end=END, lang=lang,
                     tz=UTC, now=NOW, pce_label="pce")
    spec = flowsections.window(inp)
    totals = flow_totals(ctx, spec)
    hosts = load_lateral_context(ctx, now=NOW).hosts
    return totals, flowsections.monitor_only_section(inp, spec, flowsections.seen(totals), hosts=hosts)


def _tables(section):
    from illumio_ops.domain.report import TableBlock
    return {b.title: b for b in section.blocks if isinstance(b, TableBlock)}


@pytest.fixture
def sample(tmp_path):
    from tests.services.reports.test_findings import undecided_sample
    c = configured_ctx(tmp_path)
    undecided_sample(c)
    return c


def test_every_flow_decided_no_chapter_and_no_sentence(tmp_path):
    from tests.services.reports.test_findings import flow
    c = configured_ctx(tmp_path)
    with c.flows().connect() as conn:
        upsert_flows(conn, [flow(port=443), flow(port=22, decision="potentially_blocked")], origin=DataOrigin.INGEST,
                     now=NOW)
    totals, sections = _monitor(c)
    assert totals.flows == 2 and sections == ()
    assert flowsections.undecided_caveat(Language.EN, flowsections.seen(totals)) == ()


def test_the_two_kinds_add_up_to_the_undecided_flows_and_their_shares_are_of_everything_seen(sample):
    totals, (section,) = _monitor(sample)
    assert section.id == "monitor_only" and section.title == "Traffic that can only be watched"
    assert "reported no decision" in section.intro
    kinds = next(iter(_tables(section).values()))
    assert [c.key for c in kinds.columns] == ["kind", "means", "flows", "connections", "share_flows",
                                              "share_connections"]
    assert [(r[0], *r[2:]) for r in kinds.rows] == [("Neither end has a VEN", 1, 50, "11.1%", "45.9%"),
                                                    ("At least one end has a VEN", 4, 19, "44.4%", "17.4%")]
    u = totals.undecided
    assert sum(r[2] for r in kinds.rows) == u.flows == 5 and sum(r[3] for r in kinds.rows) == u.connections == 69
    assert (totals.flows, totals.connections) == (9, 109)  # the shares' denominators: every flow, every connection


def test_each_kinds_busiest_sources_and_destinations_are_host_columns(sample):
    _, (section,) = _monitor(sample)
    t = _tables(section)
    src = t["Top sources, at least one end has a VEN"]
    assert src.rows == (("left-1", 1, 10), ("db", 1, 4), ("idle-1", 1, 3), ("sel-1", 1, 2))
    assert src.columns[0].kind == "host" and src.host_section == "connections"
    assert src.host_keys == {"host": tuple(f"/orgs/1/workloads/{n}" for n in ("left-1", "db", "idle-1", "sel-1"))}
    dst = t["Top destinations, at least one end has a VEN"]
    assert dst.rows == (("db", 3, 15), ("idle-1", 1, 4)) and dst.host_section == "connections"
    lone = t["Top sources, neither end has a VEN"]
    assert len(lone.rows) == 1 and lone.rows[0][1:] == (1, 50)
    assert lone.host_keys["host"][0] == f"ip:{lone.rows[0][0]}"  # an address without a VEN is its address
    assert t["Top destinations, neither end has a VEN"].rows[0][1:] == (1, 50)
    # what the rankings add up to is what the totals counted: the same flows read twice
    assert sum(r[1] for r in src.rows) == 4 and sum(r[2] for r in src.rows) == 19


def test_a_hosts_mode_is_the_inventorys_current_one_never_the_flow_rows(sample):
    """sel-1's flow row carries src_mode 'idle' (the mode stored with a flow is some day's, not the flow's); the
    inventory says Selective now. idle-1's rows say Visibility Only; the inventory says Idle now."""
    with sample.flows().connect() as conn:
        stored = dict(conn.execute("SELECT src_hostname, src_mode FROM flows WHERE src_hostname IN ('sel-1', 'idle-1') "
                                   "AND dst_hostname = 'db'").fetchall())
    assert stored == {"sel-1": "idle", "idle-1": "visibility_only"}
    _, (section,) = _monitor(sample)
    hosts = _tables(section)["Hosts with a VEN that appear in these flows"]
    assert [c.label for c in hosts.columns] == ["Host", "Mode now", "Flows", "Connections", "Which end", "Note"]
    idle_note = "A VEN in Idle only records snapshots; it reports no decision."
    assert hosts.rows == (
        ("db", "Blocking everything (Full)", 4, 19, "Both", ""),
        ("left-1", "Not in the inventory", 1, 10, "Source", ""),
        ("idle-1", "Not blocking yet (Idle)", 2, 7, "Both", idle_note),
        ("sel-1", "Blocking some (Selective)", 1, 2, "Source", ""))  # no reason given for a host not in Idle now
    assert hosts.host_keys == {"host": tuple(f"/orgs/1/workloads/{n}" for n in ("db", "left-1", "idle-1", "sel-1"))}
    words = " ".join(p for b in section.blocks if not hasattr(b, "rows") for p in b.paragraphs)
    assert "the inventory's current one" in words
    _, (zh,) = _monitor(sample, Language.ZH_TW)
    table = _tables(zh)["出現在裡面、有 VEN 的主機"]
    assert [c.label for c in table.columns][1] == "現在的模式"
    assert table.rows[2][1:] == ("還沒開始擋（Idle）", 2, 7, "兩端", "Idle 的 VEN 只記快照，不回報判定。")
    assert table.rows[1][1] == "不在清冊" and table.rows[3][5] == ""


def test_more_ends_and_hosts_than_the_tables_list_is_said(tmp_path, monkeypatch):
    from tests.services.reports.test_findings import flow
    c = configured_ctx(tmp_path)
    with c.flows().connect() as conn:
        upsert_flows(conn, [flow(src=f"h{i:02d}", port=8443, decision="unknown", conns=20 - i) for i in range(12)],
                     origin=DataOrigin.INGEST, now=NOW)
    monkeypatch.setattr(flowsections, "MONITOR_HOSTS", 5)
    _, (section,) = _monitor(c)
    t = _tables(section)
    src = t["Top sources, at least one end has a VEN"]
    assert [r[0] for r in src.rows] == [f"h{i:02d}" for i in range(10)] and src.total_rows == 12
    assert src.limit_note == "Only the top 10 are listed."
    assert "Top sources, neither end has a VEN" not in t  # a kind with no flow has a 0 in the first table, no ranking
    hosts = t["Hosts with a VEN that appear in these flows"]
    assert len(hosts.rows) == 5 and hosts.total_rows == 13 and hosts.limit_note == "Only the top 5 are listed."
    assert hosts.rows[0][0] == "db" and len(hosts.host_keys["host"]) == 5


def test_the_first_pages_sentence_gives_both_shares(sample):
    totals, _ = _monitor(sample)
    saw = flowsections.seen(totals)
    from tests.services.reports.test_findings import UNDECIDED_EN, UNDECIDED_ZH
    assert UNDECIDED_EN.startswith("Flows without a decision: 55.6% of the period's flows (63.3% by connections).")
    assert flowsections.undecided_caveat(Language.EN, saw) == (UNDECIDED_EN,)
    assert flowsections.undecided_caveat(Language.ZH_TW, saw) == (UNDECIDED_ZH,)
    plain = flowsections.undecided_caveat(Language.ZH_TW, saw, chapter=False)[0]
    assert plain.startswith("期間內有 55.6% 的流量（依連線數是 63.3%）沒有判定；") and "只能監看" not in plain


def test_a_share_one_decimal_cannot_show_is_not_said_as_0_or_100():
    from illumio_ops.services.flowsource import Undecided
    assert flowsections.share_text(Language.EN, 1, 3) == "33.3%"
    assert flowsections.share_text(Language.EN, 1, 10_000) == "less than 0.1%"
    assert flowsections.share_text(Language.ZH_TW, 1, 10_000) == "不到 0.1%"
    assert flowsections.share_text(Language.EN, 9_999, 10_000) == "more than 99.9%"
    assert flowsections.share_text(Language.ZH_TW, 9_999, 10_000) == "超過 99.9%"
    assert flowsections.share_text(Language.EN, 10_000, 10_000) == "100.0%"
    saw = flowsections.Seen(flows=10_000, connections=40_000, undecided=Undecided(
        flows=1, connections=1, managed_flows=1, managed_connections=1))
    (said,) = flowsections.undecided_caveat(Language.EN, saw)
    assert "less than 0.1% of the period's flows (less than 0.1% by connections)" in said and "0.0%" not in said


def test_seen_adds_up_disjoint_reads(sample):
    totals, _ = _monitor(sample)
    one, two = flowsections.seen(totals), flowsections.seen(totals, totals)
    assert (one.flows, one.connections, one.undecided) == (totals.flows, totals.connections, totals.undecided)
    assert (two.flows, two.connections, two.undecided.managed_connections) == (18, 218, 38)


@pytest.mark.parametrize("lang", list(Language))
def test_sentences_that_point_at_the_chapter_name_it_as_it_is_titled(sample, lang):
    from illumio_ops.i18n import dictionary
    _, (section,) = _monitor(sample, lang)
    words = dictionary(lang)
    for key in ("rpt_decided_note", "rpt_kpi_decided_only", "rpt_caveat_undecided"):
        assert section.title in words[key], key
    assert section.title not in words["rpt_caveat_undecided_plain"]


@pytest.mark.parametrize("lang", list(Language))
def test_the_chapters_tables_keep_their_names_as_xlsx_sheets(sample, lang):
    """Excel cuts a sheet name at 31 characters: the six tables stay apart there, none becomes "… (2)"."""
    from illumio_ops.services.reports.sheets import sheet_names
    _, (section,) = _monitor(sample, lang)
    titles = list(_tables(section))
    assert len(titles) == 6
    names = sheet_names(titles)
    assert len(set(names)) == 6 and not [n for n in names if n.endswith(")")]
