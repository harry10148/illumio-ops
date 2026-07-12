"""siem status/replay must only render the zero-count fallback for genuine
first-run states (db file absent). Schema mismatches must surface as errors —
previously any OperationalError silently rendered zeros (analysis 2026-07-12).
"""
import sqlite3
from types import SimpleNamespace

from click.testing import CliRunner
from sqlalchemy.exc import OperationalError

from src.cli._exit_codes import EXIT_SOFTWARE
from src.cli.root import cli
from src.cli.siem import _is_first_run_db_error


def _op_error(msg: str) -> OperationalError:
    return OperationalError(msg, None, Exception(msg))


def test_first_run_signatures_classified():
    assert _is_first_run_db_error(_op_error("no such table: siem_dispatch"))
    assert _is_first_run_db_error(_op_error("unable to open database file"))
    assert not _is_first_run_db_error(
        _op_error("no such column: siem_dispatch.destination")
    )
    assert not _is_first_run_db_error(_op_error("database disk image is malformed"))


class _StubCM:
    def __init__(self, db_path: str):
        self.models = SimpleNamespace(
            pce_cache=SimpleNamespace(db_path=db_path),
            siem=SimpleNamespace(destinations=[]),
        )


def test_status_surfaces_schema_mismatch(tmp_path, monkeypatch):
    # 造一張缺欄位的 siem_dispatch 舊表，並讓 init_schema 不修它，
    # 模擬「schema 異常但兜底把它吞掉」的原始情境。
    db = tmp_path / "stale.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE siem_dispatch (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    monkeypatch.setattr("src.config.ConfigManager", lambda: _StubCM(str(db)))
    monkeypatch.setattr("src.pce_cache.schema.init_schema", lambda engine: None)

    result = CliRunner().invoke(cli, ["siem", "status"])
    assert result.exit_code == EXIT_SOFTWARE
    assert "no such column" in result.output


def test_status_zero_fallback_when_db_absent(tmp_path, monkeypatch):
    db = tmp_path / "nonexistent-dir" / "cache.sqlite"  # 目錄不存在 → 開檔失敗
    monkeypatch.setattr("src.config.ConfigManager", lambda: _StubCM(str(db)))

    result = CliRunner().invoke(cli, ["siem", "status"])
    assert result.exit_code == 0  # 首次執行情境維持原有的優雅降級
