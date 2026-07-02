"""Regression test for ScheduleEngine.check: one_time schedule + timezone
'local' must not silently fail to expire due to aware/naive datetime
comparison TypeError being swallowed by the per-item except."""
from unittest.mock import MagicMock

from src.rule_scheduler import ScheduleDB, ScheduleEngine


def test_one_time_local_tz_expires_correctly(tmp_path):
    """one_time schedule with timezone='local' (aware `now`) compared against a
    naive `expire_at` must still expire and be cleaned up, not raise a
    TypeError that gets swallowed by the per-item except."""
    db_path = tmp_path / "rule_schedules.json"
    href = "/orgs/1/sec_policy/draft/rules/1"
    db = ScheduleDB(str(db_path))
    db.put(href, {
        "type": "one_time",
        "name": "test_rule",
        "action": "allow",
        "expire_at": "2000-01-01T00:00:00",  # naive, far in the past
        "timezone": "local",
    })

    api = MagicMock()
    api.has_draft_changes.return_value = False
    engine = ScheduleEngine(db, api)

    engine.check(silent=True, tz_str="local")

    api.toggle_and_provision.assert_called_once_with(href, False, None)
    assert db.get(href) is None, "expired one_time schedule must be removed from db"
