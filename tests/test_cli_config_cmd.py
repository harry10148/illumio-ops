"""CLI tests for `illumio-ops config` subcommands (Track B Task 6)."""
from __future__ import annotations

import json
import pytest
from click.testing import CliRunner

from src.cli.config import config_group
from src.cli._exit_codes import EXIT_NOINPUT, EXIT_USAGE


@pytest.fixture
def runner():
    return CliRunner()


def test_validate_missing_file_exits_noinput(runner, tmp_path):
    """validate with a non-existent file must exit EXIT_NOINPUT (66)."""
    missing = str(tmp_path / "does_not_exist.json")
    result = runner.invoke(config_group, ["validate", "--file", missing])
    assert result.exit_code == EXIT_NOINPUT
    assert "not found" in result.output.lower() or "not found" in result.output


def test_validate_malformed_json_exits_dataerr(runner, tmp_path):
    """validate on a file with invalid JSON must exit EXIT_DATAERR (65)."""
    from src.cli._exit_codes import EXIT_DATAERR
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{ this is not json", encoding="utf-8")
    result = runner.invoke(config_group, ["validate", "--file", str(bad_file)])
    assert result.exit_code == EXIT_DATAERR
    assert "Malformed" in result.output or "malformed" in result.output.lower()


def test_show_unknown_section_exits_usage(runner, tmp_path):
    """show --section with unknown key must exit EXIT_USAGE (64)."""
    from unittest.mock import MagicMock, patch

    mock_cm = MagicMock()
    mock_cm.config = {"api": {"url": "https://pce.test"}, "settings": {}}

    with patch("src.config.ConfigManager", return_value=mock_cm):
        result = runner.invoke(config_group, ["show", "--section", "no_such_section"])

    assert result.exit_code == EXIT_USAGE
    assert "Unknown section" in result.output


def test_show_section_api_emits_parseable_json(runner, tmp_path):
    """show --section api must emit valid JSON to stdout."""
    from unittest.mock import MagicMock, patch

    api_data = {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"}
    mock_cm = MagicMock()
    mock_cm.config = {"api": api_data, "settings": {}}

    with patch("src.config.ConfigManager", return_value=mock_cm):
        result = runner.invoke(config_group, ["show", "--section", "api"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["url"] == "https://pce.test"
