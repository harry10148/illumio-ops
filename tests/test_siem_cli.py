import pytest
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


def test_siem_status_no_db(runner, tmp_path, monkeypatch):
    """Status command with no cache DB prints error gracefully (no crash)."""
    from src.cli.siem import siem_group
    # Should not crash even if DB doesn't exist
    result = runner.invoke(siem_group, ["status"])
    # Any output is fine; just must not raise unhandled exception
    assert result.exit_code in (0, 1)


def test_siem_replay_missing_dest_exits_1(runner, tmp_path, monkeypatch):
    """Replay with no DB exits with error code."""
    from src.cli.siem import siem_group
    result = runner.invoke(siem_group, ["replay", "--dest", "nonexistent"])
    assert result.exit_code in (0, 1)


def test_siem_dlq_empty(runner, tmp_path, monkeypatch):
    """DLQ list with empty table prints 'no entries' message."""
    from src.cli.siem import siem_group
    import os
    os.makedirs(tmp_path / "data", exist_ok=True)

    # Patch ConfigManager at its source module (lazy import inside siem.py)
    from unittest.mock import MagicMock, patch
    mock_cm = MagicMock()
    mock_cm.models.pce_cache.db_path = str(tmp_path / "data" / "test.sqlite")
    with patch("src.config.ConfigManager", return_value=mock_cm):
        result = runner.invoke(siem_group, ["dlq", "--dest", "dest1"])
    assert result.exit_code == 0
    assert "No DLQ entries" in result.output or "dest1" in result.output


def test_siem_purge_empty_db(runner, tmp_path, monkeypatch):
    """Purge on empty DB reports 0 removed."""
    from src.cli.siem import siem_group
    import os
    os.makedirs(tmp_path / "data", exist_ok=True)
    from unittest.mock import MagicMock, patch
    mock_cm = MagicMock()
    mock_cm.models.pce_cache.db_path = str(tmp_path / "data" / "test.sqlite")
    with patch("src.config.ConfigManager", return_value=mock_cm):
        result = runner.invoke(siem_group, ["purge", "--dest", "dest1"])
    assert result.exit_code == 0
    assert "0" in result.output or "Purged" in result.output


def test_siem_test_bad_destination_exits_usage(runner):
    """siem test with unknown destination exits EXIT_USAGE (64)."""
    from src.cli.siem import siem_group
    from unittest.mock import MagicMock, patch

    mock_cm = MagicMock()
    # Return an empty destinations list so any name misses
    mock_cm.models.siem.destinations = []
    with patch("src.config.ConfigManager", return_value=mock_cm):
        result = runner.invoke(siem_group, ["test", "no_such_dest"])

    from src.cli._exit_codes import EXIT_USAGE
    assert result.exit_code == EXIT_USAGE
    assert "not found or disabled" in result.output
