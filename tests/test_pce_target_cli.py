"""Task 9: extend the "changing which PCE this points at needs an explicit
decision" guard from POST /api/settings to the two CLI paths that also write
api.url / api.org_id directly.

Covers:
  - pce_target_changed(), the single predicate shared by the GUI and both
    CLI paths (src/pce_target.py).
  - `illumio-ops config login --no-interactive`: must refuse (non-zero exit,
    config untouched) when the target changes and no --pce-target-change
    flag was given; must proceed when one was given.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner


# ---------------------------------------------------------------------------
# pce_target_changed()
# ---------------------------------------------------------------------------

def test_changing_url_is_a_target_change():
    from src.pce_target import pce_target_changed
    old = {"url": "https://pce.example.com:8443", "org_id": "1"}
    assert pce_target_changed(old, "https://other.example.com:8443", None) is True


def test_changing_org_id_is_a_target_change():
    from src.pce_target import pce_target_changed
    old = {"url": "https://pce.example.com:8443", "org_id": "1"}
    assert pce_target_changed(old, None, "7") is True


def test_rotating_key_secret_only_is_not_a_target_change():
    """Neither url nor org_id is passed (both None) — nothing to compare."""
    from src.pce_target import pce_target_changed
    old = {"url": "https://pce.example.com:8443", "org_id": "1"}
    assert pce_target_changed(old, None, None) is False


def test_same_values_are_not_a_target_change():
    from src.pce_target import pce_target_changed
    old = {"url": "https://pce.example.com:8443", "org_id": "1"}
    assert pce_target_changed(old, "https://pce.example.com:8443", "1") is False


def test_none_means_not_provided_not_changed_to_empty():
    from src.pce_target import pce_target_changed
    old = {"url": "https://pce.example.com:8443", "org_id": "1"}
    # Explicit "" would be a change; None (not provided) must not be.
    assert pce_target_changed(old, "", None) is True
    assert pce_target_changed(old, None, None) is False


# ---------------------------------------------------------------------------
# login_cmd — CLI plumbing
# ---------------------------------------------------------------------------

def _make_cm(url="https://pce.example.com:8443", org_id="1"):
    """Minimal mock ConfigManager whose .config is a real (mutable) dict,
    following the pattern in tests/test_cli_config_cmd.py's _make_cm()."""
    cm = MagicMock()
    cm.config = {
        "api": {"url": url, "org_id": org_id, "key": "oldkey", "secret": "oldsecret",
                "profile": "production", "verify_ssl": True},
    }
    cm.config_file = "/fake/config.json"
    cm.models.pce_cache.db_path = "/fake/pce_cache.sqlite"
    return cm


@pytest.fixture
def runner():
    return CliRunner()


def test_no_interactive_target_change_without_flag_is_refused(runner):
    """The riskiest path: automation calling --no-interactive with a changed
    url/org_id and no explicit decision must fail loudly and write nothing."""
    from src.cli.config import config_group
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, [
            "login",
            "--url", "https://other-pce.example.com:8443",
            "--key", "k", "--secret", "s",
            "--no-interactive",
        ])
    assert result.exit_code != 0
    cm.save.assert_not_called()
    # Config must be left exactly as it was — not even mutated in-memory.
    assert cm.config["api"]["url"] == "https://pce.example.com:8443"


def test_no_interactive_target_change_with_same_pce_flag_saves(runner):
    from src.cli.config import config_group
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, [
            "login",
            "--url", "https://other-pce.example.com:8443",
            "--key", "k", "--secret", "s",
            "--no-interactive",
            "--pce-target-change", "same-pce",
        ])
    assert result.exit_code == 0, result.output
    cm.save.assert_called_once()
    assert cm.config["api"]["url"] == "https://other-pce.example.com:8443"


def test_no_interactive_target_change_with_flush_flag_flushes(runner):
    from src.cli.config import config_group
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        with patch("src.pce_cache.flush.flush_pce_derived_state") as mock_flush:
            result = runner.invoke(config_group, [
                "login",
                "--url", "https://other-pce.example.com:8443",
                "--key", "k", "--secret", "s",
                "--no-interactive",
                "--pce-target-change", "flush",
            ])
    assert result.exit_code == 0, result.output
    cm.save.assert_called_once()
    mock_flush.assert_called_once()
    args = mock_flush.call_args[0]
    assert args[0] == cm.models.pce_cache.db_path


def test_no_interactive_rotating_credentials_only_needs_no_flag(runner):
    """Same url/org_id, only key/secret rotate — must pass through untouched."""
    from src.cli.config import config_group
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, [
            "login",
            "--url", "https://pce.example.com:8443",
            "--key", "newkey", "--secret", "newsecret",
            "--org-id", "1",
            "--no-interactive",
        ])
    assert result.exit_code == 0, result.output
    cm.save.assert_called_once()
    assert cm.config["api"]["key"] == "newkey"


