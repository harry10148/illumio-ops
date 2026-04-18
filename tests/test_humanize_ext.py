"""humanize wrapper must honor i18n language setting."""
import datetime as _dt
from unittest.mock import patch

from src.humanize_ext import human_size, human_time_delta, human_number


def test_human_size_bytes_to_mb():
    assert human_size(1_500_000) in ("1.4 MB", "1.5 MB")  # humanize rounds


def test_human_size_handles_zero():
    assert human_size(0) == "0 Bytes"


def test_human_time_delta_seconds():
    with patch("src.humanize_ext.get_language", return_value="en"):
        delta = _dt.timedelta(seconds=45)
        assert "second" in human_time_delta(delta)


def test_human_time_delta_zh_tw():
    with patch("src.humanize_ext.get_language", return_value="zh_TW"):
        delta = _dt.timedelta(hours=2)
        result = human_time_delta(delta)
        # Chinese locale should produce chinese or at minimum not English 'hour'
        assert "小時" in result or "時" in result or "hour" not in result.lower()


def test_human_number_thousands():
    assert human_number(12345) in ("12,345", "12345")
