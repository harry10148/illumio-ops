"""B.2 back-compat：既有 int-style rule_id（以字串 key 存在 JSON）仍可載入。"""
import json
from src.rule_scheduler import ScheduleDB


def test_legacy_int_rule_id_still_loadable(tmp_path):
    """rule_schedules.json 中的舊 int key（字串化）與新 UUID hex key 可共存。"""
    db_path = tmp_path / "rule_schedules.json"
    db_path.write_text(json.dumps({
        "1700000000": {"name": "legacy_int_rule"},
        "abc123def456789012345678901234ab": {"name": "new_uuid_rule"},
    }))
    db = ScheduleDB(str(db_path))
    db.load()
    assert "1700000000" in db.db, "legacy int-style key must survive load"
    assert "abc123def456789012345678901234ab" in db.db, "uuid key must survive load"


def test_empty_db_loadable(tmp_path):
    """空 JSON 物件不造成錯誤。"""
    db_path = tmp_path / "rule_schedules.json"
    db_path.write_text("{}")
    db = ScheduleDB(str(db_path))
    db.load()
    assert db.db == {}
