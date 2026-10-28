"""Final-review findings on the P5b-2 reports (Codex, 2026-10-28), each pinned by the input that broke it."""
import copy
import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from illumio_ops.domain.filter import EndpointFilter, FlowCondition, LabelCond
from illumio_ops.domain.report import BarBlock, TableBlock, TextBlock
from illumio_ops.domain.values import Language, ReportStatus, ReportType
from illumio_ops.pce.async_query import AsyncQueryResult
from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.services.analysis import predicted_block
from illumio_ops.services.analysis.predicted_block import predicted_summary
from illumio_ops.services.reports import generate
from illumio_ops.services.reports import readiness as readiness_report
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.store import reports as report_store
from illumio_ops.store.flowdb import analysis, labels, workloads
from illumio_ops.store.flowdb.db import db_time
from tests_v6.services.analysis.test_predicted_block import ROWS, SPEC, fake  # noqa: F401  (fixture)
from tests_v6.services.collect.conftest import configured_ctx
from tests_v6.services.reports.test_audit import _write as write_events
from tests_v6.services.reports.test_audit import event
from tests_v6.services.reports.test_findings import flow
from tests_v6.services.reports.test_readiness import summary
from tests_v6.services.reports.test_traffic import _write as write_flows

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)


def _build(ctx, report_type, *, cond=None, tz=UTC, start=START, end=END, now=NOW):
    return specs()[report_type].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=report_type, filter=cond), start=start, end=end, lang=Language.EN,
        tz=tz, now=now, pce_label="pce"))


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _tables(doc, sid):
    return [b for b in _section(doc, sid).blocks if isinstance(b, TableBlock)]


def _texts(doc, sid=None):
    secs = [_section(doc, sid)] if sid else doc.sections
    return " ".join(p for s in secs for b in s.blocks if isinstance(b, TextBlock) for p in b.paragraphs)


def _kpi(doc):
    return {k.key: k for k in doc.kpis}


def _inventory(ctx, hosts):
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=f"/orgs/1/workloads/{n}", hostname=n, name=None, managed=1, enforcement_mode=mode,
            visibility_level=None, os_id=None, ven_version="26.2", ven_href=None,
            label_set=labels.label_set_id(conn, (("app", app), ("env", "Dev"))), online=1, risk_exposure=None,
            risk_percent=None, risk_updated_at=None, fetched_at=db_time(NOW), agent_status="active",
            last_heartbeat_at=db_time(NOW - timedelta(minutes=5)), policy_sync_state="applied",
            policy_received_at=db_time(NOW), policy_applied_at=db_time(NOW), fw_config_current=1)
            for n, app, mode in hosts])
        conn.commit()


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness_report, "predicted_summary", lambda ctx, spec, **kw: summary())
    return configured_ctx(tmp_path)


# 1: one window for every audit read: [start, end)
def test_audit_event_at_the_end_is_outside(ctx):
    write_events(ctx, [event("sec_policy.create", END, user="alice")])
    doc = _build(ctx, ReportType.AUDIT)
    assert _tables(doc, "policy")[0].rows == ()


