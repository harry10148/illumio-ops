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
    gen.assert_called_once_with(fmt="json", output_dir=str(tmp_path))


def test_report_resolve_empty_emits_note_not_silent(cli_runner, tmp_path):
    """0 resolvable rows → no files; CLI must say so (not exit 0 silently)."""
    mock_cm = MagicMock()
    mock_cm.config = {"settings": {"language": "en"}}
    with patch("src.cli.report.generate_policy_resolver_report", return_value=[]), \
         patch("src.config.ConfigManager", return_value=mock_cm):
        result = cli_runner.invoke(
            report_group,
            ["resolve", "--format", "all", "--output-dir", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output
    assert "resolvable" in result.stderr.lower()
