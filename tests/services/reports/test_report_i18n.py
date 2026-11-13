"""Every built report type in both languages (P5a Task 10): no raw message key in the HTML, the XLSX or the email,
and a zh_TW report carries no English sentence of the report's own copy."""
import json
import re
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook

from illumio_ops.domain.filter import EndpointFilter, FlowCondition, LabelCond
from illumio_ops.domain.findings_rules import RULES
from illumio_ops.domain.values import DataOrigin, Language, ReportType, RhcState
from illumio_ops.i18n import translate
from illumio_ops.pce.policy import PendingItem, PolicyNames
from illumio_ops.services.analysis.policy_resolver import Resolved
from illumio_ops.services.analysis.predicted_block import (
    PredictedGroup,
    PredictedSummary,
)
from illumio_ops.services.analysis.ransomware import HostRansomware
from illumio_ops.services.reports import policy_diff as policy_diff_report
from illumio_ops.services.reports import policy_resolver as policy_resolver_report
from illumio_ops.services.reports import ransomware_report, rule_hit_count
from illumio_ops.services.reports import readiness as readiness_report
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.services.reports.render_email import render_email
from illumio_ops.services.reports.render_html import render_html
from illumio_ops.services.reports.render_xlsx import render_xlsx
from illumio_ops.services.rhc import RhcPull, RhcRow, RhcStatus
from illumio_ops.store.flowdb import analysis
from illumio_ops.store.flowdb.db import db_time
from illumio_ops.store.flowdb.events import upsert_events
from illumio_ops.store.flowdb.flows import upsert_flows
from tests.services.collect.conftest import configured_ctx
from tests.services.reports.test_audit import event as audit_event
from tests.services.reports.test_findings import flow, undecided_sample
from tests.services.reports.test_lateral_posture import (
    _detection,
    _exposure,
    _hosts,
    _snapshot,
)
from tests.services.reports.test_new_connections import _baseline
from tests.services.reports.test_unmanaged import _rollup

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
RAW_KEY = re.compile(r"\b(?:rpt|gui_reports|detector_name|decision|term|severity)_[a-z0-9_]+\b")
# PCE console words zh_TW keeps in English (spec §6.2.1): not report copy left untranslated.
PCE_TERMS = frozenset({"Rule Hit Count", "Override Deny"})
APP_DB = FlowCondition(dst=EndpointFilter(labels=(LabelCond(key="app", values=("DB",)),)))
EN = json.loads((Path(__file__).resolve().parents[3] / "illumio_ops/i18n/en.json")
                .read_text(encoding="utf-8"))
# The types this build generates, written out. rule_hit_count stays in ReportType for the reports made before its
# counts became a chapter of policy usage (stage 3b) and has no builder; that this is exactly the registry's set is
# pinned in test_retired_type.py.
GENERATED = [t for t in ReportType if t is not ReportType.RULE_HIT_COUNT]


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    c = configured_ctx(tmp_path_factory.mktemp("i18n"))
    c.settings.update(c.settings.current().revision,
                      lambda d: d["lateral"].update(critical_assets=[{"key": "app", "value": "Finance"}]))
    _hosts(c)
    _exposure(c)
    _snapshot(c, "2026-10-26")
    _detection(c, "fanout", datetime(2026, 10, 21, tzinfo=UTC), severity="high")
    _detection(c, "auth_to_non_dc", datetime(2026, 10, 22, tzinfo=UTC), summary={"target": "dc", "port": 88})
    d = datetime(2026, 10, 22, tzinfo=UTC)
    _baseline(c, [("/orgs/1/workloads/a", "/orgs/1/workloads/db", 3389, d, "allowed"),
                  ("ip:10.9.9.9", "/orgs/1/workloads/a", 445, d, "unknown")])
    _rollup(c, [("2026-10-21", "ip:10.5.5.5", "/orgs/1/workloads/a", 445, "allowed", 10),
                ("2026-10-23", "/orgs/1/workloads/a", "ip:8.8.8.8", 53, "allowed", 3)])
    _rule_flows(c)
    _p5b2_sample(c)
    _alerts_sample(c)
    mp = pytest.MonkeyPatch()
    # The readiness report's draft recompute is a PCE call: a fixed answer here, so every section has content.
    mp.setattr(readiness_report, "predicted_summary", lambda ctx, spec, **kw: PredictedSummary(
        groups=[PredictedGroup(dst_app="DB", rule_href="/orgs/1/sec_policy/draft/rule_sets/1/deny_rules/2", flows=3,
                               connections=7)], rules={}, blocked_flows=3, blocked_connections=7, undetermined_flows=2, capped=True,
        computed_at=NOW, unsupported=False, missing_rules=["/orgs/1/sec_policy/draft/rule_sets/1/deny_rules/2"]))
    _rhc_sample(mp)
    _pdf_sample(mp)
    mp.setattr(policy_resolver_report, "resolve", lambda ctx, **kw: Resolved(
        rows=[{"ruleset_name": "Web", "rule_href": "/r/1", "action": "allow", "src_ip": "<5001 hosts: expansion capped>",
               "dst_ip": "10.0.0.2", "port": 1433, "protocol": "TCP", "truncated": "src"}],
        per_ruleset={"Web": 1}, rule_count=1, rules_capped=1, truncated_rulesets=["Web"], rows_omitted=3,
        not_expanded=[("Web", "/r/2", "virtual_services"), ("Web", "/r/3", "unknown_reference")], rules_no_address=1,
        computed_at=NOW))
    mp.setattr(ransomware_report, "host_ransomware", lambda ctx, href, **kw: HostRansomware.model_construct(
        breakdown=None, allow_rules={"445/6": []}, allow_status={"445/6": "error"}))
    yield c
    mp.undo()


