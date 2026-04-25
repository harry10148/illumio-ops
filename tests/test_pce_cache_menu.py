import builtins
import json
import os
from unittest.mock import patch

import pytest

from src.config import ConfigManager


@pytest.fixture
def cm(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({}))
    return ConfigManager(config_file=str(p))


def _seq(values):
    it = iter(values)
    return lambda _p="": next(it)


def test_menu_back_exits(cm, capsys):
    from src.pce_cache_cli import manage_pce_cache_menu
    with patch.object(builtins, "input", _seq(["0"])):
        manage_pce_cache_menu(cm)
    assert "PCE Cache Menu" in capsys.readouterr().out


def test_menu_edit_settings_persists(cm):
    """Option 2, accept defaults except events_retention_days=60."""
    from src.pce_cache_cli import manage_pce_cache_menu
    # Sequence: choose 2 → 9 prompts (enabled, db_path, events_retention_days,
    # traffic_raw_retention_days, traffic_agg_retention_days,
    # events_poll_interval_seconds, traffic_poll_interval_seconds,
    # rate_limit_per_minute, async_threshold_events) → then "0" to exit
    inputs = ["2", "", "", "60", "", "", "", "", "", "", "0"]
    with patch.object(builtins, "input", _seq(inputs)):
        manage_pce_cache_menu(cm)
    # Reload from disk to verify persistence
    cm2 = ConfigManager(config_file=cm.config_file)
    assert cm2.config.get("pce_cache", {}).get("events_retention_days") == 60


def test_menu_invalid_choice(cm, capsys):
    from src.pce_cache_cli import manage_pce_cache_menu
    with patch.object(builtins, "input", _seq(["99", "0"])):
        manage_pce_cache_menu(cm)
    out = capsys.readouterr().out.lower()
    assert "invalid" in out or "please" in out
