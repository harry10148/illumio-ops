"""The hourly analysis job: steps in order, one failing step never stops the others."""
import json

from illumio_ops.services.analysis import hourly
from illumio_ops.store.flowdb import analysis
from tests_v6.services.collect.conftest import NOW, configured_ctx


def test_hourly_step_failure_does_not_stop_others(tmp_path, monkeypatch):
    ctx = configured_ctx(tmp_path)
    ran = []

    def boom(ctx, now):
        raise RuntimeError("bad graph")

    def ok(ctx, now):
        ran.append(now)
    monkeypatch.setattr(hourly, "HOURLY_STEPS", [("first", boom), ("second", ok)])
    statuses = hourly.run_hourly_analysis(ctx, now=NOW)
    assert statuses == {"first": "RuntimeError: bad graph", "second": "ok"} and ran == [NOW]
    with ctx.flows().connect() as conn:
        first, second = analysis.get_run(conn, "first"), analysis.get_run(conn, "second")
    assert first["last_error"] == "RuntimeError: bad graph" and first["last_ok_at"] is None
    assert second["last_ok_at"] is not None and second["last_error"] is None


def test_hourly_registers_exposure_first():
    assert hourly.HOURLY_STEPS[0][0] == "exposure"
    assert json.dumps([name for name, _ in hourly.HOURLY_STEPS])
