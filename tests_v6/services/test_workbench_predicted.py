"""The workbench's predicted-block view (P6e, spec §6.5.3 / §6.6 F1): the request's flows recomputed against the
draft policy on the PCE, asked for explicitly, bounded for an interactive request, one PCE download at a time."""
import threading
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.services import ondemand, workbench
from illumio_ops.services.analysis.predicted_block import PredictedBlock
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)


def _flows(**kw):
    return workbench.FlowRequest(mode="flows", start=NOW - timedelta(days=7), end=NOW, view="detail", **kw)


def _empty():
    return PredictedBlock(rows=[], rules={}, capped=False, limit_hit=False, computed_at=NOW, unsupported=False,
                          missing_rules=[])


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path, mode="lightweight")


def test_bounded_and_carries_its_request(ctx, monkeypatch):
    seen = {}

    def fake(c, spec, **kw):
        seen.update(spec=spec, **kw)
        return _empty()
    monkeypatch.setattr(workbench, "predict_blocks", fake)
    req = _flows()
    v = workbench.predicted(ctx, req)
    assert v.request == req and v.predicted.rows == []
    assert seen["limit"] == workbench.PREDICTED_LIMIT and seen["max_results"] == workbench.PREDICTED_MAX_RESULTS
    assert seen["deadline_seconds"] == workbench.PREDICTED_DEADLINE
    assert seen["spec"].start == req.start and seen["spec"].end == req.end


def test_events_refused(ctx):
    with pytest.raises(ValueError):
        workbench.predicted(ctx, workbench.EventRequest(mode="events", start=NOW - timedelta(days=1), end=NOW,
                                                        view="detail"))


def test_waits_for_another_pull(ctx, monkeypatch):
    monkeypatch.setattr(workbench, "predict_blocks", lambda c, s, **kw: _empty())
    done = threading.Event()
    with ondemand.INTERACTIVE_PULL:
        t = threading.Thread(target=lambda: (workbench.predicted(ctx, _flows()), done.set()))
        t.start()
        assert not done.wait(0.5)
    assert done.wait(5)
    t.join(5)


def test_previous_pce_refused(ctx):
    from illumio_ops.services.collect.guard import BindingMismatch, ensure_binding
    with ctx.flows().connect() as conn:
        ensure_binding(conn, ctx.settings.current().pce, NOW)
        conn.commit()
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(url="https://pce-b.example:8443"))
    with pytest.raises(BindingMismatch):
        workbench.predicted(ctx, _flows())


def test_grouping_of_the_request_ignored(ctx, monkeypatch):
    """e2e 2026-10-31: the workbench keeps its ranking's grouping in the request; the recompute lists flows."""
    from illumio_ops.domain.segment import GroupBy
    monkeypatch.setattr(workbench, "predict_blocks", lambda c, s, **kw: _empty())
    req = workbench.FlowRequest(mode="flows", start=NOW - timedelta(days=1), end=NOW, view="ranking",
                                group_by=(GroupBy(dimension="src_host"),))
    assert workbench.predicted(ctx, req).request == req
