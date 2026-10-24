"""Regression tests for the Codex adversarial review of P2 Tasks 2-6 (one test per finding)."""
import itertools
import sqlite3
import threading
import time
from dataclasses import replace
from datetime import timedelta

import pytest

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin, IngestSource
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.services.collect import traffic
from illumio_ops.services.collect.guard import normalize_target
from illumio_ops.services.collect.traffic import normalize_all, run_traffic_cycle
from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.flows import upsert_flows

from .conftest import NOW, configured_ctx, minutes, raw_flow


def _state(ctx, source=IngestSource.TRAFFIC):
    with ctx.flows().connect() as conn:
        return ingest_state.get(conn, source), ingest_state.open_gaps(conn, source)


# 1
def test_cold_start_failure_keeps_original_start(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    fake_traffic.answer = lambda s, e, m: (_ for _ in ()).throw(PceQueryError("timeout"))
    run_traffic_cycle(ctx, now=NOW)
    fake_traffic.answer = lambda s, e, m: []
    run_traffic_cycle(ctx, now=NOW + minutes(10))
    assert fake_traffic.calls[1][0] == "2026-10-23T12:00:00Z"  # the original cold-start lower bound
    state, gaps = _state(ctx)
    assert gaps == [] and state.watermark == NOW + minutes(10)


# 2
def test_write_failure_marks_failed_and_records_gap(tmp_path, fake_traffic, monkeypatch):
    ctx = configured_ctx(tmp_path)
    fake_traffic.answer = lambda s, e, m: [raw_flow(1, e - minutes(2), e - minutes(1))]
    def broken(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(traffic, "upsert_flows", broken)
    with pytest.raises(sqlite3.OperationalError):
        run_traffic_cycle(ctx, now=NOW)
    state, gaps = _state(ctx)
    assert state.watermark is None and state.consecutive_failures == 1 and "disk I/O" in state.last_error
    assert [g.kind for g in gaps] == ["failed"]


# 3
def test_flows_and_rollups_commit_together(tmp_path, fake_traffic, monkeypatch):
    ctx = configured_ctx(tmp_path)
    fake_traffic.answer = lambda s, e, m: [raw_flow(1, e - minutes(2), e - minutes(1))]
    def broken_rollup(conn, day):
        raise sqlite3.OperationalError("rollup failed")
    monkeypatch.setattr(traffic, "rebuild_rollup", broken_rollup)
    with pytest.raises(sqlite3.OperationalError):
        run_traffic_cycle(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        assert conn.execute("SELECT count(*) FROM flows").fetchone()[0] == 0  # rolled back with the rollup


# 4
def _three(recs):
    inn = recs[0]  # inbound 10.0.0.1 -> 10.0.0.2 2055/udp
    out = recs[1]
    inn2 = replace(inn, first_detected=inn.first_detected + timedelta(hours=1))
    return {"I1": inn, "I2": inn2, "O": out}


@pytest.fixture(scope="module")
def recs():
    import json
    from pathlib import Path
    raw = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "pce" / "flows_sample.json").read_text())
    return [normalize_flow(r) for r in raw]


@pytest.mark.parametrize("order", list(itertools.permutations(["I1", "I2", "O"])))
def test_pairing_is_order_independent(tmp_path, recs, order):
    from illumio_ops.store.flowdb.db import FlowDb
    three = _three(recs)
    with FlowDb(tmp_path / "f.sqlite").connect() as conn:
        for name in order:
            upsert_flows(conn, [three[name]], origin=DataOrigin.INGEST, now=NOW)
        primaries = conn.execute("SELECT count(*) FROM flows WHERE is_primary = 1").fetchone()[0]
        pairs = conn.execute("SELECT count(*) FROM (SELECT conn_key FROM flows GROUP BY conn_key HAVING count(*) = 2)").fetchone()[0]
    assert (primaries, pairs) == (2, 1)  # O pairs with the earliest overlapping inbound; I2 stands alone


def test_refresh_that_brings_ranges_together_pairs(tmp_path, recs):
    from illumio_ops.store.flowdb.db import FlowDb
    out = recs[1]
    far = replace(recs[0], first_detected=out.last_detected + timedelta(minutes=19),
                  last_detected=out.last_detected + timedelta(minutes=25))
    with FlowDb(tmp_path / "f.sqlite").connect() as conn:
        upsert_flows(conn, [out, far], origin=DataOrigin.INGEST, now=NOW)
        assert conn.execute("SELECT count(*) FROM flows WHERE is_primary = 1").fetchone()[0] == 2
        upsert_flows(conn, [replace(out, last_detected=out.last_detected + timedelta(minutes=20))],
                     origin=DataOrigin.INGEST, now=NOW)
        assert conn.execute("SELECT count(*) FROM flows WHERE is_primary = 1").fetchone()[0] == 1


# 5
def test_split_window_duplicates_keep_bytes():
    first = raw_flow(1, NOW - minutes(10), NOW - minutes(5))
    first["dst_bi"], first["dst_bo"] = 1000, 10
    later = raw_flow(1, NOW - minutes(10), NOW - minutes(1))
    later["num_connections"] = 3
    [merged], skipped = normalize_all([first, later])
    assert (merged.bytes_in, merged.bytes_out, merged.num_connections) == (1000, 10, 3)
    assert merged.last_detected == NOW - minutes(1) and skipped == 0


# 6
def test_client_and_binding_use_same_settings_snapshot(tmp_path, fake_traffic, monkeypatch):
    ctx = configured_ctx(tmp_path)
    a = ctx.settings.current()
    b = a.model_copy(update={"pce": a.pce.model_copy(update={"url": "https://other-pce.example.com:8443"})})
    calls = []
    monkeypatch.setattr(ctx.settings, "current", lambda: (calls.append(1), a if len(calls) == 1 else b)[1])
    seen = []
    real_factory = ctx.pce_factory
    ctx.pce_factory = lambda cfg, **kw: (seen.append(cfg.url), real_factory(cfg, **kw))[1]
    run_traffic_cycle(ctx, now=NOW)
    assert seen == ["https://pce.example.com:8443"]


# 7, 8, 10
def test_normalize_target_cases():
    assert normalize_target("https://proxy.example.com/pce-a/", "1") != normalize_target("https://proxy.example.com/pce-b", "1")
    v6 = normalize_target("https://[2001:db8::1]:8443", "1")
    assert normalize_target(*v6) == v6 and v6[0] == "https://[2001:db8::1]:8443"
    assert normalize_target("https://pce.example", "1") == normalize_target("https://PCE.example:443/", "01")
    assert normalize_target("http://pce.example:80", "1") == normalize_target("http://pce.example", "1")


# 9
def test_mark_started_waits_for_the_write_lock(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    fdb = ctx.flows()
    fdb.connect().close()
    fdb.write_lock.acquire()
    t = threading.Thread(target=lambda: run_traffic_cycle(ctx, now=NOW), daemon=True)
    t.start()
    try:
        time.sleep(0.3)
        with fdb.connect() as conn:
            before = ingest_state.get(conn, IngestSource.TRAFFIC)
    finally:
        fdb.write_lock.release()
    t.join(5)
    assert before is None  # blocked on the lock before writing anything
    assert _state(ctx)[0].last_ok_at == NOW
