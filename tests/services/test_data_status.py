"""System › Modes and data sources (UI redesign spec §4.10): what is collected up to when, the baseline, the live
activity hours, open gaps, and the disk each part takes."""
from datetime import UTC, datetime, timedelta

from illumio_ops.services import data_status
from illumio_ops.store.flowdb import ingest_state
from tests.services.collect.conftest import configured_ctx

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


def test_lightweight_has_no_flows(tmp_path):
    c = configured_ctx(tmp_path, mode="lightweight")
    s = data_status.status(c, now=NOW)
    assert s.mode == "basic" and s.flows_latest is None and s.baseline_days is None and s.live_hours_days is None


def test_watermarks_and_gaps_listed(tmp_path):
    c = configured_ctx(tmp_path, mode="full")
    with c.flows().connect() as conn:
        ingest_state.mark_started(conn, "traffic", NOW)
        ingest_state.mark_ok(conn, "traffic", NOW, watermark=NOW - timedelta(minutes=20), rows=5)
        ingest_state.mark_started(conn, "events", NOW)
        ingest_state.mark_ok(conn, "events", NOW, watermark=NOW - timedelta(minutes=2), rows=1)
        ingest_state.record_gap(conn, "traffic", NOW - timedelta(hours=5), NOW - timedelta(hours=4), "failed",
                                detail="HTTP 503", at=NOW)
        conn.execute("INSERT INTO live_activity_hours (hour) VALUES (?), (?), (?)",
                     ("2026-11-02T10:00:00", "2026-11-02T11:00:00", "2026-11-03T09:00:00"))
        conn.commit()
    s = data_status.status(c, now=NOW)
    assert s.mode == "advanced"
    assert s.flows_latest == NOW - timedelta(minutes=20) and s.events_latest == NOW - timedelta(minutes=2)
    assert s.live_hours_days == 2 and s.baseline_target_days == c.settings.current().collection.retention.baseline_days
    assert [(g.source, g.kind) for g in s.gaps] == [("traffic", "failed")]


def test_disk_parts_sum_files(tmp_path):
    c = configured_ctx(tmp_path, mode="full")
    c.paths.reports_dir.mkdir(parents=True, exist_ok=True)
    (c.paths.reports_dir / "a.html").write_bytes(b"x" * 1000)
    (c.paths.reports_dir / "sub").mkdir()
    (c.paths.reports_dir / "sub" / "b.xlsx").write_bytes(b"y" * 500)
    parts = {p.name: p.bytes for p in data_status.status(c, now=NOW).disk}
    assert parts["reports"] == 1500 and parts["flows"] > 0 and parts["app"] > 0 and parts["archive"] == 0
