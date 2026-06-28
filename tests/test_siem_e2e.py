"""End-to-end: ingest → inline enqueue → dispatcher.tick() → fake transport."""
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import SiemDispatch
from src.siem.dispatcher import DestinationDispatcher
from src.siem.formatters.cef import CEFFormatter
from src.siem.formatters.normalized_json import NormalizedJSONFormatter
from src.siem.transports.base import Transport


@pytest.fixture
def sf(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


class CapturingTransport(Transport):
    def __init__(self):
        self.payloads: list[str] = []

    def send(self, payload: str) -> None:
        self.payloads.append(payload)


class FakeEventsApi:
    def __init__(self, events): self._events = events
    def get_events(self, max_results=500, since=None, rate_limit=False, **kw):
        return self._events[:max_results]
    def get_events_async(self, since=None, rate_limit=False, **kw):
        return []


class FakeTrafficApi:
    def __init__(self, flows): self._flows = flows
    def get_traffic_flows_async(self, max_results=200000, rate_limit=False, **kw):
        return self._flows[:max_results]


def test_e2e_event_reaches_transport(sf):
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc)
    api = FakeEventsApi([{
        "href": "/orgs/1/events/1", "uuid": "uuid-1",
        "timestamp": ts.isoformat(), "event_type": "policy.update",
        "severity": "info", "status": "success", "pce_fqdn": "pce.test",
    }])
    EventsIngestor(
        api=api, session_factory=sf, watermark=WatermarkStore(sf),
        siem_destinations=["splunk"],
    ).run_once()

    transport = CapturingTransport()
    dispatcher = DestinationDispatcher("splunk", sf, CEFFormatter(), transport)
    result = dispatcher.tick()

    assert result == {"sent": 1, "failed": 0, "quarantined": 0}
    assert len(transport.payloads) == 1
    assert "CEF:0|Illumio|PCE|" in transport.payloads[0]
    assert "policy.update" in transport.payloads[0]
    with sf() as s:
        row = s.execute(select(SiemDispatch)).scalar_one()
    assert row.status == "sent"
    assert row.sent_at is not None


def test_e2e_traffic_flow_reaches_transport_as_json(sf):
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc)
    api = FakeTrafficApi([{
        "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2",
        "port": 443, "protocol": "tcp", "policy_decision": "blocked",
        "flow_count": 5, "bytes_in": 100, "bytes_out": 200,
        "first_detected": ts.isoformat(),
        "last_detected": (ts + timedelta(seconds=1)).isoformat(),
        "src_workload": "web", "dst_workload": "db",
    }])
    TrafficIngestor(
        api=api, session_factory=sf, watermark=WatermarkStore(sf),
        siem_destinations=["elastic"],
    ).run_once()

    transport = CapturingTransport()
    dispatcher = DestinationDispatcher("elastic", sf, NormalizedJSONFormatter(), transport)
    result = dispatcher.tick()

    assert result["sent"] == 1
    assert len(transport.payloads) == 1
    payload = transport.payloads[0]
    assert "10.0.0.1" in payload
    assert "10.0.0.2" in payload
    assert "blocked" in payload


def test_e2e_multi_destination_fanout(sf):
    """One event, two destinations → two transports each receive one payload."""
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc)
    api = FakeEventsApi([{
        "href": "/orgs/1/events/1", "uuid": "uuid-1",
        "timestamp": ts.isoformat(), "event_type": "policy.update",
        "severity": "info", "status": "success", "pce_fqdn": "pce.test",
    }])
    EventsIngestor(
        api=api, session_factory=sf, watermark=WatermarkStore(sf),
        siem_destinations=["splunk", "elastic"],
    ).run_once()

    splunk_tr = CapturingTransport()
    elastic_tr = CapturingTransport()
    DestinationDispatcher("splunk", sf, CEFFormatter(), splunk_tr).tick()
    DestinationDispatcher("elastic", sf, NormalizedJSONFormatter(), elastic_tr).tick()

    assert len(splunk_tr.payloads) == 1
    assert len(elastic_tr.payloads) == 1
    with sf() as s:
        rows = s.execute(select(SiemDispatch)).scalars().all()
    assert len(rows) == 2
    assert all(r.status == "sent" for r in rows)


def test_e2e_safety_net_backfills_only_when_needed(sf):
    """After inline enqueue, enqueue_new_records must find nothing to do."""
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore
    from src.siem.dispatcher import enqueue_new_records

    ts = datetime.now(timezone.utc)
    api = FakeEventsApi([{
        "href": "/orgs/1/events/1", "uuid": "uuid-1",
        "timestamp": ts.isoformat(), "event_type": "policy.update",
        "severity": "info", "status": "success", "pce_fqdn": "pce.test",
    }])
    EventsIngestor(
        api=api, session_factory=sf, watermark=WatermarkStore(sf),
        siem_destinations=["splunk"],
    ).run_once()

    backfilled = enqueue_new_records(sf, ["splunk"])
    assert backfilled == 0


def test_e2e_safety_net_picks_up_rows_with_no_inline_destinations(sf):
    """If a destination is added later, safety net catches up historical rows."""
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore
    from src.siem.dispatcher import enqueue_new_records

    ts = datetime.now(timezone.utc)
    api = FakeEventsApi([{
        "href": "/orgs/1/events/1", "uuid": "uuid-1",
        "timestamp": ts.isoformat(), "event_type": "policy.update",
        "severity": "info", "status": "success", "pce_fqdn": "pce.test",
    }])
    # Ingest with no destinations (SIEM disabled at write time)
    EventsIngestor(
        api=api, session_factory=sf, watermark=WatermarkStore(sf),
    ).run_once()

    # Operator enables a destination → safety net catches up
    backfilled = enqueue_new_records(sf, ["splunk"])
    assert backfilled == 1
    with sf() as s:
        row = s.execute(select(SiemDispatch)).scalar_one()
    assert row.destination == "splunk"
    assert row.status == "pending"
