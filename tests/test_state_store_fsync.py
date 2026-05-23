import os
import json
from unittest.mock import patch
from src import state_store


def test_update_state_calls_fsync_on_file(tmp_path, monkeypatch):
    """update_state_file should fsync the file before os.replace."""
    f = tmp_path / "state.json"
    f.write_text("{}")

    fsync_calls = []
    real_fsync = os.fsync

    def tracking_fsync(fd):
        fsync_calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", tracking_fsync)
    state_store.update_state_file(str(f), lambda s: {**s, "key": "value"})
    assert len(fsync_calls) >= 1, "update_state_file must call os.fsync at least once"


def test_update_state_fsyncs_parent_dir(tmp_path, monkeypatch):
    """update_state_file should fsync the parent dir after os.replace for metadata durability."""
    f = tmp_path / "state.json"
    f.write_text("{}")

    # Track fsync calls and whether any was on a directory
    fsync_targets = []
    real_fsync = os.fsync

    def tracking_fsync(fd):
        # try fstat to check S_ISDIR
        import stat
        st = os.fstat(fd)
        fsync_targets.append("dir" if stat.S_ISDIR(st.st_mode) else "file")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", tracking_fsync)
    state_store.update_state_file(str(f), lambda s: {**s, "key": "value"})
    assert "dir" in fsync_targets, f"parent dir fsync missing; saw {fsync_targets}"


def test_update_state_writes_correct_content(tmp_path):
    """sanity: fsync changes don't break the actual write."""
    f = tmp_path / "state.json"
    f.write_text("{}")
    state_store.update_state_file(str(f), lambda s: {**s, "key": "value"})
    data = json.loads(f.read_text())
    assert data.get("key") == "value"
