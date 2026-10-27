"""Final-review findings on the P5b-1 flow reports (Codex, 2026-10-27), each pinned by the input that broke it."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.filter import (
    EndpointFilter,
    FlowCondition,
    LabelCond,
    PortProto,
)
from illumio_ops.domain.report import TableBlock
from illumio_ops.domain.values import Language, PolicyDecision, ReportType
from illumio_ops.services.reports import findings, generate
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.store.flowdb import analysis, labels, workloads
from tests_v6.services.collect.conftest import configured_ctx
from tests_v6.services.reports.test_findings import NOW, SPEC, flow
from tests_v6.services.reports.test_traffic import _write

START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
FIN = LabelCond(key="app", values=("Finance",))


def _build(ctx, report_type, cond=None):
    return specs()[report_type].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=report_type, filter=cond), start=START, end=END, lang=Language.EN,
        tz=UTC, now=NOW, pce_label="pce"))


def _table(doc, sid, i=0):
    return [b for b in next(s for s in doc.sections if s.id == sid).blocks if isinstance(b, TableBlock)][i]


def _kpi(doc):
    return {k.key: k for k in doc.kpis}


def _inventory(ctx, hosts):
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=f"/orgs/1/workloads/{n}", hostname=n, name=None, managed=1, enforcement_mode=mode,
            visibility_level=None, os_id=None, ven_version=None, ven_href=None,
            label_set=labels.label_set_id(conn, tuple(sorted(lab.items()))), online=1, risk_exposure=None,
            risk_percent=None, risk_updated_at=None, fetched_at="x") for n, lab, mode in hosts])
        conn.commit()


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


# 1: app_summary keeps the app side's other labels and refuses filters it cannot honour
def test_app_summary_keeps_other_labels_on_the_app_side(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443, conns=3)])
    cond = FlowCondition(dst=EndpointFilter(labels=(FIN, LabelCond(key="role", values=("db",)))))
    doc = _build(ctx, ReportType.APP_SUMMARY, cond)
    assert _table(doc, "inbound").rows == ()  # the flow's Finance end has no role=db


def test_app_summary_refuses_an_ambiguous_filter(ctx):
    s = ctx.settings.current()
    both = FlowCondition(src=EndpointFilter(labels=(LabelCond(key="app", values=("HR",)),)),
                         dst=EndpointFilter(labels=(FIN,)))
    excl = FlowCondition(dst=EndpointFilter(labels=(FIN,)), src_exclude=EndpointFilter(ips=("10.0.0.0/8",)))
    for cond in (both, excl):
        assert generate.refusal(s, ReportParams(report_type=ReportType.APP_SUMMARY, filter=cond)) == \
            "rpt_err_app_filter_shape"


# 2: a section's own decision condition narrows the report's, never replaces it
def test_section_decisions_intersect_the_filter(ctx):
    _write(ctx, [flow(port=443), flow(port=22, decision="potentially_blocked")])
    doc = _build(ctx, ReportType.SECURITY_RISK, FlowCondition(decisions=(PolicyDecision.ALLOWED,)))
    assert _table(doc, "pb").rows == () and _table(doc, "uncovered").rows == ()


# 4: a lookback that reaches before the flow retention floor is refused; data quality uses flow retention
def test_lookback_equal_to_flow_days_is_refused(ctx):
    s = ctx.settings.current()
    days = s.collection.retention.flow_days
    assert generate.refusal(s, ReportParams(report_type=ReportType.TRAFFIC, lookback_days=days)) == \
        "rpt_err_lookback_beyond_retention"
    assert generate.refusal(s, ReportParams(report_type=ReportType.TRAFFIC, lookback_days=days - 1)) is None


def test_coverage_note_uses_flow_retention_for_flow_reports(ctx, monkeypatch):
    seen = []
    real = generate.coverage_note

    def spy(*a, **k):
        seen.append(k.get("flows"))
        return real(*a, **k)
    monkeypatch.setattr("illumio_ops.services.reports.traffic.coverage_note", spy)
    _write(ctx, [flow(port=443)])
    _build(ctx, ReportType.TRAFFIC)
    assert seen == [True]


# 5: no matching traffic: no maturity number and the rules say they were not evaluated
def test_no_matching_flows_no_maturity_and_rules_not_evaluated(ctx):
    _inventory(ctx, [("f1", {"app": "Finance"}, "full")])
    _write(ctx, [flow(port=443, dst_app="Other")])
    doc = _build(ctx, ReportType.SECURITY_RISK, FlowCondition(dst=EndpointFilter(labels=(FIN,))))
    assert _kpi(doc)["maturity"].value is None and _kpi(doc)["maturity"].note
    assert "not evaluated" in _table(doc, "findings").empty_text.lower()


# 6: network_inventory's inventory part follows the filter, matching labels exactly
def test_network_inventory_hosts_follow_the_filter(ctx):
    _inventory(ctx, [("f1", {"app": "Finance"}, "full"), ("f2", {"app": "finance"}, "full")])
    _write(ctx, [flow(port=443, dst_app="Finance")])
    doc = _build(ctx, ReportType.NETWORK_INVENTORY, FlowCondition(dst=EndpointFilter(labels=(FIN,))))
    assert _kpi(doc)["managed_hosts"].value == 1


# 8: the ransomware priority list follows the filter
def test_ransomware_priority_follows_the_filter(ctx):
    _inventory(ctx, [("f1", {"app": "Finance"}, "full"), ("o1", {"app": "Other"}, "full")])
    _write(ctx, [flow(port=443, dst_app="Finance")])
    row = {"name": "SMB", "port": 445, "proto": 6, "severity": "critical", "weight": 40, "recent_sources": 3}
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "ransomware", params={}, at=NOW, result={
            "unsupported": False, "contradictions": 0, "safe_to_block": [], "suspicious": [],
            "priority": [{**row, "host": "/orgs/1/workloads/o1", "hostname": "o1"},
                         {**row, "host": "/orgs/1/workloads/f1", "hostname": "f1"}], "hosts": []})
        conn.commit()
    doc = _build(ctx, ReportType.SECURITY_RISK, FlowCondition(dst=EndpointFilter(labels=(FIN,))))
    assert [r[0] for r in _table(doc, "ransomware").rows] == ["f1"]


# 9: maturity's lateral part counts remote-execution ports only
def test_maturity_lateral_part_is_remote_ports_only(ctx):
    _write(ctx, [flow(port=88)])
    assert _kpi(_build(ctx, ReportType.SECURITY_RISK))["admin_open_connections"].value == 0


# 10: a management port configured for any protocol stays any protocol in the rules
def test_any_protocol_admin_port_in_rules(ctx):
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["lateral"]["extra_admin_ports"].append(
        {"port": 8443, "proto": None, "category": "remote"}))
    _write(ctx, [flow(src="jump", dst=f"t{i}", port=8443, proto=132) for i in range(3)])
    t = ctx.settings.current().reports.rule_thresholds.model_copy(update={"lateral_outbound_dst": 2})
    got = {o.rule_id for o in findings.run_rules(ctx, SPEC, t, Language.EN, now=NOW)}
    assert "B006" in got


# 11: a domain account in two spellings is one user
def test_b007_folds_domain_account_case(ctx):
    _write(ctx, [flow(dst="t1", port=443, user="CORP\\Alice"), flow(dst="t2", port=443, user="corp\\alice")])
    t = ctx.settings.current().reports.rule_thresholds.model_copy(update={"user_destination": 1})
    got = {o.rule_id: o for o in findings.run_rules(ctx, SPEC, t, Language.EN, now=NOW)}
    assert got["B007"].params["n_users"] == 1


# 12: a service whose protection state is unknown is not counted as unprotected
def test_unknown_protection_state_not_unprotected(ctx):
    _write(ctx, [flow(port=443)])
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "ransomware", params={}, at=NOW, result={
            "unsupported": False, "priority": [], "hosts": [{"href": "/orgs/1/workloads/db", "services": [
                {"severity": "critical", "protection_state": None},
                {"severity": "high", "protection_state": "protected_open"}]}]})
        conn.commit()
    assert _kpi(_build(ctx, ReportType.SECURITY_RISK))["ransomware_protected_pct"].value == 100.0


# 13: B008 thresholds computed in SQL give the same answer
def test_b008_same_answer_in_sql(ctx):
    _write(ctx, [flow(dst=f"t{i}", port=443, bytes_=1000) for i in range(40)] +
           [flow(dst="big", port=443, bytes_=50 * 1024 * 1024), flow(dst="big2", port=443, bytes_=40 * 1024 * 1024)])
    o = {x.rule_id: x for x in findings.run_rules(ctx, SPEC, ctx.settings.current().reports.rule_thresholds,
                                                  Language.EN, now=NOW)}["B008"]
    assert o.params["n_outliers"] == 2 and o.params["n_with_bytes"] == 42 and o.params["top_pairs"].index("big ") \
        < o.params["top_pairs"].index("big2")


# 15: the services-per-app table says when it lists only the top apps
def test_services_table_discloses_its_limit(ctx):
    _write(ctx, [flow(port=443, dst_app=f"A{i:02}") for i in range(21)])
    t = _table(_build(ctx, ReportType.NETWORK_INVENTORY), "services")
    assert len(t.rows) == 20 and t.total_rows == 21 and t.limit_note


def test_port_filter_kept_by_app_summary(ctx):
    _write(ctx, [flow(src_app="Web", dst_app="Finance", port=443), flow(src_app="Web", dst_app="Finance", port=80)])
    cond = FlowCondition(dst=EndpointFilter(labels=(FIN,)), ports=(PortProto(port=443, proto=6),))
    assert [r[1] for r in _table(_build(ctx, ReportType.APP_SUMMARY, cond), "inbound").rows] == ["443/TCP"]
