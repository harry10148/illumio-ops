"""The enforcement readiness report (P5b-2 Task 5): per app (environment), five factors over its inbound connections
and its hosts, the predicted blocks of the draft policy, and the order to enforce in."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.filter import EndpointFilter, FlowCondition, LabelCond
from illumio_ops.domain.report import TableBlock, TextBlock
from illumio_ops.domain.values import Language, ReportType
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.services.analysis.predicted_block import (
    PredictedGroup,
    PredictedSummary,
)
from illumio_ops.services.reports import readiness as readiness_report
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.store.flowdb import labels, workloads
from tests_v6.services.collect.conftest import configured_ctx
from tests_v6.services.reports.test_findings import flow
from tests_v6.services.reports.test_traffic import _write

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)


def summary(**kw):
    base = {"groups": [PredictedGroup(dst_app="DB", rule_href="/orgs/1/sec_policy/draft/rule_sets/1/deny_rules/2",
                                      flows=3, connections=7)],
            "rules": {}, "blocked_flows": 3, "blocked_connections": 7, "capped": False, "computed_at": NOW,
            "unsupported": False, "missing_rules": ["/orgs/1/sec_policy/draft/rule_sets/1/deny_rules/2"]}
    return PredictedSummary(**{**base, **kw})


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness_report, "predicted_summary", lambda ctx, spec, **kw: summary())
    return configured_ctx(tmp_path)


def _inventory(ctx, hosts):
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=f"/orgs/1/workloads/{n}", hostname=n, name=None, managed=1, enforcement_mode=mode,
            visibility_level=None, os_id=None, ven_version=None, ven_href=None,
            label_set=labels.label_set_id(conn, (("app", app), ("env", "Dev"))), online=1, risk_exposure=None,
            risk_percent=None, risk_updated_at=None, fetched_at="x") for n, app, mode in hosts])
        conn.commit()


def _build(ctx, cond=None, lang=Language.EN):
    return specs()[ReportType.READINESS].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=ReportType.READINESS, filter=cond), start=START, end=END, lang=lang,
        tz=UTC, now=NOW, pce_label="pce"))


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _table(doc, sid, i=0):
    return [b for b in _section(doc, sid).blocks if isinstance(b, TableBlock)][i]


def _texts(doc, sid):
    return " ".join(p for b in _section(doc, sid).blocks if isinstance(b, TextBlock) for p in b.paragraphs)


def test_inbound_only(ctx):
    # DB's inbound: two allowed from Web, one potentially blocked from DB itself; DB -> Web counts for Web only.
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432, conns=2),
                 flow(src_app="DB", dst_app="DB", port=5432, decision="potentially_blocked", conns=2),
                 flow(src_app="DB", dst_app="Web", port=443, conns=10)])
    rows = {r[0]: r for r in _table(_build(ctx), "scores").rows}
    db = rows["DB (Dev)"]
    assert db[3:7] == ("50.0%", "50.0%", "—", "50.0%")  # policy, ringfence, enforcement (no hosts), staged


def test_enforcement_from_inventory_exact_labels(ctx):
    _inventory(ctx, [("d1", "DB", "full"), ("d2", "DB", "selective"), ("x", "db", "full")])
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    row = {r[0]: r for r in _table(_build(ctx), "scores").rows}["DB (Dev)"]
    assert row[5] == "75.0%" and "1 full, 1 selective" in row[9]


def test_predicted_grouped_by_rule(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    doc = _build(ctx)
    assert _table(doc, "predicted").rows[0][0] == "DB" and _table(doc, "predicted").rows[0][2:] == (3, 7)
    assert {k.key: k.value for k in doc.kpis}["predicted_blocked"] == 7


def test_predicted_unsupported_says_so(ctx, monkeypatch):
    monkeypatch.setattr(readiness_report, "predicted_summary", lambda ctx, spec, **kw: summary(
        groups=[], unsupported=True, blocked_flows=0, blocked_connections=0))
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    doc = _build(ctx)
    assert "does not recompute" in _texts(doc, "predicted")
    assert {k.key: k.value for k in doc.kpis}["predicted_blocked"] is None


def test_predicted_error_report_still_built(ctx, monkeypatch):
    def boom(ctx, spec, **kw):
        raise PceQueryError("poll", 500)
    monkeypatch.setattr(readiness_report, "predicted_summary", boom)
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    doc = _build(ctx)
    assert "could not" in _texts(doc, "predicted").lower() and _table(doc, "scores").rows


def test_predicted_capped_disclosed(ctx, monkeypatch):
    monkeypatch.setattr(readiness_report, "predicted_summary", lambda ctx, spec, **kw: summary(capped=True))
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    assert _table(_build(ctx), "predicted").limit_note


def test_queue_orders_by_score(ctx):
    _inventory(ctx, [("w1", "Web", "full"), ("d1", "DB", "idle")])
    _write(ctx, [flow(src_app="Web", dst_app="Web", port=443), flow(src_app="Web", dst_app="DB", port=5432,
                                                                    decision="potentially_blocked")])
    rows = _table(_build(ctx), "queue").rows
    assert [r[0] for r in rows] == ["Web (Dev)", "DB (Dev)"]


def test_filter_narrows_apps(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432), flow(src_app="DB", dst_app="Web", port=443)])
    cond = FlowCondition(dst=EndpointFilter(labels=(LabelCond(key="app", values=("DB",)),)))
    assert [r[0] for r in _table(_build(ctx, cond), "scores").rows] == ["DB (Dev)"]


def test_zh_tw_builds(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    assert _build(ctx, lang=Language.ZH_TW).title


def test_unknown_decisions_left_out(ctx):
    """Lab, 2026-10-28: 84% of the traffic had no reported decision and every app scored F on "allowed by a rule".
    A connection without a decision says nothing about policy: it is left out of policy and staged, and said."""
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432, conns=2),
                 flow(src_app="Web", dst_app="DB", port=5432, decision="unknown", conns=8)])
    doc = _build(ctx)
    row = {r[0]: r for r in _table(doc, "scores").rows}["DB (Dev)"]
    assert row[3] == "100.0%" and row[6] == "100.0%"  # policy and staged over the 2 decided connections
    assert any("80.0%" in q for q in doc.data_quality)


def test_all_unknown_no_policy_factor(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="DB", port=5432, decision="unknown", conns=5)])
    row = {r[0]: r for r in _table(_build(ctx), "scores").rows}["DB (Dev)"]
    assert row[3] == "—" and row[6] == "—"
