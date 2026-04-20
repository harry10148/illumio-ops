"""
Phase 13 E2E: ingestor → cache → dispatcher → loopback TCP transport.

Scenario:
1. In-memory SQLite cache
2. FakeApiClient seeded with 3 events + 10 traffic flows
3. Run EventsIngestor.run_once() + TrafficIngestor.run_once()
4. Enqueue all rows for a "loopback-dest" SIEM destination
5. LoopbackTCPTransport captures sent payloads in-memory
6. Run DestinationDispatcher.tick()
7. Assert: cache has 3 events + 10 flows, loopback received 13 CEF lines,
   watermarks advanced, all dispatch rows are status='sent'
"""
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    IngestionWatermark, PceEvent, PceTrafficFlowRaw, SiemDispatch,
)


@pytest.fixture
def sf(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'e2e.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _mk_event(i):
    ts = datetime.now(timezone.utc)
    return {
        "href": f"/orgs/1/events/{i}",
        "uuid": f"e2e-uuid-{i}",
        "timestamp": ts.isoformat(),
        "event_type": "policy.update",
        "severity": "info",
        "status": "success",
        "pce_fqdn": "pce.e2e.test",
    }


def _mk_flow(i):
    ts = datetime.now(timezone.utc)
    return {
        "src_ip": f"10.0.{i}.1",
        "dst_ip": f"10.1.{i}.1",
        "port": 443,
        "protocol": "tcp",
        "action": "blocked",
        "flow_count": 1,
        "bytes_in": 100,
        "bytes_out": 200,
        "first_detected": ts.isoformat(),
        "last_detected": (ts + timedelta(seconds=1)).isoformat(),
        "src_workload": "web",
        "dst_workload": "db",
    }


class FakeApi:
    def __init__(self, events, flows):
        self._events = events
        self._flows = flows

    def get_events(self, max_results=500, since=None, rate_limit=False, **kw):
        return self._events

    def get_events_async(self, since=None, rate_limit=False, **kw):
        return self._events

    def get_traffic_flows_async(self, max_results=200000, rate_limit=False, since=None, **kw):
        return self._flows


class LoopbackTransport:
    def __init__(self):
        self.received: list = []

    def send(self, payload: str) -> None:
        self.received.append(payload)

    def close(self) -> None:
        pass


def test_phase13_e2e_full_stack(sf):
    from src.pce_cache.watermark import WatermarkStore
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.traffic_filter import TrafficFilter
    from src.siem.dispatcher import DestinationDispatcher, enqueue
    from src.siem.formatters.cef import CEFFormatter

    events = [_mk_event(i) for i in range(3)]
    flows = [_mk_flow(i) for i in range(10)]
    api = FakeApi(events, flows)
    wm = WatermarkStore(sf)

    # 1. Ingest events
    events_ing = EventsIngestor(api=api, session_factory=sf, watermark=wm)
    ev_count = events_ing.run_once()
    assert ev_count == 3

    # 2. Ingest traffic (filter passes all blocked flows)
    traffic_filter = TrafficFilter(actions=["blocked", "allowed", "potentially_blocked", "unknown"])
    traffic_ing = TrafficIngestor(api=api, session_factory=sf, watermark=wm,
                                   traffic_filter=traffic_filter)
    fl_count = traffic_ing.run_once()
    assert fl_count == 10

    # 3. Verify cache contents
    with sf() as s:
        ev_rows = s.execute(select(PceEvent)).scalars().all()
        fl_rows = s.execute(select(PceTrafficFlowRaw)).scalars().all()
    assert len(ev_rows) == 3
    assert len(fl_rows) == 10

    # 4. Verify watermarks advanced
    ev_wm = wm.get("events")
    tr_wm = wm.get("traffic")
    assert ev_wm is not None and ev_wm.last_status == "ok"
    assert tr_wm is not None and tr_wm.last_status == "ok"

    # 5. Enqueue all rows for SIEM dispatch
    for ev in ev_rows:
        enqueue(sf, "pce_events", ev.id, ["loopback-dest"])
    for fl in fl_rows:
        enqueue(sf, "pce_traffic_flows_raw", fl.id, ["loopback-dest"])

    with sf() as s:
        pending = s.execute(
            select(SiemDispatch).where(SiemDispatch.status == "pending")
        ).scalars().all()
    assert len(pending) == 13

    # 6. Run dispatcher
    transport = LoopbackTransport()
    dispatcher = DestinationDispatcher(
        "loopback-dest", sf, CEFFormatter(), transport, max_retries=3, batch_size=50,
    )
    result = dispatcher.tick()

    # 7. Assert all sent
    assert result["sent"] == 13
    assert result["failed"] == 0
    assert len(transport.received) == 13

    # All CEF lines should start with "CEF:"
    for line in transport.received:
        assert line.startswith("CEF:")

    # All dispatch rows should now be status='sent'
    with sf() as s:
        sent_rows = s.execute(
            select(SiemDispatch).where(SiemDispatch.status == "sent")
        ).scalars().all()
    assert len(sent_rows) == 13
