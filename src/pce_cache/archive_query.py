"""封存日檔的串流讀取。

封存是「PCE 只保留三個月，之後還想查」的唯一途徑，所以查詢一定落在舊資料
上——而舊檔在 `archive_gzip_after_days`（預設 7）之後就被原地換成 .gz。
兩種副檔名都要開，否則核心情境永遠查不到東西。
"""
from __future__ import annotations

import gzip
import heapq
import os
import re
from dataclasses import dataclass, field
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


SUMMARY_TOP_K = 500

_VOLATILE_MAX = ("flow_count", "bytes_in", "bytes_out", "event_time", "ingested_at")

_SORT_FIELD = {
    "volume": lambda r: (r.get("bytes_in") or 0) + (r.get("bytes_out") or 0),
    "connections": lambda r: r.get("flow_count") or 0,
    # "bandwidth" 刻意不在這裡：analyzer 的 bandwidth 是速率
    # (calculate_mbps，bytes 除以時間區間，src/analyzer.py:285-325)，
    # 跟 volume（總量，calculate_volume_mb，:327-342）是兩個不同的量——
    # 同樣的 bytes，一秒內傳完跟一天內傳完，volume 相同、bandwidth 天差
    # 地遠。封存列沒有 calculate_mbps 需要算速率的欄位（ddms/tdms 從沒
    # 經過 _traffic_record 寫進封存），硬湊出來的數字會叫「bandwidth」
    # 卻不是那個意思——正是這個功能要防的「看似合理但錯」。stream_query
    # 對不在這份表裡的 sort_by 一律拒絕；不要把 bandwidth alias 回來。
}


@dataclass
class ArchiveQueryResult:
    rows: list = field(default_factory=list)
    summary: list = field(default_factory=list)
    summary_omitted: int = 0
    truncated: bool = False
    matched: int = 0
    scanned: int = 0
    unsupported: list = field(default_factory=list)


def merge_row(acc: dict | None, row: dict) -> dict:
    """同 flow_hash 的兩列合併，沿用 ArchiveImporter 的 upsert 取值規則：
    volatile 欄位取 MAX、first_detected 取 MIN、raw 取較新 event_time 那一側。"""
    if acc is None:
        return dict(row)
    out = dict(acc)
    for k in _VOLATILE_MAX:
        a, b = acc.get(k), row.get(k)
        if b is not None and (a is None or b > a):
            out[k] = b
    a_fd, b_fd = acc.get("first_detected"), row.get("first_detected")
    if b_fd is not None and (a_fd is None or b_fd < a_fd):
        out["first_detected"] = b_fd
    if (row.get("event_time") or "") >= (acc.get("event_time") or ""):
        out["raw"] = row.get("raw")
    return out


def stream_query(archive_dir: str, source: str, start, end, filters: dict,
                 cap: int, sort_by: str, matcher,
                 summary_top_k: int = SUMMARY_TOP_K) -> ArchiveQueryResult:
    """掃描 [start, end] 的封存日檔，回傳有界的列與有界的摘要。

    matcher 由呼叫端提供（GUI 路徑傳 Analyzer._match_flow_filters 的包裝），
    這樣封存與快取共用同一套比對語意，不會長出第二套比對器。
    """
    # 0 是合法的 filter 值（例如 port=0）必須算「有在用」；"" 和 [] 是
    # 這個模組與呼叫端（Analyzer.query_flows，src/analyzer.py:2276-2289）
    # 預設塞滿、沒被使用者填的空值 key，不算「有在用」——跟上面
    # unsupported_filters() 的 truthy 判斷（「空值代表沒在用這個條件」）
    # 是同一套語意，這裡故意不用更寬鬆的 is not None。
    if not any(v not in (None, "", []) for v in filters.values()):
        raise ValueError("archive query needs at least one filter")

    if sort_by not in _SORT_FIELD:
        raise ValueError(
            f"archive query does not support sort_by={sort_by!r}: the archive "
            "does not carry the per-flow interval fields (ddms/tdms) a rate "
            "is computed from, so only 'volume' and 'connections' are "
            "supported here"
        )
    key = _SORT_FIELD[sort_by]
    merged: dict[str, dict] = {}
    scanned = 0
    for row in iter_archive_rows(archive_dir, source, start, end):
        scanned += 1
        if not matcher(row):
            continue
        fh = row.get("flow_hash")
        if fh is None:
            continue
        merged[fh] = merge_row(merged.get(fh), row)

    res = ArchiveQueryResult(scanned=scanned, matched=len(merged))

    # 列：全域排序後取前 cap（heapq.nlargest 內部就是 cap 大小的 heap）
    res.rows = heapq.nlargest(cap, merged.values(), key=key)
    res.truncated = len(merged) > cap

    # 摘要：group by src/dst/port/proto，同樣取有界的 top-K
    groups: dict[tuple, dict] = {}
    for r in merged.values():
        gk = (r.get("src_ip"), r.get("dst_ip"), r.get("port"), r.get("protocol"))
        g = groups.setdefault(gk, {"src_ip": gk[0], "dst_ip": gk[1], "port": gk[2],
                                   "protocol": gk[3], "flow_count": 0,
                                   "bytes_in": 0, "bytes_out": 0})
        g["flow_count"] += r.get("flow_count") or 0
        g["bytes_in"] += r.get("bytes_in") or 0
        g["bytes_out"] += r.get("bytes_out") or 0
    res.summary = heapq.nlargest(summary_top_k, groups.values(), key=key)
    res.summary_omitted = max(0, len(groups) - summary_top_k)
    return res
