"""run_gui_only must warn when PCE cache is enabled.

GUI-only mode starts no scheduler, so cache ingestion/aggregation/retention never
fire automatically. A cache-enabled deploy on the `gui` command would silently get
no live data — the warning is the guard against that. (The systemd unit uses
`monitor-gui`, which DOES run the scheduler; this protects the other entrypoint.)
"""
import json
import os
import tempfile

from loguru import logger

from src.config import ConfigManager
from src.cli import _runtime


def _cm(enabled):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump({
            "web_gui": {"username": "a", "password": "p", "secret_key": "s"},
            "pce_cache": {"enabled": enabled, "db_path": "/tmp/_gui_only_test.sqlite"},
        }, f)
    cm = ConfigManager(config_file=path)
    cm.load()
    os.unlink(path)
    return cm


def _run_capture(cm, monkeypatch):
    import src.gui
    monkeypatch.setattr(src.gui, "launch_gui", lambda *a, **k: None)
    msgs = []
    sink = logger.add(lambda m: msgs.append(str(m)), level="WARNING")
    try:
        _runtime.run_gui_only(cm)
    finally:
        logger.remove(sink)
    return msgs


def test_gui_only_warns_when_cache_enabled(monkeypatch):
    msgs = _run_capture(_cm(True), monkeypatch)
    assert any("GUI-only mode" in m and "cache" in m.lower() for m in msgs), msgs


def test_gui_only_quiet_when_cache_disabled(monkeypatch):
    msgs = _run_capture(_cm(False), monkeypatch)
    assert not any("GUI-only mode" in m for m in msgs), msgs
