import json
import os
import pytest
from pydantic import BaseModel, Field
from src.config import ConfigManager
from src.gui.settings_helpers import save_section


class _DemoModel(BaseModel):
    enabled: bool = False
    count: int = Field(default=1, ge=1, le=10)


@pytest.fixture
def cm(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({}))
    return ConfigManager(str(cfg_path))


def test_save_section_happy_path(cm):
    r = save_section(cm, "demo", {"enabled": True, "count": 5}, _DemoModel)
    assert r["ok"] is True and r["requires_restart"] is True
    cm.load()
    assert cm.config["demo"] == {"enabled": True, "count": 5}


def test_save_section_validation_error(cm):
    r = save_section(cm, "demo", {"enabled": True, "count": 999}, _DemoModel)
    assert r["ok"] is False and "count" in r["errors"]


def test_save_section_atomic_on_failure(cm):
    path = cm.config_file
    before = open(path).read()
    save_section(cm, "demo", {"count": -5}, _DemoModel)
    assert open(path).read() == before
