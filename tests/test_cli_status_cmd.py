"""Tests for illumio-ops status command."""
import json
import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock


def _make_config():
    return {
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "settings": {"language": "en"},
        "rules": [{"type": "event", "name": "r1"}],
    }


def test_status_default_output():
    """Default output shows rich table with PCE URL."""
    from src.cli.root import cli
    from src.config import ConfigManager

    config = _make_config()
    with patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None):
        with patch.object(ConfigManager, 'config', config, create=True):
            runner = CliRunner()
            result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0
    assert "https://pce.test" in result.output
    assert "illumio-ops status" in result.output


def test_status_json_output():
    """--json flag emits parseable JSON object."""
    from src.cli.root import cli
    from src.config import ConfigManager

    config = _make_config()
    with patch.object(ConfigManager, '__init__', lambda self, *a, **kw: None):
        with patch.object(ConfigManager, 'config', config, create=True):
            runner = CliRunner()
            result = runner.invoke(cli, ["--json", "status"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["pce_url"] == "https://pce.test"
    assert data["language"] == "en"
    assert data["rules"] == 1
    assert "last_log_activity" in data
