"""Archive: complete UTC days only, once, atomically; archive files expire by retention_days."""
import gzip
import json
import os
import tracemalloc
from datetime import timedelta

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.services.collect import archive as archive_job
from illumio_ops.services.collect.archive import run_archive
from illumio_ops.services.collect.reset import reset_for_new_pce
from illumio_ops.services.collect.retention import run_retention
from illumio_ops.store.flowdb import archive as archive_log
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
    run_retention(ctx, now=NOW)  # the 10-day-old rows go first (an expired file waits for them)
    run_archive(ctx, now=NOW)
    names = sorted(p.name for p in ctx.paths.archive_dir.iterdir())
    assert names == [f"flows-{(NOW - timedelta(days=2)).strftime('%Y-%m-%d')}.jsonl.gz"]


def test_archive_writes_a_day_without_holding_all_its_rows_in_memory(tmp_path):
    # A 1M-row day held as dicts peaked at 3.1 GB (P2 re-measure); rows are written as they are read.
    ctx = configured_ctx(tmp_path)
    _enable(ctx)
    day_ago = NOW - timedelta(days=1)
    recs = [normalize_flow(raw_flow(i, day_ago - timedelta(seconds=i + 300), day_ago - timedelta(seconds=i)))
            for i in range(5000)]
    with ctx.flows().connect() as conn:
        upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW)
    tracemalloc.start()
    try:
        assert run_archive(ctx, now=NOW) == 1
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    day1 = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
    with gzip.open(ctx.paths.archive_dir / f"flows-{day1}.jsonl.gz", "rt") as fh:
        assert sum(1 for _ in fh) == 5000
    assert peak < 4 * 1024 * 1024, f"archiving 5,000 rows peaked at {peak / 1e6:.1f} MB"


def _during_write(monkeypatch, action):
    """Run action() just before the archive job writes a day's file, then write it."""
    real = archive_job._write_atomic

    def write(path, lines):
        action()
        return real(path, lines)
    monkeypatch.setattr(archive_job, "_write_atomic", write)


def test_archive_writes_a_day_without_holding_the_write_lock(tmp_path, monkeypatch):
    # One 1M-row day took 269 s to write (P2 re-measure, 35 days); collection must not wait for it.
    ctx = configured_ctx(tmp_path)
    _enable(ctx)
    _write_flows(ctx, [2, 1])
    held = []
    _during_write(monkeypatch, lambda: held.append(ctx.flows().write_lock.locked()))
    assert run_archive(ctx, now=NOW) == 2
    assert held == [False, False]


def test_a_day_changed_while_its_file_is_written_is_written_again(tmp_path, monkeypatch):
    ctx = configured_ctx(tmp_path)
    _enable(ctx)
    _write_flows(ctx, [1])
    fdb = ctx.flows()
    day1 = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
    late = normalize_flow(raw_flow(7, NOW - timedelta(days=1, minutes=9), NOW - timedelta(days=1, minutes=4)))

    def late_record():
        assert fdb.write_lock.acquire(timeout=1), "the archive job held the write lock while writing"
        try:
            with fdb.connect() as conn:
                upsert_flows(conn, [late], origin=DataOrigin.INGEST, now=NOW)
        finally:
            fdb.write_lock.release()
    _during_write(monkeypatch, late_record)
    assert run_archive(ctx, now=NOW) == 0
    with fdb.connect() as conn:
        assert day1 not in archive_log.archived_days(conn, "flows")  # retention keeps the day's rows
    monkeypatch.undo()
    assert run_archive(ctx, now=NOW) == 1
    with gzip.open(ctx.paths.archive_dir / f"flows-{day1}.jsonl.gz", "rt") as fh:
        assert sum(1 for _ in fh) == 2


def test_a_day_whose_file_could_not_be_written_is_not_archived(tmp_path, monkeypatch):
    ctx = configured_ctx(tmp_path)
    _enable(ctx)
    _write_flows(ctx, [1])

    def disk_full():
        raise OSError(28, "No space left on device")
    _during_write(monkeypatch, disk_full)
    try:
        run_archive(ctx, now=NOW)
    except OSError:
        pass
    with ctx.flows().connect() as conn:
        assert archive_log.archived_days(conn, "flows") == set()


