"""Tests for src/report/tz_utils.py — report engine timezone parsing.

parse_tz must delegate unknown formats (IANA names) to the unified
src.tz_utils.resolve_tz, while keeping local/UTC/UTC±N behaviour unchanged.
"""
import datetime

from src.report.tz_utils import parse_tz


def test_parse_tz_iana_name_has_correct_offset():
    """Asia/Taipei is UTC+8 year-round (no DST) — must NOT silently fall
    back to UTC (offset 0), which was the pre-fix behaviour for IANA names."""
    tz = parse_tz("Asia/Taipei")
    dt = datetime.datetime(2026, 1, 1, tzinfo=tz)
    assert dt.utcoffset() == datetime.timedelta(hours=8)


def test_parse_tz_local_unchanged():
    expected = datetime.datetime.now(datetime.timezone.utc).astimezone().utcoffset()
    tz = parse_tz("local")
    assert tz.utcoffset(None) == expected


def test_parse_tz_empty_string_is_local_unchanged():
    expected = datetime.datetime.now(datetime.timezone.utc).astimezone().utcoffset()
    tz = parse_tz("")
    assert tz.utcoffset(None) == expected


def test_parse_tz_plain_utc_unchanged():
    assert parse_tz("UTC") == datetime.timezone.utc


def test_parse_tz_positive_utc_offset_unchanged():
    tz = parse_tz("UTC+8")
    assert tz.utcoffset(None) == datetime.timedelta(hours=8)


def test_parse_tz_negative_utc_offset_unchanged():
    tz = parse_tz("UTC-5")
    assert tz.utcoffset(None) == datetime.timedelta(hours=-5)


def test_parse_tz_fractional_utc_offset_unchanged():
    tz = parse_tz("UTC+5.5")
    assert tz.utcoffset(None) == datetime.timedelta(hours=5, minutes=30)


def test_parse_tz_unknown_still_falls_back_to_utc():
    """Truly invalid strings (not a valid IANA name either) still fall back
    to UTC, same end result as before — now via resolve_tz's fallback."""
    assert parse_tz("Not/AZone") == datetime.timezone.utc


def test_parse_tz_path_shaped_string_falls_back_to_utc():
    """修前的 parse_tz 對任何字串都不 raise（最後分支無條件回 UTC）；
    委派 resolve_tz 後必須維持此契約——路徑形狀字串（zoneinfo 丟
    ValueError）也要退 UTC，不能讓 ven_status_generator 崩潰。"""
    for bad in ("../etc/passwd", "/etc/passwd", ".."):
        assert parse_tz(bad) == datetime.timezone.utc
