# 2F-1 流量調閱資料來源與封存串流查詢 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓操作者在流量調閱頁明確選擇資料來源（快取優先／直接查 PCE／封存），並把封存查詢從「先匯入 review DB」改成「直接串流掃描日檔」，使「隨意載入一堆資料」這件事不存在。

**Architecture:** 純 API 的能力已存在於 `Analyzer._fetch_flows`，只缺入口，所以來源選擇器是接線。封存則新增 `src/pce_cache/archive_query.py`：接收 `archive_import.py` 既有的 gzip-aware 逐列讀取器與日期挑檔函式，逐列比對後以 `flow_hash` 合併、用固定大小的 top-N heap 取列、固定基數的 top-K 產摘要。**列比對沿用 `Analyzer._match_flow_filters`**，餵給它的是封存列的 `raw` 欄位——那與 `CacheReader.read_flows_raw` 回傳的形狀相同（都是 PCE 原始 payload），所以不會出現第二套比對器。review DB 整條路徑移除。

**Tech Stack:** Python 3.12 / Flask / SQLAlchemy 2.x / orjson / 原生 ES modules（`src/static/js/v2/`）/ pytest + Playwright

**Spec:** `docs/superpowers/specs/2026-08-23-2f1-traffic-source-and-archive-query-design.md`

## Global Constraints

- **Commit 訊息用英文 conventional-commits**；計畫與說明文件用繁體中文。
- **虛擬環境是 `./venv`**（不是 `.venv`）。測試一律**前景執行並帶 timeout**，禁止背景或輪詢。
- **i18n 三份字典要同步**：`src/i18n_zh_TW.json`、`src/i18n_en.json`、`src/i18n/data/zh_explicit.json`。三者皆以 `json.dumps(d, indent=2, ensure_ascii=False) + "\n"` 精確 round-trip。漏改 `zh_explicit` 會在下次 precompute 被機器翻譯覆蓋。
- **新文案不得帶工程敘述**：不寫 HTTP 端點、狀態碼、「後端／前端」、內部欄位名。守門測試 `tests/test_i18n_no_reviewer_copy.py` 會擋。
- **每個任務結束前這三個閘門必須綠 / 0**：
  - `timeout 300 ./venv/bin/python scripts/audit_i18n_usage.py` → `Total: 0 finding(s)`
  - `timeout 300 ./venv/bin/python -m pytest tests/test_i18n_no_reviewer_copy.py tests/test_i18n_zh_explicit_sync.py -q`
- **不得產生第二套 flow×filter 比對器。** 封存列的比對一律走 `Analyzer._match_flow_filters`，輸入是封存列的 `raw` 欄位。這是本專案被咬過的坑（2026-07-24 審查 M4）。
- **截斷不可無聲**：任何被 cap／top-K 截掉的結果都必須在回應中標明，前端必須顯示。既有 `QUERY_RESULT_CAP = 500` 的註解已明訂此紀律。
- 既有 dead code 不要順手清；只改與該任務直接相關的行。
- 全套測試由 orchestrator 在任務之間自己跑；實作者只跑該任務的覆蓋測試。

---

## 檔案結構

| 檔案 | 責任 |
|---|---|
| `src/pce_cache/archive_query.py`（新增） | 封存串流查詢的全部邏輯：挑檔、逐列讀、比對、合併、top-N、top-K 摘要 |
| `src/pce_cache/archive_import.py`（縮減後刪除） | 現有的 review DB 匯入。`_iter_lines` / `_matching_traffic_files` 先搬進 `archive_query.py`，其餘於 Task 7 整檔刪除 |
| `src/gui/routes/actions.py` | `/api/quarantine/search`：接 `data_source`、封存改走串流、回報實際路徑 |
| `src/analyzer.py` | `query_flows` 尊重明示的來源偏好；回報實際走了哪條路 |
| `src/static/js/v2/areas/investigate.mjs` | 三選一來源選擇器、封存日期區間、截斷與摘要的呈現 |
| `src/pce_cache/web.py` | 移除 `POST /archive/load` |
| `src/static/js/v2/areas/system.mjs` | 移除封存載入 UI |

---

### Task 1: 封存檔的挑檔與逐列讀取（含 gzip）

