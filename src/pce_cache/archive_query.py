"""封存日檔的串流讀取。

封存是「PCE 只保留三個月，之後還想查」的唯一途徑，所以查詢一定落在舊資料
上——而舊檔在 `archive_gzip_after_days`（預設 7）之後就被原地換成 .gz。
兩種副檔名都要開，否則核心情境永遠查不到東西。
"""
from __future__ import annotations

import gzip
import os
import re
from datetime import date
from typing import Iterator

import orjson
from loguru import logger

_DAY_FILE = re.compile(r"^(?P<source>[a-z_]+)-(?P<day>\d{4}-\d{2}-\d{2})\.jsonl(?P<gz>\.gz)?$")


def _matching_files(archive_dir: str, source: str, start: date, end: date) -> list[str]:
    """[start, end]（含端點）內該 source 的日檔，依日期排序。

    同一天同時存在 .jsonl 與 .jsonl.gz 時取 .jsonl：壓縮是原地取代，兩者並存
    只會在輪替中途出現，未壓縮的那份才是完整的。
    """
    try:
        names = sorted(os.listdir(archive_dir))
    except OSError:
        return []
    by_day: dict[str, str] = {}
    for name in names:
        m = _DAY_FILE.match(name)
        if not m or m.group("source") != source:
            continue
        try:
            day = date.fromisoformat(m.group("day"))
        except ValueError:
            continue
        if not (start <= day <= end):
            continue
        key = m.group("day")
        if key in by_day and m.group("gz"):
            continue  # 已有未壓縮版本，優先用它
        by_day[key] = os.path.join(archive_dir, name)
    return [by_day[k] for k in sorted(by_day)]


def _iter_lines(path: str) -> Iterator[bytes]:
    opener = gzip.open if path.endswith(".gz") else open
    try:
        with opener(path, "rb") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield line
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        # 截斷/損壞的封存檔：已讀出的行照常處理，放棄該檔剩餘部分，
        # 讓呼叫端繼續下一檔。與 archive_import 的既有行為一致。
        logger.warning("archive_query: corrupt/truncated file {}: {}", path, exc)


def iter_archive_rows(archive_dir: str, source: str,
                      start: date, end: date) -> Iterator[dict]:
    """依序產出 [start, end] 內該 source 每個日檔的每一列。

    無法解析的單列跳過並記 warning——一列壞掉不該讓整趟查詢失敗。
    """
    for path in _matching_files(archive_dir, source, start, end):
        for line in _iter_lines(path):
            try:
                yield orjson.loads(line)
            except orjson.JSONDecodeError as exc:
                logger.warning("archive_query: unparsable line in {}: {}", path, exc)


# 封存是離線資料：沒有 PCE 可問，所以任何需要向 PCE 展開或即時計算的條件
# 都判不了。這份清單必須涵蓋 analyzer 的 _CACHE_UNEVALUABLE_FILTER_KEYS
# （label group / AMS），額外多一個 draft_policy_decision——那是即時查詢才
# 算得出來的欄位，封存列裡根本不存在。
#
# 帶著這些條件靜默回未過濾的結果，正是 2026-07-24 審查 M4 抓到的缺陷；
# 這裡明確拒絕。清單刻意逐字列出而不 import analyzer：pce_cache 是 analyzer
# 的下層（analyzer 自己 import src.pce_cache.reader）。反向 import 今天雖不
# 循環，卻把整個 analyzer 拖進這個小模組，也讓分層倒過來。
# tests/test_archive_query.py 的 drift 測試負責擋住兩者脫節。
UNSUPPORTED_ARCHIVE_FILTER_KEYS: tuple[str, ...] = (
    "src_label_group", "src_label_groups", "dst_label_group", "dst_label_groups",
    "ex_src_label_group", "ex_src_label_groups",
    "ex_dst_label_group", "ex_dst_label_groups",
    "src_include_groups", "dst_include_groups",
    "src_ams", "dst_ams", "ex_src_ams", "ex_dst_ams",
    "draft_policy_decision",
)


def unsupported_filters(filters: dict) -> list[str]:
    """請求中命中黑名單且**有值**的 key（排序）。空值代表沒在用這個條件。"""
    return sorted(k for k in UNSUPPORTED_ARCHIVE_FILTER_KEYS if filters.get(k))
