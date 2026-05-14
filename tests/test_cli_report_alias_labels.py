"""report --help should annotate aliases."""
from __future__ import annotations

from click.testing import CliRunner
from src.cli.root import cli


def test_generate_traffic_marked_as_alias():
    runner = CliRunner()
    result = runner.invoke(cli, ["report", "--help"])
    assert result.exit_code == 0
    assert "generate-traffic" in result.output
    line = next(l for l in result.output.splitlines() if "generate-traffic" in l)
    assert "alias of traffic" in line.lower(), (
        f"Expected '(alias of traffic)' on line: {line!r}"
    )


def test_generate_audit_marked_as_alias():
    runner = CliRunner()
    result = runner.invoke(cli, ["report", "--help"])
    assert result.exit_code == 0
    line = next(l for l in result.output.splitlines() if "generate-audit" in l)
    assert "alias of audit" in line.lower()


def test_generate_ven_status_marked_as_alias():
    runner = CliRunner()
    result = runner.invoke(cli, ["report", "--help"])
    assert result.exit_code == 0
    line = next(l for l in result.output.splitlines() if "generate-ven-status" in l)
    assert "alias of ven-status" in line.lower()


def test_generate_policy_usage_marked_as_alias():
    runner = CliRunner()
    result = runner.invoke(cli, ["report", "--help"])
    assert result.exit_code == 0
    line = next(l for l in result.output.splitlines() if "generate-policy-usage" in l)
    assert "alias of policy-usage" in line.lower()


def test_canonical_traffic_unmarked():
    runner = CliRunner()
    result = runner.invoke(cli, ["report", "--help"])
    lines = [l for l in result.output.splitlines() if l.lstrip().startswith("traffic")]
    assert lines, "Expected canonical 'traffic' subcommand line"
    assert "alias" not in lines[0].lower()


def test_canonical_audit_unmarked():
    runner = CliRunner()
    result = runner.invoke(cli, ["report", "--help"])
    lines = [l for l in result.output.splitlines() if l.lstrip().startswith("audit")]
    assert lines
    assert "alias" not in lines[0].lower()