**Files:**
- Create: `src/pce_cache/archive_query.py`
- Test: `tests/test_archive_query.py`（新建）

**Interfaces:**
- Consumes: 無（本任務把 `archive_import.py` 的兩個私有函式搬過來，原檔暫時保留，Task 7 才刪）
- Produces: `iter_archive_rows(archive_dir: str, source: str, start: date, end: date) -> Iterator[dict]` — 依序產出該區間內每個日檔的每一列（已 `orjson.loads`）。壞檔只記 warning 並跳過該檔剩餘部分。

- [ ] **Step 1: 寫失敗測試**

新建 `tests/test_archive_query.py`：

```python
"""封存串流查詢：檔案層。

封存檔超過 `archive_gzip_after_days`（預設 7）就會被 `_gzip_old_files()`
原地換成 .jsonl.gz，而本功能的核心情境是「PCE 只留三個月，三個月後來這裡
查」——那個時間點的資料必然只有 .gz。只開 .jsonl 會把實際存在的資料回報成
「沒有封存資料」。
"""
from __future__ import annotations

import gzip
import json
from datetime import date

from src.pce_cache.archive_query import iter_archive_rows


def _write(tmp_path, name, rows, *, gz=False):
    p = tmp_path / name
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    if gz:
        with gzip.open(p, "wb") as fh:
            fh.write(body.encode("utf-8"))
    else:
        p.write_text(body, encoding="utf-8")
    return p


def test_reads_plain_and_gzipped_days(tmp_path):
    _write(tmp_path, "traffic-2026-05-01.jsonl.gz", [{"flow_hash": "a"}], gz=True)
    _write(tmp_path, "traffic-2026-05-02.jsonl", [{"flow_hash": "b"}])
    got = [r["flow_hash"] for r in iter_archive_rows(
        str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 2))]
    assert got == ["a", "b"]


def test_days_outside_the_range_are_not_opened(tmp_path):
    _write(tmp_path, "traffic-2026-04-30.jsonl", [{"flow_hash": "before"}])
    _write(tmp_path, "traffic-2026-05-01.jsonl", [{"flow_hash": "in"}])
    _write(tmp_path, "traffic-2026-05-03.jsonl", [{"flow_hash": "after"}])
    got = [r["flow_hash"] for r in iter_archive_rows(
        str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 2))]
    assert got == ["in"]


def test_a_truncated_gz_does_not_abort_the_whole_scan(tmp_path):
    (tmp_path / "traffic-2026-05-01.jsonl.gz").write_bytes(b"not actually gzip")
    _write(tmp_path, "traffic-2026-05-02.jsonl", [{"flow_hash": "survivor"}])
    got = [r["flow_hash"] for r in iter_archive_rows(
        str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 2))]
    assert got == ["survivor"]


def test_a_bad_line_is_skipped_not_fatal(tmp_path):
    p = tmp_path / "traffic-2026-05-01.jsonl"
    p.write_text('{"flow_hash": "ok"}\nnot json\n{"flow_hash": "ok2"}\n', encoding="utf-8")
    got = [r["flow_hash"] for r in iter_archive_rows(
        str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1))]
    assert got == ["ok", "ok2"]


def test_missing_directory_yields_nothing(tmp_path):
    assert list(iter_archive_rows(
        str(tmp_path / "nope"), "traffic", date(2026, 5, 1), date(2026, 5, 1))) == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 300 ./venv/bin/python -m pytest tests/test_archive_query.py -q`
Expected: FAIL —`ModuleNotFoundError: No module named 'src.pce_cache.archive_query'`

- [ ] **Step 3: 實作**

新建 `src/pce_cache/archive_query.py`。`_iter_lines` 與挑檔邏輯是從 `src/pce_cache/archive_import.py` **搬過來的**（該檔的 `_iter_lines` 在 `:52-63`、`_matching_traffic_files` 在 `:66` 起）——先讀那兩個函式，照抄其行為（gzip 判斷、壞檔 warning 後放棄該檔剩餘、目錄不存在回空），只把「只認 traffic」一般化成吃 `source` 參數：

```python
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
```

- [ ] **Step 4: 測試通過**

