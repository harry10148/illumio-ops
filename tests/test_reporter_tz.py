"""Regression test for Reporter._resolve_tz IANA-name support (Important,
2026-07-02 code review): settings.timezone values that aren't 'local'/'UTC'/
'UTC±N' (e.g. 'Asia/Taipei') silently fell back to UTC, so every alert/report
timestamp Reporter formats was wrong for operators using an IANA timezone."""
import datetime
import types

from src.reporter import Reporter


def _cm(tz_str):
    return types.SimpleNamespace(config={"settings": {"timezone": tz_str}})


def test_resolve_tz_recognizes_iana_name():
    r = Reporter(_cm("Asia/Taipei"))
    tz, label = r._resolve_tz()
    ref = datetime.datetime(2026, 1, 1, tzinfo=tz)
    assert ref.utcoffset().total_seconds() == 8 * 3600
    assert label == "UTC+08"


def test_resolve_tz_unknown_string_falls_back_to_utc():
    r = Reporter(_cm("Not/AZone"))
    tz, label = r._resolve_tz()
    ref = datetime.datetime(2026, 1, 1, tzinfo=tz)
    assert ref.utcoffset().total_seconds() == 0


def test_fmt_event_ts_uses_iana_timezone():
    """A UTC event timestamp must localize to the real IANA offset, not UTC."""
    r = Reporter(_cm("Asia/Taipei"))
    out = r._fmt_event_ts("2026-06-19T05:00:00.000Z")
    assert "13:00" in out  # 05:00 UTC + 8h = 13:00 Taipei
