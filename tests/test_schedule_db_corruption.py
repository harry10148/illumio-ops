import json
import os
import pytest
from src.rule_scheduler import ScheduleDB


def test_corrupt_db_quarantined_and_raised(tmp_path):
    """Corrupt rule_schedules.json should be moved to .corrupt.<ts> and load() raises."""
    db_path = tmp_path / "rule_schedules.json"
    db_path.write_text("{not valid json")
    db = ScheduleDB(str(db_path))
    with pytest.raises(ValueError, match="corrupt"):
        db.load()
    # Quarantine file should exist
    corrupts = list(tmp_path.glob("rule_schedules.json.corrupt.*"))
    assert len(corrupts) == 1, f"expected 1 quarantine file, found {[str(p) for p in corrupts]}"
    # Original file should be gone (moved)
    assert not db_path.exists()


def test_non_dict_root_quarantined(tmp_path):
    """If JSON parses but isn't a dict, also quarantine and raise."""
    db_path = tmp_path / "rule_schedules.json"
    db_path.write_text('[1, 2, 3]')  # list root, not dict
    db = ScheduleDB(str(db_path))
    with pytest.raises(ValueError):
        db.load()
    assert list(tmp_path.glob("rule_schedules.json.corrupt.*"))


def test_missing_file_treated_as_empty(tmp_path):
    """Missing file is not 'corrupt' — should load() to empty dict without raising."""
    db = ScheduleDB(str(tmp_path / "rule_schedules.json"))
    db.load()
    assert db.db == {}


def test_valid_file_loaded_normally(tmp_path):
    db_path = tmp_path / "rule_schedules.json"
    db_path.write_text('{"sched1": {"name": "x"}}')
    db = ScheduleDB(str(db_path))
    db.load()
    assert db.db == {"sched1": {"name": "x"}}


def test_save_atomic_failure_raises(tmp_path, monkeypatch):
    """If os.replace fails, save() must NOT fall back to truncating write — must raise."""
    db_path = tmp_path / "rule_schedules.json"
    db = ScheduleDB(str(db_path))
    db.db = {"existing": "data"}
    db.save()  # initial save works
    # Now force os.replace to fail
    def boom(*args, **kwargs):
        raise OSError("simulated atomic rename failure")
    monkeypatch.setattr(os, "replace", boom)
    db.db = {"updated": "data"}
    with pytest.raises(OSError):
        db.save()
    # Original file must still contain old data (NOT truncated)
    on_disk = json.loads(db_path.read_text())
    assert on_disk == {"existing": "data"}, f"DB was clobbered: {on_disk}"
