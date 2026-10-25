"""Switching PCE: one list of derived data, the flow database rebuilt, archives moved aside."""
import threading
import time

from illumio_ops.services.collect.reset import (
    APP_DB_PCE_DERIVED,
    APP_DB_PCE_INDEPENDENT,
    pce_target_changed,
    reset_for_new_pce,
)
from illumio_ops.settings.schema import PceSettings
from illumio_ops.store.flowdb import binding

from .conftest import NOW, configured_ctx


def _pce(**kw):
    base = {"url": "https://pce.example.com:8443", "org_id": "1", "api_key": "k", "api_secret": "s",
            "deployment_type": "on_prem", "console_url": None, "verify_tls": True, "events_timeout_seconds": None}
    return PceSettings(**(base | kw))


def test_target_change_ignores_case_and_trailing_slash():
    assert not pce_target_changed(_pce(), _pce(url="https://PCE.example.com:8443/"))
    assert pce_target_changed(_pce(), _pce(org_id="2"))
    assert pce_target_changed(_pce(), _pce(url="https://other.example.com:8443"))


def test_reset_clears_flowdb_and_pce_probe(tmp_path):
    ctx = configured_ctx(tmp_path)
    with ctx.flows().connect() as conn:
        binding.bind(conn, "https://pce.example.com:8443", "1", NOW)
    with ctx.db() as conn:
        conn.execute("INSERT INTO pce_probe (id, checked_at, results_json) VALUES (1, 'x', '[]')")
    report = reset_for_new_pce(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        assert binding.current(conn) is None
    with ctx.db() as conn:
        assert conn.execute("SELECT count(*) FROM pce_probe").fetchone()[0] == 0
    assert "pce_probe" in report.cleared and "flows" in report.cleared


def test_reset_moves_archive_aside_not_deletes(tmp_path):
    ctx = configured_ctx(tmp_path)
    (ctx.paths.archive_dir / "flows-2026-10-01.jsonl.gz").write_bytes(b"x")
    report = reset_for_new_pce(ctx, now=NOW)
    moved = ctx.paths.archive_dir / report.archive_moved_to
    assert (moved / "flows-2026-10-01.jsonl.gz").read_bytes() == b"x"
    assert report.archive_moved_to == "previous-20261024T120000Z"
    assert [p.name for p in ctx.paths.archive_dir.iterdir()] == [report.archive_moved_to]


def test_reset_without_archive_files_moves_nothing(tmp_path):
    assert reset_for_new_pce(configured_ctx(tmp_path), now=NOW).archive_moved_to is None


def test_reset_waits_for_running_collector(tmp_path):
    ctx = configured_ctx(tmp_path)
    fdb = ctx.flows()
    order = []
    fdb.write_lock.acquire()
    t = threading.Thread(target=lambda: (reset_for_new_pce(ctx, now=NOW), order.append("reset")))
    t.start()
    time.sleep(0.2)
    order.append("collector finished")
    fdb.write_lock.release()
    t.join(5)
    assert order == ["collector finished", "reset"]


def test_app_db_tables_are_classified(tmp_path):
    ctx = configured_ctx(tmp_path)
    with ctx.db() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == set(APP_DB_PCE_DERIVED) | set(APP_DB_PCE_INDEPENDENT)
    assert not set(APP_DB_PCE_DERIVED) & set(APP_DB_PCE_INDEPENDENT)


def test_a_switch_whose_reset_failed_is_finished_by_the_next_collector_run(tmp_path, fake_traffic):
    # The PCE page saves the new PCE first and clears afterwards; if clearing failed (or the service
    # stopped in between), every collector refused to write for good and saving again changed nothing.
    from illumio_ops.jobs.scheduler import _collector_jobs
    ctx = configured_ctx(tmp_path)
    with ctx.flows().connect() as conn:
        binding.bind(conn, "https://old-pce.example.com:8443", "7", NOW)
        conn.execute("INSERT INTO events (href, event_type, timestamp, raw_json, origin, ingested_at) "
                     "VALUES ('/orgs/7/events/1', 'x', '2026-10-24T00:00:00Z', '{}', 'ingest', 'x')")
        conn.commit()
    _collector_jobs(ctx)["collect_traffic"]()
    with ctx.flows().connect() as conn:
        bound = binding.current(conn)
        assert bound is not None and bound.pce_url == "https://pce.example.com:8443"
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
