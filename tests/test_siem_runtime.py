"""Tests for SIEM runtime dispatch pipeline wiring."""
from __future__ import annotations
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import Base, PceEvent, PceTrafficFlowRaw, SiemDispatch


@pytest.fixture
def sf():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(engine)


def _add_event(sf, ts=None):
    ts = ts or datetime.now(timezone.utc)
    with sf.begin() as s:
        ev = PceEvent(
            pce_fqdn="pce.test",
            pce_href="/orgs/1/events/1",
            pce_event_id="evt-001",
            event_type="system.auth.login",
            severity="informational",
            status="success",
            timestamp=ts,
            raw_json="{}",
            ingested_at=ts,
        )
        s.add(ev)
    with sf() as s:
        return s.execute(select(PceEvent)).scalars().first().id


def _add_flow(sf, ts=None):
    ts = ts or datetime.now(timezone.utc)
    with sf.begin() as s:
        f = PceTrafficFlowRaw(
            flow_hash="abc123",
            src_ip="1.2.3.4",
            dst_ip="5.6.7.8",
            port=443,
            protocol="tcp",
            action="allowed",
            flow_count=1,
            bytes_in=0,
            bytes_out=0,
            first_detected=ts,
            last_detected=ts,
            raw_json="{}",
            ingested_at=ts,
        )
        s.add(f)
    with sf() as s:
        return s.execute(select(PceTrafficFlowRaw)).scalars().first().id


def test_enqueue_new_records_creates_dispatch_rows(sf):
    """enqueue_new_records queues new events and flows for each destination."""
    from src.siem.dispatcher import enqueue_new_records
    _add_event(sf)
    _add_flow(sf)
    enqueue_new_records(sf, destinations=["syslog://host:514"])
    with sf() as s:
        rows = s.execute(select(SiemDispatch)).scalars().all()
    assert len(rows) == 2  # 1 event + 1 flow
    tables = {r.source_table for r in rows}
    assert "pce_events" in tables
    assert "pce_traffic_flows_raw" in tables


def test_enqueue_new_records_skips_already_dispatched(sf):
    """enqueue_new_records does not create duplicate dispatch rows."""
    from src.siem.dispatcher import enqueue_new_records, enqueue
    eid = _add_event(sf)
    enqueue(sf, "pce_events", eid, ["syslog://host:514"])  # pre-enqueue
    enqueue_new_records(sf, destinations=["syslog://host:514"])
    with sf() as s:
        rows = s.execute(select(SiemDispatch)).scalars().all()
    assert len(rows) == 1  # no duplicate


def test_enqueue_new_records_noop_when_no_records(sf):
    """enqueue_new_records does nothing when cache is empty."""
    from src.siem.dispatcher import enqueue_new_records
    enqueue_new_records(sf, destinations=["syslog://host:514"])
    with sf() as s:
        count = s.execute(select(SiemDispatch)).scalars().all()
    assert len(count) == 0


def test_run_siem_dispatch_calls_tick_and_enqueue():
    """run_siem_dispatch enqueues new records and calls build_dispatcher().tick() per destination."""
    from src.scheduler.jobs import run_siem_dispatch
    from src.config_models import SiemDestinationSettings

    dest = SiemDestinationSettings(
        name="test-dest", enabled=True, transport="udp",
        format="cef", endpoint="192.168.1.1:514",
    )
    cm = MagicMock()
    cm.models.siem.enabled = True
    cm.models.siem.destinations = [dest]
    cm.models.pce_cache.db_path = ":memory:"

    with patch("src.siem.dispatcher.enqueue_new_records") as mock_enqueue, \
         patch("src.siem.dispatcher.build_dispatcher") as mock_build, \
         patch("src.pce_cache.schema.init_schema"), \
         patch("sqlalchemy.create_engine"), \
         patch("sqlalchemy.orm.sessionmaker"):
        mock_enqueue.return_value = 0
        mock_dispatcher = MagicMock()
        mock_build.return_value = mock_dispatcher
        run_siem_dispatch(cm)

    mock_enqueue.assert_called_once()
    assert mock_build.call_args[0][0] is dest
    mock_dispatcher.tick.assert_called_once()
