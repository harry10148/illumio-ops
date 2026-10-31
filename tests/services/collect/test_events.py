"""Events collector: windowing on the 10,000 cap, deployment timeout, tamper capability."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from illumio_ops.domain.values import IngestSource
from illumio_ops.pce.events import EventsPage
from illumio_ops.services.collect import events as ev
from illumio_ops.services.collect.events import run_events_cycle
from illumio_ops.store.flowdb import capabilities, ingest_state

from .conftest import NOW, configured_ctx, minutes

TAMPER = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "pce" / "events_tamper.json").read_text())


def _event(i, ts):
    return {"href": f"/orgs/1/events/e-{i}", "event_type": "user.sign_in", "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "severity": "info", "status": "success", "created_by": {"user": {"href": "/users/1", "username": "u"}}}


class FakeEvents:
    def __init__(self):
        self.calls = []
        self.answer = lambda start, end, max_results: []

    def __call__(self, client, *, start, end, timeout, deadline, max_results=10000):
        self.calls.append((start, end, timeout))
        items = self.answer(start, end, max_results)
        return EventsPage(items=items[:max_results], capped=len(items) >= max_results)


@pytest.fixture
def fake_events(monkeypatch):
    fake = FakeEvents()
    monkeypatch.setattr(ev, "fetch_events", fake)
    return fake


def test_events_cycle_writes_and_advances(tmp_path, fake_events):
    ctx = configured_ctx(tmp_path)
    fake_events.answer = lambda s, e, m: [_event(i, e - minutes(1)) for i in range(3)]
    assert run_events_cycle(ctx, now=NOW).rows == 3
    with ctx.flows().connect() as conn:
        assert ingest_state.get(conn, IngestSource.EVENTS).watermark == NOW


def test_events_window_overlaps_300s(tmp_path, fake_events):
    ctx = configured_ctx(tmp_path)
    run_events_cycle(ctx, now=NOW)
    run_events_cycle(ctx, now=NOW + minutes(5))
    assert fake_events.calls[1][0] == NOW - minutes(5)  # watermark NOW minus the 300 s overlap


def test_events_cycle_bisects_on_10000_cap(tmp_path, fake_events, monkeypatch):
    monkeypatch.setattr(ev, "EVENTS_PAGE", 3)
    ctx = configured_ctx(tmp_path)
    items = [_event(i, NOW - minutes(60 * (i + 1))) for i in range(5)]
    def answer(s, e, m):
        return [x for x in items if s <= datetime.fromisoformat(x["timestamp"]) <= e]
    fake_events.answer = answer
    result = run_events_cycle(ctx, now=NOW)
    assert result.rows == 5 and result.gaps == 0 and result.windows > 1


def test_events_timeout_from_settings(tmp_path, fake_events):
    ctx = configured_ctx(tmp_path)
    ctx.settings.update(ctx.settings.current().revision,
                        lambda d: d["pce"].update({"deployment_type": "saas", "events_timeout_seconds": None}))
    run_events_cycle(ctx, now=NOW)
    assert fake_events.calls[0][2] == 180


def test_tamper_signal_marks_capability(tmp_path, fake_events):
    ctx = configured_ctx(tmp_path)
    fake_events.answer = lambda s, e, m: TAMPER
    run_events_cycle(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        caps = capabilities.all(conn)
    assert caps["tamper_signal"].state == "supported"


def test_confirmed_only_does_not_mark_unsupported(tmp_path, fake_events):
    ctx = configured_ctx(tmp_path)
    fake_events.answer = lambda s, e, m: TAMPER[:2]
    run_events_cycle(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        assert "tamper_signal" not in capabilities.all(conn)
