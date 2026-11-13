"""Built-in reports link each section computed from traffic or events to the workbench (6.5.0 B2, spec §6.5.5): the
link carries the same segment the section ran, and is left out without a GUI address."""
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from illumio_ops.domain.filter import EndpointFilter, FlowCondition, LabelCond
from illumio_ops.domain.values import DataOrigin, Language, ReportType
from illumio_ops.services import workbench
from illumio_ops.services.analysis import segments
from illumio_ops.services.reports import audit, flowsections
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.store.flowdb.flows import upsert_flows
from tests.services.collect.conftest import configured_ctx
from tests.services.reports.test_findings import flow

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
BASE = "https://ops.example.com:5001"
APP = FlowCondition(dst=EndpointFilter(labels=(LabelCond(key="app", values=("erp",)),)))
# report type -> (its filter, the sections that must link)
FLOW_REPORTS = {
    ReportType.TRAFFIC: (None, {"labels", "services", "users"}),  # users: from the security risk report (3b)
    ReportType.SECURITY_RISK: (None, set()),
    ReportType.NETWORK_INVENTORY: (None, set()),
    ReportType.APP_SUMMARY: (APP, set()),
}


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path)
    c.settings.update(c.settings.current().revision, lambda d: d["reports"].update(gui_external_url=BASE))
    with c.flows().connect() as conn:
        upsert_flows(conn, [flow(port=443, conns=3), flow(port=22, decision="potentially_blocked"),
                            flow(port=3389, decision="blocked"), flow(port=443, user="CORP\\alice")],
                     origin=DataOrigin.INGEST, now=NOW)
    return c


def _build(ctx, rt, cond=None):
    return specs()[rt].build(BuildInput(ctx=ctx, params=ReportParams(report_type=rt, filter=cond), start=START,
                                        end=END, lang=Language.EN, tz=UTC, now=NOW, pce_label="pce"))


def _request(link):
    url = urlparse(link)
    assert link.startswith(f"{BASE}/investigate?")
    return json.loads(parse_qs(url.query)["q"][0])


@pytest.mark.parametrize("rt", list(FLOW_REPORTS))
def test_flow_sections_link_to_the_segment_they_ran(ctx, monkeypatch, rt):
    ran = []
    real = segments.run_segment

    def recording(c, seg, **kw):
        ran.append(seg)
        return real(c, seg, **kw)
    monkeypatch.setattr(flowsections, "run_segment", recording)
    cond, must = FLOW_REPORTS[rt]
    doc = _build(ctx, rt, cond)
    linked = {s.id: s.workbench_link for s in doc.sections if s.workbench_link}
    assert linked, "no section links to the workbench"
    assert must <= set(linked)
    for link in linked.values():
        req = workbench.FlowRequest.model_validate(_request(link))
        seg = req.segment()
        # the request the link opens is one this report ran: same filter, grouping and metric
        assert any((seg.filter, seg.group_by, seg.metric) == (r.filter, r.group_by, r.metric) for r in ran), link


@pytest.mark.parametrize("rt", [*FLOW_REPORTS, ReportType.AUDIT])
def test_no_link_without_a_gui_address(ctx, rt):
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["reports"].update(gui_external_url=""))
    doc = _build(ctx, rt, FLOW_REPORTS.get(rt, (None,))[0])
    assert not any(s.workbench_link for s in doc.sections)
    assert any("external address" in line for line in doc.data_quality)  # and the report says why


def test_audit_event_sections_link_to_their_event_types(ctx):
    doc = _build(ctx, ReportType.AUDIT)
    linked = {s.id: _request(s.workbench_link) for s in doc.sections if s.workbench_link}
    assert {"policy", "agent"} <= set(linked)
    assert linked["policy"]["mode"] == "events" and linked["policy"]["event_types"] == [audit.PROVISION]
    assert linked["agent"]["event_types"] == list(audit.AGENT_SECURITY)
    assert linked["policy"]["start"].startswith("2026-10-20") and linked["policy"]["end"].startswith("2026-10-26T23:59:59")
