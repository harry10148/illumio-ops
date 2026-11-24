from datetime import UTC, datetime, timedelta

from illumio_ops.domain.values import ReportStatus
from illumio_ops.services.reports import retention
from illumio_ops.store import reports as store
from tests.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 27, tzinfo=UTC)


def _add(ctx, created, status=ReportStatus.DONE):
    with ctx.db() as conn:
        rid = store.insert(conn, report_type="lateral_posture", params_json="{}", status=status, trigger="manual",
                           schedule_id=None, pce_label="p", period_start=created, period_end=created,
                           created_at=created)
    d = ctx.paths.reports_dir / str(rid)
    d.mkdir()
    (d / "a.html").write_text("x")
    return rid


def test_retention_removes_old_reports_and_only_report_dirs(tmp_path):
    ctx = configured_ctx(tmp_path)
    old = _add(ctx, NOW - timedelta(days=91))
    running = _add(ctx, NOW - timedelta(days=91), ReportStatus.RUNNING)
    fresh = _add(ctx, NOW - timedelta(days=89))
    stray = ctx.paths.reports_dir / "notes"
    stray.mkdir()
    (ctx.paths.reports_dir / "999").mkdir()  # not a report this database knows: left alone
    assert retention.run_report_retention(ctx, now=NOW) == 1
    assert not (ctx.paths.reports_dir / str(old)).exists()
    assert (ctx.paths.reports_dir / str(running)).exists() and (ctx.paths.reports_dir / str(fresh)).exists()
    assert stray.exists() and (ctx.paths.reports_dir / "999").exists()
    with ctx.db() as conn:
        assert store.get(conn, old) is None and store.get(conn, fresh) is not None


def test_remove_report_refuses_running(tmp_path):
    ctx = configured_ctx(tmp_path)
    running = _add(ctx, NOW, ReportStatus.RUNNING)
    done = _add(ctx, NOW)
    assert retention.remove_report(ctx, running, by="t") == "running"
    assert retention.remove_report(ctx, done, by="t") == "removed" and not (ctx.paths.reports_dir / str(done)).exists()
    assert retention.remove_report(ctx, 12345, by="t") == "missing"


def test_remove_only_clears_files_of_rows_it_deleted(tmp_path, monkeypatch):
    """Review: a delete racing the job's claim removed the directory of a report now running."""
    ctx = configured_ctx(tmp_path)
    rid = _add(ctx, NOW, ReportStatus.QUEUED)
    real_get = store.get

    def get_then_claimed(conn, report_id):
        row = real_get(conn, report_id)
        store.claim_next(conn, at=NOW)  # the reports job claims it between the read and the delete
        return row
    monkeypatch.setattr(store, "get", get_then_claimed)
    assert retention.remove_report(ctx, rid, by="t") == "running"
    assert (ctx.paths.reports_dir / str(rid)).exists()


def test_claim_is_atomic_and_skips_deleted(tmp_path):
    ctx = configured_ctx(tmp_path)
    rid = _add(ctx, NOW, ReportStatus.QUEUED)
    with ctx.db() as conn:
        assert store.delete(conn, [rid]) == [rid]
        assert store.claim_next(conn, at=NOW) is None


def test_every_removal_is_logged_with_who_or_why(tmp_path):
    """6.15.3 on .106: every report made before 2026-11-23 had gone, and nothing said who or what removed them."""
    from loguru import logger
    ctx = configured_ctx(tmp_path)
    old = _add(ctx, NOW - timedelta(days=91))
    mine = _add(ctx, NOW)
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="INFO")
    try:
        retention.run_report_retention(ctx, now=NOW)
        retention.remove_report(ctx, mine, by="illumio")
        retention.remove_report(ctx, 12345, by="illumio")  # nothing removed: nothing said
    finally:
        logger.remove(sink)
    assert [line for line in lines if "report" in line] == [
        f"reports: retention removed 1 report(s) older than 90 days or beyond their schedule's keep: #{old}",
        f"reports: #{mine} (lateral_posture) removed by illumio",
    ]
