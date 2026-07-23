"""Snapshot store: KPI-only JSON files in reports/snapshots/<type>/<YYYY-MM-DD>.json."""
import json
from datetime import datetime, timezone

import pytest

from src.report.snapshot_store import (
    write_snapshot, read_latest, list_snapshots, cleanup_old, SCHEMA_VERSION,
)


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("src.report.snapshot_store._BASE_DIR", str(tmp_path))
    return tmp_path


def _make_snapshot(date_str: str, profile: str = "security_risk", **kpi_overrides):
    base_kpis = {
        "microsegmentation_maturity": 0.62,
        "active_allow_coverage": 0.71,
        "pb_uncovered_exposure": 1234,
        "blocked_flows": 87,
        "high_risk_lateral_paths": 14,
        "top_remediation_action": {"code": "QUARANTINE", "count": 3},
    }
    base_kpis.update(kpi_overrides)
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "traffic",
        "profile": profile,
        "generated_at": f"{date_str}T08:00:00Z",
        "query_window": {"start": "2026-04-18", "end": date_str},
        "kpis": base_kpis,
        "policy_changes_since_previous": [],
    }


def test_write_then_read_latest(store_dir):
    snap = _make_snapshot("2026-04-25")
    write_snapshot("traffic", snap)
    latest = read_latest("traffic", profile="security_risk")
    assert latest is not None
    assert latest["kpis"]["pb_uncovered_exposure"] == 1234


def test_read_latest_returns_none_when_empty(store_dir):
    assert read_latest("traffic", profile="security_risk") is None


def test_list_snapshots_sorted_desc(store_dir):
    write_snapshot("traffic", _make_snapshot("2026-04-23"))
    write_snapshot("traffic", _make_snapshot("2026-04-25"))
    write_snapshot("traffic", _make_snapshot("2026-04-24"))
    items = list_snapshots("traffic", profile="security_risk")
    dates = [it["generated_at"][:10] for it in items]
    assert dates == ["2026-04-25", "2026-04-24", "2026-04-23"]


def test_same_date_overwrites(store_dir):
    write_snapshot("traffic", _make_snapshot("2026-04-25", pb_uncovered_exposure=100))
    write_snapshot("traffic", _make_snapshot("2026-04-25", pb_uncovered_exposure=200))
    latest = read_latest("traffic", profile="security_risk")
    assert latest["kpis"]["pb_uncovered_exposure"] == 200


def test_cleanup_old_respects_retention(store_dir):
    write_snapshot("traffic", _make_snapshot("2026-01-01"))
    write_snapshot("traffic", _make_snapshot("2026-04-25"))
    removed = cleanup_old("traffic", retention_days=30, today=datetime(2026, 4, 25, tzinfo=timezone.utc))
    items = list_snapshots("traffic", profile="security_risk")
    assert len(items) == 1
    assert items[0]["generated_at"].startswith("2026-04-25")
    assert removed == 1


def test_read_latest_filters_by_profile(store_dir):
    write_snapshot("traffic", _make_snapshot("2026-04-25", profile="security_risk", pb_uncovered_exposure=111))
    write_snapshot("traffic", _make_snapshot("2026-04-25", profile="network_inventory", pb_uncovered_exposure=999))
    sec = read_latest("traffic", profile="security_risk")
    net = read_latest("traffic", profile="network_inventory")
    assert sec["kpis"]["pb_uncovered_exposure"] == 111
    assert net["kpis"]["pb_uncovered_exposure"] == 999


def test_corrupt_snapshot_logged_not_silently_skipped(store_dir):
    """損毀的 snapshot 檔被跳過時必須記 warning——否則 read_latest 靜默
    回較舊快照，過期資料被當成當前資料。"""
    from loguru import logger as _logger
    from src.report.snapshot_store import _dir_for
    write_snapshot("traffic", _make_snapshot("2026-07-01"))
    corrupt = _dir_for("traffic") / "2026-07-02.json"
    corrupt.write_text("{not json")
    records = []
    sink_id = _logger.add(lambda m: records.append(m), level="WARNING")
    try:
        latest = read_latest("traffic")
    finally:
        _logger.remove(sink_id)
    assert latest is not None
    assert latest["generated_at"].startswith("2026-07-01")
    assert any("corrupt snapshot" in str(m) for m in records)
