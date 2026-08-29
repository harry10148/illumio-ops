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

@pytest.mark.parametrize(("api_cfg", "expected"), [
    ({"deployment_type": "saas", "url": "https://ap-scp45.illum.io", "console_url": ""},
     "https://console.illum.io"),
    ({"deployment_type": "saas", "url": "https://poc3.illum.io:443",
      "console_url": "https://acme.illumio.ai/"}, "https://acme.illumio.ai"),
    ({"deployment_type": "on_prem", "url": "https://pce.lab:8443/api/v2", "console_url": ""},
     "https://pce.lab:8443"),
])
def test_resolve_pce_console_url(api_cfg, expected):
    from src.pce_target import resolve_pce_console_url
    assert resolve_pce_console_url(api_cfg) == expected


def test_deployment_and_console_url_are_not_pce_target_changes():
    from src.pce_target import pce_target_changed
    old = {
        "deployment_type": "on_prem",
        "console_url": "",
        "url": "https://pce.example.com:8443",
        "org_id": "1",
    }
    updated = {**old, "deployment_type": "saas", "console_url": "https://console.illum.io"}
    assert pce_target_changed(old, updated["url"], updated["org_id"]) is False


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
# normalization — the guard has to compare like with like (review M4)
# ---------------------------------------------------------------------------

def test_a_retyped_trailing_slash_is_not_a_target_change():
    """The stored value carries a trailing slash (nothing writes the validated
    model back, so config holds whatever was typed). Retyping the same PCE
    without it must not offer to destroy a cache that was fine."""
    from src.pce_target import pce_target_changed
    old = {"url": "https://pce.example.com:8443/", "org_id": "1"}
    assert pce_target_changed(old, "https://pce.example.com:8443", None) is False


def test_case_only_differences_in_scheme_and_host_are_not_a_target_change():
    from src.pce_target import pce_target_changed
    old = {"url": "https://pce.example.com:8443", "org_id": "1"}
    assert pce_target_changed(old, "HTTPS://PCE.Example.COM:8443", None) is False


def test_surrounding_whitespace_is_not_a_target_change():
    from src.pce_target import pce_target_changed
    old = {"url": "https://pce.example.com:8443", "org_id": "5"}
    assert pce_target_changed(old, "  https://pce.example.com:8443  ", " 5 ") is False


def test_normalization_leaves_the_path_and_a_real_host_change_alone():
    """Only the scheme and the host fold case — a path is case-sensitive to
    the server, and a different host is still a different PCE."""
    from src.pce_target import normalize_pce_url, pce_target_changed
    assert normalize_pce_url("HTTPS://Pce.Example.com:8443/API/v2/") == \
        "https://pce.example.com:8443/API/v2"
    old = {"url": "https://pce.example.com:8443", "org_id": "1"}
    assert pce_target_changed(old, "https://other.example.com:8443", None) is True


def test_login_stores_the_normalized_url_not_what_was_typed(runner):
    """Storing the raw string is what leaves the NEXT comparison wrong."""
    from src.cli.config import config_group
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, [
            "login",
            "--url", "  HTTPS://PCE.Example.COM:8443/  ",
            "--key", "k", "--secret", "s",
            "--no-interactive",
        ])
    assert result.exit_code == 0, result.output
    assert cm.config["api"]["url"] == "https://pce.example.com:8443"


# ---------------------------------------------------------------------------
# login_cmd — CLI plumbing
# ---------------------------------------------------------------------------

