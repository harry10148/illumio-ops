"""Contract: preflight.sh must check the bundled Python's SQLite floor
(3.35.0, mirror of src/runtime_checks.MIN_SQLITE_VERSION) and report the
existing cache DB state on upgrades."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_preflight_checks_bundled_sqlite_floor():
    compact = (ROOT / "scripts" / "preflight.sh").read_text().replace(" ", "")
    assert "sqlite_version_info>=(3,35,0)" in compact
    assert "BundledSQLite" in compact  # pass/fail 標籤存在


def test_preflight_reports_existing_cache_db():
    src = (ROOT / "scripts" / "preflight.sh").read_text()
    assert "data/pce_cache.sqlite" in src
    assert "user_version" in src