def test_no_interactive_unknown_choice_is_rejected(runner):
    from src.cli.config import config_group
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, [
            "login",
            "--url", "https://other-pce.example.com:8443",
            "--key", "k", "--secret", "s",
            "--no-interactive",
            "--pce-target-change", "bogus",
        ])
    assert result.exit_code != 0
    cm.save.assert_not_called()


def test_interactive_target_change_prompts_and_flushes_on_choice(runner):
    """Interactive mode without the flag must ask, not default to proceeding."""
    from src.cli.config import config_group
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        with patch("src.pce_cache.flush.flush_pce_derived_state") as mock_flush:
            result = runner.invoke(config_group, [
                "login",
                "--url", "https://other-pce.example.com:8443",
                "--key", "k",
                "--org-id", "1",
                # secret prompt (blank keeps existing) + pce-target-change prompt
            ], input="\nflush\n")
    assert result.exit_code == 0, result.output
    cm.save.assert_called_once()
    mock_flush.assert_called_once()


# ---------------------------------------------------------------------------
# settings_menu() — interactive settings wizard, src/cli/menus/_root.py
# ---------------------------------------------------------------------------

def _make_menu_cm(url="https://pce.example.com:8443", org_id="1"):
    cm = MagicMock()
    cm.config = {
        "api": {"url": url, "org_id": org_id, "key": "oldkey", "secret": "oldsecret",
                "verify_ssl": True},
        "email": {"sender": "alerts@example.com"},
        "alerts": {"active": ["mail"]},
        "smtp": {"host": "localhost", "port": 25, "enable_auth": False},
        "report": {"output_dir": "reports/", "retention_days": 30},
        "rule_scheduler": {"enabled": False},
    }
    cm.models.pce_cache.db_path = "/fake/pce_cache.sqlite"
    return cm


def _run_menu(monkeypatch, cm, answers):
    from src.cli.menus import _root as root_module
    it = iter(answers)
    monkeypatch.setattr(root_module.os, "system", lambda *a, **k: None)
    monkeypatch.setattr(root_module, "draw_panel", lambda *a, **k: None)
    monkeypatch.setattr(root_module, "safe_input", lambda *a, **k: next(it))
    root_module.settings_menu(cm)


def test_menu_cancelling_target_change_abandons_whole_edit(monkeypatch):
    """Cancel (safe_input -> None) at the target-change question must not
    save anything, not even the url/key that were already typed."""
    cm = _make_menu_cm()
    answers = [
        1,                                     # select item 1
        "https://other-pce.example.com:8443",  # new url (changed)
        None, None, None,                      # org_id/key/secret unchanged
        None,                                  # cancel the target-change question
        None,                                  # back out of the menu loop
    ]
    with patch("src.pce_cache.flush.flush_pce_derived_state") as mock_flush:
        _run_menu(monkeypatch, cm, answers)
    cm.save.assert_not_called()
    mock_flush.assert_not_called()
    assert cm.config["api"]["url"] == "https://pce.example.com:8443"


def test_menu_target_change_same_pce_saves_without_flush(monkeypatch):
    cm = _make_menu_cm()
    answers = [
        1, "https://other-pce.example.com:8443", None, None, None,
        2,      # same-pce
        None,
    ]
    with patch("src.pce_cache.flush.flush_pce_derived_state") as mock_flush:
        _run_menu(monkeypatch, cm, answers)
    cm.save.assert_called_once()
    mock_flush.assert_not_called()
    assert cm.config["api"]["url"] == "https://other-pce.example.com:8443"


def test_menu_target_change_flush_clears_cache(monkeypatch):
    cm = _make_menu_cm()
    answers = [
        1, "https://other-pce.example.com:8443", None, None, None,
        1,      # flush
        None,
    ]
    with patch("src.pce_cache.flush.flush_pce_derived_state") as mock_flush:
        _run_menu(monkeypatch, cm, answers)
    cm.save.assert_called_once()
    mock_flush.assert_called_once()
    args = mock_flush.call_args[0]
    assert args[0] == cm.models.pce_cache.db_path


def test_menu_rotating_credentials_only_saves_without_asking(monkeypatch):
    """Same url/org_id, only key/secret rotate — no target-change question."""
    cm = _make_menu_cm()
    answers = [
        1, None, None, "newkey", "newsecret",
        None,
    ]
    with patch("src.pce_cache.flush.flush_pce_derived_state") as mock_flush:
        _run_menu(monkeypatch, cm, answers)
    cm.save.assert_called_once()
    mock_flush.assert_not_called()
    assert cm.config["api"]["key"] == "newkey"
    assert cm.config["api"]["secret"] == "newsecret"
