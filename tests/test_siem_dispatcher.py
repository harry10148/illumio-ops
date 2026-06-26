from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import DeadLetter, PceEvent, SiemDispatch


@pytest.fixture
def sf(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _seed_event(sf, idx=1):
    now = datetime.now(timezone.utc)
    with sf.begin() as s:
        ev = PceEvent(
            pce_href=f"/orgs/1/events/{idx}", pce_event_id=f"uuid-{idx}",
            timestamp=now, event_type="policy.update", severity="info",
            status="success", pce_fqdn="pce.test",
            raw_json='{"event_type":"policy.update","severity":"info","pce_fqdn":"pce.test"}',
            ingested_at=now,
        )
        s.add(ev)
        s.flush()
        dispatch = SiemDispatch(
            source_table="pce_events", source_id=idx,
            destination="test-dest", status="pending",
            retries=0, queued_at=now,
        )
        s.add(dispatch)
    return idx


class SuccessTransport:
    def __init__(self): self.sent = []
    def send(self, p): self.sent.append(p)
    def close(self): pass


class FailTransport:
    def __init__(self, fail_times=999):
        self.calls = 0
        self.fail_times = fail_times
    def send(self, p):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("simulated failure")
    def close(self): pass


def test_dispatcher_sends_pending_row(sf):
    from src.siem.dispatcher import DestinationDispatcher
    from src.siem.formatters.cef import CEFFormatter
    _seed_event(sf)
    tr = SuccessTransport()
    d = DestinationDispatcher("test-dest", sf, CEFFormatter(), tr)
    result = d.tick()
    assert result["sent"] == 1
    assert len(tr.sent) == 1
    with sf() as s:
        row = s.execute(select(SiemDispatch)).scalar_one()
    assert row.status == "sent"


def test_dispatcher_increments_retries_on_failure(sf):
    from src.siem.dispatcher import DestinationDispatcher
    from src.siem.formatters.cef import CEFFormatter
    _seed_event(sf)
    tr = FailTransport()
    d = DestinationDispatcher("test-dest", sf, CEFFormatter(), tr, max_retries=5)
    d.tick()
    with sf() as s:
        row = s.execute(select(SiemDispatch)).scalar_one()
    assert row.retries == 1
    assert row.status == "pending"
    assert row.next_attempt_at is not None


def test_dispatcher_quarantines_after_max_retries(sf):
    from src.siem.dispatcher import DestinationDispatcher
    from src.siem.formatters.cef import CEFFormatter
    from src.pce_cache.models import PceEvent
    # Seed event with retries already at max-1
    now = datetime.now(timezone.utc)
    with sf.begin() as s:
        ev = PceEvent(
            pce_href="/orgs/1/events/99", pce_event_id="uuid-99",
            timestamp=now, event_type="test", severity="info",
            status="success", pce_fqdn="pce.test",
            raw_json='{"event_type":"test","pce_fqdn":"pce.test"}',
            ingested_at=now,
        )
        s.add(ev)
        s.flush()
        ev_id = ev.id
        disp = SiemDispatch(
            source_table="pce_events", source_id=ev_id,
            destination="test-dest", status="pending",
            retries=9,  # one below max_retries=10
            queued_at=now,
        )
        s.add(disp)
    tr = FailTransport()
    d = DestinationDispatcher("test-dest", sf, CEFFormatter(), tr, max_retries=10)
    d.tick()
    with sf() as s:
        dispatch_row = s.execute(select(SiemDispatch).where(SiemDispatch.source_id == ev_id)).scalar_one()
        dlq_rows = s.execute(select(DeadLetter)).scalars().all()
    assert dispatch_row.status == "failed"
    assert len(dlq_rows) == 1
    assert "simulated failure" in dlq_rows[0].last_error


def test_transport_for_udp_uses_host_port():
    from src.siem.dispatcher import _transport_for
    from src.config_models import SiemDestinationSettings
    cfg = SiemDestinationSettings(name="t", transport="udp", host="10.0.0.5", port=1514)
    t = _transport_for(cfg)
    from src.siem.transports.syslog_udp import SyslogUDPTransport
    assert isinstance(t, SyslogUDPTransport)
    assert t._host == "10.0.0.5"
    assert t._port == 1514


def test_transport_for_hec_constructs_url():
    from src.siem.dispatcher import _transport_for
    from src.config_models import SiemDestinationSettings
    cfg = SiemDestinationSettings(name="h", transport="hec", host="splunk.corp", port=8088, hec_token="tok")
    t = _transport_for(cfg)
    from src.siem.transports.splunk_hec import SplunkHECTransport
    assert isinstance(t, SplunkHECTransport)


def test_transport_for_tls_threads_ca_bundle_and_verify():
    """Regression: _transport_for must pass tls_ca_bundle (and tls_verify) into
    the TLS transport, mirroring the tester — otherwise custom-CA destinations
    pass 'Test' but fail every real dispatch."""
    from src.siem.dispatcher import _transport_for
    from src.config_models import SiemDestinationSettings
    cfg = SiemDestinationSettings(
        name="t", transport="tls", host="siem.corp", port=6514,
        tls_verify=True, tls_ca_bundle="/etc/pki/ca.pem",
    )
    t = _transport_for(cfg)
    from src.siem.transports.syslog_tls import SyslogTLSTransport
    assert isinstance(t, SyslogTLSTransport)
    assert t._ca_bundle == "/etc/pki/ca.pem"
    assert t._tls_verify is True


def test_transport_for_hec_threads_verify_tls():
    """Regression: _transport_for must forward tls_verify to the HEC transport
    so an operator's tls_verify=False (dev/self-signed lab) is honored in
    production dispatch, not just in the 'Test' button."""
    from src.siem.dispatcher import _transport_for
    from src.config_models import SiemDestinationSettings
    cfg = SiemDestinationSettings(
        name="h", transport="hec", host="splunk.corp", port=8088,
        hec_token="tok", profile="dev", tls_verify=False,
    )
    t = _transport_for(cfg)
    from src.siem.transports.splunk_hec import SplunkHECTransport
    assert isinstance(t, SplunkHECTransport)
    assert t._verify is False


def test_enqueue_new_records_anti_join_only_undispatched(sf):
    """Regression: enqueue_new_records must use a SQL anti-join (NOT EXISTS),
    not load the dispatched-id set + `id NOT IN (...)` which blew SQLite's
    variable cap on a large cache. Functionally: only rows lacking a dispatch
    row get enqueued, and a second run is a no-op."""
    from src.siem.dispatcher import enqueue_new_records
    from src.pce_cache.models import PceEvent, SiemDispatch

    _seed_event(sf, 1)   # already dispatched (has a SiemDispatch row)
    _seed_event(sf, 2)
    now = datetime.now(timezone.utc)
    with sf.begin() as s:  # event 3: NO dispatch row yet
        s.add(PceEvent(
            pce_href="/orgs/1/events/3", pce_event_id="uuid-3", timestamp=now,
            event_type="policy.update", severity="info", status="success",
            pce_fqdn="pce.test", raw_json="{}", ingested_at=now,
        ))

    assert enqueue_new_records(sf, ["test-dest"]) == 1   # only event 3
    assert enqueue_new_records(sf, ["test-dest"]) == 0   # idempotent

    with sf() as s:
        rows = s.execute(
            select(SiemDispatch).where(SiemDispatch.source_id == 3)
        ).scalars().all()
    assert len(rows) == 1
