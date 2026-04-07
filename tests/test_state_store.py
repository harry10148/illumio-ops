import json
import os
import tempfile

from src.state_store import load_state_file, update_state_file


def test_update_state_file_preserves_unrelated_keys():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"alert_history": {"1": "a"}, "report_schedule_states": {"2": "b"}}, f)

        update_state_file(path, lambda data: {**data, "alert_history": {"1": "updated"}})

        saved = load_state_file(path)
        assert saved["alert_history"] == {"1": "updated"}
        assert saved["report_schedule_states"] == {"2": "b"}
    finally:
        if os.path.exists(path):
            os.unlink(path)