Run: `timeout 300 ./venv/bin/python -m pytest tests/test_archive_query.py -q`
Expected: PASS（5 條）

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache/archive_query.py tests/test_archive_query.py
git commit -m "feat(archive): stream archive day files, gzipped ones included"
```

---

### Task 2: 篩選白名單與列比對

**Files:**
- Modify: `src/pce_cache/archive_query.py`
- Test: `tests/test_archive_query.py`

**Interfaces:**
- Consumes: Task 1 的 `iter_archive_rows`
- Produces:
  - `UNSUPPORTED_ARCHIVE_FILTER_KEYS: tuple[str, ...]` — 封存查不到的 filter key
  - `unsupported_filters(filters: dict) -> list[str]` — 回傳請求中命中黑名單且有值的 key（排序）

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_archive_query.py` 末尾加：

```python
from src.pce_cache.archive_query import unsupported_filters


def test_label_group_and_ams_filters_are_rejected():
    got = unsupported_filters({"src_label_groups": ["x"], "dst_ams": ["y"], "port": 443})
    assert got == ["dst_ams", "src_label_groups"]


def test_draft_policy_decision_is_rejected():
    assert unsupported_filters({"draft_policy_decision": "allowed"}) == ["draft_policy_decision"]


def test_empty_values_do_not_count_as_used():
    assert unsupported_filters({"src_label_groups": [], "dst_ams": None}) == []


def test_evaluable_filters_pass():
    assert unsupported_filters({"port": 443, "src_ip": "10.0.0.1"}) == []


def test_the_blacklist_covers_every_analyzer_unevaluable_key():
    """analyzer 已經維護了一份『cache 端無法評估』的清單；封存是更嚴格的
    離線情境，不得比它寬鬆。這條在 analyzer 新增 key 時會紅。"""
    from src.analyzer import _CACHE_UNEVALUABLE_FILTER_KEYS
    from src.pce_cache.archive_query import UNSUPPORTED_ARCHIVE_FILTER_KEYS
    missing = set(_CACHE_UNEVALUABLE_FILTER_KEYS) - set(UNSUPPORTED_ARCHIVE_FILTER_KEYS)
    assert missing == set(), f"archive blacklist is looser than the cache's: {sorted(missing)}"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 300 ./venv/bin/python -m pytest tests/test_archive_query.py -q -k "unsupported or blacklist or rejected or evaluable"`
Expected: FAIL —`ImportError: cannot import name 'unsupported_filters'`

- [ ] **Step 3: 實作**

在 `src/pce_cache/archive_query.py` 加入：

```python
from src.analyzer import _CACHE_UNEVALUABLE_FILTER_KEYS

# 封存是離線資料：沒有 PCE 可問，所以任何需要向 PCE 展開或即時計算的條件
# 都判不了。analyzer 已維護一份 cache 端無法評估的清單（label group / AMS），
# 封存至少要涵蓋它；額外多一個 draft_policy_decision——那是即時查詢才算得出
# 來的欄位，封存列裡根本不存在。
#
# 帶著這些條件靜默回未過濾的結果，正是 2026-07-24 審查 M4 抓到的缺陷；
# 這裡明確拒絕。
UNSUPPORTED_ARCHIVE_FILTER_KEYS: tuple[str, ...] = (
    tuple(_CACHE_UNEVALUABLE_FILTER_KEYS) + ("draft_policy_decision",)
)


def unsupported_filters(filters: dict) -> list[str]:
    """請求中命中黑名單且**有值**的 key（排序）。空值代表沒在用這個條件。"""
    return sorted(k for k in UNSUPPORTED_ARCHIVE_FILTER_KEYS if filters.get(k))
```

- [ ] **Step 4: 測試通過**

Run: `timeout 300 ./venv/bin/python -m pytest tests/test_archive_query.py -q`
Expected: PASS（10 條）

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache/archive_query.py tests/test_archive_query.py
git commit -m "feat(archive): refuse filters the archive cannot evaluate offline"
```

---

### Task 3: 合併、排序截斷與有界摘要

**Files:**
- Modify: `src/pce_cache/archive_query.py`
- Test: `tests/test_archive_query.py`

**Interfaces:**
- Consumes: Task 1 的 `iter_archive_rows`
- Produces:
  - `merge_row(acc: dict | None, row: dict) -> dict` — 同 `flow_hash` 的合併
  - `SUMMARY_TOP_K: int = 500`
  - `stream_query(archive_dir, source, start, end, filters, cap, sort_by, matcher) -> ArchiveQueryResult`
  - `ArchiveQueryResult`：`rows` / `summary` / `summary_omitted` / `truncated` / `matched` / `scanned` / `unsupported`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_archive_query.py` 末尾加：