# 2: a failed policy read after the recompute is said, the report still built
def test_readiness_survives_policy_read_failure(ctx, monkeypatch):
    def boom(ctx_, spec, **kw):
        raise PceCollectionIncomplete("/sec_policy/draft/rule_sets", 0, "HTTP 403")
    monkeypatch.setattr(readiness_report, "predicted_summary", boom)
    write_flows(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    doc = _build(ctx, ReportType.READINESS)
    assert "could not" in _texts(doc, "predicted").lower() and _tables(doc, "scores")[0].rows


# 4: rows without a draft decision are counted, and zero blocked is not claimed
def test_summary_counts_undetermined(tmp_path, fake, monkeypatch):  # noqa: F811
    rows = copy.deepcopy(ROWS)
    for r in rows:
        r.pop("draft_policy_decision", None)
    monkeypatch.setattr(predicted_block, "run_traffic_query", lambda client, payload, **kw: AsyncQueryResult(
        rows=rows, matches_count=len(rows), flows_count=len(rows), capped=False))
    s = predicted_summary(configured_ctx(tmp_path), SPEC)
    assert s.undetermined_flows > 0 and s.blocked_flows == 0


def test_readiness_says_undetermined(ctx, monkeypatch):
    monkeypatch.setattr(readiness_report, "predicted_summary", lambda ctx_, spec, **kw: summary(
        groups=[], blocked_flows=0, blocked_connections=0, undetermined_flows=5))
    write_flows(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    doc = _build(ctx, ReportType.READINESS)
    assert "5" in _texts(doc, "predicted") and _kpi(doc)["predicted_blocked"].value is None


# 5: an app without traffic in the period is not scored
def test_no_traffic_not_scored(ctx):
    _inventory(ctx, [("d1", "DB", "full")])
    write_flows(ctx, [flow(src_app="Web", dst_app="Web", port=443)])
    doc = _build(ctx, ReportType.READINESS)
    db = {r[0]: r for r in _tables(doc, "scores")[0].rows}["DB (Dev)"]
    assert db[1] is None and db[2] == "—" and _kpi(doc)["ready"].value == 1  # Web only
    assert "DB (Dev)" not in [r[0] for r in _tables(doc, "queue")[0].rows]


# 7: a stored result is dated, and a later failure is said
def test_stale_analysis_disclosed(ctx):
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "ransomware", params={}, at=NOW - timedelta(days=30), result={
            "unsupported": False, "priority": [], "safe_to_block": [], "suspicious": [], "hosts": []})
        analysis.set_run(conn, "ransomware", ok_at=NOW - timedelta(days=30))
        analysis.set_run(conn, "ransomware", error="PCE timeout")
        conn.commit()
    doc = _build(ctx, ReportType.RANSOMWARE)
    quality = " ".join(doc.data_quality)
    assert "2026-09-27" in quality and "PCE timeout" in quality


# 8: a source condition does not take the destination app's hosts away
def test_readiness_source_filter_keeps_destination_hosts(ctx):
    _inventory(ctx, [("w1", "Web", "full"), ("d1", "DB", "full")])
    write_flows(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    cond = FlowCondition(src=EndpointFilter(labels=(LabelCond(key="app", values=("Web",)),)))
    rows = {r[0]: r for r in _tables(_build(ctx, ReportType.READINESS, cond=cond), "scores")[0].rows}
    assert rows["DB (Dev)"][5] == "100.0%" and rows["Web (Dev)"][1] is None  # Web has no traffic into it here


# 9: the predicted blocks counted are the ones into managed hosts, as the scores
def test_summary_into_managed_only(tmp_path, fake, monkeypatch):  # noqa: F811
    rows = copy.deepcopy(ROWS)
    for r in rows:
        r["dst"].pop("workload", None)  # every destination unmanaged
    monkeypatch.setattr(predicted_block, "run_traffic_query", lambda client, payload, **kw: AsyncQueryResult(
        rows=rows, matches_count=len(rows), flows_count=len(rows), capped=False))
    assert predicted_summary(configured_ctx(tmp_path), SPEC).blocked_flows == 0


# 10: VENs are not users in the attention list either
def test_attention_actors_are_users(ctx):
    write_events(ctx, [event("sec_policy.create", datetime(2026, 10, 22, tzinfo=UTC), user="db-ven")])
    from illumio_ops.domain.events import normalize_event
    ven = normalize_event({"href": "/orgs/1/events/v1", "event_type": "sec_policy.create",
                           "timestamp": "2026-10-22T01:00:00Z", "created_by": {"ven": {"href": "/v/1", "hostname": "db-ven"}}})
    write_events(ctx, [ven])
    row = _tables(_build(ctx, ReportType.AUDIT), "attention")[0].rows[0]
    assert row[3] == "db-ven (1)"


# 11: organisation summaries from the period and the period before only
def test_org_summary_bounded_to_the_periods(ctx):
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "ransomware", params={}, at=NOW, result={
            "unsupported": False, "priority": [], "safe_to_block": [], "suspicious": [], "hosts": []})
        conn.execute("INSERT INTO org_risk_snapshot_daily (day, summary_json) VALUES ('2026-09-01', ?)",
                     (json.dumps({"ransomware": {"ransomware_protection_coverage_percent": 42.0}}),))
        conn.commit()
    k = _kpi(_build(ctx, ReportType.RANSOMWARE))["org_percent"]
    assert k.value is None and k.previous is None and "2026-09-01" in k.note


# 12: the audit trend counts local days, across a DST change too
def test_audit_trend_local_days(ctx):
    kolkata = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 10, 21, tzinfo=kolkata).astimezone(UTC)
    end = datetime(2026, 10, 22, tzinfo=kolkata).astimezone(UTC)
    write_events(ctx, [event("user.sign_in", datetime(2026, 10, 21, 0, 15, tzinfo=kolkata).astimezone(UTC), user="a")])
    bars = next(b for b in _section(_build(ctx, ReportType.AUDIT, tz=kolkata, start=start, end=end), "types").blocks
                if isinstance(b, BarBlock))
    assert bars.points == (("2026-10-21", 1),)
    ny = ZoneInfo("America/New_York")
    s2, e2 = datetime(2026, 3, 5, tzinfo=ny).astimezone(UTC), datetime(2026, 3, 12, tzinfo=ny).astimezone(UTC)
    write_events(ctx, [event("user.sign_in", datetime(2026, 3, 6, tzinfo=UTC), user="a")])
    bars = next(b for b in _section(_build(ctx, ReportType.AUDIT, tz=ny, start=s2, end=e2,
                                           now=datetime(2026, 3, 12, 6, tzinfo=UTC)), "types").blocks
                if isinstance(b, BarBlock))
    assert len(bars.points) == 7


