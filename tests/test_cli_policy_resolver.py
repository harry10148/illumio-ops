"""Tests for the `report resolve` CLI command."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from src.cli.report import report_group


def test_report_resolve_invokes_generator(tmp_path):
    runner = CliRunner()
    with patch("src.cli.report.generate_policy_resolver_report") as gen:
        gen.return_value = [str(tmp_path / "out.json")]
        (tmp_path / "out.json").write_text("{}")
        result = runner.invoke(
            report_group,
            ["resolve", "--format", "json", "--output-dir", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output
    gen.assert_called_once()