def test_a_pce_switch_while_a_file_is_written_leaves_no_file_for_the_new_pce(tmp_path, monkeypatch):
    ctx = configured_ctx(tmp_path)
    _enable(ctx)
    _write_flows(ctx, [1])

    def switch():
        if not ctx.flows().write_lock.locked():  # (the old code held it: switching here would hang)
            reset_for_new_pce(ctx, now=NOW)
    _during_write(monkeypatch, switch)
    assert run_archive(ctx, now=NOW) == 0
    assert [p.name for p in ctx.paths.archive_dir.iterdir() if p.is_file()] == []


def test_an_expired_archive_file_waits_until_its_rows_are_gone(tmp_path):
    # Raw 7 days, archive 8, but the initial backfill reaches 30 days back: a day older than the archive
    # retention was archived, its file deleted and its log forgotten at once, so retention never
    # dropped its rows (they were "unarchived") and the cycle repeated every day.
    ctx = configured_ctx(tmp_path)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"]["retention"].update(
        {"flow_days": 7, "event_days": 7, "rollup_days": 7, "baseline_days": 7}))
    _enable(ctx, retention_days=8)
    _write_flows(ctx, [10])
    day10 = (NOW - timedelta(days=10)).strftime("%Y-%m-%d")
    run_archive(ctx, now=NOW)
    assert (ctx.paths.archive_dir / f"flows-{day10}.jsonl.gz").exists()  # kept while its rows exist
    run_retention(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        assert conn.execute("SELECT count(*) FROM flows").fetchone()[0] == 0
    run_archive(ctx, now=NOW)
    assert not (ctx.paths.archive_dir / f"flows-{day10}.jsonl.gz").exists()
    with ctx.flows().connect() as conn:
        assert archive_log.archived_days(conn, "flows") == set()


def test_archive_file_name_is_made_durable_before_the_day_is_recorded(tmp_path, monkeypatch):
    # The rename is durable only once the directory is synced; retention may drop the day's rows right after.
    import stat
    ctx = configured_ctx(tmp_path)
    _enable(ctx)
    _write_flows(ctx, [1])
    synced, real = [], os.fsync

    def fsync(fd):
        synced.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        real(fd)
    monkeypatch.setattr(archive_job.os, "fsync", fsync)
    assert run_archive(ctx, now=NOW) == 1
    assert synced == [False, True]  # the file, then its directory


def test_rewriting_a_day_retention_has_thinned_keeps_its_archived_rows(tmp_path):
    # The cutoff day's morning rows go to retention once archived; a backfilled record of the next day
    # that pairs with an evening record marks the day stale, and its file was rewritten from what was
    # left: the archived morning rows were lost for good.
    ctx = configured_ctx(tmp_path)
    _enable(ctx)
    cutoff = NOW - timedelta(days=35)  # flow_days 35
    day = cutoff.strftime("%Y-%m-%d")
    morning, evening = cutoff.replace(hour=1), cutoff.replace(hour=23, minute=55)
    with ctx.flows().connect() as conn:
        upsert_flows(conn, [normalize_flow(raw_flow(1, morning, morning + timedelta(minutes=5))),
                            normalize_flow(raw_flow(2, evening, evening + timedelta(minutes=3)))],
                     origin=DataOrigin.INGEST, now=cutoff)
    run_archive(ctx, now=cutoff + timedelta(days=2))
    run_retention(ctx, now=NOW)  # the morning connection goes (its day is archived)
    nxt = (cutoff + timedelta(days=1)).replace(hour=0, minute=1)
    with ctx.flows().connect() as conn:
        stats = upsert_flows(conn, [normalize_flow(raw_flow(2, nxt, nxt + timedelta(minutes=3), direction="inbound"))],
                             origin=DataOrigin.BACKFILL, now=NOW)
        assert stats.paired == 1 and day not in archive_log.archived_days(conn, "flows")  # stale again
    run_archive(ctx, now=NOW)
    with gzip.open(ctx.paths.archive_dir / f"flows-{day}.jsonl.gz", "rt") as fh:
        rows = [json.loads(line) for line in fh]
    assert sorted(r["src_ip"] for r in rows) == ["10.0.1.1", "10.0.1.2"]
    with ctx.flows().connect() as conn:
        assert day in archive_log.archived_days(conn, "flows")
        assert conn.execute("SELECT rows FROM archive_log WHERE kind = 'flows' AND day = ?", (day,)).fetchone()[0] == 2
