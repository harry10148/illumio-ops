"""Tests for src/tz_utils.py — the unified timezone-string resolver."""
import datetime

from src.tz_utils import now_in_tz, resolve_tz


def test_resolve_tz_iana_name_has_correct_offset():
    """Asia/Taipei is UTC+8 year-round (no DST) — must NOT silently fall back
    to UTC (offset 0), which was the pre-fix behaviour for IANA names."""
    tz = resolve_tz("Asia/Taipei")
    dt = datetime.datetime(2026, 1, 1, tzinfo=tz)
    assert dt.utcoffset() == datetime.timedelta(hours=8)


def test_resolve_tz_utc_offset_string():
    tz = resolve_tz("UTC+8")
    assert tz.utcoffset(None) == datetime.timedelta(hours=8)


def test_resolve_tz_negative_utc_offset_string():
    tz = resolve_tz("UTC-5")
    assert tz.utcoffset(None) == datetime.timedelta(hours=-5)


def test_resolve_tz_plain_utc():
    assert resolve_tz("UTC") == datetime.timezone.utc


def test_resolve_tz_local_matches_server_local_offset():
    expected = datetime.datetime.now(datetime.timezone.utc).astimezone().utcoffset()
    for tz_str in ("local", "", None):
        tz = resolve_tz(tz_str)
        assert tz.utcoffset(None) == expected


def test_resolve_tz_unknown_falls_back_to_utc():
    assert resolve_tz("Not/AZone") == datetime.timezone.utc


def test_now_in_tz_is_aware_and_close_to_utc_instant():
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    dt = now_in_tz("Asia/Taipei")
    assert dt.tzinfo is not None
    assert abs((dt - utc_now).total_seconds()) < 60
