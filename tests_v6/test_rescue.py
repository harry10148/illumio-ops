import fcntl
import json
import os

import pytest

from illumio_ops import rescue
from illumio_ops.paths import resolve_paths
from illumio_ops.settings.secrets import verify_password
from illumio_ops.settings.store import SettingsStore
from tests_v6.web.conftest import cached_hash


def _init(root, port=5001):
    paths = resolve_paths(root)
    paths.ensure_dirs()
    SettingsStore(paths.settings_file).create_initial(password_hash=cached_hash("illumio"),
                                                      secret_key="ab" * 32, port=port)
    return paths


def _passwords(monkeypatch, *answers):
    it = iter(answers)
    monkeypatch.setattr(rescue.getpass, "getpass", lambda prompt="": next(it))


def test_init_writes_port_and_refuses_existing(tmp_path, capsys):
    root = tmp_path / "fresh"
    assert rescue.main(["init", "--root", str(root), "--port", "5443"]) == 0
    s = SettingsStore(resolve_paths(root).settings_file).load()
    assert s.web.port == 5443 and verify_password("illumio", s.web.password_hash)
    before = resolve_paths(root).settings_file.read_bytes()
    assert rescue.main(["init", "--root", str(root), "--port", "6000"]) == 73
    assert resolve_paths(root).settings_file.read_bytes() == before


def test_init_on_fresh_root_without_data_dir(tmp_path):
    root = tmp_path / "nothing-here"
    assert rescue.main(["init", "--root", str(root)]) == 0
    assert resolve_paths(root).data_dir.is_dir()


def test_reset_password_refused_while_service_lock_held(tmp_path, monkeypatch, capsys):
    paths = _init(tmp_path)
    fd = os.open(paths.service_lock, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        _passwords(monkeypatch, "a-brand-new-pass", "a-brand-new-pass")
        assert rescue.main(["reset-password", "--root", str(tmp_path)]) == 75
    finally:
        os.close(fd)
    assert "stop" in capsys.readouterr().err.lower()


def test_reset_password_enforces_12_to_512_and_rotates_key(tmp_path, monkeypatch):
    paths = _init(tmp_path)
    _passwords(monkeypatch, "short", "short")
    assert rescue.main(["reset-password", "--root", str(tmp_path)]) == 65
    _passwords(monkeypatch, "a-brand-new-pass", "different-pass-1")
    assert rescue.main(["reset-password", "--root", str(tmp_path)]) == 65
    _passwords(monkeypatch, "a-brand-new-pass", "a-brand-new-pass")
    assert rescue.main(["reset-password", "--root", str(tmp_path)]) == 0
    s = SettingsStore(paths.settings_file).load()
    assert verify_password("a-brand-new-pass", s.web.password_hash) and s.web.secret_key != "ab" * 32


def test_check_settings_exit_codes(tmp_path, capsys):
    assert rescue.main(["check-settings", "--root", str(tmp_path / "none")]) == 66
    paths = _init(tmp_path)
    assert rescue.main(["check-settings", "--root", str(tmp_path)]) == 0
    d = json.loads(paths.settings_file.read_text())
    d["web"]["port"] = 0
    paths.settings_file.write_text(json.dumps(d))
    assert rescue.main(["check-settings", "--root", str(tmp_path)]) == 78
    assert "web.port" in capsys.readouterr().err


def test_rescue_prints_no_secret(tmp_path, monkeypatch, capsys):
    _init(tmp_path)
    _passwords(monkeypatch, "a-brand-new-pass", "a-brand-new-pass")
    rescue.main(["reset-password", "--root", str(tmp_path)])
    rescue.main(["check-settings", "--root", str(tmp_path)])
    out = capsys.readouterr()
    assert "a-brand-new-pass" not in out.out + out.err and "$argon2" not in out.out + out.err


@pytest.mark.parametrize("cmd", ["init", "check-settings"])
def test_rescue_refuses_while_service_runs(tmp_path, cmd):
    paths = _init(tmp_path)
    fd = os.open(paths.service_lock, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert rescue.main([cmd, "--root", str(tmp_path)]) == 75
    finally:
        os.close(fd)


def test_rescue_refuses_to_run_as_another_user_than_the_owner(tmp_path, monkeypatch, capsys):
    _init(tmp_path)
    monkeypatch.setattr(rescue.os, "geteuid", lambda: os.stat(tmp_path / "config").st_uid + 1)
    assert rescue.main(["check-settings", "--root", str(tmp_path)]) == 77
    assert "runuser" in capsys.readouterr().err
