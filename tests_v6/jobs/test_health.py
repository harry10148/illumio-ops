from datetime import UTC, datetime, timedelta

from illumio_ops.jobs.health import list_health, record_finish, record_start
from illumio_ops.store.db import connect, migrate

T0 = datetime(2026, 10, 24, 1, 0, tzinfo=UTC)


def _conn(tmp_path):
    c = connect(tmp_path / "app.sqlite")
    migrate(c)
    return c


def test_start_then_finish_ok(tmp_path):
    c = _conn(tmp_path)
    record_start(c, "pce_probe", T0)
    record_finish(c, "pce_probe", T0 + timedelta(seconds=2), None)
    (h,) = list_health(c)
    assert (h.job_id, h.last_ok, h.last_error, h.runs, h.failures) == ("pce_probe", True, None, 1, 0)
    assert h.last_started_at == T0 and h.last_finished_at == T0 + timedelta(seconds=2)


def test_failure_is_counted_and_cleared_by_next_success(tmp_path):
    c = _conn(tmp_path)
    record_start(c, "j", T0)
    record_finish(c, "j", T0, "RuntimeError: boom")
    record_start(c, "j", T0 + timedelta(minutes=5))
    (h,) = list_health(c)
    assert (h.last_ok, h.last_error, h.runs, h.failures) == (False, "RuntimeError: boom", 1, 1)
    assert h.last_started_at > h.last_finished_at  # running now
    record_finish(c, "j", T0 + timedelta(minutes=5), None)
    (h,) = list_health(c)
    assert (h.last_ok, h.last_error, h.runs, h.failures) == (True, None, 2, 1)


def test_list_health_orders_by_job_id(tmp_path):
    c = _conn(tmp_path)
    for j in ("zeta", "alpha", "mid"):
        record_start(c, j, T0)
    assert [h.job_id for h in list_health(c)] == ["alpha", "mid", "zeta"]


def test_consecutive_failures_reset_on_success(tmp_path):
    from datetime import UTC, datetime

    from illumio_ops.jobs.health import list_health, record_finish, record_start
    from tests_v6.web.conftest import make_ctx
    ctx = make_ctx(tmp_path)
    now = datetime(2026, 10, 26, tzinfo=UTC)
    with ctx.db() as conn:
        record_start(conn, "j", now)
        for err in ("a", "b"):
            record_finish(conn, "j", now, err)
        assert list_health(conn)[0].consecutive_failures == 2
        record_finish(conn, "j", now, None)
        assert list_health(conn)[0].consecutive_failures == 0
