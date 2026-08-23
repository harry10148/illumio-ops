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
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterator

import orjson
from loguru import logger

_DAY_FILE = re.compile(r"^(?P<source>[a-z_]+)-(?P<day>\d{4}-\d{2}-\d{2})\.jsonl(?P<gz>\.gz)?$")


def _matching_files(archive_dir: str, source: str, start: date, end: date) -> list[str]:
    """[start, end]（含端點）內該 source 的日檔，依日期排序；同一天若兩種
    副檔名都在，兩個都回傳（.gz 在前、.jsonl 在後）。

    `ArchiveExporter._gzip_old_files()`（src/pce_cache/archive.py:204-232）
    在既有 .gz 存在時是用 "ab" 把新內容當一個新的 gzip member **附加**進去，
    寫完才刪掉 .jsonl——所以同一天可能長期同時存在兩個檔：.gz 裝著上次
    gzip 之前的全部內容，.jsonl 只裝這次 gzip 之後新收到的那一批（例如
    遲到的匯出在已經 gzip 過的舊日期又建了新檔）。只取 .jsonl 會把 .gz
    裡的歷史整批漏掉；兩個都讀，交給呼叫端的 flow_hash merge 去對帳
    重複列（multi-member gzip 對標準工具是透明解壓，不需要特別處理）。
    """
    try:
        names = sorted(os.listdir(archive_dir))
    except OSError:
        return []
    by_day: dict[str, dict[bool, str]] = {}
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
        by_day.setdefault(key, {})[bool(m.group("gz"))] = os.path.join(archive_dir, name)
    result: list[str] = []
    for k in sorted(by_day):
        paths = by_day[k]
        if True in paths:
            result.append(paths[True])  # .gz：較舊、gzip 輪替之前累積的整批
        if False in paths:
            result.append(paths[False])  # .jsonl：這次 gzip 輪替之後的新批
    return result


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

# 「這個 query 有沒有指定至少一個窄化條件」的守門要看白名單，不能看
# filters 裡「隨便哪個 key 有值」——Task 4 會把整包查詢參數轉成 filters
# dict 傳進來，裡面混著 sort_by／source／policy_decisions（預設四值全給）
# 這類控制欄位，這些欄位一定有值，看「有沒有任何 key 有值」形同虛設。
#
# 這份清單抄 Analyzer.query_flows 的 query_filters dict
# （src/analyzer.py 內 "port" 開始到 "ex_any_workload" 結束那段，約
# :2220-2289）扣掉唯一的控制欄位 sort_by。draft_policy_decision／
# label_group／AMS 系列封存端評估不了（見 UNSUPPORTED_ARCHIVE_FILTER_KEYS），
# 但仍算「有意圖窄化」——該由 unsupported_filters() 給出更精確的「不支援」
# 錯誤，不該被這裡的 guard 誤判成「完全沒給條件」。
#
# 額外加 "action"：analyzer 把 policy-decision 過濾放在 query_flows 的
# 頂層 policy_decisions 參數（預設四值全給，屬控制欄位不算窄化）而非
# query_filters 裡，但封存列本身有 action 欄位可比對；Task 4 若要開放
# 依 action 窄化封存查詢，key 名稱是這個。
_NARROWING_FILTER_KEYS: tuple[str, ...] = (
    "port", "proto", "port_range", "ex_port", "ex_port_range",
    "services", "ex_services", "ports", "ex_ports",
    "process_name", "ex_process_name",
    "windows_service_name", "ex_windows_service_name",
    "src_label", "src_label_group", "src_label_groups",
    "dst_label", "dst_label_group", "dst_label_groups",
    "src_ip_in", "dst_ip_in",
    "ex_src_label", "ex_src_label_group", "ex_src_label_groups",
    "ex_dst_label", "ex_dst_label_group", "ex_dst_label_groups",
    "ex_src_ip", "ex_dst_ip",
    "any_label", "any_ip", "ex_any_label", "ex_any_ip",
    "src_ams", "dst_ams", "ex_src_ams", "ex_dst_ams",
    "transmission_excludes", "transmission",
    "src_include_groups", "dst_include_groups",
    "search", "draft_policy_decision",
    "src_labels", "dst_labels", "ex_src_labels", "ex_dst_labels",
    "src_iplist", "src_iplists", "dst_iplist", "dst_iplists",
    "ex_src_iplists", "ex_dst_iplists",
    "src_workloads", "dst_workloads", "ex_src_workloads", "ex_dst_workloads",
    "any_iplist", "any_workload", "ex_any_iplist", "ex_any_workload",
    "action",
)

