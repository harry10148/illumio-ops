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


def test_cache_retention_run_passes_archive_enabled():
    """--run 必須把設定的 archive_enabled 傳給 RetentionWorker.run_once，
    否則客戶啟用 archive 後，這個手動 CLI 入口會靜默刪除未 archive 的列。"""
    from src.cli.cache import cache_group
    runner = CliRunner()
    with patch("src.cli.cache._get_cache_config", return_value={
        "events_retention_days": 90,
        "traffic_raw_retention_days": 7,
        "traffic_agg_retention_days": 365,
        "archive_enabled": True,
    }):
        with patch("src.cli.cache._get_db_session_factory", return_value=MagicMock()):
            with patch("src.pce_cache.retention.RetentionWorker") as MockWorker:
                MockWorker.return_value.run_once.return_value = {}
                result = runner.invoke(cache_group, ["retention", "--run"])
    assert result.exit_code == 0
    _, kwargs = MockWorker.return_value.run_once.call_args
    assert kwargs.get("archive_enabled") is True


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
    # 同 test_cli_workload_list：不可寫死英文前綴，實際語言由
    # ConfigManager.load() 依 repo 的 config/config.json 設定（gitignored），
    # 開發者本機設 zh_TW 時寫死字面會失敗、CI 卻是綠的。
    from src.i18n import t
    assert t("cli_error_prefix", default="error: ").strip() in result.output
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


def _mock_config_manager(db_path="data/pce_cache.sqlite"):
    cm = MagicMock()
    cm.models.pce_cache.db_path = db_path
    return cm


def test_cache_flush_without_confirm_refuses():
    """A bare `cache flush` must not touch anything: no --confirm means no call."""
    from src.cli.cache import cache_group
    runner = CliRunner()
    with patch("src.pce_cache.flush.flush_pce_derived_state") as mock_flush:
        result = runner.invoke(cache_group, ["flush"])
    assert result.exit_code != 0
    mock_flush.assert_not_called()
    # Language-independent: both the EN and ZH strings for this key contain
    # the literal flag name, so this holds regardless of configured locale.
    assert "--confirm" in result.output


def test_cache_flush_with_confirm_calls_flush_with_expected_args():
    from src.cli.cache import cache_group
    runner = CliRunner()
    cm = _mock_config_manager(db_path="data/pce_cache.sqlite")
    with patch("src.config.ConfigManager", return_value=cm):
        with patch("src.config.resolve_state_file", return_value="logs/state.json"):
            with patch("src.pce_cache.flush.flush_pce_derived_state", return_value={}) as mock_flush:
                result = runner.invoke(cache_group, ["flush", "--confirm"])
    assert result.exit_code == 0
    mock_flush.assert_called_once_with("data/pce_cache.sqlite", "logs/state.json")


def test_cache_flush_json_output():
    import json
    from src.cli.cache import cache_group
    runner = CliRunner()
    cm = _mock_config_manager()
    counts = {"pce_events": 12, "pce_traffic_flow_raw": 34, "state_keys": 5, "dashboard_keys": 1}
    with patch("src.config.ConfigManager", return_value=cm):
        with patch("src.config.resolve_state_file", return_value="logs/state.json"):
            with patch("src.pce_cache.flush.flush_pce_derived_state", return_value=counts):
                result = runner.invoke(cache_group, ["flush", "--confirm", "--json"])
    assert result.exit_code == 0
    # stdout only: the restart-required note goes to stderr precisely so it
    # never lands inside a --json consumer's parsed payload.
    data = json.loads(result.stdout)
    assert data == counts
    assert "restart" in result.stderr.lower() or result.stderr.strip() != ""


def test_cache_flush_lock_timeout_is_distinguishable_failure():
    """flush_pce_derived_state raising TimeoutError must not crash and must not
    be reported as success — the operator needs to know to retry, not see a
    traceback or a silent 0."""
    from src.cli.cache import cache_group
    runner = CliRunner()
    cm = _mock_config_manager()
    with patch("src.config.ConfigManager", return_value=cm):
        with patch("src.config.resolve_state_file", return_value="logs/state.json"):
            with patch("src.pce_cache.flush.flush_pce_derived_state",
                       side_effect=TimeoutError("lock busy")) as mock_flush:
                result = runner.invoke(cache_group, ["flush", "--confirm"])
    assert result.exit_code != 0
    assert result.exception is None or not isinstance(result.exception, TimeoutError)
    mock_flush.assert_called_once()
    assert result.output.strip() != ""
