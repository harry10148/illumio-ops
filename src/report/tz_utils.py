"""
src/report/tz_utils.py
Shared timezone helpers for the report engine.

Consolidates timezone parsing and formatting that was previously duplicated
across report_generator.py and ven_status_generator.py.

IANA 時區名稱（例如 'Asia/Taipei'）委派給 src.tz_utils.resolve_tz 解析，
避免與其餘呼叫端（reporter、schedulers）分歧；local/UTC/UTC±N 行為保持不變。
"""
import datetime

from src.tz_utils import resolve_tz as _resolve_tz

def parse_tz(tz_str: str) -> datetime.tzinfo:
    """
    Parse a config timezone string into a tzinfo object.
    Supported formats: 'local', 'UTC', 'UTC+8', 'UTC-5', 'UTC+5.5', IANA
    names (e.g. 'Asia/Taipei'), etc.
    'local' returns the system's local timezone via UTC offset.
    """
    if not tz_str or tz_str == 'local':
        local_offset = datetime.datetime.now(datetime.timezone.utc).astimezone().utcoffset()
        return datetime.timezone(local_offset)
    if tz_str == 'UTC':
        return datetime.timezone.utc
    if tz_str.startswith('UTC+') or tz_str.startswith('UTC-'):
        sign = 1 if tz_str[3] == '+' else -1
        hours_part = float(tz_str[4:])
        total_minutes = int(sign * hours_part * 60)
        return datetime.timezone(datetime.timedelta(minutes=total_minutes))
    return _resolve_tz(tz_str)

def fmt_tz_now(tz: datetime.tzinfo) -> str:
    """Return current time formatted as '2026-03-26 16:30:00 (UTC+08:00)'."""
    now = datetime.datetime.now(tz)
    return fmt_tz_str(now)

def fmt_tz_str(dt: datetime.datetime) -> str:
    """Format a timezone-aware datetime as '2026-03-26 16:30:00 (UTC+08)'."""
    offset_s = dt.strftime('%z')
    sign = offset_s[0]
    hh = int(offset_s[1:3])
    mm = int(offset_s[3:5])
    tz_label = f"UTC{sign}{hh}" if mm == 0 else f"UTC{sign}{hh}:{mm:02d}"
    return dt.strftime('%Y-%m-%d %H:%M:%S') + f' ({tz_label})'

def fmt_ts_local(ts_str, tz: datetime.timezone) -> str:
    """Format an ISO timestamp string to 'YYYY-MM-DD HH:MM (UTC+N)' in local time."""
    if not ts_str:
        return ''
    try:
        dt = datetime.datetime.fromisoformat(str(ts_str).replace('Z', '+00:00'))
        local_dt = dt.astimezone(tz)
        offset_s = local_dt.strftime('%z')
        sign = offset_s[0]
        hh = int(offset_s[1:3])
        mm = int(offset_s[3:5])
        tz_label = f"UTC{sign}{hh}" if mm == 0 else f"UTC{sign}{hh}:{mm:02d}"
        return local_dt.strftime('%Y-%m-%d %H:%M') + f' ({tz_label})'
    except Exception:
        return str(ts_str)  # intentional fallback: return raw timestamp string if timezone formatting fails
