import json

from illumio_ops.services.collect import backfill

from .conftest import LOCAL, csrf, login


def _send(client, method, path, body):
    return client.open(path, method=method, json=body, environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})


def test_get_and_update_collection(client, ctx):
    login(client)
    data = client.get("/api/system/collection", environ_overrides=LOCAL).get_json()["data"]
    assert data["settings"]["traffic_interval_seconds"] == 600
    data["settings"]["traffic_interval_seconds"] = 900
    data["settings"]["rate_limit_per_minute"] = 120
    r = _send(client, "PUT", "/api/system/collection", data)
    assert r.status_code == 200 and ctx.settings.current().collection.traffic_interval_seconds == 900


def test_collection_update_reschedules_and_sets_rate(client, ctx):
    from illumio_ops.jobs.scheduler import build_scheduler
    login(client)
    ctx.scheduler = build_scheduler(ctx)
    data = client.get("/api/system/collection", environ_overrides=LOCAL).get_json()["data"]
    data["settings"]["events_interval_seconds"] = 120
    data["settings"]["rate_limit_per_minute"] = 60
    assert _send(client, "PUT", "/api/system/collection", data).status_code == 200
    assert ctx.scheduler.get_job("collect_events").trigger.interval.total_seconds() == 120
    assert ctx.rate_limiter.rate_per_minute == 60


def test_invalid_retention_is_a_field_error(client, ctx):
    login(client)
    data = client.get("/api/system/collection", environ_overrides=LOCAL).get_json()["data"]
    data["settings"]["retention"]["flow_days"] = 10  # below baseline_days
    r = _send(client, "PUT", "/api/system/collection", data)
    err = r.get_json()["error"]
    assert r.status_code == 400 and err["field"] == "settings.retention" and err["code"] == "invalid_input"


def test_status_endpoint(client):
    login(client)
    data = client.get("/api/system/collection/status", environ_overrides=LOCAL).get_json()["data"]
    assert {s["source"] for s in data["sources"]} == {"traffic", "events", "inventory", "ransomware", "backfill"}
    assert data["pce_configured"] is False


def test_backfill_conflict_returns_409(client):
    login(client)
    backfill.BACKFILL_LOCK.acquire()
    try:
        r = _send(client, "POST", "/api/system/collection/backfill", {"start": "2026-10-20", "end": "2026-10-21"})
    finally:
        backfill.BACKFILL_LOCK.release()
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "backfill_running"


def test_backfill_range_checks(client):
    login(client)
    r = _send(client, "POST", "/api/system/collection/backfill", {"start": "2026-10-22", "end": "2026-10-21"})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "backfill_range_invalid"
    r = _send(client, "POST", "/api/system/collection/backfill", {"start": "2020-01-01", "end": "2020-01-02"})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "backfill_beyond_retention"


def test_logs_tail_filters_and_truncation_flag(client, ctx):
    login(client)
    lines = [f"2026-10-24 10:00:0{i}.000 | {lvl:<8} | illumio_ops.{mod}:f:1 - message {i}"
             for i, (lvl, mod) in enumerate([("INFO", "pce.client"), ("WARNING", "services.collect.traffic"),
                                             ("ERROR", "services.collect.traffic"), ("INFO", "web.app")])]
    lines.insert(3, "Traceback (most recent call last):")
    (ctx.paths.logs_dir / "illumio-ops.log").write_text("\n".join(lines) + "\n")
    q = lambda body: _send(client, "POST", "/api/system/logs/query", body).get_json()["data"]
    assert [x["message"].split("\n")[0] for x in q({})["lines"]] == ["message 3", "message 2", "message 1", "message 0"]
    assert [x["level"] for x in q({"level": "WARNING"})["lines"]] == ["ERROR", "WARNING"]
    assert q({"module": "illumio_ops.web"})["lines"][0]["message"] == "message 3"
    assert "Traceback" in q({"contains": "traceback"})["lines"][0]["message"]
    page = q({"limit": 2})
    assert len(page["lines"]) == 2 and page["truncated"] is True
    assert json.dumps(page)  # serialisable


def test_archive_retention_shorter_than_raw_is_a_field_error(client, ctx):
    login(client)
    data = client.get("/api/system/collection", environ_overrides=LOCAL).get_json()["data"]
    data["settings"]["archive"] = {"enabled": True, "retention_days": 7}
    err = _send(client, "PUT", "/api/system/collection", data).get_json()["error"]
    assert err["field"] == "settings" and err["code"] == "invalid_input"
