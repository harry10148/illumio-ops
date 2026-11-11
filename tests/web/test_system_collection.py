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
    assert err["field"] == "settings.archive" and err["code"] == "invalid_input"


def _capture_backfill(monkeypatch):
    import threading
    seen: dict = {}
    done = threading.Event()

    def fake(ctx, *, start, end, sources=None, **kw):
        seen.update(start=start, end=end, sources=sources)
        done.set()
    monkeypatch.setattr(backfill, "run_backfill", fake)
    return seen, done


def _days_ago(n):
    from datetime import UTC, datetime, timedelta
    return (datetime.now(UTC).date() - timedelta(days=n)).isoformat()


def test_backfill_reads_only_what_was_asked(client, ctx, monkeypatch):
    """5.x backfilled events or traffic per request (parity 2026-11-06); v6 decided by the mode alone."""
    from illumio_ops.domain.values import IngestSource
    login(client)
    seen, done = _capture_backfill(monkeypatch)
    r = _send(client, "POST", "/api/system/collection/backfill",
              {"start": _days_ago(3), "end": _days_ago(2), "sources": "events"})
    assert r.status_code == 200 and done.wait(5)
    assert seen["sources"] == (IngestSource.EVENTS,)
    done.clear()
    r = _send(client, "POST", "/api/system/collection/backfill",
              {"start": _days_ago(3), "end": _days_ago(2), "sources": "traffic"})
    assert r.status_code == 200 and done.wait(5) and seen["sources"] == (IngestSource.TRAFFIC,)
    done.clear()
    r = _send(client, "POST", "/api/system/collection/backfill", {"start": _days_ago(3), "end": _days_ago(2)})
    assert r.status_code == 200 and done.wait(5)
    assert seen["sources"] == (IngestSource.TRAFFIC, IngestSource.EVENTS)  # both, in full mode


def test_backfill_of_traffic_the_mode_does_not_collect_is_refused(client, ctx):
    login(client)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"].update(mode="lightweight"))
    r = _send(client, "POST", "/api/system/collection/backfill",
              {"start": _days_ago(3), "end": _days_ago(2), "sources": "traffic"})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "backfill_source_not_collected"


def test_events_backfill_goes_back_as_far_as_events_are_kept(client, ctx, monkeypatch):
    login(client)
    _seen, done = _capture_backfill(monkeypatch)
    keep = ctx.settings.current().collection.retention
    assert keep.event_days > keep.flow_days
    old = _days_ago(keep.flow_days + 5)
    r = _send(client, "POST", "/api/system/collection/backfill", {"start": old, "end": old, "sources": "both"})
    err = r.get_json()["error"]
    assert r.status_code == 400 and err["code"] == "backfill_beyond_retention"
    assert err["params"] == {"days": str(keep.flow_days), "earliest": _days_ago(keep.flow_days)}
    r = _send(client, "POST", "/api/system/collection/backfill", {"start": old, "end": old, "sources": "events"})
    assert r.status_code == 200 and done.wait(5)


def test_retention_runs_now_through_its_job(client, ctx):
    """5.x POST /retention/run; v6 moves the daily retention job to now, so job health records the run."""
    from datetime import UTC, datetime, timedelta

    from illumio_ops.jobs.scheduler import build_scheduler
    login(client)
    ctx.scheduler = build_scheduler(ctx)
    r = _send(client, "POST", "/api/system/collection/retention/run", {})
    assert r.status_code == 200 and r.get_json()["data"]["queued"] is True
    nxt = ctx.scheduler.get_job("collect_retention").next_run_time
    assert abs(nxt - datetime.now(UTC)) < timedelta(seconds=10)


def test_retention_runs_beside_the_request_without_a_scheduler(client, ctx, monkeypatch):
    import threading

    from illumio_ops.web.routes import system_collection
    login(client)
    ran = threading.Event()
    monkeypatch.setattr(system_collection, "run_retention", lambda c: ran.set() or {})
    r = _send(client, "POST", "/api/system/collection/retention/run", {})
    assert r.status_code == 200 and ran.wait(5)


def _collected(ctx):
    from datetime import UTC, datetime

    from illumio_ops.store.flowdb import binding
    with ctx.flows().connect() as conn:
        binding.bind(conn, "https://pce.example.com:8443", "1", datetime.now(UTC))
        conn.execute("INSERT INTO events (href, event_type, timestamp, raw_json, origin, ingested_at) "
                     "VALUES ('/orgs/1/events/1', 'x', '2026-10-24T00:00:00Z', '{}', 'ingest', 'x')")
        conn.commit()


def _events(ctx):
    with ctx.flows().connect() as conn:
        return conn.execute("SELECT count(*) FROM events").fetchone()[0]


def test_clearing_collected_data_needs_the_typed_word(client, ctx):
    """5.x `cache flush --confirm` (parity 2026-11-06)."""
    login(client)
    _collected(ctx)
    for word in ("", "clear it", "yes"):
        r = _send(client, "POST", "/api/system/collection/clear", {"confirm": word})
        assert r.status_code == 400 and r.get_json()["error"]["code"] == "confirm_mismatch"
    assert _events(ctx) == 1


def test_clearing_collected_data_keeps_settings_alerts_and_reports(client, ctx):
    from datetime import UTC, datetime

    from illumio_ops.services import shell
    from tests.web.test_shell_status import _alert
    login(client)
    _collected(ctx)
    _alert(ctx, at=datetime.now(UTC))
    (ctx.paths.archive_dir / "events-2026-10-01.jsonl.gz").write_bytes(b"x")
    before = ctx.settings.current().model_dump()
    r = _send(client, "POST", "/api/system/collection/clear", {"confirm": "CLEAR"})
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert "flows" in data["cleared"] and data["archive_moved_to"].startswith("previous-")
    assert _events(ctx) == 0
    assert ctx.settings.current().model_dump() == before
    assert shell.status(ctx).new_alerts == 1


def test_clearing_while_a_reader_holds_the_store_says_so(client, ctx, monkeypatch):
    from illumio_ops.store.flowdb import db as flowdb
    monkeypatch.setattr(flowdb, "RESET_WAIT_SECONDS", 0.2)
    login(client)
    _collected(ctx)
    reader = ctx.flows().connect()
    r = _send(client, "POST", "/api/system/collection/clear", {"confirm": "CLEAR"})
    reader.close()
    assert r.status_code == 503 and r.get_json()["error"]["code"] == "store_busy"
    assert _events(ctx) == 1
