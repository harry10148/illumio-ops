from datetime import UTC, datetime

from illumio_ops.store.job_health import record_finish, record_start

from .conftest import LOCAL, login


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


def test_jobs_page_shows_settings_interval(client, ctx):
    login(client)
    ctx.settings.update(ctx.settings.current().revision,
                        lambda d: d["collection"].update({"traffic_interval_seconds": 900}))
    jobs = {j["job_id"]: j for j in client.get("/api/system/jobs", environ_overrides=LOCAL).get_json()["data"]["jobs"]}
    assert jobs["collect_traffic"]["interval_seconds"] == 900 and jobs["collect_events"]["interval_seconds"] == 300