```python
from src.pce_cache.archive_query import merge_row, stream_query


def _row(fh, **kw):
    base = {"flow_hash": fh, "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2",
            "port": 443, "protocol": "tcp", "action": "allowed",
            "flow_count": 1, "bytes_in": 100, "bytes_out": 200,
            "first_detected": "2026-05-01T00:00:00+00:00",
            "event_time": "2026-05-01T01:00:00+00:00", "raw": {}}
    base.update(kw)
    return base


def test_merge_takes_max_of_volatile_fields_and_min_of_first_detected():
    """封存檔不是唯一列集合：長壽 flow 更新時會再次匯出，崩潰重跑也會重寫
    整批。ArchiveImporter 因此用 MAX/MIN upsert；串流不合併就會重複計數。"""
    a = _row("h", flow_count=3, bytes_in=10, bytes_out=20,
             first_detected="2026-05-01T05:00:00+00:00",
             event_time="2026-05-01T05:00:00+00:00")
    b = _row("h", flow_count=7, bytes_in=5, bytes_out=90,
             first_detected="2026-05-01T02:00:00+00:00",
             event_time="2026-05-01T09:00:00+00:00")
    m = merge_row(merge_row(None, a), b)
    assert m["flow_count"] == 7
    assert m["bytes_in"] == 10
    assert m["bytes_out"] == 90
    assert m["first_detected"] == "2026-05-01T02:00:00+00:00"
    assert m["event_time"] == "2026-05-01T09:00:00+00:00"


def test_duplicate_exports_do_not_inflate_the_summary(tmp_path):
    _write(tmp_path, "traffic-2026-05-01.jsonl", [
        _row("h", flow_count=3, bytes_in=10, bytes_out=20),
        _row("h", flow_count=7, bytes_in=10, bytes_out=20),
    ])
    res = stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1),
                       {"port": 443}, cap=10, sort_by="connections",
                       matcher=lambda r: True)
    assert res.matched == 1
    assert len(res.rows) == 1
    assert res.summary[0]["flow_count"] == 7


def test_cap_keeps_the_globally_heaviest_not_the_first_seen(tmp_path):
    """現行 query_flows 是排序全部命中再取前 N。用檔案順序取前 N 會漏掉
    後面日期檔裡的大流量——這條測試就是為了讓那種實作失敗。"""
    _write(tmp_path, "traffic-2026-05-01.jsonl",
           [_row(f"small{i}", flow_count=1) for i in range(5)])
    _write(tmp_path, "traffic-2026-05-02.jsonl", [_row("huge", flow_count=999)])
    res = stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 2),
                       {"port": 443}, cap=2, sort_by="connections",
                       matcher=lambda r: True)
    assert res.truncated is True
    assert res.rows[0]["flow_hash"] == "huge"
    assert len(res.rows) == 2


def test_summary_cardinality_is_bounded_and_reports_what_it_dropped(tmp_path):
    _write(tmp_path, "traffic-2026-05-01.jsonl",
           [_row(f"h{i}", port=1000 + i) for i in range(50)])
    res = stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1),
                       {"port": 0}, cap=100, sort_by="connections",
                       matcher=lambda r: True, summary_top_k=10)
    assert len(res.summary) == 10
    assert res.summary_omitted == 40


def test_matcher_decides_what_counts_as_a_hit(tmp_path):
    _write(tmp_path, "traffic-2026-05-01.jsonl",
           [_row("keep", port=443), _row("drop", port=80)])
    res = stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1),
                       {"port": 443}, cap=10, sort_by="connections",
                       matcher=lambda r: r.get("port") == 443)
    assert [r["flow_hash"] for r in res.rows] == ["keep"]
    assert res.scanned == 2


def test_a_query_with_no_filters_is_refused(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        stream_query(str(tmp_path), "traffic", date(2026, 5, 1), date(2026, 5, 1),
                     {}, cap=10, sort_by="connections", matcher=lambda r: True)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 300 ./venv/bin/python -m pytest tests/test_archive_query.py -q -k "merge or cap or summary or matcher or refused or inflate"`
