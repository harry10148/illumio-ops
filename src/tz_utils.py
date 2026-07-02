"""
src/tz_utils.py
統一時區字串解析工具。

背景：report_scheduler._now_in_schedule_tz、rule_scheduler._now_in_tz、
reporter._resolve_tz 過去各自維護一套「local / UTC / UTC±N」的半相容解析邏輯，
都不認得 IANA 時區名稱（例如 'Asia/Taipei'）——不符合的字串一律靜默退回
UTC（偏移量算成 0），造成 cron 排程觸發時間、告警時間戳跟著錯開一個 UTC
offset。本模組是唯一的時區字串解析入口，介面刻意保持極簡：只提供
``resolve_tz``（字串 → tzinfo）與 ``now_in_tz``（字串 → aware datetime）。

呼叫端各自保留 naive/aware 慣例（例如 report_scheduler 對 'UTC+N' 回傳 naive
牆鐘），本模組只負責把時區字串正確解析成 tzinfo，不強制內部時間慣例。
"""
from __future__ import annotations

import datetime
import re
import zoneinfo

from loguru import logger

# 'UTC+8' / 'UTC-5.5' 這類固定偏移字串。與 report_scheduler._tz_offset_hours
# 原本使用的 pattern 相同，確保既有呼叫端行為不變。
_UTC_OFFSET_RE = re.compile(r'^UTC([+-])(\d+(?:\.\d+)?)$')


def resolve_tz(tz_str: str | None) -> datetime.tzinfo:
    """把時區字串解析成 tzinfo。

    支援：
      * 'local' / 空值 → 伺服器實際本地時區偏移
      * 'UTC'           → UTC
      * 'UTC+N' / 'UTC-N' → 固定偏移
      * IANA 名稱（例如 'Asia/Taipei'） → zoneinfo.ZoneInfo

    無法解析（非上述任何格式、或無效的 IANA 名稱）時 fallback 回 UTC，
    並記錄 warning。
    """
    if not tz_str or tz_str == 'local':
        offset = datetime.datetime.now(datetime.timezone.utc).astimezone().utcoffset()
        return datetime.timezone(offset)
    if tz_str == 'UTC':
        return datetime.timezone.utc
    m = _UTC_OFFSET_RE.match(tz_str)
    if m:
        return datetime.timezone(datetime.timedelta(hours=float(m.group(1) + m.group(2))))
    try:
        return zoneinfo.ZoneInfo(tz_str)
    except (KeyError, ValueError, zoneinfo.ZoneInfoNotFoundError):
        # ValueError：路徑形狀的字串（例如 '../etc/passwd'、'/etc/passwd'、'..'）
        # 會讓 zoneinfo 丟 ValueError 而非 KeyError，同樣必須退回 UTC，
        # 不能讓錯誤的 config 字串弄崩呼叫端。
        logger.warning("Unknown timezone {!r}, falling back to UTC", tz_str)
        return datetime.timezone.utc


def now_in_tz(tz_str: str | None) -> datetime.datetime:
    """回傳指定時區的目前時間（aware）。"""
    return datetime.datetime.now(resolve_tz(tz_str))
