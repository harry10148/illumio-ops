"""A.1 驗證：scheduler fallback 必須回傳 timezone-aware datetime。"""
import datetime


def test_report_scheduler_now_in_local_returns_aware():
    """_now_in_schedule_tz('local') fallback 必須回傳 aware datetime。"""
    from src.report_scheduler import _now_in_schedule_tz
    result = _now_in_schedule_tz('local')
    assert result.tzinfo is not None, f"_now_in_schedule_tz('local') returned naive: {result}"


def test_report_scheduler_now_in_empty_returns_aware():
    """_now_in_schedule_tz('') fallback 必須回傳 aware datetime。"""
    from src.report_scheduler import _now_in_schedule_tz
    result = _now_in_schedule_tz('')
    assert result.tzinfo is not None, f"_now_in_schedule_tz('') returned naive: {result}"


def test_rule_scheduler_now_in_local_returns_aware():
    """_now_in_tz('local') fallback 必須回傳 aware datetime。"""
    from src.rule_scheduler import _now_in_tz
    result = _now_in_tz('local')
    assert result.tzinfo is not None, f"_now_in_tz('local') returned naive: {result}"


def test_rule_scheduler_now_in_empty_returns_aware():
    """_now_in_tz('') fallback 必須回傳 aware datetime。"""
    from src.rule_scheduler import _now_in_tz
    result = _now_in_tz('')
    assert result.tzinfo is not None, f"_now_in_tz('') returned naive: {result}"


def test_rule_scheduler_now_in_utc_plus_offset_returns_naive():
    """UTC+8 偏移仍回傳 naive（設計上這路徑是去掉 tzinfo 的 wall-clock）。"""
    from src.rule_scheduler import _now_in_tz
    result = _now_in_tz('UTC+8')
    # UTC offset path 回傳 naive（設計如此，只測不崩潰）
    assert isinstance(result, datetime.datetime)


def test_report_scheduler_utc_path_returns_naive():
    """UTC path 回傳 naive wall-clock（設計如此）。"""
    from src.report_scheduler import _now_in_schedule_tz
    result = _now_in_schedule_tz('UTC')
    assert isinstance(result, datetime.datetime)
