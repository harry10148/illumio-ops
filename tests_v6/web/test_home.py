import json
from datetime import UTC, datetime, timedelta

from illumio_ops.jobs.health import record_finish, record_start

from .conftest import LOCAL, login


def _store_probe(ctx, checked_at):
    with ctx.db() as conn:
        conn.execute("INSERT INTO pce_probe (id, checked_at, results_json) VALUES (1, ?, ?)",
                     (checked_at.isoformat(), json.dumps([{"name": "noop", "ok": True, "status": 204,
                                                           "category": "ok", "detail_key": "probe_ok"}])))


def test_home_summary_null_when_never_checked(client):
    login(client)
    assert client.get("/api/home/summary", environ_overrides=LOCAL).get_json()["data"] == {"pce": None}


def test_home_summary_marks_stale(client, ctx):
    login(client)
    _store_probe(ctx, datetime.now(UTC) - timedelta(seconds=601))
    pce = client.get("/api/home/summary", environ_overrides=LOCAL).get_json()["data"]["pce"]
    assert pce["stale"] is True and pce["results"][0]["ok"] is True


def test_home_summary_fresh(client, ctx):
    login(client)
    _store_probe(ctx, datetime.now(UTC) - timedelta(seconds=30))
    assert client.get("/api/home/summary", environ_overrides=LOCAL).get_json()["data"]["pce"]["stale"] is False


def test_jobs_list_includes_never_run_jobs(client, ctx):
    login(client)
    before = client.get("/api/system/jobs", environ_overrides=LOCAL).get_json()["data"]["jobs"]
    assert {"job_id": "pce_probe", "interval_seconds": 300, "last_started_at": None, "last_finished_at": None,
            "last_ok": None, "last_error": None, "runs": 0, "failures": 0} in before
    t0 = datetime(2026, 10, 24, tzinfo=UTC)
    with ctx.db() as conn:
        record_start(conn, "pce_probe", t0)
        record_finish(conn, "pce_probe", t0, "PceTransportError: dns")
    jobs = client.get("/api/system/jobs", environ_overrides=LOCAL).get_json()["data"]["jobs"]
    probe = next(j for j in jobs if j["job_id"] == "pce_probe")
    assert probe["last_ok"] is False and probe["failures"] == 1 and probe["interval_seconds"] == 300
