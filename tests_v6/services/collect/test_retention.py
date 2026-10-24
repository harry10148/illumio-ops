"""Retention: per-kind cutoffs, whole connections, archive awareness, baseline by last_seen."""
from dataclasses import replace
from datetime import timedelta

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.services.collect.retention import run_retention
from illumio_ops.store.flowdb import archive as archive_store
from illumio_ops.store.flowdb.flows import upsert_flows

from .conftest import NOW, configured_ctx, raw_flow


def _write(ctx, recs):
    with ctx.flows().connect() as conn:
        upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW)


def _count(ctx, table):
    with ctx.flows().connect() as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _rec(i, age_days, **kw):
    last = NOW - timedelta(days=age_days)
    return normalize_flow(raw_flow(i, last - timedelta(minutes=5), last, **kw))


def test_retention_deletes_flows_older_than_flow_days(tmp_path):
    ctx = configured_ctx(tmp_path)  # flow_days 35
    _write(ctx, [_rec(1, 40), _rec(2, 10)])
    counts = run_retention(ctx, now=NOW)
    assert counts["flows"] == 1 and _count(ctx, "flows") == 1


def test_retention_deletes_whole_connections(tmp_path):
    ctx = configured_ctx(tmp_path)
    cutoff = NOW - timedelta(days=35)
    out = replace(_rec(1, 0), first_detected=cutoff - timedelta(minutes=8), last_detected=cutoff + timedelta(minutes=3))
    inn = replace(out, direction=out.direction.__class__("inbound"), last_detected=cutoff - timedelta(minutes=3))
    _write(ctx, [out, inn])  # one connection straddling the cutoff
    run_retention(ctx, now=NOW)
    assert _count(ctx, "flows") == 2  # newest row of the connection is inside retention: keep both


def test_retention_respects_unarchived_days(tmp_path):
    ctx = configured_ctx(tmp_path)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"]["archive"].update({"enabled": True}))
    old = _rec(1, 40)
    _write(ctx, [old])
    run_retention(ctx, now=NOW)
    assert _count(ctx, "flows") == 1  # not archived yet: kept
    with ctx.flows().connect() as conn:
        archive_store.record(conn, "flows", old.last_detected.strftime("%Y-%m-%d"), 1, "/x.jsonl.gz", NOW)
    run_retention(ctx, now=NOW)
    assert _count(ctx, "flows") == 0


def test_retention_prunes_baseline_by_last_seen(tmp_path):
    ctx = configured_ctx(tmp_path)
    _write(ctx, [_rec(1, 31, user="LAB\\alice"), _rec(2, 5, user="LAB\\bob")])
    run_retention(ctx, now=NOW)  # baseline_days 30
    assert _count(ctx, "connection_baseline") == 1 and _count(ctx, "user_baseline") == 1


def test_retention_prunes_rollups_and_snapshots(tmp_path):
    ctx = configured_ctx(tmp_path)
    with ctx.flows().connect() as conn:
        conn.execute("INSERT INTO flow_rollup_daily VALUES ('2026-01-01','a','b',22,6,'allowed','','',1,1,0,0,0)")
        conn.execute("INSERT INTO workload_snapshot_daily VALUES ('2026-01-01','/w',NULL,NULL,NULL,NULL)")
        conn.execute("INSERT INTO org_risk_snapshot_daily VALUES ('2026-01-01','{}')")
        conn.commit()
    counts = run_retention(ctx, now=NOW)  # rollup_days 180
    assert counts["rollups"] == 1 and counts["snapshots"] == 2