def _alerts_sample(c):
    """Alerts for the weekly overview: this period's (each severity but low, four of the five categories, three
    hosts), the previous period's, and one from before both — the records reach back over the previous period."""
    from dataclasses import replace

    from illumio_ops.domain.alert_devices import Device
    from illumio_ops.domain.values import AlertRuleType, Severity
    from illumio_ops.store import alerts as alert_store
    from tests.services.collect.conftest import PCE
    from tests.store.test_alert_store import trig
    a, db = "/orgs/1/workloads/a", "/orgs/1/workloads/db"
    sample = [
        (datetime(2026, 10, 10, tzinfo=UTC), Severity.LOW, AlertRuleType.SYSTEM, None, ()),
        (datetime(2026, 10, 15, tzinfo=UTC), Severity.MEDIUM, AlertRuleType.TRAFFIC, None, ()),
        (datetime(2026, 10, 21, 9, tzinfo=UTC), Severity.HIGH, AlertRuleType.LATERAL, "fanout",
         (Device(a, "source"), Device(db, "destination"))),
        (datetime(2026, 10, 22, 9, tzinfo=UTC), Severity.MEDIUM, AlertRuleType.LATERAL, "volume_surge",
         (Device(a, "source"),)),
        (datetime(2026, 10, 23, 9, tzinfo=UTC), Severity.CRITICAL, AlertRuleType.EVENT, None,
         (Device("ip:10.9.9.9", "source"),)),
        (datetime(2026, 10, 24, 9, tzinfo=UTC), Severity.HIGH, AlertRuleType.SYSTEM, None, ()),
    ]
    with c.db() as conn:
        for at, severity, rule_type, detector, devices in sample:
            t = replace(trig(at.isoformat()), severity=severity, rule_type=rule_type, devices=devices,
                        params={"detector": detector} if detector else {"free_bytes": 1})
            alert_store.insert_alert(conn, pce_url=PCE["url"], org_id=PCE["org_id"], rule_name="r", pack_key=None,
                                     trigger=t, at=at, channels=["line"], hold=None)
        conn.commit()


def _rhc_sample(mp):
    """Rule Hit Count on, for the policy usage report's chapter of it: two rules hit (one no longer in the policy),
    one at 0, two with no record, a row the PCE could not count (P5c-2; a chapter since stage 3b)."""
    a = "/orgs/1/sec_policy/active/rule_sets/1"
    mp.setattr(rule_hit_count, "rhc_status", lambda ctx: RhcStatus(
        state=RhcState.ENABLED, pce_report=True, ven_scopes=True, reason_key=None, detail=None, write_key=True,
        saas=False))
    mp.setattr(rule_hit_count, "pull_rhc", lambda ctx, start, end: RhcPull(rows=[
        RhcRow(rule_href=f"{a}/sec_rules/1", ruleset_name="Web", description="", hit_count=9,
               last_hit_at="2026-10-26T10:00:00Z"),
        RhcRow(rule_href=f"{a}/sec_rules/2", ruleset_name="Web", description="", hit_count=0, last_hit_at=None),
        RhcRow(rule_href=f"{a}/sec_rules/9", ruleset_name="Old", description="", hit_count=1, last_hit_at=None)],
        start=start, end=end, unparsed=1))
    rule = {"consumers": [], "providers": [], "ingress_services": [], "enabled": True}
    mp.setattr(rule_hit_count, "fetch_rule_sets", lambda client, pversion, *, deadline: [
        {"href": a, "name": "Web", "rules": [{**rule, "href": f"{a}/sec_rules/{i}"} for i in (1, 2, 3)],
         "deny_rules": [{**rule, "href": f"{a}/deny_rules/4", "override": True}]}])
    mp.setattr(rule_hit_count, "fetch_policy_names",
               lambda client, pversion, *, deadline: PolicyNames(labels={}, names={}))


