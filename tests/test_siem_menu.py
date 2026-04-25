import builtins
import json
import os
from unittest.mock import patch

import pytest

from src.config import ConfigManager


@pytest.fixture
def cm(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"siem": {"enabled": True, "destinations": []}}))
    return ConfigManager(config_file=str(p))


def _seq(values):
    it = iter(values)
    return lambda _p="": next(it)


def test_menu_list_empty(cm, capsys):
    from src.siem_cli import manage_siem_menu
    with patch.object(builtins, "input", _seq(["3", "", "0"])):
        manage_siem_menu(cm)
    assert "destinations" in capsys.readouterr().out.lower()


def test_menu_add_destination(cm):
    """Option 4: add minimal destination."""
    from src.siem_cli import manage_siem_menu
    inputs = ["4",
              "demo", "true", "udp", "cef", "127.0.0.1:514",
              "", "", "", "", "", "",   # tls_verify, tls_ca_bundle, hec_token, batch_size, source_types, max_retries
              "0"]
    with patch.object(builtins, "input", _seq(inputs)):
        manage_siem_menu(cm)
    cm.load()
    dests = cm.config.get("siem", {}).get("destinations", [])
    assert any(d.get("name") == "demo" for d in dests)