Expected: FAIL —`ImportError: cannot import name 'merge_row'`

- [ ] **Step 3: 實作**

在 `src/pce_cache/archive_query.py` 加入。合併規則照抄 `src/pce_cache/archive_import.py:176-196` 的 upsert 語意（實作前讀那段），排序鍵沿用 `analyzer.py` 的 `sort_by` 三值：

```python
import heapq
from dataclasses import dataclass, field

SUMMARY_TOP_K = 500

_VOLATILE_MAX = ("flow_count", "bytes_in", "bytes_out", "event_time", "ingested_at")

_SORT_FIELD = {
    "bandwidth": lambda r: (r.get("bytes_in") or 0) + (r.get("bytes_out") or 0),
    "volume": lambda r: (r.get("bytes_in") or 0) + (r.get("bytes_out") or 0),
    "connections": lambda r: r.get("flow_count") or 0,
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
    if not any(v for v in filters.values()):
        raise ValueError("archive query needs at least one filter")

    key = _SORT_FIELD.get(sort_by, _SORT_FIELD["connections"])
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
```

> **已知取捨，寫進報告即可**：`merged` 與 `groups` 仍是 O(命中列數) 的記憶體。真正的 O(1) 記憶體需要兩趟掃描或近似演算法。本任務把**回傳值**限制成有界（這是 API 契約），記憶體的有界化列為後續事項——實作者不要自行擴大範圍去做它。

- [ ] **Step 4: 測試通過**

