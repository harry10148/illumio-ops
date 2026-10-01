"""PCE audit events 的完整視窗抓取（碰 max_results 上限時二分抽乾）。

PCE 同步 GET /events 在視窗內筆數超過 max_results（上限 10000）時，只回傳
**最新**的那一批——更舊的事件不會出現在回應裡，也沒有分頁可接著拿。舊的
ingest 碰頂後改走 get_events_async（一直是回傳 [] 的 stub），結果是保留最新
一萬筆、watermark 往前推，較舊的事件永久遺失。

這裡改成帶明確結束時間（timestamp[lte]）查詢，碰頂就把視窗對半切開各自再抓，
直到每個子窗都低於上限。兩端點的重複由 pce_href 的 unique 約束去重。切到
深度上限或最小跨度仍碰頂時，回報 truncated=True 讓呼叫端發 overflow 告警。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from loguru import logger


class EventsFetchError(RuntimeError):
    """PCE 回報 fetch 失敗（ApiClient 把連線層錯誤吞成空清單，只寫 last_fetch_error）。"""


@dataclass
class EventsFetchResult:
    events: list[dict]
    truncated_windows: list[dict] = field(default_factory=list)

    @property
    def truncated(self) -> bool:
        return bool(self.truncated_windows)


def iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # 保留微秒：截掉的話 until 會往前移，視窗結尾那不到一秒的事件就漏了。
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_events_drained(
    api,
    since_dt: datetime,
    until_dt: datetime,
    *,
    max_results: int = 10000,
    max_depth: int = 10,
    min_span: timedelta = timedelta(minutes=1),
    fetch=None,
) -> EventsFetchResult:
    """抓 [since_dt, until_dt] 的全部事件；碰頂就二分直到抽乾。

    depth 10 → 最小子窗 = 原窗 / 1024（24 小時冷啟動約 1.4 分鐘），再配
    min_span 硬下限，遞迴有界。PCE 回報錯誤時拋 EventsFetchError。

    fetch：選用的抓取函式 fetch(start_iso, end_iso, max_results) -> list；
    預設用 api.fetch_events 並檢查 last_fetch_error。
    """
    if fetch is None:
        def fetch(start_iso, end_iso, limit):
            return _default_fetch(api, start_iso, end_iso, limit)
    result = EventsFetchResult(events=[])
    _fetch_window(fetch, since_dt, until_dt, 0, max_results, max_depth, min_span, result)
    return result


def _default_fetch(api, start_iso: str, end_iso: str, limit: int) -> list:
    events = api.fetch_events(start_iso, end_time_str=end_iso, max_results=limit,
                              rate_limit=True)
    fetch_error = getattr(api, "last_fetch_error", None)
    # isinstance guard：測試常用 MagicMock 當 api，未設定的屬性會自動長出
    # truthy 的 child mock；真正的 ApiClient 合約是 str | None。
    if isinstance(fetch_error, str) and fetch_error:
        raise EventsFetchError(fetch_error)
    return events


def _fetch_window(fetch, since_dt, until_dt, depth, max_results, max_depth, min_span, result):
    events = list(fetch(iso_z(since_dt), iso_z(until_dt), max_results) or [])
    if len(events) < max_results:
        result.events.extend(events)
        return
    span = until_dt - since_dt
    if depth >= max_depth or span <= min_span:
        logger.warning(
            "Events fetch hit max_results cap ({}) in window {} → {} at depth {}; "
            "cannot bisect further — older events in this window may be missing",
            max_results, since_dt, until_dt, depth,
        )
        result.truncated_windows.append({
            "since": since_dt.isoformat(),
            "until": until_dt.isoformat(),
            "count": len(events),
        })
        result.events.extend(events)
        return
    mid = since_dt + span / 2
    logger.info(
        "Events fetch hit max_results cap ({}); bisecting {} → {} at {}",
        max_results, since_dt, until_dt, mid,
    )
    _fetch_window(fetch, since_dt, mid, depth + 1, max_results, max_depth, min_span, result)
    _fetch_window(fetch, mid, until_dt, depth + 1, max_results, max_depth, min_span, result)
