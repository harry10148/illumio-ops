"""Hosts that report no allowed traffic are named in every report whose conclusions rest on host traffic (6.5.0 B4,
spec §6.5 data visibility): readiness, ransomware, lateral posture, policy usage and custom reports. Their numbers
for those hosts are incomplete; with no such host the section is not there."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.report import TableBlock
from illumio_ops.domain.segment import GroupBy
from illumio_ops.domain.values import Language, ReportType, SegmentMetric, SegmentView
from illumio_ops.services import custom_reports
from illumio_ops.services.analysis import focus
from illumio_ops.services.reports import policy_usage, ransomware_report, visibility
from illumio_ops.services.reports import readiness as readiness_report
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.services.workbench import FlowRequest
from illumio_ops.store.flowdb import workloads
from tests.services.collect.conftest import configured_ctx
from tests.services.reports.test_policy_usage import usage
from tests.services.reports.test_readiness import summary

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
TYPES = [ReportType.READINESS, ReportType.RANSOMWARE, ReportType.LATERAL_POSTURE, ReportType.POLICY_USAGE,
         ReportType.CUSTOM]


def _inventory(ctx, levels):
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=f"/orgs/1/workloads/h{i}", hostname=f"h{i}", name=None, managed=managed, enforcement_mode="full",
            visibility_level=level, os_id=None, ven_version=None, ven_href=None, label_set=None, online=1,
            risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x")
            for i, (level, managed) in enumerate(levels)])
        conn.commit()


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    from illumio_ops.services.analysis.ransomware import HostRansomware
    monkeypatch.setattr(readiness_report, "predicted_summary", lambda ctx, spec, **kw: summary())
    monkeypatch.setattr(policy_usage, "rule_usage", lambda ctx, **kw: usage())
    monkeypatch.setattr(ransomware_report, "host_ransomware", lambda ctx, href, **kw: HostRansomware.model_construct(
        breakdown=None, allow_rules={}, allow_status={}))
    return configured_ctx(tmp_path)


def _build(ctx, rt):
    custom_id = None
    if rt is ReportType.CUSTOM:
        req = FlowRequest(mode="flows", start=START, end=END, view=SegmentView.RANKING, metric=SegmentMetric.FLOWS,
                          group_by=(GroupBy(dimension="dst_host"),))
        custom_id = custom_reports.add_section(ctx, report_id=None, name="Custom", title="Ranking", by="t", now=NOW,
                                               request=req).id
    return specs()[rt].build(BuildInput(ctx=ctx, params=ReportParams(report_type=rt, custom_id=custom_id), start=START,
                                        end=END, lang=Language.EN, tz=UTC, now=NOW, pce_label="pce"))


@pytest.mark.parametrize("rt", TYPES)
def test_hosts_reporting_no_allowed_traffic_are_named(ctx, rt):
    _inventory(ctx, [("flow_off", 1), ("flow_drops", 1), ("flow_summary", 1), ("flow_off", 0)])
    sec = next(s for s in _build(ctx, rt).sections if s.id == "visibility")
    table = next(b for b in sec.blocks if isinstance(b, TableBlock))
    # the two managed hosts; an unmanaged row and a host that reports its flows are not listed
    assert table.rows == (("h0", "Reports no traffic"), ("h1", "Reports blocked traffic only"))
    assert table.total_rows == 2 and "2 managed hosts" in sec.intro


@pytest.mark.parametrize("rt", TYPES)
def test_no_such_host_no_section(ctx, rt):
    _inventory(ctx, [("flow_summary", 1), ("enhanced_data_collection", 1)])
    assert all(s.id != "visibility" for s in _build(ctx, rt).sections)


def test_same_test_as_the_home_focus_list():
    assert visibility.BLIND is focus.BLIND
