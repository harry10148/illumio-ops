"""The app summary report (P5b-1 Task 6): one application's inbound, outbound and intra-app traffic, its policy
impact and hosts, and the rule findings over its flows only. The app is the report filter's app label, matched
exactly (5.x readiness lowercased it, app_summary did not)."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.filter import EndpointFilter, FlowCondition, LabelCond
from illumio_ops.domain.report import TableBlock
from illumio_ops.domain.values import Language, ReportType
from illumio_ops.services.reports import generate
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.store.flowdb import labels, workloads
from tests_v6.services.collect.conftest import configured_ctx
from tests_v6.services.reports.test_findings import flow
from tests_v6.services.reports.test_traffic import _write

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)


def _app(app, env=None):
    conds = (LabelCond(key="app", values=(app,)),) + ((LabelCond(key="env", values=(env,)),) if env else ())
    return FlowCondition(dst=EndpointFilter(labels=conds))


def _build(ctx, cond, lang=Language.EN, report_type=ReportType.APP_SUMMARY):
    return specs()[report_type].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=report_type, filter=cond), start=START, end=END, lang=lang, tz=UTC,
        now=NOW, pce_label="pce"))


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _table(doc, sid, i=0):
    return [b for b in _section(doc, sid).blocks if isinstance(b, TableBlock)][i]


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


def test_app_required(ctx):
    spec = specs()[ReportType.APP_SUMMARY]
    assert spec.requires_app
    assert generate.refusal(ctx.settings.current(), ReportParams(report_type=ReportType.APP_SUMMARY)) == \
        "rpt_err_app_required"
    assert generate.refusal(ctx.settings.current(),
                            ReportParams(report_type=ReportType.APP_SUMMARY, filter=_app("Finance"))) is None


def test_inbound_outbound_split(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443, conns=4),
                 flow(src_app="Finance", dst_app="DB", port=5432, conns=2),
                 flow(src_app="Finance", dst_app="Finance", port=8080, conns=1)])
    doc = _build(ctx, _app("Finance"))
    assert _table(doc, "inbound").rows == (("Web", "443/TCP", 4),)
    assert _table(doc, "outbound").rows == (("DB", "5432/TCP", 2),)
    assert _table(doc, "intra").rows == (("8080/TCP", 1),)


def test_intra_app_counted_once(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443), flow(src_app="Finance", dst_app="Finance", port=8080),
                 flow(src_app="Finance", dst_app="DB", port=5432, decision="potentially_blocked")])
    doc = _build(ctx, _app("Finance"))
    rows = {r[0]: r[1] for r in _table(doc, "impact").rows}
    assert rows == {"Allowed": 2, "Potentially blocked": 1}
    kpi = {k.key: k.value for k in doc.kpis}
    assert kpi["inbound_connections"] == 1 and kpi["outbound_connections"] == 1 and kpi["intra_connections"] == 1
    assert kpi["pb_flows"] == 1


def test_app_match_is_exact_everywhere(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443, conns=3),
                 flow(src_app="Web", dst_app="finance", port=443, conns=5)])
    assert _table(_build(ctx, _app("Finance")), "inbound").rows == (("Web", "443/TCP", 3),)
    inv = _build(ctx, None, report_type=ReportType.NETWORK_INVENTORY)
    assert {r[0] for r in _table(inv, "services").rows} == {"Finance", "finance"}


def test_env_narrows_the_app(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Finance", dst_env="Prod", port=443, conns=3),
                 flow(src_app="Web", dst_app="Finance", dst_env="Dev", port=443, conns=5)])
    doc = _build(ctx, _app("Finance", "Prod"))
    assert _table(doc, "inbound").rows == (("Web", "443/TCP", 3),) and "Finance" in doc.title and "Prod" in doc.title


def test_hosts_of_the_app(ctx):
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=f"/orgs/1/workloads/{n}", hostname=n, name=None, managed=1, enforcement_mode=mode,
            visibility_level=None, os_id=None, ven_version=None, ven_href=None,
            label_set=labels.label_set_id(conn, (("app", app), ("env", "Prod"))), online=1, risk_exposure=None,
            risk_percent=None, risk_updated_at=None, fetched_at="x")
            for n, app, mode in (("f1", "Finance", "full"), ("f2", "finance", "idle"), ("w1", "Web", "full"))])
        conn.commit()
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443)])
    doc = _build(ctx, _app("Finance"))
    assert [r[0] for r in _table(doc, "hosts").rows] == ["f1"]
    assert {k.key: k.value for k in doc.kpis}["enforced_hosts_pct"] == 100.0


def test_findings_only_this_app(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Other", port=5900), flow(src_app="Web", dst_app="Finance", port=443)])
    doc = _build(ctx, _app("Finance"))
    assert not any(r[0] == "B002" for r in _table(doc, "findings").rows)
    _write(ctx, [flow(src_app="Finance", dst_app="Other", port=5900)])
    assert any(r[0] == "B002" for r in _table(_build(ctx, _app("Finance")), "findings").rows)


def test_zh_tw_builds(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443)])
    assert "Finance" in _build(ctx, _app("Finance"), Language.ZH_TW).title


def test_exposure_finding_limited_to_the_app(ctx):
    from illumio_ops.store.flowdb import analysis
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443)])
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "exposure", params={}, at=NOW, result={
            "hosts": [{"key": "/orgs/1/workloads/elsewhere", "reach_now": 50}]})
        conn.commit()
    assert not any(r[0] == "L006" for r in _table(_build(ctx, _app("Finance")), "findings").rows)
