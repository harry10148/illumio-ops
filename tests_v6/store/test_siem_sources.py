"""The SIEM sources' ids never come back after a delete, the new-connection log, and the cursor store (P7 Task 4)."""
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.store import siem
from illumio_ops.store.flowdb import analysis
from illumio_ops.store.flowdb.db import FlowDb
from illumio_ops.store.flowdb.flows import (
    delete_baselines_before,
    delete_new_connection_log_before,
    upsert_flows,
)
from tests_v6.store.test_alert_store import insert
from tests_v6.store.test_analysis_store import DEDUP, _det
from tests_v6.web.conftest import make_ctx

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pce" / "flows_sample.json"
NOW = datetime(2026, 10, 31, 7, 0, tzinfo=UTC)


@pytest.fixture
def fconn(tmp_path):
    c = FlowDb(tmp_path / "flows.sqlite").connect()
    yield c
    c.close()


@pytest.fixture(scope="module")
def recs():
    return [normalize_flow(r) for r in json.loads(FIXTURE.read_text())]


def test_a_deleted_newest_alert_id_is_never_given_again(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        insert(conn)
        top = insert(conn)
        conn.execute("DELETE FROM alerts WHERE id = ?", (top,))
        conn.commit()
        assert insert(conn) > top


def test_a_deleted_newest_detection_id_is_never_given_again(fconn):
    analysis.upsert_detections(fconn, [_det("fanout|a"), _det("fanout|b")], dedup=DEDUP, late=False, at=NOW)
    top = fconn.execute("SELECT MAX(id) FROM detections").fetchone()[0]
    fconn.execute("DELETE FROM detections WHERE id = ?", (top,))
    analysis.upsert_detections(fconn, [_det("fanout|c")], dedup=DEDUP, late=False, at=NOW)
    assert fconn.execute("SELECT MAX(id) FROM detections").fetchone()[0] > top


def _log(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM new_connection_log ORDER BY id")]


def test_live_collection_logs_each_connection_the_baseline_did_not_hold(fconn, recs):
    upsert_flows(fconn, recs, origin=DataOrigin.INGEST, now=NOW, increments="cycle", log_new_connections=True)
    log = _log(fconn)
    expected = fconn.execute("SELECT COUNT(*) FROM connection_baseline WHERE port >= 0 AND port < 49152").fetchone()[0]
    assert len(log) == expected > 0
    row = log[0]
    assert row["recorded_at"].startswith("2026-10-31T07:00") and row["src_ip"] and row["dst_ip"]
    assert row["decision"] in ("allowed", "potentially_blocked", "blocked", "unknown")
    # seen again: already in the baseline
    later = [replace(r, last_detected=r.last_detected + timedelta(minutes=10), num_connections=r.num_connections + 1)
             for r in recs]
    upsert_flows(fconn, later, origin=DataOrigin.INGEST, now=NOW + timedelta(minutes=10), increments="cycle",
                 log_new_connections=True)
    assert len(_log(fconn)) == len(log)


def test_history_and_an_unfilled_baseline_log_nothing(fconn, recs):
    upsert_flows(fconn, recs, origin=DataOrigin.BACKFILL, now=NOW)  # a backfill never logs
    upsert_flows(fconn, recs, origin=DataOrigin.INGEST, now=NOW, increments="cycle")  # flag off: baseline not full
    assert _log(fconn) == []


def test_dynamic_ports_are_not_new_services(fconn, recs):
    high = [replace(r, port=50_000 + i) for i, r in enumerate(recs)]
    upsert_flows(fconn, high, origin=DataOrigin.INGEST, now=NOW, increments="cycle", log_new_connections=True)
    assert _log(fconn) == []


def test_a_connection_unseen_for_the_baseline_period_is_new_again(fconn, recs):
    one = recs[:1]
    upsert_flows(fconn, one, origin=DataOrigin.INGEST, now=NOW, increments="cycle", log_new_connections=True)
    first = len(_log(fconn))
    delete_baselines_before(fconn, one[0].last_detected + timedelta(days=1))  # its baseline row expires
    back = [replace(one[0], first_detected=NOW + timedelta(days=40), last_detected=NOW + timedelta(days=40))]
    upsert_flows(fconn, back, origin=DataOrigin.INGEST, now=NOW + timedelta(days=40), increments="cycle",
                 log_new_connections=True)
    assert len(_log(fconn)) == first + 1 and first >= 1
    delete_new_connection_log_before(fconn, NOW + timedelta(days=1))
    assert len(_log(fconn)) == 1


def test_a_cursor_written_for_another_pce_is_not_moved(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        siem.start_cursor(conn, "d" * 32, "audit", pce_url="https://a", org_id="1", last_id=5)
        assert not siem.advance(conn, "d" * 32, "audit", pce_url="https://b", org_id="1", last_id=9, sent=4, at=NOW)
        assert siem.get_cursor(conn, "d" * 32, "audit").last_id == 5
        assert siem.advance(conn, "d" * 32, "audit", pce_url="https://a", org_id="1", last_id=9, sent=4, at=NOW)
        c = siem.get_cursor(conn, "d" * 32, "audit")
        assert c.last_id == 9 and c.sent == 4 and c.last_sent_at == NOW


def test_failures_count_against_the_same_head_record(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        siem.start_cursor(conn, "d" * 32, "audit", pce_url="https://a", org_id="1", last_id=5)
        assert siem.record_failure(conn, "d" * 32, "audit", head_id=6, error="x", at=NOW) == 1
        assert siem.record_failure(conn, "d" * 32, "audit", head_id=6, error="x", at=NOW) == 2
        assert siem.record_failure(conn, "d" * 32, "audit", head_id=7, error="y", at=NOW) == 1


def test_a_pce_switch_restarts_the_flow_store_cursors_only(tmp_path):
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:
        for source in ("audit", "alerts", "detections", "new_connections"):
            siem.start_cursor(conn, "d" * 32, source, pce_url="https://a", org_id="1", last_id=5)
        siem.restart_flow_cursors(conn, pce_url="https://b", org_id="1")
        got = {s: (c.pce_url, c.last_id) for (_, s), c in siem.cursors(conn).items()}
    assert got == {"alerts": ("https://a", 5), "audit": ("https://b", 0), "detections": ("https://b", 0),
                   "new_connections": ("https://b", 0)}
