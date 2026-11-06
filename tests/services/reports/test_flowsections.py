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
