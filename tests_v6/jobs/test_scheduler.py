import responses

from illumio_ops.jobs.health import list_health
from illumio_ops.jobs.scheduler import JOB_INTERVALS, build_scheduler, instrument
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
    assert JOB_INTERVALS["pce_probe"] == 300
    assert job.trigger.interval.total_seconds() == 300
    assert job.coalesce is True and job.max_instances == 1
    assert job.next_run_time is not None  # first run right away, not five minutes later
    assert str(sched.timezone) == "UTC"