Run: `timeout 600 ./venv/bin/python -m pytest tests/test_archive_query.py -q`
Expected: PASS（16 條）

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache/archive_query.py tests/test_archive_query.py
git commit -m "feat(archive): merge duplicate exports, keep the heaviest, bound the summary"
```

---

### Task 4: 把封存來源接上串流查詢

**Files:**
- Modify: `src/gui/routes/actions.py`（`api_quarantine_search`，`source == "archive"` 分支約 `:92-110`）
- Modify: `src/i18n_zh_TW.json`、`src/i18n_en.json`、`src/i18n/data/zh_explicit.json`
- Test: `tests/test_actions_archive_source.py`（既有檔，加測試）

**Interfaces:**
- Consumes: Task 2 的 `unsupported_filters`、Task 3 的 `stream_query`
- Produces: `POST /api/quarantine/search` 在 `source == "archive"` 時回 `{"ok": true, "rows": [...], "summary": [...], "summary_omitted": n, "truncated": bool, "matched": n, "scanned": n, "actual_source": "archive"}`；帶不支援的 filter 時回 400 與 `unsupported` 清單。

- [ ] **Step 1: 寫失敗測試**

先讀 `tests/test_actions_archive_source.py` 現有的 fixture 與 client 建法，照抄其慣例，在末尾加：

```python
def test_archive_source_rejects_filters_it_cannot_evaluate(authed_client):
    client, csrf = authed_client
    res = client.post("/api/quarantine/search",
                      json={"source": "archive", "src_label_groups": ["g1"],
                            "archive_start": "2026-05-01", "archive_end": "2026-05-01"},
                      headers={"X-CSRFToken": csrf},
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert res.status_code == 400
    body = res.get_json()
    assert body["ok"] is False
    assert "src_label_groups" in body["unsupported"]


def test_archive_source_requires_a_date_range(authed_client):
    client, csrf = authed_client
    res = client.post("/api/quarantine/search",
                      json={"source": "archive", "port": 443},
                      headers={"X-CSRFToken": csrf},
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert res.status_code == 400
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 600 ./venv/bin/python -m pytest tests/test_actions_archive_source.py -q`
Expected: FAIL（目前回 200，且無 `unsupported` 欄位）

- [ ] **Step 3: 實作**

`src/gui/routes/actions.py` 的 `source == "archive"` 分支整段改寫：不再建 review DB reader，改為

1. 解析 `archive_start` / `archive_end`（`date.fromisoformat`），缺任一個或格式錯 → 400，訊息用新 i18n 鍵 `gui_err_archive_range_required`
2. `unsupported_filters(...)` 非空 → 400，回 `{"ok": False, "unsupported": [...], "error": t("gui_err_archive_filter_unsupported")}`
3. 建立 matcher：沿用既有 Analyzer 實例，把 `rule` 依現行 `query_flows` 的組法建好（讀 `analyzer.py` 約 `:2328` 那段的 `rule` 組法照抄），matcher 為 `lambda row: base_ana._match_flow_filters(rule, row.get("raw") or {}, start_dt)`
4. 呼叫 `stream_query(cm.models.pce_cache.archive_dir, "traffic", start, end, filters, QUERY_RESULT_CAP, sort_by, matcher)`
5. 回應加 `actual_source: "archive"`

新 i18n 鍵（三份字典）：

| key | zh_TW | en |
|---|---|---|
| `gui_err_archive_range_required` | 查詢封存需要指定日期區間。 | Searching the archive needs a date range. |
| `gui_err_archive_filter_unsupported` | 這些條件需要即時向 PCE 查詢才能判定，封存裡查不到：{keys} | These conditions can only be resolved by asking the PCE directly, so the archive cannot answer them: {keys} |

- [ ] **Step 4: 測試與閘門通過**

```bash
timeout 600 ./venv/bin/python -m pytest tests/test_actions_archive_source.py tests/test_archive_query.py -q
timeout 300 ./venv/bin/python -m pytest tests/test_i18n_no_reviewer_copy.py tests/test_i18n_zh_explicit_sync.py -q
timeout 300 ./venv/bin/python scripts/audit_i18n_usage.py
```
Expected: 全綠；audit `Total: 0 finding(s)`

- [ ] **Step 5: Commit**

```bash
git add src/gui/routes/actions.py src/i18n_zh_TW.json src/i18n_en.json src/i18n/data/zh_explicit.json tests/test_actions_archive_source.py
git commit -m "feat(gui): search the archive by streaming its day files"
```

---

### Task 5: 明示的資料來源偏好與實際路徑回報

**Files:**
- Modify: `src/analyzer.py`（`_fetch_flows` 的 `cover_state` 判斷處，約 `:2070-2100`；`query_flows` 的 `last_query_stats`，約 `:2201`）
- Modify: `src/gui/routes/actions.py`（把 `data_source` 傳進去、回應帶 `actual_source`）
- Test: `tests/test_traffic_data_source.py`（新建）

**Interfaces:**
- Consumes: `src/report/cache_support.py` 的 `resolve_data_source(value, cache_ok) -> (use_cache, clip_to_cache, warning)`
- Produces: `Analyzer.query_flows` 接受 `params["data_source"]`；`Analyzer.last_query_stats["actual_source"]` 為 `"cache"` / `"api"` / `"mixed"`

- [ ] **Step 1: 寫失敗測試**

新建 `tests/test_traffic_data_source.py`。用該 repo 既有的 Analyzer 測試慣例（`grep -rn "Analyzer(" tests/ | head` 找最近的範例照抄 fixture 與 stub 建法）。要涵蓋：

- `data_source="live"` 時，即使 `cover_state` 回 `"full"`，也**不得**讀 cache（stub 的 `read_flows_raw` 不可被呼叫），且 `actual_source == "api"`
- `data_source="hybrid"`（或未指定）維持現行行為：`cover_state == "full"` 時走 cache，`actual_source == "cache"`
- `cover_state == "partial"` 且 hybrid 時 `actual_source == "mixed"`

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 600 ./venv/bin/python -m pytest tests/test_traffic_data_source.py -q`
Expected: FAIL —`live` 仍走 cache；無 `actual_source`

- [ ] **Step 3: 實作**

`_fetch_flows` 開頭插入：操作者明示 `live` 時直接走 `execute_traffic_query_stream` 並記 `actual_source="api"`，跳過 `cover_state` 判斷；其餘維持現行邏輯，但在三個既有分支（cache 全覆蓋、API、partial 合併）各自記下 `actual_source`。`query_flows` 的 `last_query_stats` 加上該欄位並由端點回傳。

- [ ] **Step 4: 測試通過**

Run: `timeout 900 ./venv/bin/python -m pytest tests/test_traffic_data_source.py tests/test_actions_archive_source.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/analyzer.py src/gui/routes/actions.py tests/test_traffic_data_source.py
git commit -m "feat(analyzer): honour an explicit data source and report the one used"
```

---

### Task 6: 前端三選一來源、封存日期區間與截斷呈現

**Files:**
- Modify: `src/static/js/v2/areas/investigate.mjs`（`SOURCES` 於 `:156`；traffic 面板的查詢送出與結果呈現）
- Modify: 三份 i18n 字典
- Test: `tests/test_v2_investigate_e2e.py`

**Interfaces:**
- Consumes: Task 4／5 的回應欄位 `actual_source` / `truncated` / `summary_omitted` / `unsupported`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_v2_investigate_e2e.py` 末尾加測試：選「封存」時出現日期區間欄位；送出的請求帶 `data_source` 與 `archive_start` / `archive_end`；回應帶 `truncated` 時畫面出現截斷提示。照該檔既有的 `_goto` / `_labels` / `page.route` 慣例寫（實作前先讀）。

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 1800 ./venv/bin/python -m pytest tests/test_v2_investigate_e2e.py -q -k "source or archive"`

- [ ] **Step 3: 實作**

`SOURCES` 改為三項：`[["hybrid","gui_traffic_source_hybrid"],["live","gui_traffic_source_api"],["archive","gui_traffic_source_archive"]]`。選「封存」時顯示兩個日期輸入。請求帶 `data_source`（前兩者）或 `source:"archive"` ＋ 日期。結果區顯示 `actual_source`、截斷提示與摘要省略計數；`unsupported` 回來時把那些條件標出來。

新 i18n 鍵（三份字典）：`gui_traffic_source_hybrid`（快取優先／Cache first）、`gui_traffic_source_api`（直接查 PCE／Query the PCE directly）、`gui_traffic_truncated`、`gui_traffic_summary_omitted`、`gui_traffic_actual_source_*` 三個。文案不得帶端點或欄位名。

- [ ] **Step 4: 測試與閘門通過**

```bash
timeout 1800 ./venv/bin/python -m pytest tests/test_v2_investigate_e2e.py -q
timeout 300 ./venv/bin/python scripts/audit_i18n_usage.py
timeout 300 ./venv/bin/python -m pytest tests/test_i18n_no_reviewer_copy.py tests/test_i18n_zh_explicit_sync.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/static/js/v2/areas/investigate.mjs src/i18n_zh_TW.json src/i18n_en.json src/i18n/data/zh_explicit.json tests/test_v2_investigate_e2e.py
git commit -m "feat(gui-v2): choose the traffic data source, and say which one answered"
```

---

### Task 7: 移除封存載入路徑

**Files:**
- Delete: `src/pce_cache/archive_import.py`、`tests/test_pce_cache_archive_import.py`
- Modify: `src/pce_cache/web.py`（`POST /archive/load`，約 `:298-328`）
- Modify: `src/static/js/v2/areas/system.mjs`（封存載入 UI）、`src/static/js/v2/core/store-map.mjs`（若有對應條目）
- Modify: `src/config.py`（`_DEPRECATED_KEY_PATHS` 加 `pce_cache.archive_review_max_days`）、`src/config_models.py`（移除該欄位）
- Test: `tests/test_config_deprecated_keys.py`、`tests/test_archive_query.py`

**Interfaces:**
- Consumes: 前六個任務已讓封存查詢不再需要 review DB

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_config_deprecated_keys.py` 加一條：帶 `pce_cache.archive_review_max_days` 的舊 config 仍能載入且該鍵被丟棄（照該檔既有 `test_strip_removes_pce_profile_keys_in_place` 的寫法）。

在 `tests/test_archive_query.py` 加移除守門（比照 `tests/test_config_models.py` 的命名守門寫法，用集合相等）：

```python
def test_the_review_db_path_is_gone():
    """封存查閱不再匯入 review DB；殘留的符號代表某條路徑還在用它。"""
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parents[1]
    pat = re.compile(r"load_archive_review|start_archive_load|review_db_path|archive_review_max_days")
    hits = []
    for sub in ("src", "tests"):
        for p in (root / sub).rglob("*.py"):
            if p.name == pathlib.Path(__file__).name:
                continue
            if pat.search(p.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(p.relative_to(root)))
    assert hits == [], f"still referencing the removed archive-load path: {hits}"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 600 ./venv/bin/python -m pytest tests/test_config_deprecated_keys.py tests/test_archive_query.py -q`
Expected: FAIL — deprecated 鍵未被丟棄；守門列出一串仍在引用的檔

- [ ] **Step 3: 實作**

依守門測試列出的清單逐一移除。**順序要緊**：先移除所有呼叫端，最後才刪 `archive_import.py` 與 `config_models` 欄位——與本 repo 移除 PCE profile 時同一條紀律（`extra="forbid"`，deprecated-key 要先認得才能刪欄位）。

- [ ] **Step 4: 測試通過**

```bash
timeout 900 ./venv/bin/python -m pytest tests/test_config_deprecated_keys.py tests/test_config_models.py tests/test_archive_query.py tests/test_actions_archive_source.py -q
```

- [ ] **Step 5: Commit**

```bash
git add -u && git add tests/
git commit -m "refactor(archive): drop the review-DB load path"
```

---

### Task 8: 全套測試、文件與 CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`、`docs/guide/gui-tour.md`、`docs/guide/configuration.md`、`docs/reference/rest-api.md`

- [ ] **Step 1: 全套測試**（orchestrator 執行）

Run: `timeout 5400 ./venv/bin/python -m pytest -q`（背景執行並掛回叫等待器；用 `pgrep -fc "(bin/pytest|-m pytest)"` 確認確實在跑——**注意等待器自己的命令列會匹配到 `pytest` 這個字**，樣式要錨定執行檔）
Expected: 0 failed

- [ ] **Step 2: CHANGELOG**

`### Added` 記三選一來源與封存串流查詢；`### Removed` 記封存載入與 `archive_review_max_days`，並明說**既有的 review DB 會失效**。照既有條目的散文語氣寫，不要列檔名。

- [ ] **Step 3: 文件**

`configuration.md` 的 `pce_cache` 段移除 `archive_review_max_days`、加上「封存查詢不再需要載入」；`gui-tour.md` 的調查頁段落補三選一來源；`rest-api.md` 移除 `POST /api/cache/archive/load`、補 `/api/quarantine/search` 的新欄位。

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md docs/guide/gui-tour.md docs/guide/configuration.md docs/reference/rest-api.md
git commit -m "docs: record the traffic source selector and the archive streaming query"
```

---

## 自我檢查（撰寫時已執行）

- **Spec 覆蓋**：§4.1 由 Task 5、6 覆蓋；§4.2 由 Task 1-4、7 覆蓋（gzip→T1、白名單→T2、合併／top-N／有界摘要→T3、移除→T7）；§4.3 錯誤處理由 T1（壞檔／壞列）、T4（無區間／不支援條件）覆蓋；§4.4 測試逐條對應。§5 的三項排除未產生任務，正確。
- **佔位字掃描**：無 TBD／TODO。Task 5、6 的測試以「涵蓋哪些情境」描述而非完整程式碼——這是刻意的，因為兩者都要照抄該測試檔當下的 fixture 慣例，寫死會重演本專案「brief 指的 helper 不存在」的既有失敗；步驟中已明文要求先讀該檔。
- **型別一致性**：`iter_archive_rows` / `unsupported_filters` / `merge_row` / `stream_query` / `ArchiveQueryResult` 的名稱與欄位在 Task 1-4 間一致；`sort_by` 三值與 `analyzer.py` 一致；`resolve_data_source` 的回傳形狀與 `cache_support.py` 一致。
- **已知取捨**：Task 3 的記憶體仍是 O(命中列數)，只有**回傳值**有界。已在該任務明文標示為後續事項，避免實作者自行擴大範圍。

## 本計畫不處理

- 封存的產生端（retention、archiver、gzip 輪替）完全不動
- 報表的資料來源（已有三模式選擇器）
- 摘要的視覺呈現形式，留給 2F-3
- `stream_query` 的記憶體有界化（需兩趟掃描或近似演算法）
