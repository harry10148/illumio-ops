import json
import threading

import pytest

from illumio_ops.settings.store import SettingsConflict, SettingsInvalid, SettingsStore

from .conftest import HASH, KEY


def _locs(e):
    return [loc for loc, _ in e.value.errors]


def test_load_missing_file_raises_and_creates_nothing(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    with pytest.raises(FileNotFoundError):
        store.load()
    assert not (tmp_path / "settings.json").exists()


def test_load_invalid_never_writes(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"schema_version": 1, "bogus": 1}')
    before = p.read_bytes()
    with pytest.raises(SettingsInvalid) as e:
        SettingsStore(p).load()
    assert "bogus" in _locs(e)
    assert p.read_bytes() == before


def test_load_bad_json_is_invalid(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"schema_version": 1,')
    with pytest.raises(SettingsInvalid):
        SettingsStore(p).load()


def test_load_missing_field_is_invalid_not_defaulted(settings_file):
    d = json.loads(settings_file.read_text())
    del d["web"]["port"]
    del d["schema_version"]
    settings_file.write_text(json.dumps(d))
    with pytest.raises(SettingsInvalid) as e:
        SettingsStore(settings_file).load()
    assert {"web.port", "schema_version"} <= set(_locs(e))


def test_load_nested_unknown_key_is_invalid(settings_file):
    d = json.loads(settings_file.read_text())
    d["web"]["tls"]["bogus"] = 1
    settings_file.write_text(json.dumps(d))
    with pytest.raises(SettingsInvalid) as e:
        SettingsStore(settings_file).load()
    assert "web.tls.bogus" in _locs(e)


def test_future_schema_version_is_invalid(settings_file):
    d = json.loads(settings_file.read_text())
    d["schema_version"] = 2
    settings_file.write_text(json.dumps(d))
    with pytest.raises(SettingsInvalid) as e:
        SettingsStore(settings_file).load()
    assert "schema_version" in _locs(e)


def test_invalid_error_message_never_echoes_secret(settings_file):
    d = json.loads(settings_file.read_text())
    d["pce"]["api_secret"] = ["SUPERSECRETVALUE"]
    d["pce"]["org_id"] = "SECRETORGVALUE"
    settings_file.write_text(json.dumps(d))
    with pytest.raises(SettingsInvalid) as e:
        SettingsStore(settings_file).load()
    text = str(e.value) + repr(e.value.errors)
    assert "SUPERSECRETVALUE" not in text and "SECRETORGVALUE" not in text
    assert {"pce.api_secret", "pce.org_id"} <= set(_locs(e))


def test_update_persists_and_bumps_revision(settings_file):
    store = SettingsStore(settings_file)
    s0 = store.load()

    def m(d):
        d["pce"]["url"] = "https://pce.example.com:8443"

    s1 = store.update(s0.revision, m)
    assert s1.revision == s0.revision + 1 and s1.pce.url == "https://pce.example.com:8443"
    assert store.current() == s1
    assert SettingsStore(settings_file).load() == s1


def test_update_with_stale_revision_conflicts(settings_file):
    store = SettingsStore(settings_file)
    rev = store.load().revision
    store.update(rev, lambda d: d["display"].update(language="zh_TW"))
    with pytest.raises(SettingsConflict) as e:
        store.update(rev, lambda d: d["display"].update(language="en"))
    assert (e.value.expected, e.value.actual) == (rev, rev + 1)


def test_update_rejects_invalid_and_keeps_file(settings_file):
    store = SettingsStore(settings_file)
    s0 = store.load()
    before = settings_file.read_bytes()
    with pytest.raises(SettingsInvalid) as e:
        store.update(s0.revision, lambda d: d["web"].update(port=0))
    assert "web.port" in _locs(e)
    assert settings_file.read_bytes() == before
    assert store.current() == s0


def test_failed_update_leaves_current_untouched(settings_file):
    store = SettingsStore(settings_file)
    s0 = store.load()
    s0 = store.update(s0.revision, lambda d: d["web"].update(allowed_ips=["10.0.0.0/8"]))
    before = settings_file.read_bytes()

    def clear_then_break(d):
        d["web"]["allowed_ips"].clear()
        d["web"]["port"] = 0

    with pytest.raises(SettingsInvalid):
        store.update(s0.revision, clear_then_break)

    def clear_then_raise(d):
        d["web"]["allowed_ips"].clear()
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        store.update(s0.revision, clear_then_raise)
    assert store.current().web.allowed_ips == ("10.0.0.0/8",)
    assert settings_file.read_bytes() == before


def test_saved_file_mode_is_0600(settings_file):
    store = SettingsStore(settings_file)
    settings_file.chmod(0o644)
    s0 = store.load()
    store.update(s0.revision, lambda d: None)
    assert (settings_file.stat().st_mode & 0o777) == 0o600


def test_create_initial_and_refuse_existing(tmp_path):
    p = tmp_path / "settings.json"
    store = SettingsStore(p)
    s = store.create_initial(password_hash=HASH, secret_key=KEY, port=5443)
    assert s.web.port == 5443 and (p.stat().st_mode & 0o777) == 0o600
    before = p.read_bytes()
    with pytest.raises(FileExistsError):
        SettingsStore(p).create_initial(password_hash=HASH, secret_key=KEY)
    assert p.read_bytes() == before


def test_default_settings_roundtrip_is_valid(tmp_path, initial):
    p = tmp_path / "settings.json"
    SettingsStore(p).create_initial(password_hash=HASH, secret_key=KEY)
    assert SettingsStore(p).load() == initial


def test_concurrent_updates_serialise(settings_file):
    store = SettingsStore(settings_file)
    store.load()
    errors = []

    def worker():
        for _ in range(20):
            while True:
                rev = store.current().revision
                try:
                    store.update(rev, lambda d: None)
                    break
                except SettingsConflict:
                    continue
                except (SettingsInvalid, OSError) as ex:  # pragma: no cover - failure path
                    errors.append(ex)
                    return

    ts = [threading.Thread(target=worker) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == [] and store.current().revision == 80


def test_directory_fsync_failure_after_rename_keeps_memory_in_sync(settings_file, monkeypatch):
    import os
    import stat

    store = SettingsStore(settings_file)
    s0 = store.load()
    real_fsync = os.fsync

    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(5, "EIO")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    s1 = store.update(s0.revision, lambda d: d["web"].update(port=6000))
    assert store.current() == s1 and s1.web.port == 6000
    assert SettingsStore(settings_file).load().web.port == 6000
