"""Unit tests for compute_next_trigger — pure next-trigger computation for the
rule-scheduler GUI KPI card. Clock is injected so the cases are deterministic."""
import datetime

from src.rule_scheduler import compute_next_trigger


# A fixed reference "now": Wednesday 2026-06-10 14:30 (naive wall-clock).
NOW = datetime.datetime(2026, 6, 10, 14, 30, 0)


def test_recurring_later_today():
    """A recurring schedule whose window starts later today returns today's start."""
    schedules = {
        "/orgs/1/sec_policy/draft/rule_sets/1": {
            "type": "recurring",
            "days": ["Wed"],
            "start": "18:00",
            "end": "22:00",
            "timezone": "UTC",
        }
    }
    result = compute_next_trigger(schedules, now=NOW)
    assert result is not None
    dt = datetime.datetime.fromisoformat(result)
    assert dt.year == 2026 and dt.month == 6 and dt.day == 10
    assert dt.hour == 18 and dt.minute == 0


def test_recurring_next_week():
    """A recurring schedule only on a past weekday rolls to next week's occurrence."""
    schedules = {
        "/orgs/1/sec_policy/draft/rule_sets/2": {
            "type": "recurring",
            "days": ["Mon"],  # NOW is Wednesday → next Monday
            "start": "09:00",
            "end": "17:00",
            "timezone": "UTC",
        }
    }
    result = compute_next_trigger(schedules, now=NOW)
    assert result is not None
    dt = datetime.datetime.fromisoformat(result)
    # Next Monday after Wed 2026-06-10 is 2026-06-15.
    assert dt.year == 2026 and dt.month == 6 and dt.day == 15
    assert dt.hour == 9 and dt.minute == 0


def test_one_time_expired_returns_none():
    """An only-schedule that is a past one_time contributes nothing → None."""
    schedules = {
        "/orgs/1/sec_policy/draft/rule_sets/3": {
            "type": "one_time",
            "expire_at": "2026-06-01T10:00:00",  # before NOW
            "timezone": "UTC",
        }
    }
    result = compute_next_trigger(schedules, now=NOW)
    assert result is None
