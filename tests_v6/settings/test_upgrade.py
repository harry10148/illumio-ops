"""Settings files written by an older v6 load through an in-memory version upgrade."""
import json
import os

import pytest

from illumio_ops.settings.schema import SCHEMA_VERSION, default_settings
from illumio_ops.settings.store import SettingsInvalid, SettingsStore, validate_settings
from illumio_ops.settings.upgrade import upgrade

from .conftest import HASH, KEY


def _v1(tmp_path):
    """A settings file exactly as P1 (schema 1) wrote it: no collection section."""
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 1
    del d["collection"]
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(d, indent=2))
    p.chmod(0o600)
    return p


def _locs(e):
    return [loc for loc, _ in e.value.errors]


def test_v1_file_loads_as_v2_in_memory(tmp_path):
    p = _v1(tmp_path)
    before, mtime = p.read_bytes(), os.stat(p).st_mtime_ns
    s = SettingsStore(p).load()
    assert s.schema_version == SCHEMA_VERSION == 2
    assert s.collection.traffic_interval_seconds == 600
    assert s.collection.retention.baseline_days == 30
    assert p.read_bytes() == before and os.stat(p).st_mtime_ns == mtime


def test_invalid_v1_file_still_writes_nothing(tmp_path):
    p = _v1(tmp_path)
    d = json.loads(p.read_text())
    d["web"]["bogus"] = 1
    p.write_text(json.dumps(d))
    before = p.read_bytes()
    with pytest.raises(SettingsInvalid) as e:
        SettingsStore(p).load()
    assert "web.bogus" in _locs(e)
    assert p.read_bytes() == before


def test_first_update_after_upgrade_writes_v2_without_conflict(tmp_path):
    p = _v1(tmp_path)
    store = SettingsStore(p)
    s = store.load()
    new = store.update(s.revision, lambda d: d["display"].__setitem__("language", "zh_TW"))
    on_disk = json.loads(p.read_text())
    assert on_disk["schema_version"] == 2
    assert on_disk["collection"]["traffic_interval_seconds"] == 600
    assert new.revision == s.revision + 1


def test_newer_schema_version_is_refused(tmp_path):
    p = _v1(tmp_path)
    d = json.loads(p.read_text())
    d["schema_version"] = SCHEMA_VERSION + 1
    p.write_text(json.dumps(d))
    with pytest.raises(SettingsInvalid) as e:
        SettingsStore(p).load()
    assert "schema_version" in _locs(e)


def test_upgrade_leaves_current_version_untouched():
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    assert upgrade(d) == d


def test_upgrade_passes_non_dict_through_to_validation():
    with pytest.raises(SettingsInvalid):
        validate_settings(["not", "a", "dict"])
