"""Reading the archive back (parity audit 2026-11-06 A2): v6 wrote data/archive but nothing read it, so traffic
older than the store's floor was gone for every report although its files were there."""
import gzip
from datetime import timedelta

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin, IngestSource
from illumio_ops.services.archive_read import archive_period, earliest
from illumio_ops.services.collect.archive import run_archive
from illumio_ops.services.collect.retention import run_retention
from illumio_ops.services.coverage import store_coverage
from illumio_ops.store.flowdb.flows import upsert_flows

from .conftest import NOW, configured_ctx, raw_flow


def _setup(tmp_path, ages):
    ctx = configured_ctx(tmp_path)
    ctx.settings.update(ctx.settings.current().revision, lambda d: (
        d["collection"]["retention"].update({"flow_days": 7, "event_days": 7, "rollup_days": 7, "baseline_days": 7}),
        d["collection"]["archive"].update({"enabled": True, "retention_days": 0})))
    recs = [normalize_flow(raw_flow(i, NOW - timedelta(days=a, minutes=5), NOW - timedelta(days=a)))
            for i, a in enumerate(ages)]
    with ctx.flows().connect() as conn:
        upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW)
    run_archive(ctx, now=NOW)
    run_retention(ctx, now=NOW)  # the rows older than 7 days leave the store; their files stay
    return ctx


def _count(ctx):
    with ctx.flows().connect() as conn:
        return conn.execute("SELECT count(*) FROM flows").fetchone()[0]


def test_rows_retention_dropped_come_back_from_the_archive(tmp_path):
    ctx = _setup(tmp_path, [12, 10, 3, 2])
    assert _count(ctx) == 2  # 12 and 10 days old are gone from the store
    start, end = NOW - timedelta(days=13), NOW - timedelta(days=1)
    with archive_period(ctx, start=start, end=end, now=NOW) as res:
        assert _count(res.ctx) == 4  # two from the store, two from their archive files, none twice
        assert len(res.archived_days["flows"]) == 2 and res.rows == 2 and res.unreadable == 0
        assert (NOW - timedelta(days=13)).strftime("%Y-%m-%d") in res.missing_days["flows"]  # no file: said
        with res.ctx.flows().connect() as conn:
            cov = store_coverage(conn, IngestSource.TRAFFIC, (start, end), floor=start)
            rolled = conn.execute("SELECT count(DISTINCT day) FROM flow_rollup_daily").fetchone()[0]
        assert cov.covers_any and rolled == 4  # the archived days are covered and rolled up like stored ones
        path = res.ctx.flows().path
    assert not path.exists()  # the throwaway store goes on exit
    assert _count(ctx) == 2  # and the install's store was not touched


def test_earliest_is_the_first_archive_day(tmp_path):
    ctx = _setup(tmp_path, [12, 2])
    assert earliest(ctx, "flows", NOW).date() == (NOW - timedelta(days=12)).date()


def test_a_damaged_archive_line_is_counted_not_loaded(tmp_path):
    ctx = _setup(tmp_path, [12, 2])
    day = (NOW - timedelta(days=12)).strftime("%Y-%m-%d")
    f = ctx.paths.archive_dir / f"flows-{day}.jsonl.gz"
    with gzip.open(f, "rt") as fh:
        good = fh.read()
    with gzip.open(f, "wt") as fh:
        fh.write(good + "{not json\n")
    with archive_period(ctx, start=NOW - timedelta(days=13), end=NOW, now=NOW) as res:
        assert res.rows == 1 and res.unreadable == 1


def test_a_line_from_an_older_schema_loads_with_the_columns_it_has(tmp_path):
    ctx = _setup(tmp_path, [12, 2])
    day = (NOW - timedelta(days=12)).strftime("%Y-%m-%d")
    f = ctx.paths.archive_dir / f"flows-{day}.jsonl.gz"
    import json
    with gzip.open(f, "rt") as fh:
        rows = [json.loads(line) for line in fh]
    for r in rows:  # columns added by later migrations (0002, 0005)
        for k in ("own_bytes_in", "own_bytes_out", "counted_connections", "counted_bytes"):
            r.pop(k, None)
    with gzip.open(f, "wt") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in rows))
    with archive_period(ctx, start=NOW - timedelta(days=13), end=NOW, now=NOW) as res:
        assert res.rows == 1 and res.unreadable == 0


def test_workbench_answers_an_archived_period_from_the_files_not_the_pce(tmp_path, monkeypatch):
    """6.5.0 B1: the workbench asked for a period the store no longer keeps reads the archive (it pulled the
    period from the PCE again, although the files were on disk). Its rows are the archive's rows."""
    from illumio_ops.domain.values import SegmentView
    from illumio_ops.services import workbench, workbench_store

    def no_pce(*a, **kw):
        raise AssertionError("the PCE was asked for an archived period")
    ctx = _setup(tmp_path, [12, 10, 3, 2])
    monkeypatch.setattr(workbench_store, "open_period", no_pce)
    workbench_store.drop()
    try:
        req = workbench.FlowRequest(mode="flows", start=NOW - timedelta(days=12, hours=1),
                                    end=NOW - timedelta(days=9), view=SegmentView.DETAIL)
        got = workbench.run(ctx, req, now=NOW)
        assert got.pulled is not None and got.pulled.source == "archive"
        assert got.pulled.archive_days == 2 and got.pulled.rows == 2
        # the days in between were never collected in this fixture: no file, and said
        assert got.pulled.missing_days == ["2026-10-13", "2026-10-15"]
        assert len(got.result.detail) == 2
    finally:
        workbench_store.drop()
