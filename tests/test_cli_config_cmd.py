"""CLI tests for `illumio-ops config` subcommands (Track B Task 6)."""
from __future__ import annotations

import json
import pytest
from click.testing import CliRunner

from src.cli.config import config_group
from src.cli._exit_codes import EXIT_NOINPUT, EXIT_USAGE, EXIT_DATAERR, EXIT_CONFIG


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


# ---------------------------------------------------------------------------
# config set tests
# ---------------------------------------------------------------------------

def _make_cm(api_url="https://pce.test:8443"):
    """Return a minimal mock ConfigManager whose .config is a real dict."""
    from unittest.mock import MagicMock
    cm = MagicMock()
    cm.config = {
        "api": {"url": api_url, "org_id": "1", "key": "", "secret": "",
                "profile": "production", "verify_ssl": True},
        "smtp": {"host": "localhost", "port": 25, "user": "", "password": "",
                 "enable_auth": False, "enable_tls": False},
        "settings": {"language": "en", "theme": "light", "timezone": "local",
                     "enable_health_check": True, "dashboard_queries": []},
        "web_gui": {"username": "illumio", "password": "", "secret_key": "",
                    "allowed_ips": [], "must_change_password": False,
                    "tls": {"enabled": True, "cert_file": "", "key_file": "",
                            "self_signed": True, "auto_renew": True,
                            "auto_renew_days": 30, "min_version": "TLSv1.2",
                            "ciphers": None, "key_algorithm": "ecdsa-p256",
                            "validity_days": 397}},
    }
    cm.config_file = "/fake/config.json"
    return cm


def test_config_set_api_url(runner):
    from unittest.mock import patch
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, ["set", "api.url", "https://new.pce:8443"])
    assert result.exit_code == 0
    cm.save.assert_called_once()
    assert cm.config["api"]["url"] == "https://new.pce:8443"


def test_config_set_unknown_section_exits_usage(runner):
    from unittest.mock import patch
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, ["set", "no_such_section.field", "x"])
    assert result.exit_code == EXIT_USAGE


def test_config_set_invalid_url_exits_config(runner):
    from unittest.mock import patch
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, ["set", "api.url", "ftp://bad"])
    assert result.exit_code == EXIT_CONFIG


def test_config_set_invalid_field_exits_usage(runner):
    from unittest.mock import patch
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, ["set", "api.nonexistent", "x"])
    assert result.exit_code == EXIT_USAGE


def test_config_set_bool_coercion(runner):
    from unittest.mock import patch
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, ["set", "smtp.enable_auth", "true"])
    assert result.exit_code == 0
    assert cm.config["smtp"]["enable_auth"] is True


def test_config_set_json_output(runner):
    import json as _json
    from unittest.mock import patch
    from src.cli.root import cli
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(cli, ["--json", "config", "set", "api.org_id", "5"])
    assert result.exit_code == 0
    parsed = _json.loads(result.output)
    assert parsed["key"] == "api.org_id"
    assert parsed["value"] == "5"
    assert parsed["saved"] is True


def test_config_set_secret_redacted_in_output(runner):
    from unittest.mock import patch
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, ["set", "api.key", "my-secret-key"])
    assert result.exit_code == 0
    assert "my-secret-key" not in result.output
    assert "[REDACTED]" in result.output


def test_config_set_bad_format_no_dot_exits_usage(runner):
    from unittest.mock import patch
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, ["set", "nodotkey", "x"])
    assert result.exit_code == EXIT_USAGE


# ---------------------------------------------------------------------------
# config login tests
# ---------------------------------------------------------------------------

def test_config_login_non_interactive_sets_all_fields(runner):
    """--no-interactive with all options sets api fields and saves."""
    from unittest.mock import patch
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, [
            "login",
            "--url", "https://pce.prod:8443",
            "--key", "mykey",
            "--secret", "mysecret",
            "--org-id", "3",
            "--no-interactive",
        ])
    assert result.exit_code == 0
    assert cm.config["api"]["url"] == "https://pce.prod:8443"
    assert cm.config["api"]["key"] == "mykey"
    assert cm.config["api"]["secret"] == "mysecret"
    assert cm.config["api"]["org_id"] == "3"
    cm.save.assert_called_once()


def test_config_login_invalid_url_exits_config(runner):
    """--url with bad scheme should exit EXIT_CONFIG."""
    from unittest.mock import patch
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, [
            "login",
            "--url", "ftp://bad",
            "--key", "k",
            "--secret", "s",
            "--no-interactive",
        ])
    assert result.exit_code == EXIT_CONFIG


def test_config_login_json_output(runner):
    import json as _json
    from unittest.mock import patch
    from src.cli.root import cli
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(cli, [
            "--json", "config", "login",
            "--url", "https://pce.test:8443",
            "--key", "k",
            "--secret", "s",
            "--no-interactive",
        ])
    assert result.exit_code == 0
    parsed = _json.loads(result.output)
    assert parsed["saved"] is True
    assert parsed["url"] == "https://pce.test:8443"
    assert parsed["org_id"] == "1"


def test_config_login_missing_required_opts_exits_usage(runner):
    """--no-interactive without --url should exit EXIT_USAGE."""
    from unittest.mock import patch
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, [
            "login",
            "--key", "k",
            "--secret", "s",
            "--no-interactive",
        ])
    assert result.exit_code == EXIT_USAGE
