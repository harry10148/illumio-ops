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


def test_workload_list_pick_non_tty_prints_hint_and_ignores(tmp_path, monkeypatch):
    """非 TTY（CliRunner 預設）+ --pick：印提示、忽略挑選，列出所有 workload（不掛）。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.json").write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
    }), encoding="utf-8")
    with patch("src.api_client.ApiClient", return_value=_make_mock_api()):
        from src.cli.root import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["workload", "list", "--pick"])
    assert result.exit_code == 0
    assert "web-server-01" in result.output
    assert "db-server-01" in result.output
    from src.i18n import t as i18n_t
    assert i18n_t("cli_wl_pick_non_tty_hint", lang=None) in result.output


def test_workload_list_pick_filters_by_selected_label(tmp_path, monkeypatch):
    """TTY 分支：pick_objects 選中 env=prod → 只保留帶該 label 的 workload。

    只 mock questionary（picker 的 TTY 邊界），不 stub pick_objects 本身——走真實
    候選載入 + 選擇邏輯，等同既有 test_cli_object_picker.py 的測試手法。
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.json").write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
    }), encoding="utf-8")
    mock_api = _make_mock_api()
    mock_api.get_all_labels.return_value = [
        {"key": "env", "value": "prod", "href": "/orgs/1/labels/1"},
        {"key": "env", "value": "dev", "href": "/orgs/1/labels/2"},
    ]
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    with patch("src.api_client.ApiClient", return_value=mock_api), \
         patch("questionary.select") as msel, patch("questionary.autocomplete") as mauto:
        msel.return_value.unsafe_ask.side_effect = ["label", "__done__"]
        mauto.return_value.unsafe_ask.side_effect = ["env=prod"]
        from src.cli.root import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["workload", "list", "--pick"])
    assert result.exit_code == 0
    assert "web-server-01" in result.output
    assert "db-server-01" not in result.output


def test_workload_list_pick_keyboard_interrupt_cancels_without_crashing(tmp_path, monkeypatch):
    """Ctrl-C（KeyboardInterrupt）在挑選中觸發 → 取消挑選，list 指令本身不中斷、顯示未過濾結果。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.json").write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
    }), encoding="utf-8")
    mock_api = _make_mock_api()
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    with patch("src.api_client.ApiClient", return_value=mock_api), \
         patch("questionary.select") as msel:
        msel.return_value.unsafe_ask.side_effect = KeyboardInterrupt
        from src.cli.root import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["workload", "list", "--pick"])
    assert result.exit_code == 0
    assert "web-server-01" in result.output
    assert "db-server-01" in result.output


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
