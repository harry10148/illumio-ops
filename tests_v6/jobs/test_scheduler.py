import responses

from illumio_ops.jobs.health import list_health
from illumio_ops.jobs.scheduler import (
    apply_schedule,
    build_scheduler,
    instrument,
    job_intervals,
)
from tests_v6.web.conftest import make_ctx


def _health(ctx):
    with ctx.db() as conn:
        return {h.job_id: h for h in list_health(conn)}


def test_instrument_records_failure_and_keeps_scheduler_alive(tmp_path):
    ctx = make_ctx(tmp_path)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("first run fails")

    job = instrument("flaky", flaky, ctx)
    job()  # must not raise
    h = _health(ctx)["flaky"]
    assert (h.last_ok, h.failures, h.runs) == (False, 1, 1) and "first run fails" in h.last_error
    job()
    h = _health(ctx)["flaky"]
    assert (h.last_ok, h.last_error, h.failures, h.runs) == (True, None, 1, 2)


def test_probe_job_skips_when_unconfigured(tmp_path):
    ctx = make_ctx(tmp_path)
    sched = build_scheduler(ctx)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        sched.get_job("pce_probe").func()
        assert len(rsps.calls) == 0  # no HTTP at all
    h = _health(ctx)["pce_probe"]
    assert (h.last_ok, h.last_error) == (True, None)


def test_build_scheduler_registers_jobs_with_safe_defaults(tmp_path):
    sched = build_scheduler(make_ctx(tmp_path))
    job = sched.get_job("pce_probe")
    assert job_intervals(make_ctx(tmp_path / "b").settings.current())["pce_probe"] == 300
    assert job.trigger.interval.total_seconds() == 300
    assert job.coalesce is True and job.max_instances == 1
    assert job.next_run_time is not None  # first run right away, not five minutes later
    assert str(sched.timezone) == "UTC"


def test_job_intervals_follow_settings(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.settings.update(0, lambda d: d["collection"].update({"traffic_interval_seconds": 900,
                                                             "events_interval_seconds": 120}))
    iv = job_intervals(ctx.settings.current())
    assert (iv["collect_traffic"], iv["collect_events"], iv["pce_probe"]) == (900, 120, 300)


def test_collectors_registered_and_first_run_delayed(tmp_path):
    from datetime import UTC, datetime
    sched = build_scheduler(make_ctx(tmp_path))
    for job_id in ("collect_traffic", "collect_events"):
        job = sched.get_job(job_id)
        assert job is not None and job.coalesce is True and job.max_instances == 1
        assert (job.next_run_time - datetime.now(UTC)).total_seconds() > 20


def test_apply_schedule_reschedules_changed_interval(tmp_path):
    ctx = make_ctx(tmp_path)
    sched = build_scheduler(ctx)
    ctx.settings.update(0, lambda d: d["collection"].update({"traffic_interval_seconds": 1800}))
    apply_schedule(sched, ctx.settings.current())
    assert sched.get_job("collect_traffic").trigger.interval.total_seconds() == 1800
    assert sched.get_job("collect_events").trigger.interval.total_seconds() == 300


def test_flow_store_checkpoint_runs_as_its_own_job(tmp_path):
    from illumio_ops.jobs.scheduler import FLOWS_CHECKPOINT_SECONDS
    ctx = make_ctx(tmp_path)
    sched = build_scheduler(ctx)
    job = sched.get_job("flows_checkpoint")
    assert job is not None and job.trigger.interval.total_seconds() == FLOWS_CHECKPOINT_SECONDS == 60
    job.func()
    assert _health(ctx)["flows_checkpoint"].last_ok is True


def test_backfill_check_also_runs_the_daily_reread(tmp_path, monkeypatch):
    from illumio_ops.jobs import scheduler
    calls = []
    monkeypatch.setattr(scheduler, "ensure_initial_backfill", lambda ctx: calls.append("initial"))
    monkeypatch.setattr(scheduler, "ensure_daily_reread", lambda ctx: calls.append("reread"))
    ctx = make_ctx(tmp_path)
    build_scheduler(ctx).get_job("collect_backfill").func()
    assert calls == ["initial", "reread"] and _health(ctx)["collect_backfill"].last_ok is True


def test_scheduler_registers_analysis_hourly(tmp_path, monkeypatch):
    from illumio_ops.jobs import scheduler as sched_mod
    ctx = make_ctx(tmp_path)
    sched = build_scheduler(ctx)
    job = sched.get_job("analysis_hourly")
    assert job is not None and job.trigger.interval.total_seconds() == 3600
    assert job.coalesce is True and job.max_instances == 1
    calls = []
    monkeypatch.setattr(sched_mod, "run_hourly_analysis", lambda c: calls.append(c))
    sched_mod.build_scheduler(ctx).get_job("analysis_hourly").func()
    assert calls == [ctx]
