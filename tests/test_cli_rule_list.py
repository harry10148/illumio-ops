"""Tests for illumio-ops rule list subcommand."""
import json
import pytest
from click.testing import CliRunner
from pathlib import Path
import os
from unittest.mock import patch


def _create_default_config(rules=None):
    """Helper to create a default config dict."""
    return {
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s", "verify_ssl": True},
        "alerts": {
            "active": ["mail"],
            "line_channel_access_token": "",
            "line_target_id": "",
            "webhook_url": ""
        },
        "email": {"sender": "monitor@localhost", "recipients": ["admin@example.com"]},
        "smtp": {"host": "localhost", "port": 25, "user": "", "password": "", "enable_auth": False, "enable_tls": False},
        "settings": {"language": "en", "theme": "light"},
        "rules": rules or [],
        "report": {
            "enabled": False,
            "schedule": "weekly",
            "day_of_week": "monday",
            "hour": 8,
            "source": "api",
            "format": ["html"],
            "email_report": False,
            "output_dir": "reports/",
            "retention_days": 30,
            "include_raw_data": False,
            "max_top_n": 20,
            "api_query": {
                "start_date": None,
                "end_date": None,
                "max_results": 200000
            }
        },
        "report_schedules": [],
        "pce_profiles": [],
        "active_pce_id": None,
        "rule_scheduler": {
            "enabled": True,
            "check_interval_seconds": 300
        },
        "web_gui": {
            "username": "illumio",
            "password_hash": "",
            "password_salt": "",
            "secret_key": "",
            "allowed_ips": [],
            "tls": {
                "enabled": False,
                "cert_file": "",
                "key_file": "",
                "self_signed": False
            }
        }
    }


def test_rule_list_no_rules():
    """Test rule list with empty rules list."""
    from src.cli.root import cli
    from src.config import ConfigManager

    config = _create_default_config(rules=[])

    with patch.object(ConfigManager, '__init__', lambda self, *args, **kwargs: None):
        with patch.object(ConfigManager, 'config', config, create=True):
            runner = CliRunner()
            result = runner.invoke(cli, ["rule", "list"])

    assert result.exit_code == 0
    assert "Monitoring Rules" in result.output
    assert "(0)" in result.output


def test_rule_list_shows_rules():
    """Test rule list displays configured rules."""
    from src.cli.root import cli
    from src.config import ConfigManager

    rules = [
        {"type": "event", "name": "login_fail", "enabled": True, "threshold": 5},
        {"type": "traffic", "name": "lateral_move", "enabled": False},
    ]
    config = _create_default_config(rules=rules)

    with patch.object(ConfigManager, '__init__', lambda self, *args, **kwargs: None):
        with patch.object(ConfigManager, 'config', config, create=True):
            runner = CliRunner()
            result = runner.invoke(cli, ["rule", "list"])

    assert result.exit_code == 0
    assert "login_fail" in result.output
    assert "lateral_move" in result.output
    assert "(2)" in result.output


def test_rule_list_filter_by_type():
    """Test --type filter for rule list."""
    from src.cli.root import cli
    from src.config import ConfigManager

    rules = [
        {"type": "event", "name": "evt_rule", "enabled": True},
        {"type": "traffic", "name": "trf_rule", "enabled": True},
    ]
    config = _create_default_config(rules=rules)

    with patch.object(ConfigManager, '__init__', lambda self, *args, **kwargs: None):
        with patch.object(ConfigManager, 'config', config, create=True):
            runner = CliRunner()
            result = runner.invoke(cli, ["rule", "list", "--type", "event"])

    assert result.exit_code == 0
    assert "evt_rule" in result.output
    assert "trf_rule" not in result.output
    assert "(1)" in result.output


def test_rule_list_enabled_only_filter():
    """Test --enabled-only flag for rule list."""
    from src.cli.root import cli
    from src.config import ConfigManager

    rules = [
        {"type": "event", "name": "enabled_rule", "enabled": True},
        {"type": "traffic", "name": "disabled_rule", "enabled": False},
    ]
    config = _create_default_config(rules=rules)

    with patch.object(ConfigManager, '__init__', lambda self, *args, **kwargs: None):
        with patch.object(ConfigManager, 'config', config, create=True):
            runner = CliRunner()
            result = runner.invoke(cli, ["rule", "list", "--enabled-only"])

    assert result.exit_code == 0
    assert "enabled_rule" in result.output
    assert "disabled_rule" not in result.output
    assert "(1)" in result.output


def test_rule_list_combined_filters():
    """Test combining --type and --enabled-only filters."""
    from src.cli.root import cli
    from src.config import ConfigManager

    rules = [
        {"type": "event", "name": "evt_enabled", "enabled": True},
        {"type": "event", "name": "evt_disabled", "enabled": False},
        {"type": "traffic", "name": "trf_enabled", "enabled": True},
    ]
    config = _create_default_config(rules=rules)

    with patch.object(ConfigManager, '__init__', lambda self, *args, **kwargs: None):
        with patch.object(ConfigManager, 'config', config, create=True):
            runner = CliRunner()
            result = runner.invoke(cli, ["rule", "list", "--type", "event", "--enabled-only"])

    assert result.exit_code == 0
    assert "evt_enabled" in result.output
    assert "evt_disabled" not in result.output
    assert "trf_enabled" not in result.output
    assert "(1)" in result.output


def test_rule_list_shows_threshold():
    """Test that rule thresholds are displayed."""
    from src.cli.root import cli
    from src.config import ConfigManager

    rules = [
        {"type": "event", "name": "test_rule", "enabled": True, "threshold": 42},
    ]
    config = _create_default_config(rules=rules)

    with patch.object(ConfigManager, '__init__', lambda self, *args, **kwargs: None):
        with patch.object(ConfigManager, 'config', config, create=True):
            runner = CliRunner()
            result = runner.invoke(cli, ["rule", "list"])

    assert result.exit_code == 0
    assert "42" in result.output