# 13: the ransomware trend lists every UTC day the period touches
def test_ransomware_trend_last_utc_day(ctx):
    taipei = ZoneInfo("Asia/Taipei")
    start, end = datetime(2026, 10, 20, tzinfo=taipei), datetime(2026, 10, 27, tzinfo=taipei)
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "ransomware", params={}, at=NOW, result={
            "unsupported": False, "priority": [], "safe_to_block": [], "suspicious": [], "hosts": []})
        conn.execute("INSERT INTO ransomware_snapshot_daily VALUES ('2026-10-26', '/w/1', 'S', 445, 6, 'critical', "
                     "'protected_open', 'listening')")
        conn.commit()
    doc = _build(ctx, ReportType.RANSOMWARE, tz=taipei, start=start.astimezone(UTC), end=end.astimezone(UTC))
    bars = dict(next(b for b in _section(doc, "trend").blocks if isinstance(b, BarBlock)).points)
    assert bars["2026-10-26"] == 100.0


# 14: an earlier report of the same kind gives the previous values
def test_previous_from_the_last_report(ctx):
    _inventory(ctx, [("w1", "Web", "full")])
    params = ReportParams(report_type=ReportType.VEN_STATUS)
    with ctx.db() as conn:
        rid = report_store.insert(conn, report_type="ven_status", params_json=params.model_dump_json(),
                                  status=ReportStatus.QUEUED, trigger="schedule", schedule_id=None, pce_label="pce",
                                  period_start=START - timedelta(days=7), period_end=START, created_at=START,
                                  error_key=None, pce_target=generate.pce_target(ctx.settings.current().pce))
        report_store.finish(conn, rid, status=ReportStatus.DONE, at=START, files=[],
                            kpis=[{"key": "managed", "label": "x", "value": 7, "previous": None}])
    assert _kpi(_build(ctx, ReportType.VEN_STATUS))["managed"].previous == 7


# 15: no events at all: the trend says so instead of drawing zeros
def test_audit_trend_without_events(ctx):
    bars = next(b for b in _section(_build(ctx, ReportType.AUDIT), "types").blocks if isinstance(b, BarBlock))
    assert all(v is None for _, v in bars.points)


# 3: the recompute lets each PCE row go once read, and the readiness report asks for at most 50,000
def test_recompute_releases_rows(tmp_path, fake, monkeypatch):  # noqa: F811
    held = list(ROWS)
    monkeypatch.setattr(predicted_block, "run_traffic_query", lambda client, payload, **kw: AsyncQueryResult(
        rows=held, matches_count=len(held), flows_count=len(held), capped=False))
    predicted_summary(configured_ctx(tmp_path), SPEC)
    assert held == []


def test_readiness_asks_for_50000_rows(ctx, monkeypatch):
    asked = {}

    def capture(ctx_, spec, **kw):
        asked.update(kw)
        return summary()
    monkeypatch.setattr(readiness_report, "predicted_summary", capture)
    write_flows(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    _build(ctx, ReportType.READINESS)
    assert asked["max_results"] == 50_000


def test_blocked_count_kept_with_a_few_undetermined(ctx, monkeypatch):
    """Lab: 1 flow without a draft decision hid 1.3 million blocked connections. Only a zero is unconfirmed."""
    monkeypatch.setattr(readiness_report, "predicted_summary", lambda ctx_, spec, **kw: summary(undetermined_flows=1))
    write_flows(ctx, [flow(src_app="Web", dst_app="DB", port=5432)])
    k = _kpi(_build(ctx, ReportType.READINESS))["predicted_blocked"]
    assert k.value == 7 and "1" in k.note