def _pdf_sample(mp):
    """Every change kind, field and risk the policy diff report words (P5c-3)."""
    from illumio_ops.domain.policy_diff import Change
    from illumio_ops.services.analysis.policy_diff import Attribution, PolicyDiff
    d = "/orgs/1/sec_policy/draft"
    rule_fields = ("rule_type", "enabled", "description", "providers", "consumers", "services")
    obj_fields = {"ip_list": ("ip_ranges", "fqdns", "description"),
                  "service": ("service_ports", "windows_services", "description"),
                  "label_group": ("labels", "sub_groups", "description")}
    changes = [Change(kind="rule_set", change="modified", ruleset="Q", name="Q", ref="1", href=f"{d}/rule_sets/1",
                      field=f, draft="False" if f == "enabled" else "x", active="True" if f == "enabled" else "y",
                      risk="high" if f == "enabled" else "") for f in ("name", "enabled", "description", "rule_count")]
    changes += [Change(kind="rule_set", change=ch, ruleset="N", name="N", ref="2", href=f"{d}/rule_sets/2", field="*",
                       draft="N" if ch == "added" else "", active="N" if ch == "removed" else "", rule_count=3,
                       risk="medium" if ch == "removed" else "") for ch in ("added", "removed")]
    changes += [Change(kind="rule", change="modified", ruleset="Q", name="#5", ref="deny_rules/5",
                       href=f"{d}/rule_sets/1/deny_rules/5", field=f,
                       draft="override_deny" if f == "rule_type" else "a", active="deny" if f == "rule_type" else "b",
                       rule_type="override_deny") for f in rule_fields]
    changes += [Change(kind=k, change="modified", ruleset="", name="O", ref="3", href=f"{d}/{k}s/3", field=f,
                       draft="a, b", active="a", scope_expanded=True, risk="high") for k, fs in obj_fields.items()
                for f in fs]
    mp.setattr(policy_diff_report, "policy_diff", lambda ctx, **kw: PolicyDiff(
        changes=changes, pending=[], attribution={f"{d}/rule_sets/1": Attribution(
            actor="admin", at=datetime(2026, 10, 25, tzinfo=UTC), event_type="rule_set.update")},
        other_pending=[PendingItem(kind="firewall_settings", href=f"{d}/firewall_settings", name=None,
                                   update_type="update", updated_at="2026-10-25T00:00:00Z")],
        attribution_limited=True, computed_at=NOW))


def _p5b2_sample(c):
    """VEN status, events, ransomware and tampering, so the P5b-2 reports render every section (P5b-2 Task 6)."""
    hb = NOW - timedelta(hours=5)
    with c.flows().connect() as conn:
        conn.execute("UPDATE workloads SET agent_status = 'active', last_heartbeat_at = ?, policy_sync_state = "
                     "'syncing', fw_config_current = 0, policy_received_at = ?, policy_applied_at = ?, fetched_at = ?",
                     (db_time(NOW - timedelta(minutes=5)), db_time(NOW - timedelta(minutes=10)), db_time(hb),
                      db_time(NOW)))
        conn.execute("UPDATE workloads SET online = 0, last_heartbeat_at = ? WHERE href = '/orgs/1/workloads/b'",
                     (db_time(hb),))
        analysis.write_result(conn, "tamper", params={}, at=NOW, result={"unmatched": 0, "hosts": [
            {"href": "/orgs/1/workloads/a", "hostname": "app-01", "n_60d": 4, "n_7d": 2, "pattern": "periodic",
             "median_minutes": 10.0, "last_at": NOW.isoformat(), "unexplained_7d": 1, "has_signal": True}]})
        svc = {"name": "SMB", "port": 445, "proto": 6, "severity": "critical", "category": "admin",
               "protection_state": "unprotected", "port_status": "listening", "active_policy": "allowed", "weight": 40,
               "coverage": 0.0, "contribution": 40.0, "traffic": "priority", "recent_sources": 3}
        listed = {"host": "/orgs/1/workloads/a", "hostname": "app-01", "name": "SMB", "port": 445, "proto": 6,
                  "severity": "critical", "weight": 40, "recent_sources": 3}
        analysis.write_result(conn, "ransomware", params={}, at=NOW, result={
            "unsupported": False, "contradictions": 1, "priority": [listed], "safe_to_block": [listed],
            "suspicious": [listed], "hosts": [
                {"href": "/orgs/1/workloads/a", "hostname": "app-01", "enforcement_mode": "selective",
                 "pce_percent": 10.0, "pce_exposure": "critical", "computed_percent": 10.0, "approximate": True,
                 "contradiction": False, "services": [svc]},
                {"href": "/orgs/1/workloads/b", "hostname": "bak-01", "enforcement_mode": "selective",
                 "pce_percent": 0.0, "pce_exposure": "high", "computed_percent": 100.0, "approximate": True,
                 "contradiction": True, "services": [{**svc, "protection_state": "protected_open"}]}]})
        conn.execute("INSERT INTO ransomware_snapshot_daily (day, workload_href, name, port, proto, severity, "
                     "protection_state, port_status) VALUES ('2026-10-22', '/orgs/1/workloads/a', 'SMB', 445, 6, "
                     "'critical', 'unprotected', 'listening')")
        conn.execute("INSERT INTO org_risk_snapshot_daily (day, summary_json) VALUES ('2026-10-26', ?)",
                     (json.dumps({"ransomware": {"ransomware_protection_coverage_percent": 12.5}}),))
        d = datetime(2026, 10, 22, 3, tzinfo=UTC)
        events = [audit_event("agent.tampering", d, system=True),
                  audit_event("sec_policy.create", d, user="alice", extra={"resource_changes": [{"resource": {
                      "sec_policy": {"commit_message": "open db", "workloads_affected": 3}}}]}),
                  audit_event("rule_set.update", d, user="alice"),
                  *(audit_event("request.authentication_failed", d + timedelta(minutes=i), user="eve",
                                ip="10.1.1.1", status="failure") for i in range(5)),
                  audit_event("api_key.create", d + timedelta(minutes=12), user="eve")]  # after the failures
        upsert_events(conn, events, origin=DataOrigin.INGEST, now=NOW)
        conn.commit()


