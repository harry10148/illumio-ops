"""Analysis tables of the flow database: detections (deduplicated), run state, results, daily lateral
snapshots and the focus list's first-seen record."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.store.flowdb import analysis
from illumio_ops.store.flowdb.analysis import DetectionWrite, FocusWrite
from illumio_ops.store.flowdb.db import FlowDb

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    c = FlowDb(tmp_path / "flows.sqlite").connect()
    yield c
    c.close()


def _det(fp="fanout|w1", *, seen=NOW, severity="medium", detector="fanout", targets=10):
    return DetectionWrite(detector=detector, fingerprint=fp, subject_key="w1", severity=severity,
                          first_seen=seen - timedelta(minutes=5), last_seen=seen, critical_asset=False,
                          summary_json=json.dumps({"targets": targets}), segment_json="{}", confidence_json="{}")


DEDUP = {"fanout": timedelta(minutes=60)}


def test_detection_upsert_dedups_within_window(conn):
    assert analysis.upsert_detections(conn, [_det()], dedup=DEDUP, late=False, at=NOW) == (1, 0)
    later = NOW + timedelta(minutes=30)
    assert analysis.upsert_detections(conn, [_det(seen=later, severity="high", targets=14)],
                                      dedup=DEDUP, late=False, at=later) == (0, 1)
    [row] = analysis.detections_since(conn, NOW - timedelta(days=1), limit=10)
    assert row["occurrences"] == 2 and row["severity"] == "high"
    assert row["last_seen"].startswith("2026-10-25T12:30") and json.loads(row["summary_json"])["targets"] == 14
    # an update never lowers the severity
    analysis.upsert_detections(conn, [_det(seen=later + timedelta(minutes=1), severity="low")],
                               dedup=DEDUP, late=False, at=later)
    assert analysis.detections_since(conn, NOW - timedelta(days=1), limit=10)[0]["severity"] == "high"


def test_detection_after_quiet_period_is_new_row(conn):
    analysis.upsert_detections(conn, [_det()], dedup=DEDUP, late=False, at=NOW)
    much_later = NOW + timedelta(hours=3)
    assert analysis.upsert_detections(conn, [_det(seen=much_later)], dedup=DEDUP, late=True,
                                      at=much_later) == (1, 0)
    rows = analysis.detections_since(conn, NOW - timedelta(days=1), limit=10)
    assert len(rows) == 2 and sorted(r["late"] for r in rows) == [0, 1]


def test_detections_filtered_by_detector(conn):
    analysis.upsert_detections(conn, [_det(), _det("new|a|b|22|6", detector="new_admin_connection")],
                               dedup=DEDUP | {"new_admin_connection": timedelta(days=30)}, late=False, at=NOW)
    rows = analysis.detections_since(conn, NOW - timedelta(days=1), detectors=("new_admin_connection",), limit=10)
    assert [r["detector"] for r in rows] == ["new_admin_connection"]


def test_run_and_result_roundtrip(conn):
    analysis.set_run(conn, "detect", started_at=NOW)
    analysis.set_run(conn, "detect", ok_at=NOW, watermark=NOW, status={"fanout": "ok"})
    run = analysis.get_run(conn, "detect")
    assert run["last_started_at"].startswith("2026-10-25T12:00") and run["watermark"].startswith("2026-10-25T12:00")
    assert json.loads(run["status_json"]) == {"fanout": "ok"} and run["last_error"] is None
    analysis.set_run(conn, "detect", error="boom")
    assert analysis.get_run(conn, "detect")["last_error"] == "boom"
    assert analysis.get_run(conn, "detect")["watermark"].startswith("2026-10-25T12:00")  # kept
    analysis.write_result(conn, "exposure", params={"hops": 3}, result={"nodes": 5}, at=NOW)
    res = analysis.read_result(conn, "exposure")
    assert json.loads(res["result_json"]) == {"nodes": 5} and json.loads(res["params_json"]) == {"hops": 3}
    assert analysis.read_result(conn, "focus") is None
    analysis.write_lateral_snapshot(conn, "2026-10-25", {"nodes": 5})
    analysis.write_lateral_snapshot(conn, "2026-10-25", {"nodes": 6})
    assert conn.execute("SELECT metrics_json FROM lateral_snapshot_daily").fetchall()[0][0] == '{"nodes": 6}'


def test_focus_first_seen_kept_and_missing_marked_inactive(conn):
    a, b = FocusWrite("fa", "tamper", 2.0, "{}"), FocusWrite("fb", "detection", 4.0, "{}")
    first = analysis.upsert_focus(conn, [a, b], at=NOW)
    later = NOW + timedelta(days=8)
    again = analysis.upsert_focus(conn, [a], at=later)
    assert first["fa"] == again["fa"] == NOW and set(again) == {"fa"}
    rows = {r["fingerprint"]: r for r in conn.execute("SELECT * FROM focus_items")}
    assert rows["fa"]["active"] == 1 and rows["fb"]["active"] == 0
    # back again after going inactive: still the first time it was seen
    assert analysis.upsert_focus(conn, [a, b], at=later)["fb"] == NOW


def test_delete_expired(conn):
    old = NOW - timedelta(days=100)
    analysis.upsert_detections(conn, [_det(seen=old), _det("fanout|w2", seen=NOW)], dedup=DEDUP, late=False, at=NOW)
    analysis.upsert_focus(conn, [FocusWrite("f-old", "tamper", 1.0, "{}")], at=old)
    analysis.upsert_focus(conn, [FocusWrite("f-new", "tamper", 1.0, "{}")], at=NOW)  # f-old now inactive
    analysis.write_lateral_snapshot(conn, "2026-06-01", {})
    analysis.write_lateral_snapshot(conn, "2026-10-25", {})
    n = analysis.delete_expired(conn, detections_before=NOW - timedelta(days=90),
                                focus_before=NOW - timedelta(days=90), snapshot_day_before="2026-07-27")
    assert n == 3
    assert [r["fingerprint"] for r in analysis.detections_since(conn, old - timedelta(days=1), limit=10)] == ["fanout|w2"]
    assert [r[0] for r in conn.execute("SELECT fingerprint FROM focus_items")] == ["f-new"]
    assert [r[0] for r in conn.execute("SELECT day FROM lateral_snapshot_daily")] == ["2026-10-25"]


def test_reset_clears_analysis_tables(tmp_path):
    fdb = FlowDb(tmp_path / "flows.sqlite")
    with fdb.connect() as c:
        analysis.upsert_detections(c, [_det()], dedup=DEDUP, late=False, at=NOW)
        analysis.write_result(c, "exposure", params={}, result={}, at=NOW)
    fdb.reset()
    with fdb.connect() as c:
        for table in ("detections", "analysis_runs", "analysis_results", "lateral_snapshot_daily", "focus_items"):
            assert c.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
