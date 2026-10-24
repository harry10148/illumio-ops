"""Archive: complete UTC days only, once, atomically; archive files expire by retention_days."""
import gzip
import json
import os
from datetime import timedelta

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.services.collect.archive import run_archive
from illumio_ops.store.flowdb.flows import upsert_flows

from .conftest import NOW, configured_ctx, raw_flow


def _enable(ctx, retention_days=0):
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"]["archive"].update(
        {"enabled": True, "retention_days": retention_days}))


def _write_flows(ctx, ages):
    recs = [normalize_flow(raw_flow(i, NOW - timedelta(days=a, minutes=5), NOW - timedelta(days=a)))
            for i, a in enumerate(ages)]
    with ctx.flows().connect() as conn:
        upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW)


def test_archive_disabled_writes_nothing(tmp_path):
    ctx = configured_ctx(tmp_path)
    _write_flows(ctx, [2])
    assert run_archive(ctx, now=NOW) == 0 and list(ctx.paths.archive_dir.iterdir()) == []


def test_archive_writes_complete_days_once_atomically(tmp_path):
    ctx = configured_ctx(tmp_path)
    _enable(ctx)
    _write_flows(ctx, [2, 2, 1, 0])  # today (0) is not complete yet
    assert run_archive(ctx, now=NOW) == 2
    files = sorted(p.name for p in ctx.paths.archive_dir.iterdir())
    day2 = (NOW - timedelta(days=2)).strftime("%Y-%m-%d")
    assert f"flows-{day2}.jsonl.gz" in files and not any(f.endswith(".tmp") for f in files)
    with gzip.open(ctx.paths.archive_dir / f"flows-{day2}.jsonl.gz", "rt") as fh:
        rows = [json.loads(line) for line in fh]
    assert len(rows) == 2 and {"src_ip", "dst_ip", "conn_key", "is_primary"} <= set(rows[0])
    assert (os.stat(ctx.paths.archive_dir / f"flows-{day2}.jsonl.gz").st_mode & 0o777) == 0o600
    assert run_archive(ctx, now=NOW) == 0  # already archived


def test_archive_retention_deletes_old_files(tmp_path):
    ctx = configured_ctx(tmp_path)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"]["retention"].update(
        {"flow_days": 7, "event_days": 7, "rollup_days": 7, "baseline_days": 7}))
    _enable(ctx, retention_days=8)
    _write_flows(ctx, [10, 2])
    run_archive(ctx, now=NOW)
    names = sorted(p.name for p in ctx.paths.archive_dir.iterdir())
    assert names == [f"flows-{(NOW - timedelta(days=2)).strftime('%Y-%m-%d')}.jsonl.gz"]
