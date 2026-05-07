"""Tests for illumio-ops workload list subcommand."""
import json
import pytest
from click.testing import CliRunner
from unittest.mock import MagicMock, patch


_FAKE_WORKLOADS = [
    {
        "name": "web-server-01",
        "hostname": "web01.example.com",
        "enforcement_mode": "full",
        "labels": [{"key": "env", "value": "prod"}, {"key": "app", "value": "web"}],
        "interfaces": [{"address": "10.0.0.1"}],
        "os_id": "linux",
    },
    {
        "name": "db-server-01",
        "hostname": "db01.example.com",
        "enforcement_mode": "selective",
        "labels": [{"key": "env", "value": "dev"}, {"key": "app", "value": "db"}],
        "interfaces": [],
        "os_id": "linux",
    },
]


def _make_mock_api(workloads=None):
    api = MagicMock()
    api.search_workloads.return_value = workloads if workloads is not None else _FAKE_WORKLOADS
    api.fetch_managed_workloads.return_value = workloads if workloads is not None else _FAKE_WORKLOADS
    return api


def test_workload_list_basic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.json").write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
    }), encoding="utf-8")
    with patch("src.api_client.ApiClient", return_value=_make_mock_api()):
        from src.cli.root import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["workload", "list"])
    assert result.exit_code == 0
    assert "web-server-01" in result.output or "Workloads" in result.output


def test_workload_list_env_filter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.json").write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
    }), encoding="utf-8")
    with patch("src.api_client.ApiClient", return_value=_make_mock_api()):
        from src.cli.root import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["workload", "list", "--env", "prod"])
    assert result.exit_code == 0
    assert "web-server-01" in result.output
    assert "db-server-01" not in result.output


def test_workload_list_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.json").write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
    }), encoding="utf-8")
    with patch("src.api_client.ApiClient", return_value=_make_mock_api([])):
        from src.cli.root import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["workload", "list"])
    assert result.exit_code == 0
    assert "Workloads" in result.output


def test_workload_list_rejects_non_positive_limit():
    from src.cli.root import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["workload", "list", "--limit", "0"])

    assert result.exit_code != 0
    assert "Invalid value for '--limit'" in result.output


def test_workload_list_json_output(tmp_path, monkeypatch):
    """--json flag emits parseable JSON list of workloads."""
    import json
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.json").write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
    }), encoding="utf-8")
    with patch("src.api_client.ApiClient", return_value=_make_mock_api()):
        from src.cli.root import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "workload", "list"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["hostname"] == "web01.example.com"
    assert data[0]["index"] == 1


def test_workload_list_connection_error_exits_unavailable(tmp_path, monkeypatch):
    """ConnectionError from API exits with EXIT_UNAVAILABLE (69)."""
    import json
    from src.cli._exit_codes import EXIT_UNAVAILABLE
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.json").write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
    }), encoding="utf-8")
    failing_api = MagicMock()
    failing_api.search_workloads.side_effect = ConnectionError("refused")
    with patch("src.api_client.ApiClient", return_value=failing_api):
        from src.cli.root import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["workload", "list"])
    assert result.exit_code == EXIT_UNAVAILABLE
    assert "error:" in result.output
