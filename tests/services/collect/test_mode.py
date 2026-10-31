"""Collection modes (spec §6.4): full, alert (short traffic, no traffic backfill), events only."""
from datetime import timedelta

import pytest
from pydantic import ValidationError

from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.values import CollectionMode, IngestSource
from illumio_ops.pce.events import EventsPage
from illumio_ops.services.collect import events as ev
from illumio_ops.services.collect.backfill import ensure_initial_backfill
from illumio_ops.services.collect.events import run_events_cycle
from illumio_ops.services.collect.status import collection_status
from illumio_ops.services.collect.traffic import run_traffic_cycle
from illumio_ops.services.eventsource import query_events
from illumio_ops.services.flowsource import query_flows
from illumio_ops.settings.schema import CollectionSettings, default_collection
from illumio_ops.store.flowdb import ingest_state

from .conftest import NOW, configured_ctx, minutes, raw_flow

DAY = timedelta(days=1)


@pytest.fixture
def event_calls(monkeypatch):
    calls = []
    def fetch(client, **kw):
        calls.append((kw["start"], kw["end"]))
        return EventsPage(items=[], capped=False)
    monkeypatch.setattr(ev, "fetch_events", fetch)
    return calls


def _ctx(tmp_path, mode, **collection):
    return configured_ctx(tmp_path, mode=mode, **collection)


def test_lightweight_skips_traffic(tmp_path, fake_traffic, event_calls):
    ctx = _ctx(tmp_path, "lightweight")
    fake_traffic.answer = lambda s, e, m: [raw_flow(1, NOW - minutes(30), NOW - minutes(20))]
    run_traffic_cycle(ctx, now=NOW)
    run_events_cycle(ctx, now=NOW)
    assert fake_traffic.calls == [] and event_calls
    with ctx.flows().connect() as conn:
        assert ingest_state.get(conn, IngestSource.TRAFFIC) is None
        assert ingest_state.get(conn, IngestSource.EVENTS).last_ok_at == NOW


def test_alert_mode_skips_traffic_backfill(tmp_path, fake_traffic, event_calls):
    ctx = _ctx(tmp_path, "alert", backfill_days=3, retention={"flow_days": 3, "event_days": 90, "rollup_days": 3,
                                                              "baseline_days": 30})
    run_traffic_cycle(ctx, now=NOW)  # live traffic is collected in alert mode
    live_calls = len(fake_traffic.calls)
    assert live_calls > 0
    ensure_initial_backfill(ctx, now=NOW)
    assert len(fake_traffic.calls) == live_calls  # no traffic backfill
    assert len(event_calls) >= 3  # events are backfilled, one window per day at least


def test_switching_to_full_backfills_the_traffic_it_never_read(tmp_path, fake_traffic, event_calls):
    ctx = _ctx(tmp_path, "lightweight", backfill_days=2)
    ensure_initial_backfill(ctx, now=NOW)
    assert fake_traffic.calls == []
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"].update({"mode": "full"}))
    run_traffic_cycle(ctx, now=NOW + minutes(10))
    fake_traffic.calls.clear()
    ensure_initial_backfill(ctx, now=NOW + minutes(10))
    assert len(fake_traffic.calls) >= 2  # traffic history is read now that traffic is collected
    fake_traffic.calls.clear()
    assert ensure_initial_backfill(ctx, now=NOW + minutes(20)) is None and fake_traffic.calls == []


def _settings(mode, flow, rollup, baseline=30):
    c = default_collection().model_dump()
    c["mode"] = mode
    c["retention"] = {"flow_days": flow, "event_days": 90, "rollup_days": rollup, "baseline_days": baseline}
    return c


def test_alert_mode_allows_short_flow_retention():
    assert CollectionSettings.model_validate(_settings("alert", 3, 3)).mode is CollectionMode.ALERT
    assert CollectionSettings.model_validate(_settings("lightweight", 3, 3)).retention.flow_days == 3


def test_full_mode_requires_flow_retention_over_baseline():
    with pytest.raises(ValidationError) as exc:
        CollectionSettings.model_validate(_settings("full", 3, 3))
    assert exc.value.errors()[0]["loc"] == ("retention",)
    with pytest.raises(ValidationError):
        CollectionSettings.model_validate(_settings("alert", 10, 5))  # rollup never shorter than flows


def test_archive_error_names_the_archive_field():
    c = _settings("full", 35, 180)
    c["archive"] = {"enabled": True, "retention_days": 7}
    with pytest.raises(ValidationError) as exc:
        CollectionSettings.model_validate(c)
    assert exc.value.errors()[0]["loc"] == ("archive",)


def test_default_mode_is_lightweight():
    """Spec §6.4 (2026-10-29): new installs keep no traffic; alert mode is the step up."""
    assert default_collection().mode is CollectionMode.LIGHTWEIGHT


def test_coverage_reports_collection_off(tmp_path, fake_traffic, event_calls):
    ctx = _ctx(tmp_path, "lightweight")
    q = query_flows(ctx, FilterSpec(start=NOW - minutes(60), end=NOW), limit=10, order="last_detected_desc", now=NOW)
    assert [g[2] for g in q.coverage.gaps] == ["collection_off"]
    run_events_cycle(ctx, now=NOW)
    e = query_events(ctx, start=NOW - minutes(60), end=NOW, limit=10, now=NOW)
    assert e.coverage.gaps == []
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"].update({"enabled": False}))
    e = query_events(ctx, start=NOW - minutes(60), end=NOW + minutes(10), limit=10, now=NOW)
    assert [g[2] for g in e.coverage.gaps] == ["collection_off"]


def test_status_marks_sources_outside_mode(tmp_path):
    st = collection_status(_ctx(tmp_path, "lightweight"), now=NOW)
    collected = {s.source: s.collected for s in st.sources}
    assert collected == {"traffic": False, "events": True, "inventory": True, "ransomware": True, "backfill": True}
    assert st.mode == "lightweight"