def _make_cm(url="https://pce.example.com:8443", org_id="1"):
    """Minimal mock ConfigManager whose .config is a real (mutable) dict,
    following the pattern in tests/test_cli_config_cmd.py's _make_cm()."""
    cm = MagicMock()
    cm.config = {
        "api": {"url": url, "org_id": org_id, "key": "oldkey", "secret": "oldsecret",
                "profile": "production", "verify_ssl": True,
                "deployment_type": "on_prem", "console_url": ""},
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


def test_no_interactive_rotation_without_org_id_leaves_org_id_alone(runner):
    """An absent --org-id means "unchanged", not "1" (review H3). On an org-5
    appliance a plain credential rotation used to be refused as a target
    change, and answering "same-pce" — the honest answer for a rotation —
    then silently moved it onto org 1 while keeping org 5's cache."""
    from src.cli.config import config_group
    cm = _make_cm(org_id="5")
    with patch("src.config.ConfigManager", return_value=cm):
        result = runner.invoke(config_group, [
            "login",
            "--url", "https://pce.example.com:8443",
            "--key", "rotated", "--secret", "rotated",
            "--no-interactive",
        ])
    assert result.exit_code == 0, result.output
    cm.save.assert_called_once()
    assert cm.config["api"]["org_id"] == "5"
    assert cm.config["api"]["key"] == "rotated"


def test_no_interactive_flush_tells_the_operator_to_restart_the_service(runner):
    """A headless --monitor daemon never reloads config, so it refills the
    tables that were just emptied. Nothing here can detect one — the
    instruction has to be in the output (review H2)."""
    from src.cli.config import config_group
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        with patch("src.pce_cache.flush.flush_pce_derived_state"):
            result = runner.invoke(config_group, [
                "login",
                "--url", "https://other-pce.example.com:8443",
                "--key", "k", "--secret", "s",
                "--no-interactive",
                "--pce-target-change", "flush",
            ])
    assert result.exit_code == 0, result.output
    from src.i18n import t
    assert t("cli_config_login_pce_restart_required") in result.output


def test_no_interactive_flush_failure_leaves_the_connection_unchanged(runner):
    """Flush before save (review M2): past the save the guard never fires for
    this edit again, so a clear that failed after it could never be
    completed. Failing before it costs a re-run instead."""
    from src.cli.config import config_group
    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        with patch("src.pce_cache.flush.flush_pce_derived_state",
                   side_effect=RuntimeError("cache is locked")):
            result = runner.invoke(config_group, [
                "login",
                "--url", "https://other-pce.example.com:8443",
                "--key", "k", "--secret", "s",
                "--no-interactive",
                "--pce-target-change", "flush",
            ])
    assert result.exit_code != 0
    cm.save.assert_not_called()


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


def test_no_interactive_runtime_fields_warn_without_target_guard_or_flush(runner):
    from src.cli.config import config_group
    from src.i18n import t

    cm = _make_cm()
    with patch("src.config.ConfigManager", return_value=cm):
        with patch("src.pce_cache.flush.flush_pce_derived_state") as mock_flush:
            result = runner.invoke(config_group, [
                "login",
                "--url", "https://pce.example.com:8443",
                "--key", "k", "--secret", "s",
                "--deployment-type", "saas",
                "--console-url", "https://console.illum.io",
                "--no-interactive",
            ])

    assert result.exit_code == 0, result.output
    assert t("cli_config_login_connection_restart_required") in result.output
    assert t("cli_config_login_pce_restart_required") not in result.output
    assert "cleared" not in result.output.lower()
    assert "refill" not in result.output.lower()
    mock_flush.assert_not_called()
    cm.save.assert_called_once()


# ---------------------------------------------------------------------------
# settings_menu() — interactive settings wizard, src/cli/menus/_root.py
# ---------------------------------------------------------------------------

def _make_menu_cm(url="https://pce.example.com:8443", org_id="1"):
    cm = MagicMock()
    cm.config = {
        "api": {"url": url, "org_id": org_id, "key": "oldkey", "secret": "oldsecret",
                "profile": "production", "verify_ssl": True,
                "deployment_type": "on_prem", "console_url": ""},
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


@pytest.mark.parametrize(("console_answer", "expected"), [
    ("", "https://console.illum.io"),
    ("https://tenant.illumio.example/", "https://tenant.illumio.example"),
])
def test_menu_saas_console_default_and_custom_are_atomic_runtime_edits(
    monkeypatch, capsys, console_answer, expected,
):
    cm = _make_menu_cm()
    answers = [
        1,
        "saas", console_answer,
        None, None, None, None,
        None,  # dismiss restart warning
        None,  # leave settings menu
    ]
    with patch("src.pce_cache.flush.flush_pce_derived_state") as mock_flush:
        _run_menu(monkeypatch, cm, answers)

    cm.save.assert_called_once()
    mock_flush.assert_not_called()
    assert cm.config["api"]["deployment_type"] == "saas"
    assert cm.config["api"]["console_url"] == expected
    from src.i18n import t
    output = capsys.readouterr().out
    assert t("cli_connection_restart_required_menu") in output
    assert t("cli_pce_restart_required_menu") not in output
    assert "cleared" not in output.lower()
    assert "refill" not in output.lower()


def test_menu_invalid_console_url_is_rejected_without_mutation_or_flush(
    monkeypatch, capsys,
):
    cm = _make_menu_cm()
    before = dict(cm.config["api"])
    answers = [
        1,
        "saas", "ftp://tenant.example.com",
        None, None, None, None,
        None,  # dismiss validation error
        None,  # leave settings menu
    ]

    with patch("src.pce_cache.flush.flush_pce_derived_state") as mock_flush:
        _run_menu(monkeypatch, cm, answers)

    from src.i18n import t
    output = capsys.readouterr().out
    prefix = t("cli_config_validation_failed", errors="").split(":", 1)[0]
    assert prefix in output
    assert "ftp://tenant.example.com" not in output
    cm.save.assert_not_called()
    mock_flush.assert_not_called()
    assert cm.config["api"] == before


@pytest.mark.parametrize("answers", [
    [1, None, None, None, None, None],
    [1, "saas", None, None, None, 2, None, None],
])
def test_menu_cancelling_either_new_prompt_abandons_the_whole_edit(
    monkeypatch, answers,
):
    cm = _make_menu_cm()
    before = dict(cm.config["api"])

    _run_menu(monkeypatch, cm, answers)

    cm.save.assert_not_called()
    assert cm.config["api"] == before


def test_menu_cancelling_target_change_abandons_whole_edit(monkeypatch):
    """Cancel (safe_input -> None) at the target-change question must not
    save anything, not even the url/key that were already typed."""
    cm = _make_menu_cm()
    answers = [
        1,                                     # select item 1
        "", "",                               # keep deployment / Console URL
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
        1, "", "", "https://other-pce.example.com:8443", None, None, None,
        2,      # same-pce
        None,   # dismiss the "restart the monitoring service" notice
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
        1, "", "", "https://other-pce.example.com:8443", None, None, None,
        1,      # flush
        None,   # dismiss the "restart the monitoring service" notice
        None,
    ]
    with patch("src.pce_cache.flush.flush_pce_derived_state") as mock_flush:
        _run_menu(monkeypatch, cm, answers)
    cm.save.assert_called_once()
    mock_flush.assert_called_once()
    args = mock_flush.call_args[0]
    assert args[0] == cm.models.pce_cache.db_path


def test_menu_target_change_warns_to_restart_the_monitoring_service(monkeypatch, capsys):
    cm = _make_menu_cm()
    answers = [
        1, "", "", "https://other-pce.example.com:8443", None, None, None,
        1, None, None,
    ]
    with patch("src.pce_cache.flush.flush_pce_derived_state"):
        _run_menu(monkeypatch, cm, answers)
    from src.i18n import t
    assert t("cli_pce_restart_required_menu") in capsys.readouterr().out


def test_menu_flush_failure_leaves_the_connection_unchanged(monkeypatch):
    """Same ordering rule as the other two paths (review M2)."""
    cm = _make_menu_cm()
    answers = [
        1, "", "", "https://other-pce.example.com:8443", None, None, None,
        1, None, None,
    ]
    with patch("src.pce_cache.flush.flush_pce_derived_state",
               side_effect=RuntimeError("cache is locked")):
        _run_menu(monkeypatch, cm, answers)
    cm.save.assert_not_called()
    assert cm.config["api"]["url"] == "https://pce.example.com:8443"


def test_menu_stores_the_normalized_url(monkeypatch):
    cm = _make_menu_cm()
    answers = [
        1, "", "", "  HTTPS://PCE.Example.COM:8443/  ", None, None, None,
        None,
    ]
    with patch("src.pce_cache.flush.flush_pce_derived_state") as mock_flush:
        _run_menu(monkeypatch, cm, answers)
    # Same PCE once normalized — no question, no flush, and the stored value
    # is the normalized one so the NEXT comparison is right too.
    mock_flush.assert_not_called()
    cm.save.assert_called_once()
    assert cm.config["api"]["url"] == "https://pce.example.com:8443"


def test_menu_rotating_credentials_only_saves_without_asking(monkeypatch):
    """Same url/org_id, only key/secret rotate — no target-change question."""
    cm = _make_menu_cm()
    answers = [
        1, "", "", None, None, "newkey", "newsecret",
        None,
    ]
    with patch("src.pce_cache.flush.flush_pce_derived_state") as mock_flush:
        _run_menu(monkeypatch, cm, answers)
    cm.save.assert_called_once()
    mock_flush.assert_not_called()
    assert cm.config["api"]["key"] == "newkey"
    assert cm.config["api"]["secret"] == "newsecret"
