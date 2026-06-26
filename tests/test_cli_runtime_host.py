"""The --host flag must reach launch_gui (loopback hardening must not be dropped).

run_gui_only() and run_daemon_with_gui() both accept a `host` parameter wired
from the `gui --host` / `monitor-gui --host` click options. If they call
launch_gui() without forwarding host, the GUI always binds 0.0.0.0 even when an
operator passes --host 127.0.0.1 — a silently ignored hardening step for a tool
holding PCE keys / SMTP / LINE tokens.
"""
import json
import os
import tempfile

from src.config import ConfigManager
from src.cli import _runtime


def _cm():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump({
            "web_gui": {"username": "a", "password": "p", "secret_key": "s"},
            "pce_cache": {"enabled": False, "db_path": "/tmp/_host_test.sqlite"},
        }, f)
    cm = ConfigManager(config_file=path)
    cm.load()
    os.unlink(path)
    return cm


def test_run_gui_only_forwards_host(monkeypatch):
    import src.gui
    captured = {}
    monkeypatch.setattr(src.gui, "HAS_FLASK", True)
    monkeypatch.setattr(src.gui, "launch_gui", lambda cm, **kw: captured.update(kw))

    _runtime.run_gui_only(_cm(), port=5050, host="127.0.0.1")

    assert captured.get("host") == "127.0.0.1", captured
    assert captured.get("port") == 5050, captured


def test_run_daemon_with_gui_forwards_host(monkeypatch):
    import src.gui
    captured = {}
    monkeypatch.setattr(src.gui, "HAS_FLASK", True)
    monkeypatch.setattr(src.gui, "launch_gui", lambda cm, **kw: captured.update(kw))
    # Keep the test from registering real signal handlers or starting the
    # background monitoring loop / scheduler.
    monkeypatch.setattr(_runtime, "_register_signals", lambda: None)
    monkeypatch.setattr(_runtime, "run_daemon_loop", lambda *a, **k: None)
    monkeypatch.setattr(src.gui, "_GUI_OWNS_DAEMON", False, raising=False)
    monkeypatch.setattr(src.gui, "_DAEMON_RESTART_FN", None, raising=False)

    _runtime.run_daemon_with_gui(_cm(), interval=5, port=5060, host="127.0.0.1")

    assert captured.get("host") == "127.0.0.1", captured
    assert captured.get("port") == 5060, captured
    assert captured.get("persistent_mode") is True, captured
