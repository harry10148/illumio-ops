"""Rule schedules (UI redesign spec §4.5, 5.x semantics): weekly windows (across midnight too) and expiries, the next
change, and the fixed-English note kept in the rule's description."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from illumio_ops.domain.rule_schedule import (
    Expiry,
    Weekly,
    desired,
    next_change,
    note,
    preview,
    strip_notes,
    with_note,
)

TPE = ZoneInfo("Asia/Taipei")
NY = ZoneInfo("America/New_York")


def at(y, mo, d, h, mi=0, tz=TPE):
    return datetime(y, mo, d, h, mi, tzinfo=tz).astimezone(UTC)


def weekly(days=("mon", "tue", "wed", "thu", "fri"), start="08:00", end="18:00", action="enable_in_window",
           timezone="Asia/Taipei"):
    return Weekly(days=days, start=start, end=end, action=action, timezone=timezone)


# 2026-11-02 is a Monday


def test_inside_and_outside_a_day_window():
    w = weekly()
    assert desired(w, at(2026, 11, 2, 9)) is True
    assert desired(w, at(2026, 11, 2, 7, 59)) is False
    assert desired(w, at(2026, 11, 7, 9)) is False  # Saturday


def test_end_is_outside():
    assert desired(weekly(), at(2026, 11, 2, 18)) is False
    assert desired(weekly(), at(2026, 11, 2, 17, 59)) is True


def test_across_midnight():
    w = weekly(days=("sun",), start="22:00", end="06:00")
    assert desired(w, at(2026, 11, 1, 23)) is True      # Sunday 23:00
    assert desired(w, at(2026, 11, 2, 5, 59)) is True   # Monday 05:59, the window began Sunday
    assert desired(w, at(2026, 11, 2, 6)) is False      # Monday 06:00
    assert desired(w, at(2026, 11, 2, 22, 30)) is False  # Monday is not a window day


def test_disable_in_window_is_the_opposite():
    w = weekly(action="disable_in_window")
    assert desired(w, at(2026, 11, 2, 9)) is False
    assert desired(w, at(2026, 11, 2, 20)) is True


def test_expiry():
    e = Expiry(expire_at=at(2026, 12, 1, 0), timezone="Asia/Taipei")
    assert desired(e, at(2026, 11, 30, 23, 59)) is True
    assert desired(e, at(2026, 12, 1, 0)) == "expired"
    assert desired(e, at(2026, 12, 2, 0)) == "expired"


def test_dst_days_judged_in_local_time():
    w = weekly(days=("sun",), timezone="America/New_York")
    assert desired(w, at(2027, 3, 14, 1, 30, tz=NY)) is False
    assert desired(w, at(2027, 3, 14, 9, 0, tz=NY)) is True


def test_next_change_never_a_missing_local_time():
    w = weekly(days=("sun",), start="02:30", end="09:00", timezone="America/New_York")
    nxt = next_change(w, datetime(2027, 3, 13, 12, tzinfo=UTC))
    assert nxt is not None and nxt.astimezone(NY).hour != 2  # 02:30 does not exist that Sunday


def test_next_change_across_the_week():
    w = weekly(days=("mon",))
    assert next_change(w, at(2026, 11, 2, 19)) == at(2026, 11, 9, 8)
    assert next_change(w, at(2026, 11, 2, 9)) == at(2026, 11, 2, 18)


def test_next_change_of_an_expiry():
    e = Expiry(expire_at=at(2026, 12, 1, 0), timezone="Asia/Taipei")
    assert next_change(e, at(2026, 11, 2, 9)) == at(2026, 12, 1, 0)
    assert next_change(e, at(2026, 12, 2, 9)) is None


def test_notes_fixed_english():
    w = weekly(days=("fri", "mon", "wed"), start="18:00", end="09:00", action="disable_in_window")
    assert note(w) == "[📅 Recurring: Mon,Wed,Fri 18:00-09:00 (Asia/Taipei) Disable in window]"
    assert note(Expiry(expire_at=at(2026, 12, 1, 0), timezone="Asia/Taipei")) == \
        "[⏰ Expires: 2026-12-01 00:00 (Asia/Taipei)]"


def test_strip_notes_all_three_prefixes():
    text = "Allow backups [📅 Recurring: Mon 08:00-18:00 (UTC+8) Enable in window] [⏳ Expires: 2026-08-01 00:00]" \
           "\n[⏰ Expires: 2026-08-01 00:00] keep [other]"
    assert strip_notes(text) == "Allow backups keep [other]"


def test_with_note():
    w = weekly()
    assert with_note("", w) == note(w)
    assert with_note("Allow backups [📅 Recurring: old]", w) == f"Allow backups\n{note(w)}"


@pytest.mark.parametrize("bad", [{"start": "08:00", "end": "08:00"}, {"timezone": "Mars/Olympus"}, {"days": ()},
                                 {"days": ("mon", "mon")}, {"start": "8:00"}])
def test_weekly_validation(bad):
    with pytest.raises(ValidationError):
        weekly(**bad)


def test_preview_keys():
    key, params = preview(weekly(days=("mon", "wed", "fri"), start="18:00", end="09:00", action="disable_in_window"))
    assert key == "rs_preview_weekly_disable"
    assert params == {"days": "mon,wed,fri", "start": "18:00", "end": "09:00", "next_day": "1"}
    key, params = preview(Expiry(expire_at=at(2026, 12, 1, 0), timezone="Asia/Taipei"))
    assert key == "rs_preview_expiry" and params == {"at": "2026-12-01 00:00", "timezone": "Asia/Taipei"}