def _rule_flows(c):
    """Flows that make every findings rule fire (thresholds lowered), so all rule copy is rendered."""
    c.settings.update(c.settings.current().revision, lambda d: d["reports"]["rule_thresholds"].update(
        unmanaged_connection=1, min_policy_coverage_pct=100, lateral_outbound_dst=1, user_destination=1,
        cross_env_connection=1, discovery_protocol=1, db_unique_src_app=1, identity_unique_src_app=1, blast_radius=1,
        unmanaged_critical=1, pb_lateral=1, exfil_mb=1, cross_env_lateral=1))
    flows = [flow(port=445, src_env="Dev", dst_env="Prod"), flow(port=5900), flow(port=22, decision="potentially_blocked"),
             flow(port=1433, unmanaged_src=True), flow(port=443, unmanaged_src=True),
             flow(src="jump", dst="t1", port=22), flow(src="jump", dst="t2", port=22),
             flow(dst="t1", port=443, user="CORP\\alice"), flow(dst="t2", port=443, user="CORP\\alice"),
             flow(port=23, decision="blocked"), flow(port=137, proto=17), flow(port=1433, src_app="A", src_env="Prod"), flow(port=1433),
             flow(port=389, src_app="A"), flow(port=389, src_app="B"), flow(port=443, unmanaged_dst=True, bytes_=2 * 1024 * 1024),
             *(flow(dst=f"p{i}", port=443, bytes_=1000) for i in range(20)),
             flow(dst="big", port=443, bytes_=50 * 1024 * 1024)]
    with c.flows().connect() as conn:
        upsert_flows(conn, flows, origin=DataOrigin.INGEST, now=NOW)


def _custom(ctx):
    """A custom report with each kind of section (P6e): a flow ranking, a flow detail, an event ranking."""
    from illumio_ops.domain.segment import GroupBy
    from illumio_ops.services import custom_reports
    from illumio_ops.services.workbench import EventRequest, FlowRequest
    window = {"start": END - timedelta(days=1), "end": END}
    rep = custom_reports.add_section(ctx, report_id=None, name="Custom", title="Ranking", by="t", now=NOW,
                                     request=FlowRequest(mode="flows", view="ranking",
                                                         group_by=(GroupBy(dimension="dst_host"),), **window))
    custom_reports.add_section(ctx, report_id=rep.id, name=None, title="Detail", by="t", now=NOW,
                               request=FlowRequest(mode="flows", view="detail", **window))
    custom_reports.add_section(ctx, report_id=rep.id, name=None, title="Events", by="t", now=NOW,
                               request=EventRequest(mode="events", view="ranking",
                                                    group_by=(GroupBy(dimension="event_type"),), **window))
    return rep.id


