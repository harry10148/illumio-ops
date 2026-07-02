from datetime import datetime, timedelta, timezone

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

    assert enqueue_new_records(sf, {"pce_events": ["test-dest"]}) == 1   # only event 3
    assert enqueue_new_records(sf, {"pce_events": ["test-dest"]}) == 0   # idempotent

    with sf() as s:
        rows = s.execute(
            select(SiemDispatch).where(SiemDispatch.source_id == 3)
        ).scalars().all()
    assert len(rows) == 1


def test_enqueue_new_records_backfills_newly_enabled_destination(sf):
    """RED: a row already dispatched to destination A must still be backfilled
    for newly-enabled destination B — the anti-join must be scoped per
    destination, not just per (source_table, source_id). Previously the
    anti-join only checked 'does this row have ANY dispatch row', so a row
    that had ever been enqueued for any destination could never be backfilled
    for a later-enabled one."""
    from src.siem.dispatcher import enqueue_new_records

    _seed_event(sf, 1)  # already dispatched to "test-dest" (see _seed_event)

    created = enqueue_new_records(sf, {"pce_events": ["test-dest", "new-dest"]})

    assert created == 1  # only the new-dest row is missing
    with sf() as s:
        rows = s.execute(
            select(SiemDispatch).where(SiemDispatch.source_id == 1)
        ).scalars().all()
    destinations = {r.destination for r in rows}
    assert destinations == {"test-dest", "new-dest"}


def test_enqueue_new_records_does_not_backfill_traffic_to_audit_only_destination(sf):
    """RED: destinations_by_source_table must filter per source_table (i.e. per
    source_type), mirroring the ingest-side _enabled_siem_destinations filter.
    An audit-only destination passed only for "pce_events" must never receive
    a backfilled traffic row."""
    from src.siem.dispatcher import enqueue_new_records
    from src.pce_cache.models import PceEvent, PceTrafficFlowRaw, SiemDispatch

    now = datetime.now(timezone.utc)
    with sf.begin() as s:
        s.add(PceEvent(
            pce_href="/orgs/1/events/1", pce_event_id="uuid-1", timestamp=now,
            event_type="policy.update", severity="info", status="success",
            pce_fqdn="pce.test", raw_json="{}", ingested_at=now,
        ))
        s.add(PceTrafficFlowRaw(
            flow_hash="hash-1", src_ip="1.2.3.4", dst_ip="5.6.7.8", port=443,
            protocol="tcp", action="allowed", flow_count=1, bytes_in=0, bytes_out=0,
            first_detected=now, last_detected=now, raw_json="{}", ingested_at=now,
        ))

    created = enqueue_new_records(sf, {
        "pce_events": ["audit-dest"],
        "pce_traffic_flows_raw": [],  # audit-dest is not subscribed to traffic
    })

    assert created == 1
    with sf() as s:
        rows = s.execute(select(SiemDispatch)).scalars().all()
    assert len(rows) == 1
    assert rows[0].source_table == "pce_events"
    assert rows[0].destination == "audit-dest"


def test_enqueue_new_records_not_reenqueued_after_ingested_at_bump(sf):
    """F6 副作用鎖定：re-pull 一筆已 dispatch 過的 traffic flow 會把
    ingested_at bump（見 ingestor_traffic.py），但 id 不變。安全網補登的
    anti-join 以 (source_table, source_id, destination) 判斷，不看
    ingested_at，所以 bump 後該 (row, destination) pair 已有 dispatch row，
    不會被 enqueue_new_records 誤判成「缺 dispatch」而重複派送。"""
    from src.siem.dispatcher import enqueue_new_records
    from src.pce_cache.models import PceTrafficFlowRaw, SiemDispatch

    now = datetime.now(timezone.utc)
    with sf.begin() as s:
        flow = PceTrafficFlowRaw(
            flow_hash="hash-bump", src_ip="1.2.3.4", dst_ip="5.6.7.8", port=443,
            protocol="tcp", action="allowed", flow_count=1, bytes_in=0, bytes_out=0,
            first_detected=now, last_detected=now, raw_json="{}", ingested_at=now,
        )
        s.add(flow)
        s.flush()
        flow_id = flow.id
        s.add(SiemDispatch(
            source_table="pce_traffic_flows_raw", source_id=flow_id,
            destination="test-dest", status="sent", retries=0, queued_at=now,
        ))

    # 模擬 re-pull：ingest 端 upsert 把 ingested_at bump 到更晚的時間，id 不變。
    with sf.begin() as s:
        row = s.get(PceTrafficFlowRaw, flow_id)
        row.ingested_at = now + timedelta(minutes=5)
        row.bytes_in = 900

    created = enqueue_new_records(sf, {"pce_traffic_flows_raw": ["test-dest"]})

    assert created == 0   # 已有 dispatch row，bump 不觸發重複派送
    with sf() as s:
        dispatches = s.execute(
            select(SiemDispatch).where(SiemDispatch.source_id == flow_id)
        ).scalars().all()
    assert len(dispatches) == 1


