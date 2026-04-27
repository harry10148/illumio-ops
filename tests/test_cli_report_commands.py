"""Tests for illumio-ops report subcommands and legacy report dispatch."""
import sys
import types
from unittest.mock import patch

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
