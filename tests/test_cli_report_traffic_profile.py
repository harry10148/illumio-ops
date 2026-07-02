"""Phase 1: report traffic CLI produces the new traffic profile."""
from unittest.mock import patch
from click.testing import CliRunner

from src.cli.root import cli


def _invoke(args):
    runner = CliRunner()
    # Pin the CLI language: _ctx_lang() reads config/config.json, so without
    # this the deprecation-message assertion depends on the local config.
    with patch("src.cli.report.generate_traffic_report", return_value=["/tmp/x.html"]) as gen, \
            patch("src.cli.report._ctx_lang", return_value="en"):
        result = runner.invoke(cli, args)
    return result, gen


def test_bare_traffic_uses_traffic_profile():
    result, gen = _invoke(["report", "traffic"])
    assert result.exit_code == 0
    assert gen.call_args.kwargs["traffic_report_profile"] == "traffic"


def test_profile_flag_is_deprecated_but_honored():
    result, gen = _invoke(["report", "traffic", "--profile", "security_risk"])
    assert result.exit_code == 0
    assert gen.call_args.kwargs["traffic_report_profile"] == "security_risk"
    # Note: CliRunner defaults to mix_stderr=True, so result.stderr raises
    # ValueError. result.output already contains both streams in that mode.
    assert "deprecat" in result.output.lower()


def test_security_command_unchanged():
    runner = CliRunner()
    with patch("src.cli.report.generate_traffic_report", return_value=["/tmp/x.html"]) as gen:
        result = runner.invoke(cli, ["report", "security"])
    assert result.exit_code == 0
    assert gen.call_args.kwargs["traffic_report_profile"] == "security_risk"
