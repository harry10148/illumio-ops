"""Reports over a period the store no longer keeps (parity audit 2026-11-06 A2, B1): a manual report names its own
days, and the part before the store's floor is read from the archive; the report says which days came from there."""
from datetime import timedelta

import pytest
from pydantic import ValidationError

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import (
    DataOrigin,
    IngestSource,
    Language,
    ReportStatus,
    ReportType,
)
from illumio_ops.services.collect.archive import run_archive
from illumio_ops.services.collect.retention import run_retention
from illumio_ops.services.reports import generate
from illumio_ops.services.reports.registry import ReportParams
from illumio_ops.store import reports as store
from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.flows import upsert_flows
from tests.services.collect.conftest import NOW, configured_ctx, raw_flow


def _ctx(tmp_path, *, archive=True):
    ctx = configured_ctx(tmp_path)
    ctx.settings.update(ctx.settings.current().revision, lambda d: (
        d["collection"]["retention"].update({"flow_days": 7, "event_days": 7, "rollup_days": 7, "baseline_days": 7}),
        d["collection"]["archive"].update({"enabled": archive, "retention_days": 0}),
        d["display"].update({"timezone": "UTC", "language": "en"})))
    recs = [normalize_flow(raw_flow(i, NOW - timedelta(days=a, minutes=5), NOW - timedelta(days=a)))
            for i, a in enumerate([100, 12, 10, 3, 2])]
    with ctx.flows().connect() as conn:
        upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW)
    run_archive(ctx, now=NOW)
    run_retention(ctx, now=NOW)
    return ctx


def _params(**over):
    base = {"report_type": ReportType.TRAFFIC, "lang": Language.EN,
            "period_from": (NOW - timedelta(days=12)).date(), "period_to": (NOW - timedelta(days=1)).date()}
    return ReportParams(**{**base, **over})


def test_a_traffic_report_reads_the_days_the_store_dropped_from_the_archive(tmp_path):
    ctx = _ctx(tmp_path)
    rid = generate.enqueue(ctx, _params(), trigger="manual", schedule_id=None, now=NOW)
    assert generate.run_queued(ctx, now=NOW) == rid
    with ctx.db() as conn:
        row = store.get(conn, rid)
    assert row.status is ReportStatus.DONE, (row.error_key, row.error_detail)
    assert row.period_start.date() == (NOW - timedelta(days=12)).date()
    flows = next(k for k in row.kpis if k["key"] == "flows")
    assert flows["value"] == 4  # two kept rows and the two the archive brought back
    html = (ctx.paths.reports_dir / str(rid) / next(f for f in row.files if f.endswith(".html"))).read_text()
    assert "comes from the archive" in html


def test_without_the_archive_a_period_beyond_the_pce_pull_is_refused(tmp_path):
    """Without the archive a flow report pulls an older part from the PCE, up to its 90 days."""
    ctx = _ctx(tmp_path, archive=False)
    rid = generate.enqueue(ctx, _params(period_from=(NOW - timedelta(days=100)).date()), trigger="manual",
                           schedule_id=None, now=NOW)
    with ctx.db() as conn:
        assert store.get(conn, rid).error_key == "rpt_err_lookback_beyond_retention"


def test_a_period_before_the_first_archive_day_is_refused(tmp_path):
    ctx = _ctx(tmp_path)
    ok = generate.enqueue(ctx, _params(period_from=(NOW - timedelta(days=100)).date()), trigger="manual",
                          schedule_id=None, now=NOW)
    with ctx.db() as conn:
        assert store.get(conn, ok).error_key is None  # the archive reaches back 100 days
    rid = generate.enqueue(ctx, _params(period_from=(NOW - timedelta(days=110)).date()), trigger="manual",
                           schedule_id=None, now=NOW)
    with ctx.db() as conn:
        assert store.get(conn, rid).error_key == "rpt_err_before_archive"


def test_a_period_must_be_over_and_name_both_days(tmp_path):
    ctx = _ctx(tmp_path)
    assert generate.refusal(ctx.settings.current(), _params(period_to=NOW.date()), now=NOW) == "rpt_err_period_not_over"
    with pytest.raises(ValidationError):
        ReportParams(report_type=ReportType.TRAFFIC, period_from=NOW.date())
    with pytest.raises(ValidationError):
        _params(period_from=(NOW - timedelta(days=1)).date(), period_to=(NOW - timedelta(days=3)).date())


def test_schedules_keep_counting_back_from_today():
    start, end = generate.params_period(ReportParams(report_type=ReportType.TRAFFIC, lookback_days=3), NOW, None)
    assert (end - start).days == 3


def test_an_audit_report_reads_archived_events(tmp_path):
    from illumio_ops.domain.events import normalize_event
    from illumio_ops.store.flowdb.events import upsert_events
    ctx = configured_ctx(tmp_path)
    ctx.settings.update(ctx.settings.current().revision, lambda d: (
        d["collection"]["retention"].update({"flow_days": 7, "event_days": 7, "rollup_days": 7, "baseline_days": 7}),
        d["collection"]["archive"].update({"enabled": True, "retention_days": 0}),
        d["display"].update({"timezone": "UTC", "language": "en"})))
    raw = [{"href": f"/orgs/1/events/e-{i}", "event_type": "user.sign_in", "severity": "info", "status": "success",
            "timestamp": (NOW - timedelta(days=a)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "created_by": {"user": {"href": "/users/1", "username": "u"}}} for i, a in enumerate([12, 2])]
    with ctx.flows().connect() as conn:
        upsert_events(conn, [normalize_event(r) for r in raw], origin=DataOrigin.INGEST, now=NOW)
        ingest_state.add_coverage(conn, IngestSource.EVENTS, NOW - timedelta(days=14), NOW)
    run_archive(ctx, now=NOW)
    run_retention(ctx, now=NOW)
    rid = generate.enqueue(ctx, _params(report_type=ReportType.AUDIT), trigger="manual", schedule_id=None, now=NOW)
    assert generate.run_queued(ctx, now=NOW) == rid
    with ctx.db() as conn:
        row = store.get(conn, rid)
    assert row.status is ReportStatus.DONE, (row.error_key, row.error_detail)
    assert next(k for k in row.kpis if k["key"] == "total")["value"] == 2
    html = (ctx.paths.reports_dir / str(rid) / next(f for f in row.files if f.endswith(".html"))).read_text()
    assert "come from the archive" in html
    assert "Events are missing" not in html  # the archived days are read and covered, not a gap before retention