def _outputs(ctx, report_type, lang):
    cond = APP_DB if specs()[report_type].requires_app else None
    custom_id = _custom(ctx) if report_type is ReportType.CUSTOM else None
    inp = BuildInput(ctx=ctx, params=ReportParams(report_type=report_type, filter=cond, custom_id=custom_id),
                     start=START, end=END, lang=lang, tz=UTC, now=NOW, pce_label="pce")
    doc = specs()[report_type].build(inp).model_copy(update={"gui_link": "https://ops.example/reports?id=1"})
    wb = load_workbook(BytesIO(render_xlsx(doc, tz=UTC)))
    cells = "\n".join(str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row
                      if c.value is not None)
    mail = render_email(doc, tz=UTC)
    return {"html": render_html(doc, tz=UTC), "xlsx": cells + "\n" + "\n".join(wb.sheetnames),
            "email": mail.subject + "\n" + mail.text + "\n" + (mail.html or "")}


def _raw_keys(text):
    """The message keys left in an output's own text (its stylesheet and script apart)."""
    body = text.split("<style>", 1)[0] + text.split("</style>", 1)[-1].split("<script>", 1)[0]
    return sorted(set(RAW_KEY.findall(body)))


def _english_copy():
    """The English report sentences a zh_TW output must not carry."""
    return [v for k, v in EN.items() if k.startswith(("rpt_", "detector_name_")) and len(v) > 12
            and not re.search(r"\{\w+\}", v) and v.isascii() and v not in PCE_TERMS]


@pytest.mark.parametrize("lang", [Language.EN, Language.ZH_TW])
@pytest.mark.parametrize("report_type", GENERATED)
def test_no_raw_keys_in_output(ctx, report_type, lang):
    for kind, text in _outputs(ctx, report_type, lang).items():
        found = _raw_keys(text)
        assert found == [], f"{report_type} {lang} {kind}: {found}"


@pytest.mark.parametrize("report_type", GENERATED)
def test_zh_tw_has_no_english_report_copy(ctx, report_type):
    english = _english_copy()
    for kind, text in _outputs(ctx, report_type, Language.ZH_TW).items():
        leaked = [s for s in english if s in text]
        assert leaked == [], f"{report_type} {kind}: {leaked[:3]}"


def test_period_kept_in_both_languages(ctx):
    for lang in Language:
        assert "2026-10-20 – 2026-10-26" in _outputs(ctx, ReportType.LATERAL_POSTURE, lang)["email"]
    assert START + timedelta(days=7) == END


def test_every_rule_rendered(ctx):
    """The sample makes all rules fire, so the two checks above read every rule's copy in both languages."""
    for lang in Language:
        doc = specs()[ReportType.SECURITY_RISK].build(BuildInput(
            ctx=ctx, params=ReportParams(report_type=ReportType.SECURITY_RISK), start=START, end=END, lang=lang,
            tz=UTC, now=NOW, pce_label="pce"))
        # stage 3a: every rule that fired is a finding; all were evaluated, so there is no closing section
        assert len(doc.findings) == len(RULES) and "findings" not in {s.id for s in doc.sections}


def test_every_finding_names_a_registered_thing_to_do(ctx):
    """Stage 3a: in every report type the sample builds, a finding that carries an action code carries one the
    order of the first page knows (ACTION_ORDER), with its sentence; the types whose findings all carry one are
    named, so a builder that stops setting it is caught. (This sample gives readiness no finding, and policy usage
    only the one of its Rule Hit Count chapter — its draft recompute is not answered here: their own test files
    assert theirs.)"""
    from illumio_ops.domain.actions import ACTION_ORDER
    coded: dict[ReportType, set[str]] = {}
    for report_type in GENERATED:
        cond = APP_DB if specs()[report_type].requires_app else None
        custom_id = _custom(ctx) if report_type is ReportType.CUSTOM else None
        for lang in Language:
            doc = specs()[report_type].build(BuildInput(
                ctx=ctx, params=ReportParams(report_type=report_type, filter=cond, custom_id=custom_id), start=START,
                end=END, lang=lang, tz=UTC, now=NOW, pce_label="pce"))
            for f in doc.findings:
                if f.action_code is not None:
                    assert f.action_code in ACTION_ORDER and f.action_short.strip(), (report_type, f.title)
                    assert not RAW_KEY.findall(f.what + f.why + f.action_short + f.action_focus), (report_type, f.title)
                    coded.setdefault(report_type, set()).add(f.action_code)
            if report_type not in (ReportType.POLICY_RESOLVER, ReportType.CUSTOM):
                assert all(f.action_code for f in doc.findings), report_type
    with_findings = {t for t, codes in coded.items() if codes}
    assert with_findings >= {
        ReportType.SECURITY_RISK, ReportType.TRAFFIC, ReportType.APP_SUMMARY, ReportType.NETWORK_INVENTORY,
        ReportType.POLICY_USAGE, ReportType.POLICY_DIFF, ReportType.AUDIT, ReportType.NEW_CONNECTIONS, ReportType.UNMANAGED_ENDPOINTS, ReportType.VEN_STATUS,
        ReportType.RANSOMWARE}, sorted(t.value for t in with_findings)
    assert coded[ReportType.POLICY_DIFF] == {"risky_change", "pending_other"}
    # the allow rules at 0 hits, from the chapter that was the Rule Hit Count report (its "waiting to be provisioned"
    # finding did not come along: policy usage has its own, from the draft recompute)
    assert coded[ReportType.POLICY_USAGE] == {"unused_rules"}


