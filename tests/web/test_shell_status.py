"""Shell status: the mode the interface shows, how collection is going, unprocessed alerts and the write key."""
from datetime import UTC, datetime, timedelta

from illumio_ops.domain.alerting import Confidence, Trigger
from illumio_ops.domain.values import AlertRuleType, Severity
from illumio_ops.jobs.health import record_finish, record_start
from illumio_ops.services import shell
from illumio_ops.store import alerts as store

from .conftest import LOCAL, login

NOW = datetime.now(UTC).replace(microsecond=0)


def _set(ctx, fn):
    ctx.settings.update(ctx.settings.current().revision, fn)


def _alert(ctx, *, at, grouped=None, pce_url=None):
    t = Trigger(rule_id="a" * 32, rule_type=AlertRuleType.SYSTEM, subject_key="disk_low", severity=Severity.HIGH,
                first_seen=at, last_seen=at, late=False, message_key="alert_system_disk_low",
                params={"free": "1 GB", "warn": "10 GB"}, facts={}, evidence=None, confidence=Confidence(),
                grouped_annotation=grouped)
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        store.insert_alert(conn, pce_url=pce.url if pce_url is None else pce_url, org_id=pce.org_id, rule_name="",
                           pack_key=None, trigger=t, at=at, channels=[], hold=None)


def _job(ctx, job_id, error):
    with ctx.db() as conn:
        record_start(conn, job_id, NOW)
        record_finish(conn, job_id, NOW, error)


def test_status_basic_mode(ctx):
    _set(ctx, lambda d: d["collection"].update({"mode": "lightweight"}))
    s = shell.status(ctx, now=NOW)
    assert s.mode == "basic" and s.collection_mode.value == "lightweight"


def test_status_advanced_for_alert_and_full(ctx):
    assert shell.status(ctx, now=NOW).mode == "advanced"  # the test settings collect in full mode
    _set(ctx, lambda d: d["collection"].update({"mode": "alert", "retention": {
        **d["collection"]["retention"], "flow_days": 8}}))
    assert shell.status(ctx, now=NOW).mode == "advanced"


def test_unprocessed_counts_ungrouped_last_7_days(ctx):
    _alert(ctx, at=NOW - timedelta(hours=1))
    _alert(ctx, at=NOW - timedelta(days=6))
    _alert(ctx, at=NOW - timedelta(hours=2), grouped=7)
    _alert(ctx, at=NOW - timedelta(days=8))
    _alert(ctx, at=NOW - timedelta(hours=3), pce_url="https://other.example:8443")
    assert shell.status(ctx, now=NOW).unprocessed_alerts == 2


def test_collection_not_started(ctx):
    assert shell.status(ctx, now=NOW).collection == "not_started"


def test_collection_ok_degraded_failing(ctx):
    for job in ("collect_traffic", "collect_events", "collect_inventory"):
        _job(ctx, job, None)
    assert shell.status(ctx, now=NOW).collection == "ok"
    _job(ctx, "collect_traffic", "PceTransportError: dns")
    assert shell.status(ctx, now=NOW).collection == "degraded"
    _job(ctx, "collect_events", "PceTransportError: dns")
    _job(ctx, "collect_inventory", "PceTransportError: dns")
    assert shell.status(ctx, now=NOW).collection == "failing"


def test_lightweight_ignores_traffic_job(ctx):
    _set(ctx, lambda d: d["collection"].update({"mode": "lightweight"}))
    _job(ctx, "collect_traffic", "PceTransportError: dns")  # left from before the switch
    _job(ctx, "collect_events", None)
    _job(ctx, "collect_inventory", None)
    assert shell.status(ctx, now=NOW).collection == "ok"


def test_write_key_flag(ctx):
    assert shell.status(ctx, now=NOW).write_key is False
    _set(ctx, lambda d: d["pce"].update({"write_api_key": "k"}))
    assert shell.status(ctx, now=NOW).write_key is False
    _set(ctx, lambda d: d["pce"].update({"write_api_secret": "s"}))
    assert shell.status(ctx, now=NOW).write_key is True


def test_route_requires_login_and_answers(client):
    assert client.get("/api/shell/status", environ_overrides=LOCAL).status_code == 401
    login(client)
    data = client.get("/api/shell/status", environ_overrides=LOCAL).get_json()["data"]
    assert set(data) == {"mode", "collection_mode", "collection", "unprocessed_alerts", "write_key", "version"}


def test_rule_summary_counts_known(ctx):
    _alert(ctx, at=NOW - timedelta(hours=1))
    _alert(ctx, at=NOW - timedelta(hours=2), grouped=4)
    _alert(ctx, at=NOW - timedelta(days=9), grouped=4)  # older than 7 days
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        s = store.rule_summaries(conn, pce_url=pce.url, org_id=pce.org_id, now=NOW)["a" * 32]
    assert (s.fired_7d, s.known_7d) == (2, 1)


def test_collection_failure_recorded_by_the_collector_not_the_job(ctx):
    """A collector records a PCE failure in its ingest state and returns; the job itself ends without error."""
    from illumio_ops.store.flowdb import ingest_state
    for job in ("collect_traffic", "collect_events", "collect_inventory"):
        _job(ctx, job, None)
    with ctx.flows().connect() as conn:
        for src in ("traffic", "events", "inventory"):
            ingest_state.mark_started(conn, src, NOW)
            ingest_state.mark_ok(conn, src, NOW, watermark=NOW, rows=1)
        ingest_state.mark_started(conn, "inventory", NOW)
        ingest_state.mark_failed(conn, "inventory", NOW, "PceTransportError: dns")
        conn.commit()
    assert shell.status(ctx, now=NOW).collection == "degraded"
    with ctx.flows().connect() as conn:
        for src in ("traffic", "events"):
            ingest_state.mark_started(conn, src, NOW)
            ingest_state.mark_failed(conn, src, NOW, "PceTransportError: dns")
        conn.commit()
    assert shell.status(ctx, now=NOW).collection == "failing"


def test_status_names_the_product_version(ctx, client):
    """5.x showed its version (/api/status.version); the frame shows v6's (parity 2026-11-06)."""
    import illumio_ops

    assert shell.status(ctx, now=NOW).version == illumio_ops.__version__
    login(client)
    body = client.get("/api/shell/status", environ_overrides=LOCAL).get_json()
    assert body["data"]["version"] == illumio_ops.__version__