def test_enqueue_new_records_scan_count_independent_of_destination_count(sf):
    """效率回歸鎖定：候選掃描（唯一會全表掃 source table 的查詢）每
    source_table 每次呼叫只發一次，與 destination 數無關。安全網每 tick
    無條件執行且正常找不到東西，若掃描次數隨 destination 數線性成長，
    成熟快取的穩態成本會倍增。"""
    from sqlalchemy import event
    from src.siem.dispatcher import enqueue_new_records

    dests = ["d1", "d2", "d3"]
    now = datetime.now(timezone.utc)
    with sf.begin() as s:
        for i in (1, 2):
            s.add(PceEvent(
                pce_href=f"/orgs/1/events/{i}", pce_event_id=f"uuid-{i}",
                timestamp=now, event_type="policy.update", severity="info",
                status="success", pce_fqdn="pce.test", raw_json="{}",
                ingested_at=now,
            ))
            for d in dests:  # 已全部 dispatch → 穩態（無候選）
                s.add(SiemDispatch(
                    source_table="pce_events", source_id=i, destination=d,
                    status="pending", retries=0, queued_at=now,
                ))

    engine = sf.kw["bind"]
    statements: list[str] = []

    def _spy(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _spy)
    try:
        created = enqueue_new_records(sf, {"pce_events": dests})
    finally:
        event.remove(engine, "before_cursor_execute", _spy)

    assert created == 0
    scans = [st for st in statements if "FROM pce_events" in st]
    assert len(scans) == 1  # 3 destinations 仍只掃 pce_events 一次


def _seed_many_events_without_dispatch(sf, n: int) -> None:
    now = datetime.now(timezone.utc)
    with sf.begin() as s:
        s.add_all([
            PceEvent(
                pce_href=f"/orgs/1/events/bulk-{i}", pce_event_id=f"uuid-bulk-{i}",
                timestamp=now, event_type="policy.update", severity="info",
                status="success", pce_fqdn="pce.test", raw_json="{}", ingested_at=now,
            )
            for i in range(n)
        ])


def test_enqueue_new_records_uses_one_transaction_for_many_rows(sf):
    """RED: backfilling a large cache on first SIEM enable must not open one
    transaction per row (fsync storm). Insert is chunked but committed in a
    single transaction."""
    from src.siem.dispatcher import enqueue_new_records

    _seed_many_events_without_dispatch(sf, 1200)  # > one 500-row chunk
    counting = _CountingSF(sf)

    created = enqueue_new_records(counting, {"pce_events": ["bulk-dest"]})

    assert created == 1200
    assert counting.begin_calls == 1


class _CountingSF:
    """包住 sessionmaker，計數 .begin() 呼叫次數（= 寫交易數）。"""
    def __init__(self, sf):
        self._sf = sf
        self.begin_calls = 0
    def __call__(self, *a, **k):
        return self._sf(*a, **k)
    def begin(self, *a, **k):
        self.begin_calls += 1
        return self._sf.begin(*a, **k)


class _FakeFormatter:
    def format_event(self, data): return "PAYLOAD"
    def format_flow(self, data): return "PAYLOAD"


def test_process_batch_marks_all_sent_in_one_transaction(sf):
    from src.siem.dispatcher import DestinationDispatcher
    for i in range(1, 4):
        _seed_event(sf, i)               # 3 筆 pending，destination="test-dest"
    counting = _CountingSF(sf)
    d = DestinationDispatcher("test-dest", counting, _FakeFormatter(), SuccessTransport())

    result = d.tick()

    assert result["sent"] == 3
    with sf() as s:
        rows = s.execute(select(SiemDispatch)).scalars().all()
    assert all(r.status == "sent" for r in rows)
    assert all(r.sent_at is not None for r in rows)
    assert counting.begin_calls == 1     # 3 筆成功 → 僅一個寫交易


def test_process_batch_missing_source_row_quarantines_without_affecting_others(sf):
    """Missing source row (dispatch row outlived its source, or source was
    deleted) must be quarantined via the payload_build_failed path, and must
    not affect other rows loaded in the same batch — regression guard for the
    single-session batch source load replacing the old per-row session."""
    from src.siem.dispatcher import DestinationDispatcher
    from src.siem.formatters.cef import CEFFormatter
    now = datetime.now(timezone.utc)
    _seed_event(sf, 1)  # valid row: source_id=1 exists in pce_events
    with sf.begin() as s:
        s.add(SiemDispatch(
            source_table="pce_events", source_id=9999,  # no such PceEvent row
            destination="test-dest", status="pending",
            retries=0, queued_at=now,
        ))
    tr = SuccessTransport()
    d = DestinationDispatcher("test-dest", sf, CEFFormatter(), tr)

    result = d.tick()

    assert result["sent"] == 1
    assert result["quarantined"] == 1
    assert len(tr.sent) == 1
    with sf() as s:
        dispatch_rows = s.execute(select(SiemDispatch)).scalars().all()
        dlq_rows = s.execute(select(DeadLetter)).scalars().all()
    statuses = {r.source_id: r.status for r in dispatch_rows}
    assert statuses[1] == "sent"
    assert statuses[9999] == "failed"
    assert len(dlq_rows) == 1
    assert dlq_rows[0].source_id == 9999
    assert dlq_rows[0].last_error == "payload_build_failed"


def test_process_batch_mixed_success_and_failure(sf):
    from src.siem.dispatcher import DestinationDispatcher
    for i in range(1, 4):
        _seed_event(sf, i)                      # 3 筆 pending
    counting = _CountingSF(sf)
    tr = FailTransport(fail_times=1)            # 第一筆 send 失敗，其餘成功
    d = DestinationDispatcher("test-dest", counting, _FakeFormatter(), tr, max_retries=5)

    result = d.tick()

    assert result["sent"] == 2
    assert result["failed"] == 1
    with sf() as s:
        rows = s.execute(select(SiemDispatch)).scalars().all()
    sent = [r for r in rows if r.status == "sent"]
    pending = [r for r in rows if r.status == "pending"]
    assert len(sent) == 2
    assert len(pending) == 1
    assert pending[0].retries == 1 and pending[0].next_attempt_at is not None
    # 1 個逐列 retry 交易 + 1 個批次 sent 交易 = 2
    assert counting.begin_calls == 2