def test_injected_missing_key_is_caught(ctx, monkeypatch):
    from illumio_ops import i18n
    real = i18n.dictionary

    def without(lang):
        return {k: v for k, v in real(lang).items() if k != "rpt_rule_b002_name"}
    monkeypatch.setattr(i18n, "dictionary", without)
    html = _outputs(ctx, ReportType.SECURITY_RISK, Language.ZH_TW)["html"]
    assert "rpt_rule_b002_name" in RAW_KEY.findall(html.split("</style>", 1)[-1])


COVERAGE_BUILDERS = (ReportType.APP_SUMMARY, ReportType.SECURITY_RISK, ReportType.READINESS,
                     ReportType.NETWORK_INVENTORY, ReportType.LATERAL_POSTURE, ReportType.NEW_CONNECTIONS,
                     ReportType.UNMANAGED_ENDPOINTS, ReportType.TRAFFIC, ReportType.CUSTOM,
                     ReportType.WEEKLY_OVERVIEW)


@pytest.mark.parametrize("report_type", COVERAGE_BUILDERS)
def test_a_collection_gap_is_said_under_the_conclusion_and_listed_in_the_notes(ctx, monkeypatch, report_type):
    """Every builder that reads traffic hands on both halves of coverage_text: the one sentence and the lines."""
    import sys

    from illumio_ops.services.reports.generate import CoverageText
    said = CoverageText(lines=("the gap, line by line",), caveats=("the gap, in one sentence",))
    module = sys.modules[specs()[report_type].build.__module__]
    monkeypatch.setattr(module, "coverage_text", lambda *a, **k: said)
    cond = APP_DB if specs()[report_type].requires_app else None
    custom_id = _custom(ctx) if report_type is ReportType.CUSTOM else None
    doc = specs()[report_type].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=report_type, filter=cond, custom_id=custom_id), start=START, end=END,
        lang=Language.EN, tz=UTC, now=NOW, pce_label="pce"))
    assert doc.caveats == said.caveats and said.lines[0] in doc.data_quality


def _host_tables(ctx, report_type, lang=Language.EN):
    cond = APP_DB if specs()[report_type].requires_app else None
    custom_id = _custom(ctx) if report_type is ReportType.CUSTOM else None
    doc = specs()[report_type].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=report_type, filter=cond, custom_id=custom_id), start=START, end=END,
        lang=lang, tz=UTC, now=NOW, pce_label="pce"))
    return [(s.id, b) for s, b in doc.tables()]


def _check_host_columns(ctx, tables):
    """A host column carries one key per row the HTML prints, and the key is the host the cell names: resolved the
    way the inventory names it, the nth key gives the nth cell's text."""
    from illumio_ops.domain.report import HTML_ROW_CAP
    from illumio_ops.services.hosts import display_names
    from illumio_ops.services.reports.common import unnamed_host
    for sid, table in tables:
        host_cols = {c.key for c in table.columns if c.kind == "host"}
        assert set(table.host_keys) == host_cols, (sid, table.title)
        named = display_names(ctx, {k for keys in table.host_keys.values() for k in keys if k}, lang=Language.EN)
        for col, keys in table.host_keys.items():
            i = [c.key for c in table.columns].index(col)
            assert len(keys) == min(len(table.rows), HTML_ROW_CAP), (sid, table.title, col)
            for key, row in zip(keys, table.rows, strict=False):
                if key is not None:
                    assert row[i] in (named.get(key), key.removeprefix("ip:"), key.rsplit("/", 1)[-1],
                                      unnamed_host(key, Language.EN)), (sid, table.title, col, key, row[i])


@pytest.mark.parametrize("report_type", GENERATED)
def test_every_host_column_knows_which_host_each_row_names(ctx, report_type):
    _check_host_columns(ctx, _host_tables(ctx, report_type))


