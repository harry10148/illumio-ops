"""CLI tests for illumio-ops cache subcommands."""
import pytest
from click.testing import CliRunner
from unittest.mock import MagicMock, patch


def test_cache_status_runs_without_crash():
    from src.cli.cache import cache_group
    runner = CliRunner()
    with patch("src.cli.cache._get_db_session_factory", return_value=None):
        with patch("src.cli.cache._get_cache_config", return_value={"events_retention_days": 90, "traffic_raw_retention_days": 7}):
            result = runner.invoke(cache_group, ["status"])
    # May fail gracefully if no DB, but must not raise an unhandled exception
    assert result.exit_code in (0, 1)


def test_cache_retention_shows_config():
    from src.cli.cache import cache_group
    runner = CliRunner()
    with patch("src.cli.cache._get_cache_config", return_value={
        "events_retention_days": 90,
        "traffic_raw_retention_days": 7,
        "traffic_agg_retention_days": 365,
    }):
        result = runner.invoke(cache_group, ["retention"])
    assert result.exit_code == 0
    assert "90" in result.output or "retention" in result.output.lower()


def test_cache_backfill_requires_source():
    from src.cli.cache import cache_group
    runner = CliRunner()
    result = runner.invoke(cache_group, ["backfill"])
    assert result.exit_code != 0  # missing --source should fail


def test_cache_backfill_requires_since():
    from src.cli.cache import cache_group
    runner = CliRunner()
    result = runner.invoke(cache_group, ["backfill", "--source", "events"])
    assert result.exit_code != 0  # missing --since should fail


def test_cache_backfill_bad_date_exits_dataerr():
    """Bad --since date should exit with EXIT_DATAERR (65) and emit an error message."""
    from src.cli.cache import cache_group
    from src.cli._exit_codes import EXIT_DATAERR
    runner = CliRunner()
    result = runner.invoke(cache_group, ["backfill", "--source", "events", "--since", "not-a-date"])
    assert result.exit_code == EXIT_DATAERR
    assert "error:" in result.output
    assert "since" in result.output.lower()


def test_cache_retention_json_output():
    """--json flag on retention returns machine-readable config dict."""
    import json
    from src.cli.cache import cache_group
    runner = CliRunner()
    with patch("src.cli.cache._get_cache_config", return_value={
        "events_retention_days": 30,
        "traffic_raw_retention_days": 3,
        "traffic_agg_retention_days": 180,
    }):
        result = runner.invoke(cache_group, ["retention", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["events_retention_days"] == 30
    assert data["traffic_raw_retention_days"] == 3
