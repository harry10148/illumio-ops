from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceEvent, PceTrafficFlowRaw, SiemDispatch


@pytest.fixture
def sf(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


class FakeEventsApi:
    def __init__(self, events):
        self._events = events

    def get_events(self, max_results=500, since=None, rate_limit=False, **kw):
        return self._events[:max_results]

    def get_events_async(self, since=None, rate_limit=False, **kw):
        return []

    def fetch_events(self, start_time_str, end_time_str=None, max_results=5000,
                     rate_limit=False):
        return self._events[:max_results]


class FakeTrafficApi:
    def __init__(self, flows):
        self._flows = flows

    def get_traffic_flows_async(self, max_results=200000, rate_limit=False, **kw):
        return self._flows[:max_results]


def _mk_event(i, ts):
    return {
        "href": f"/orgs/1/events/{i}",
        "uuid": f"uuid-{i}",
        "timestamp": ts.isoformat(),
        "event_type": "policy.update",
        "severity": "info",
        "status": "success",
        "pce_fqdn": "pce.test",
    }


def _mk_flow(i, ts):
    first = ts.isoformat()
    last = (ts + timedelta(seconds=1)).isoformat()
    return {
        "src_ip": f"10.0.{i}.1", "dst_ip": f"10.1.{i}.1",
        "port": 443, "protocol": "tcp", "action": "blocked",
        "flow_count": 1, "bytes_in": 100, "bytes_out": 200,
        "first_detected": first, "last_detected": last,
        "src_workload": "web", "dst_workload": "db",
    }


def test_events_ingestor_enqueues_per_destination(sf):
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc)
    api = FakeEventsApi([_mk_event(1, ts), _mk_event(2, ts + timedelta(seconds=1))])
    ing = EventsIngestor(
        api=api, session_factory=sf,
        watermark=WatermarkStore(sf),
        siem_destinations=["splunk", "elastic"],
    )
    assert ing.run_once() == 2
    with sf() as s:
        events = s.execute(select(PceEvent)).scalars().all()
        dispatches = s.execute(select(SiemDispatch)).scalars().all()
    assert len(events) == 2
    # 2 events × 2 destinations = 4 dispatch rows
    assert len(dispatches) == 4
    assert {d.destination for d in dispatches} == {"splunk", "elastic"}
    assert all(d.status == "pending" for d in dispatches)
    assert all(d.source_table == "pce_events" for d in dispatches)
    assert {d.source_id for d in dispatches} == {events[0].id, events[1].id}


def test_events_ingestor_skips_enqueue_when_no_destinations(sf):
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    api = FakeEventsApi([_mk_event(1, datetime.now(timezone.utc))])
    ing = EventsIngestor(api=api, session_factory=sf, watermark=WatermarkStore(sf))
    assert ing.run_once() == 1
    with sf() as s:
        assert s.execute(select(SiemDispatch)).scalars().all() == []


def test_traffic_ingestor_enqueues_per_destination(sf):
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc)
    api = FakeTrafficApi([_mk_flow(i, ts) for i in range(3)])
    ing = TrafficIngestor(
        api=api, session_factory=sf,
        watermark=WatermarkStore(sf),
        siem_destinations=["splunk"],
    )
    assert ing.run_once() == 3
    with sf() as s:
        flows = s.execute(select(PceTrafficFlowRaw)).scalars().all()
        dispatches = s.execute(select(SiemDispatch)).scalars().all()
    assert len(flows) == 3
    assert len(dispatches) == 3
    assert all(d.destination == "splunk" for d in dispatches)
    assert all(d.status == "pending" for d in dispatches)
    assert all(d.source_table == "pce_traffic_flows_raw" for d in dispatches)
    assert {d.source_id for d in dispatches} == {f.id for f in flows}


def test_traffic_ingestor_skips_enqueue_when_no_destinations(sf):
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc)
    api = FakeTrafficApi([_mk_flow(1, ts)])
    ing = TrafficIngestor(api=api, session_factory=sf, watermark=WatermarkStore(sf))
    assert ing.run_once() == 1
    with sf() as s:
        assert s.execute(select(SiemDispatch)).scalars().all() == []


def test_dedup_does_not_create_duplicate_dispatch(sf):
    """Duplicate event (same pce_href) must not create extra dispatch rows."""
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc)
    api = FakeEventsApi([_mk_event(1, ts)])
    ing = EventsIngestor(
        api=api, session_factory=sf,
        watermark=WatermarkStore(sf),
        siem_destinations=["splunk"],
    )
    assert ing.run_once() == 1
    assert ing.run_once() == 0  # second run dedupes
    with sf() as s:
        dispatches = s.execute(select(SiemDispatch)).scalars().all()
    assert len(dispatches) == 1