HOST_TABLES = {  # report type -> (section, column, the part of the host page its links open at)
    ReportType.LATERAL_POSTURE: {("assets", "asset", "connections"), ("reach", "host", "connections"),
                                 ("pivots", "host", "connections"), ("detections", "subject", "connections"),
                                 ("cross_env", "src", "connections"), ("cross_env", "dst", "connections"),
                                 ("directory", "subject", "connections")},  # its other two: test_lateral_posture
    ReportType.NEW_CONNECTIONS: {("by_destination", "dst", "connections"), ("admin", "src", "connections"),
                                 ("admin", "dst", "connections"), ("all", "src", "connections"),
                                 ("all", "dst", "connections")},
    ReportType.UNMANAGED_ENDPOINTS: {("admin", "address", "connections"),  # candidates: test_unmanaged
                                     ("public", "address", "connections"), ("all", "address", "connections")},
    ReportType.VEN_STATUS: {("offline", "host", "status"), ("online", "host", "status"), ("sync", "host", "status"),
                            ("tamper", "host", "tamper")},
    ReportType.RANSOMWARE: {("hosts", "host", "ransomware")},
    ReportType.NETWORK_INVENTORY: {("hygiene", "host", None)},
    ReportType.WEEKLY_OVERVIEW: {("alerts", "host", "alerts"), ("vens", "host", "status")},
}


@pytest.mark.parametrize("report_type", list(HOST_TABLES))
def test_the_tables_that_name_hosts_carry_their_keys(ctx, report_type):
    got = {(sid, col, table.host_section) for sid, table in _host_tables(ctx, report_type)
           for col, keys in table.host_keys.items() if any(keys)}
    assert got >= HOST_TABLES[report_type], HOST_TABLES[report_type] - got


@pytest.mark.parametrize("report_type", [ReportType.TRAFFIC, ReportType.SECURITY_RISK, ReportType.NETWORK_INVENTORY,
                                         ReportType.APP_SUMMARY])
def test_a_period_without_traffic_is_not_said_as_nothing_to_do(ctx, report_type):
    """The rules did not run (a period no flow falls in): through finish() and the renderer, the first page says so
    and points at the rules section — never "nothing needs action" (stage 3a Task 6)."""
    from illumio_ops.services.reports.finish import finish
    from tests.services.reports.dom import dom
    cond = APP_DB if specs()[report_type].requires_app else None
    early = timedelta(days=60)
    doc = finish(specs()[report_type].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=report_type, filter=cond), start=START - early, end=END - early,
        lang=Language.EN, tz=UTC, now=NOW, pce_label="pce")))
    assert doc.findings == () and "findings" in [s.id for s in doc.sections]
    page = dom(render_html(doc, tz=UTC))
    top = page.one("data-role", "top-actions")
    assert top.text().startswith("This period has no traffic to evaluate the rules on; see “")
    assert top.find("a")[0].attrs["href"] == "#findings" and len(page.find_attr("id", "findings")) == 1
    assert "Nothing in this report needs action" not in page.text()


@pytest.mark.parametrize("lang", [Language.EN, Language.ZH_TW])
@pytest.mark.parametrize("report_type", GENERATED)
def test_no_chapter_repeats_the_heading_of_the_closing_part(ctx, report_type, lang):
    """The closing part is headed "How to read this report": a chapter under it says what it holds, not that again."""
    cond = APP_DB if specs()[report_type].requires_app else None
    custom_id = _custom(ctx) if report_type is ReportType.CUSTOM else None
    doc = specs()[report_type].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=report_type, filter=cond, custom_id=custom_id), start=START, end=END,
        lang=lang, tz=UTC, now=NOW, pce_label="pce"))
    part = translate(lang, "rpt_part_how", {})
    assert part not in [s.title for s in doc.sections]


@pytest.mark.parametrize("lang", [Language.EN, Language.ZH_TW])
def test_what_left_the_security_risk_report_has_its_place(ctx, lang):
    """Stage 3b: ransomware is a number whose note names the ransomware report, lateral movement a sentence that
    names its report, users and processes a chapter of the traffic report. Nothing moved without landing."""
    from illumio_ops.domain.report import TableBlock, TextBlock

    def build(report_type):
        return specs()[report_type].build(BuildInput(
            ctx=ctx, params=ReportParams(report_type=report_type), start=START, end=END, lang=lang, tz=UTC, now=NOW,
            pce_label="pce"))
    risk, traffic = build(ReportType.SECURITY_RISK), build(ReportType.TRAFFIC)
    assert not {"ransomware", "lateral", "users", "ports"} & {s.id for s in risk.sections}
    kpis = {k.key: k for k in risk.kpis}
    assert "lateral_detections" not in kpis
    assert translate(lang, "rpt_title_ransomware", {}) in (kpis["ransomware_protected_pct"].note or "")
    coverage = next(s for s in risk.sections if s.id == "coverage")
    assert any(translate(lang, "rpt_title_lateral_posture", {}) in p for b in coverage.blocks
               if isinstance(b, TextBlock) for p in b.paragraphs)
    uncovered = [b for s in risk.sections if s.id == "uncovered" for b in s.blocks if isinstance(b, TableBlock)]
    assert [t.title for t in uncovered] == [translate(lang, "rpt_sec_tbl_uncovered", {}),
                                            translate(lang, "rpt_sec_tbl_port_gaps", {})]
    assert "users" in [s.id for s in traffic.sections]
    users = next(s for s in traffic.sections if s.id == "users")
    assert [b.rows for b in users.blocks if isinstance(b, TableBlock)] == [(("corp\\alice", 2),)]