# 25s：常見 gunicorn/uwsgi worker timeout 是 30s，留緩衝讓 stream_query
# 自己先回傳部分結果，而不是被 worker 直接砍斷、什麼都拿不到。專案裡
# 沒有既有的「web 請求逾時」常數可抄，這個數字是本次新訂、非查證得來的
# 預設值——deadline_s 是參數，呼叫端可覆寫。
_DEFAULT_DEADLINE_S = 25.0


def _is_valid_row(row) -> bool:
    """封存列的最低限度結構驗證：語法合法的 JSON 不保證是一筆 flow——
    `[]`、裸字串、counters 是字串的物件都能通過 orjson.loads，但會在
    merge_row 的數值比較（`b > a`）或摘要加總（`+=`）炸出
    AttributeError/TypeError，讓整個 [start, end] 掃描失敗。只驗證會被
    下游算術/合併碰到的欄位；其餘欄位維持 dict.get() 的寬鬆讀法（缺欄位
    不算錯，只是那個維度沒資料）。"""
    if not isinstance(row, dict):
        return False
    fh = row.get("flow_hash")
    if not isinstance(fh, str) or not fh:
        return False
    for k in ("flow_count", "bytes_in", "bytes_out"):
        v = row.get(k)
        if v is not None and not isinstance(v, (int, float)):
            return False
    return True


@dataclass
class ArchiveQueryResult:
    rows: list = field(default_factory=list)
    summary: list = field(default_factory=list)
    summary_omitted: int = 0
    truncated: bool = False
    matched: int = 0
    scanned: int = 0
    skipped: int = 0
    incomplete_after: date | None = None
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
                 summary_top_k: int = SUMMARY_TOP_K,
                 deadline_s: float | None = _DEFAULT_DEADLINE_S) -> ArchiveQueryResult:
    """掃描 [start, end] 的封存日檔，回傳有界的列與有界的摘要。

    matcher 由呼叫端提供（GUI 路徑傳 Analyzer._match_flow_filters 的包裝），
    這樣封存與快取共用同一套比對語意，不會長出第二套比對器。

    **先合併、再比對**：`flow_hash` 只涵蓋 src/dst ip、port、proto、
    first_detected（`ingestor_traffic._flow_hash`），policy_decision／
    labels／process 都不在裡面——同一個 flow 後來的快照可以改掉正是
    filter 在測的那些欄位。如果先比對再合併，一個較舊、曾經符合條件的
    快照可能被留下，而較新、已經不符合的快照被丟棄，回報一筆過期的
    答案。所以這裡對整個 [start, end] 先把每個 flow_hash 合併成最終
    狀態，才對合併結果跑一次 matcher。代價：會合併到最後被 matcher
    丟掉的列（例如整個 flow 從沒符合過任何 filter），但這是換取正確性
    必須付的成本，沒有更便宜的等價做法。
    """
    if not any(filters.get(k) not in (None, "", []) for k in _NARROWING_FILTER_KEYS):
        raise ValueError("archive query needs at least one narrowing filter")

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
    skipped = 0
    clock = time.monotonic
    t0 = clock()
    day = start
    last_completed: date | None = None
    while day <= end:
        for row in iter_archive_rows(archive_dir, source, day, day):
            scanned += 1
            if not _is_valid_row(row):
                skipped += 1
                continue
            fh = row["flow_hash"]
            merged[fh] = merge_row(merged.get(fh), row)
        last_completed = day
        # 只在日檔之間檢查時鐘（不逐列檢查）——便宜，且不會把一天的檔案
        # 掃到一半就砍斷。
        if deadline_s is not None and (clock() - t0) >= deadline_s:
            break
        day += timedelta(days=1)

    res = ArchiveQueryResult(scanned=scanned, skipped=skipped)
    if last_completed is not None and last_completed < end:
        res.incomplete_after = last_completed

    # 先合併完才比對：matcher 看到的是每個 flow_hash 的最終狀態
    matched_rows = {fh: r for fh, r in merged.items() if matcher(r)}
    res.matched = len(matched_rows)

    # 列：全域排序後取前 cap（heapq.nlargest 內部就是 cap 大小的 heap）
    res.rows = heapq.nlargest(cap, matched_rows.values(), key=key)
    res.truncated = len(matched_rows) > cap

    # 摘要：group by src/dst/port/proto，同樣取有界的 top-K
    groups: dict[tuple, dict] = {}
    for r in matched_rows.values():
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
