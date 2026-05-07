"""Tests for illumio-ops report subcommands and legacy report dispatch."""
import json
import os
import sys
import types
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner


def test_report_audit_subcommand_dispatches_helper():
    from src.cli.root import cli

    runner = CliRunner()
    with patch("src.cli.report.generate_audit_report", return_value=["/tmp/audit.html"]) as mock_gen:
        result = runner.invoke(
            cli,
            ["report", "audit", "--start-date", "2026-04-01", "--end-date", "2026-04-02"],
        )

    assert result.exit_code == 0
    assert "/tmp/audit.html" in result.output
    mock_gen.assert_called_once_with(
        start_date="2026-04-01",
        end_date="2026-04-02",
        fmt="html",
        output_dir=None,
    )


def test_report_policy_usage_subcommand_dispatches_helper():
    from src.cli.root import cli

    runner = CliRunner()
    with patch("src.cli.report.generate_policy_usage_report", return_value=["/tmp/policy.html"]) as mock_gen:
        result = runner.invoke(
            cli,
            ["report", "policy-usage", "--source", "api", "--format", "csv"],
        )

    assert result.exit_code == 0
    assert "/tmp/policy.html" in result.output
    mock_gen.assert_called_once_with(
        source="api",
        file_path=None,
        start_date=None,
        end_date=None,
        fmt="csv",
        output_dir=None,
    )


def test_report_traffic_subcommand_has_no_detail_level_option():
    from src.cli.root import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["report", "traffic", "--help"])

    assert result.exit_code == 0
    assert "--detail-level" not in result.output


def test_legacy_report_help_has_no_detail_level_option(monkeypatch, capsys):
    import src.main as main_module

    monkeypatch.setattr(sys, "argv", ["illumio_ops.py", "--help"])

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 0
    assert "--detail-level" not in capsys.readouterr().out


def test_legacy_report_type_audit_dispatches(monkeypatch):
    import src.main as main_module

    called = {}

    class _FakeConfigManager:
        def __init__(self):
            self.config = {"logging": {}, "report": {}}

    class _FakeModuleLog:
        @staticmethod
        def init(*_args, **_kwargs):
            return None

    def _fake_audit_report(**kwargs):
        called["kwargs"] = kwargs
        return ["/tmp/audit.html"]

    monkeypatch.setattr(main_module, "setup_logger", lambda *a, **kw: None)
    monkeypatch.setattr(main_module, "ConfigManager", _FakeConfigManager)
    monkeypatch.setitem(sys.modules, "pandas", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "src.module_log", types.SimpleNamespace(ModuleLog=_FakeModuleLog))
    monkeypatch.setattr("src.cli.report.generate_audit_report", _fake_audit_report)
    monkeypatch.setattr(sys, "argv", ["illumio_ops.py", "--report", "--report-type", "audit"])

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 0
    assert called["kwargs"] == {"fmt": "html", "output_dir": None}


def test_report_traffic_json_output_shape(tmp_path):
    """--json flag emits [{output_path, type, size}] for each returned path."""
    from src.cli.root import cli

    # Create a real file so os.path.getsize succeeds
    fake_report = tmp_path / "report.html"
    fake_report.write_text("<html/>")

    runner = CliRunner()
    with patch("src.cli.report.generate_traffic_report", return_value=[str(fake_report)]):
        result = runner.invoke(
            cli,
            ["--json", "report", "traffic"],
        )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 1
    item = data[0]
    assert item["output_path"] == str(fake_report)
    assert item["type"] == "html"
    assert item["size"] == fake_report.stat().st_size


def test_report_audit_click_exception_exits_dataerr():
    """ClickException from generate_audit_report → exit code EXIT_DATAERR (65)."""
    from src.cli.root import cli
    from src.cli._exit_codes import EXIT_DATAERR

    runner = CliRunner()
    with patch(
        "src.cli.report.generate_audit_report",
        side_effect=click.ClickException("No data for report"),
    ):
        result = runner.invoke(
            cli,
            ["report", "audit"],
        )

    assert result.exit_code == EXIT_DATAERR
    assert "No data for report" in result.output