# ── flows without a decision (stage 3b). The install above holds none — adding them would move its pinned numbers —
# so what a report says about them is read from a second install: both kinds, a host in Idle now and hosts not. ──

UNDECIDED_TYPES = (ReportType.SECURITY_RISK, ReportType.TRAFFIC, ReportType.APP_SUMMARY, ReportType.READINESS)
WITH_CHAPTER = (ReportType.SECURITY_RISK, ReportType.TRAFFIC, ReportType.APP_SUMMARY)


@pytest.fixture(scope="module")
def undecided(ctx, tmp_path_factory):
    """`ctx` is asked for its patches: the readiness report's draft recompute is a PCE call."""
    c = configured_ctx(tmp_path_factory.mktemp("undecided"))
    undecided_sample(c)
    return c


@pytest.mark.parametrize("lang", [Language.EN, Language.ZH_TW])
@pytest.mark.parametrize("report_type", UNDECIDED_TYPES)
def test_what_is_said_of_undecided_flows_has_no_raw_key_and_no_english_in_zh(undecided, report_type, lang):
    out = _outputs(undecided, report_type, lang)
    # the copy under test is in the output: the sentence under the conclusion, and the chapter where there is one
    for kind in ("html", "xlsx", "email"):
        assert translate(lang, "rpt_caveats_title", {}) in out[kind], kind
    if report_type in WITH_CHAPTER:
        assert translate(lang, "rpt_mon_tbl_hosts", {}) in out["html"] and translate(lang, "rpt_mon_tbl_hosts", {})[:31] in out["xlsx"]
        assert translate(lang, "rpt_mon_idle_note", {}) in out["html"]
    english = _english_copy() if lang is Language.ZH_TW else []
    for kind, text in out.items():
        assert _raw_keys(text) == [], f"{report_type} {lang} {kind}"
        leaked = [s for s in english if s in text]
        assert leaked == [], f"{report_type} {kind}: {leaked[:3]}"


@pytest.mark.parametrize("report_type", WITH_CHAPTER)
def test_the_undecided_chapters_host_columns_know_their_hosts(undecided, report_type):
    tables = _host_tables(undecided, report_type)
    named = {(sid, col, table.host_section) for sid, table in tables for col, keys in table.host_keys.items()
             if any(keys)}
    assert ("monitor_only", "host", "connections") in named and ("monitor_only", "host", None) in named
    assert sum(1 for sid, t in tables if sid == "monitor_only" and t.host_keys) >= 3  # two rankings and the hosts
    _check_host_columns(undecided, tables)


@pytest.mark.parametrize("lang", [Language.EN, Language.ZH_TW])
@pytest.mark.parametrize("report_type", UNDECIDED_TYPES)
def test_the_first_page_says_how_many_flows_have_no_decision(undecided, report_type, lang):
    """Through finish() and the renderer: the sentence stands under the conclusion (after the collection gap this
    sample has), and in the three flow reports it names a chapter the page has."""
    from illumio_ops.services.reports.finish import finish
    from tests.services.reports.dom import dom
    cond = APP_DB if specs()[report_type].requires_app else None
    doc = finish(specs()[report_type].build(BuildInput(
        ctx=undecided, params=ReportParams(report_type=report_type, filter=cond), start=START, end=END, lang=lang,
        tz=UTC, now=NOW, pce_label="pce")))
    assert len(doc.caveats) == 2  # no coverage is recorded here: the gap first, then the undecided flows
    page = dom(render_html(doc, tz=UTC))
    said = page.one("data-role", "caveats").text()
    assert doc.caveats[0] in said and doc.caveats[1] in said
    chapter = translate(lang, "rpt_mon_sec", {})
    assert (chapter in doc.caveats[1]) == (report_type in WITH_CHAPTER)
    assert len(page.find_attr("id", "monitor_only")) == (1 if report_type in WITH_CHAPTER else 0)
    if report_type in WITH_CHAPTER:
        assert chapter in [s.title for s in doc.sections]
