# PCE Cache 長期 Archive 保存 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `pce_cache` 到期刪除前，把 traffic 與 audit log 以純文字 JSONL 增量匯出到可長期保存的目錄，並用 archive cursor 硬守門 retention（未 archive 不刪），滿足客戶法規長期保存需求。

**Architecture:** 新增 `ArchiveExporter`（`src/pce_cache/archive.py`），以獨立的 `consumer="archiver"` cursor（沿用 `ingestion_cursors` 表）增量讀取兩個來源表的 ORM 列，依「事件時間」分日 append 成 `{prefix}-YYYY-MM-DD.jsonl`，`fsync` 成功後才推進 cursor；舊檔依 mtime 自動 gzip。`RetentionWorker` 增加 `archive_enabled` 守門：只刪「到期且 archive cursor 已覆蓋」的列。全部改動在 `archive_enabled=False` 時為 no-op。

**Tech Stack:** Python 3、SQLAlchemy 2.x ORM、SQLite（WAL）、orjson（序列化，既有相依）、gzip（標準庫）、APScheduler（排程）、Pydantic v2（`config_models`）、pytest（TDD）。

## Global Constraints

- 所有回應／註解／commit message 一律**繁體中文、無 emoji**（使用者全域規則）。
- **Surgical changes**：只動與本功能相關的行；不順手重構、不修其他既有問題（例如 `run_cache_retention` 未傳 `dispatch_days`/`dlq_days` 屬既有議題，本 plan 不處理）。
- **向後相容硬需求**：`archive_enabled` 預設 `False`；所有既有測試（尤其 `tests/test_pce_cache_retention.py`）**不得因本改動而失敗**。`RetentionWorker.run_once` 既有呼叫端不帶新參數時，行為必須與現況完全相同。
- **序列化**：一律用 `orjson`（與 `src/pce_cache/subscriber.py` 一致），不要引入 `json` 標準庫做熱路徑序列化。
- **測試隔離**：單元測試只用 `tmp_path` 建臨時 SQLite + 臨時 archive 目錄，**不得**連線真實 PCE 或碰真實 `data/`。
- **cursor 語意**：archive 與 retention 都透過既有 `IngestionCursor`（PK = `(consumer, source_table)`）解耦；`consumer` 固定字串 `"archiver"`；`source_table` 用 `"pce_events"` / `"pce_traffic_flows_raw"`（與 `_MODEL_MAP` 一致）。

### 與 spec 的一處實作偏離（重要）

spec §4 原寫「用 `CacheSubscriber` 取得 cursor、透過 subscriber 推進 cursor」。實作上**不採用** `CacheSubscriber.poll_new_rows`，因為它回傳的是 `raw_json` 解析後的 dict（見 `src/pce_cache/subscriber.py:83-92`），**遺失了分日所需的事件時間欄位（`last_detected`/`timestamp`）以及推進 cursor 所需的 `ingested_at`/`id`**。因此 `ArchiveExporter` 直接讀 ORM 列、並自管 `"archiver"` cursor（`IngestionCursor` docstring 已明列 exporters 為合法 consumer）。此偏離不改變 spec 的資料流與守門保證，只是換用能取得結構化欄位的讀取方式。

---

## File Structure

- **Create** `src/pce_cache/archive.py` — `ArchiveExporter` + `ArchiveResult`；增量 JSONL 匯出、分日、gzip 輪替、自管 archiver cursor。單一職責：把 cache 列匯出成長期檔案。
- **Create** `tests/test_pce_cache_archive.py` — exporter 的單元測試（增量、分日、保真、續傳、gzip）。
- **Modify** `src/config_models.py` — `PceCacheSettings` 新增 4 個 archive 設定欄位（`src/config_models.py:236-248`）。
- **Modify** `src/pce_cache/retention.py` — `RetentionWorker.run_once` 新增 `archive_enabled` 守門（`src/pce_cache/retention.py:17-63`）。
- **Modify** `tests/test_pce_cache_retention.py` — 追加守門行為測試（不改既有測試）。
- **Modify** `src/scheduler/jobs.py` — 新增 `run_cache_archive`；`run_cache_retention` 傳入 `archive_enabled`（`src/scheduler/jobs.py:142-156`）。
- **Modify** `src/scheduler/__init__.py` — cache 區塊註冊 `run_cache_archive`（`src/scheduler/__init__.py:117-145`）。
- **Create** `tests/test_scheduler_cache_archive.py` — 排程 job 呼叫 exporter、以及 `archive_enabled` 時才註冊的測試。

---

## Task 1: Config 欄位（`PceCacheSettings`）

**Files:**
- Modify: `src/config_models.py:236-248`
- Test: `tests/test_config_pce_cache_archive.py`

**Interfaces:**
- Consumes: 無。
- Produces: `PceCacheSettings` 新增屬性 `archive_enabled: bool`、`archive_dir: str`、`archive_interval_hours: int`、`archive_gzip_after_days: int`，供 Task 4/5 讀取（`cm.models.pce_cache.archive_*`）。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_config_pce_cache_archive.py`:

```python
from src.config_models import PceCacheSettings


def test_archive_defaults_are_off_and_safe():
    s = PceCacheSettings()
    assert s.archive_enabled is False
    assert s.archive_dir == "data/archive"
    assert s.archive_interval_hours == 24
    assert s.archive_gzip_after_days == 7


def test_archive_fields_parse_custom_values():
    s = PceCacheSettings(
        archive_enabled=True,
        archive_dir="/mnt/wormstore/illumio",
        archive_interval_hours=6,
        archive_gzip_after_days=3,
    )
    assert s.archive_enabled is True
    assert s.archive_dir == "/mnt/wormstore/illumio"
    assert s.archive_interval_hours == 6
    assert s.archive_gzip_after_days == 3


def test_archive_interval_and_gzip_have_lower_bounds():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PceCacheSettings(archive_interval_hours=0)
    with pytest.raises(ValidationError):
        PceCacheSettings(archive_gzip_after_days=0)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_config_pce_cache_archive.py -v`
Expected: FAIL（`AttributeError`/`TypeError`：`archive_enabled` 等欄位不存在）。

- [ ] **Step 3: 最小實作**

在 `src/config_models.py` 的 `PceCacheSettings` 內、`traffic_sampling` 欄位（`src/config_models.py:248`）之後，新增：

```python
    archive_enabled: bool = False
    archive_dir: str = "data/archive"
    archive_interval_hours: int = Field(default=24, ge=1)
    archive_gzip_after_days: int = Field(default=7, ge=1)
```

（`Field` 已於檔案頂部匯入，沿用即可。）

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_config_pce_cache_archive.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add src/config_models.py tests/test_config_pce_cache_archive.py
git commit -m "feat(pce_cache): add archive config fields to PceCacheSettings"
```

---

## Task 2: `ArchiveExporter` 核心（增量 JSONL 匯出 + 自管 cursor + 分日）

**Files:**
- Create: `src/pce_cache/archive.py`
- Test: `tests/test_pce_cache_archive.py`

**Interfaces:**
- Consumes: `src/pce_cache/models.py` 的 `PceEvent`、`PceTrafficFlowRaw`、`IngestionCursor`；`src/pce_cache/schema.py` 的 `init_schema`（測試用）。
- Produces:
  - `ArchiveResult`（dataclass）: `source: str`、`rows: int`、`files_written: list[str]`。
  - `ArchiveExporter(session_factory, archive_dir: str, gzip_after_days: int = 7)`。
  - `ArchiveExporter.run_once() -> dict[str, ArchiveResult]`，key 為 `"traffic"` 與 `"audit"`。
  - 檔名格式 `{prefix}-YYYY-MM-DD.jsonl`（`prefix` ∈ `traffic`/`audit`；日期取事件時間 UTC 日）。
  - cursor：`consumer="archiver"`，`source_table ∈ {"pce_traffic_flows_raw","pce_events"}`。
  - JSONL 每行欄位（供 Task 未涉及但契約鎖定）：traffic 含 `event_time,ingested_at,flow_hash,src_ip,src_workload,dst_ip,dst_workload,port,protocol,action,flow_count,bytes_in,bytes_out,raw`；audit 含 `event_time,ingested_at,pce_href,pce_event_id,event_type,severity,status,pce_fqdn,raw`。`raw` 為原始 `raw_json` 解析後物件（空則 `null`）。
  - `_gzip_old_files()`（Task 3 才實作，本任務先留空 no-op 方法，簽章固定）。

- [ ] **Step 1: 寫失敗測試（traffic 增量匯出 + 保真）**

Create `tests/test_pce_cache_archive.py`:

```python
import gzip
import os
from datetime import datetime, timezone, timedelta

import orjson
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.pce_cache.schema import init_schema
from src.pce_cache.models import PceEvent, PceTrafficFlowRaw, IngestionCursor


@pytest.fixture
def sf(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


@pytest.fixture
def archive_dir(tmp_path):
    d = tmp_path / "archive"
    d.mkdir()
    return str(d)


def _dt(y, mo, d, h=12):
    return datetime(y, mo, d, h, 0, 0, tzinfo=timezone.utc)


def _add_traffic(sf, flow_hash, last_detected, ingested_at, raw):
    with sf.begin() as s:
        s.add(PceTrafficFlowRaw(
            flow_hash=flow_hash, first_detected=last_detected, last_detected=last_detected,
            src_ip="10.0.0.1", src_workload="web", dst_ip="10.0.0.2", dst_workload="db",
            port=443, protocol="tcp", action="blocked", flow_count=1,
            bytes_in=100, bytes_out=200, raw_json=orjson.dumps(raw).decode(),
            ingested_at=ingested_at,
        ))


def _read_lines(path):
    with open(path, "rb") as fh:
        return [orjson.loads(ln) for ln in fh.read().splitlines() if ln.strip()]


def test_archive_exports_new_traffic_rows_as_jsonl(sf, archive_dir):
    from src.pce_cache.archive import ArchiveExporter
    _add_traffic(sf, "h1", _dt(2026, 6, 30), _dt(2026, 6, 30), {"href": "/f/1", "k": "v1"})
    _add_traffic(sf, "h2", _dt(2026, 6, 30), _dt(2026, 6, 30), {"href": "/f/2", "k": "v2"})

    res = ArchiveExporter(sf, archive_dir).run_once()

    assert res["traffic"].rows == 2
    path = os.path.join(archive_dir, "traffic-2026-06-30.jsonl")
    assert os.path.exists(path)
    lines = _read_lines(path)
    assert len(lines) == 2
    assert {ln["flow_hash"] for ln in lines} == {"h1", "h2"}
    # 保真：原始 raw_json 完整內嵌且可解析
    by_hash = {ln["flow_hash"]: ln for ln in lines}
    assert by_hash["h1"]["raw"] == {"href": "/f/1", "k": "v1"}
    assert by_hash["h1"]["port"] == 443
    assert by_hash["h1"]["action"] == "blocked"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_pce_cache_archive.py::test_archive_exports_new_traffic_rows_as_jsonl -v`
Expected: FAIL（`ModuleNotFoundError: src.pce_cache.archive`）。

- [ ] **Step 3: 實作 `ArchiveExporter`（含 traffic + audit 兩來源、自管 cursor、分日、fsync 後推進）**

Create `src/pce_cache/archive.py`:

```python
from __future__ import annotations

import gzip
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import orjson
from loguru import logger
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import IngestionCursor, PceEvent, PceTrafficFlowRaw

_BATCH = 5000
_CONSUMER = "archiver"


@dataclass
class ArchiveResult:
    source: str
    rows: int = 0
    files_written: list[str] = field(default_factory=list)


def _traffic_record(row: PceTrafficFlowRaw) -> dict:
    return {
        "event_time": row.last_detected.isoformat(),
        "ingested_at": row.ingested_at.isoformat(),
        "flow_hash": row.flow_hash,
        "src_ip": row.src_ip, "src_workload": row.src_workload,
        "dst_ip": row.dst_ip, "dst_workload": row.dst_workload,
        "port": row.port, "protocol": row.protocol, "action": row.action,
        "flow_count": row.flow_count,
        "bytes_in": row.bytes_in, "bytes_out": row.bytes_out,
        "raw": orjson.loads(row.raw_json) if row.raw_json else None,
    }


def _audit_record(row: PceEvent) -> dict:
    return {
        "event_time": row.timestamp.isoformat(),
        "ingested_at": row.ingested_at.isoformat(),
        "pce_href": row.pce_href, "pce_event_id": row.pce_event_id,
        "event_type": row.event_type, "severity": row.severity,
        "status": row.status, "pce_fqdn": row.pce_fqdn,
        "raw": orjson.loads(row.raw_json) if row.raw_json else None,
    }


# (prefix, model, source_table, event_time_attr, record_builder)
_SOURCES = [
    ("traffic", PceTrafficFlowRaw, "pce_traffic_flows_raw", "last_detected", _traffic_record),
    ("audit", PceEvent, "pce_events", "timestamp", _audit_record),
]


class ArchiveExporter:
    def __init__(self, session_factory: sessionmaker, archive_dir: str,
                 gzip_after_days: int = 7):
        self._sf = session_factory
        self._dir = archive_dir
        self._gzip_after_days = gzip_after_days

    def run_once(self) -> dict[str, ArchiveResult]:
        os.makedirs(self._dir, exist_ok=True)
        results: dict[str, ArchiveResult] = {}
        for prefix, model, source_table, ev_attr, builder in _SOURCES:
            results[
                "traffic" if prefix == "traffic" else "audit"
            ] = self._export_source(prefix, model, source_table, ev_attr, builder)
        self._gzip_old_files()
        return results

    def _export_source(self, prefix, model, source_table, ev_attr, builder) -> ArchiveResult:
        res = ArchiveResult(source=prefix)
        files: set[str] = set()
        last_ts, last_id = self._read_cursor(source_table)
        while True:
            with self._sf() as s:
                q = (select(model)
                     .order_by(model.ingested_at, model.id)
                     .limit(_BATCH))
                if last_ts is not None:
                    q = q.where(or_(
                        model.ingested_at > last_ts,
                        and_(model.ingested_at == last_ts, model.id > last_id),
                    ))
                rows = s.execute(q).scalars().all()
                # 在 session 開啟期間就把要用的欄位取出，避免 detached 存取
                batch = [(builder(r), getattr(r, ev_attr), r.ingested_at, r.id) for r in rows]
            if not batch:
                break
            written = self._write_batch(prefix, batch)
            files.update(written)
            last_ts, last_id = batch[-1][2], batch[-1][3]
            self._write_cursor(source_table, last_ts, last_id)
            res.rows += len(batch)
            if len(batch) < _BATCH:
                break
        res.files_written = sorted(files)
        return res

    def _write_batch(self, prefix, batch) -> set[str]:
        # 依事件時間 UTC 日分組，一批可落在多個日期檔
        by_day: dict[str, list[bytes]] = {}
        for record, ev_time, _ing, _rid in batch:
            day = ev_time.astimezone(timezone.utc).strftime("%Y-%m-%d")
            by_day.setdefault(day, []).append(orjson.dumps(record))
        written: set[str] = set()
        for day, lines in by_day.items():
            path = os.path.join(self._dir, f"{prefix}-{day}.jsonl")
            with open(path, "ab") as fh:
                for ln in lines:
                    fh.write(ln)
                    fh.write(b"\n")
                fh.flush()
                os.fsync(fh.fileno())
            written.add(path)
        return written

    def _read_cursor(self, source_table) -> tuple[datetime | None, int | None]:
        with self._sf() as s:
            cur = s.get(IngestionCursor, (_CONSUMER, source_table))
        if cur is None:
            return (None, None)
        return (cur.last_ingested_at, cur.last_row_id)

    def _write_cursor(self, source_table, ts: datetime, row_id: int) -> None:
        now = datetime.now(timezone.utc)
        with self._sf.begin() as s:
            cur = s.get(IngestionCursor, (_CONSUMER, source_table))
            if cur is None:
                cur = IngestionCursor(consumer=_CONSUMER, source_table=source_table,
                                      updated_at=now)
                s.add(cur)
            cur.last_ingested_at = ts
            cur.last_row_id = row_id
            cur.updated_at = now

    def _gzip_old_files(self) -> None:
        # Task 3 實作；本任務先 no-op，鎖定簽章。
        return None
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_pce_cache_archive.py::test_archive_exports_new_traffic_rows_as_jsonl -v`
Expected: PASS。

- [ ] **Step 5: 寫「增量不重複 + 續傳」測試**

Append to `tests/test_pce_cache_archive.py`:

```python
def test_archive_incremental_appends_only_new_rows(sf, archive_dir):
    from src.pce_cache.archive import ArchiveExporter
    exporter = ArchiveExporter(sf, archive_dir)

    _add_traffic(sf, "h1", _dt(2026, 6, 30), _dt(2026, 6, 30), {"n": 1})
    r1 = exporter.run_once()
    assert r1["traffic"].rows == 1

    # 沒有新列 → 第二次不匯出任何東西
    r2 = exporter.run_once()
    assert r2["traffic"].rows == 0

    # 新增兩列（較晚 ingested_at）→ 只匯出這兩列
    _add_traffic(sf, "h2", _dt(2026, 6, 30), _dt(2026, 6, 30, 13), {"n": 2})
    _add_traffic(sf, "h3", _dt(2026, 6, 30), _dt(2026, 6, 30, 14), {"n": 3})
    r3 = exporter.run_once()
    assert r3["traffic"].rows == 2

    path = os.path.join(archive_dir, "traffic-2026-06-30.jsonl")
    lines = _read_lines(path)
    assert [ln["flow_hash"] for ln in lines] == ["h1", "h2", "h3"]  # 無重複、順序穩定


def test_archive_cursor_persisted_for_archiver_consumer(sf, archive_dir):
    from src.pce_cache.archive import ArchiveExporter
    _add_traffic(sf, "h1", _dt(2026, 6, 30), _dt(2026, 6, 30), {"n": 1})
    ArchiveExporter(sf, archive_dir).run_once()
    with sf() as s:
        cur = s.get(IngestionCursor, ("archiver", "pce_traffic_flows_raw"))
    assert cur is not None
    assert cur.last_row_id is not None
```

- [ ] **Step 6: 跑測試確認通過（增量/續傳）**

Run: `python -m pytest tests/test_pce_cache_archive.py -v`
Expected: PASS（現有 3 個測試全過）。實作已支援，不需改碼；若失敗才回頭修 `_export_source` 游標邏輯。

- [ ] **Step 7: 寫「跨日分檔」+「audit 來源」測試**

Append to `tests/test_pce_cache_archive.py`:

```python
def test_archive_splits_files_by_event_date(sf, archive_dir):
    from src.pce_cache.archive import ArchiveExporter
    # 同一批、事件時間跨兩天（ingested_at 遞增以維持游標順序）
    _add_traffic(sf, "d1", _dt(2026, 6, 29), _dt(2026, 6, 30, 10), {"n": 1})
    _add_traffic(sf, "d2", _dt(2026, 6, 30), _dt(2026, 6, 30, 11), {"n": 2})

    res = ArchiveExporter(sf, archive_dir).run_once()
    assert res["traffic"].rows == 2

    p29 = os.path.join(archive_dir, "traffic-2026-06-29.jsonl")
    p30 = os.path.join(archive_dir, "traffic-2026-06-30.jsonl")
    assert len(_read_lines(p29)) == 1
    assert len(_read_lines(p30)) == 1
    assert _read_lines(p29)[0]["flow_hash"] == "d1"


def test_archive_exports_audit_events(sf, archive_dir):
    from src.pce_cache.archive import ArchiveExporter
    with sf.begin() as s:
        s.add(PceEvent(
            pce_href="/orgs/1/events/e1", pce_event_id="e1",
            timestamp=_dt(2026, 6, 30), event_type="user.sign_in", severity="info",
            status="success", pce_fqdn="pce.test",
            raw_json=orjson.dumps({"href": "/orgs/1/events/e1", "d": 1}).decode(),
            ingested_at=_dt(2026, 6, 30),
        ))
    res = ArchiveExporter(sf, archive_dir).run_once()
    assert res["audit"].rows == 1
    path = os.path.join(archive_dir, "audit-2026-06-30.jsonl")
    lines = _read_lines(path)
    assert lines[0]["pce_event_id"] == "e1"
    assert lines[0]["event_type"] == "user.sign_in"
    assert lines[0]["raw"] == {"href": "/orgs/1/events/e1", "d": 1}
```

- [ ] **Step 8: 跑全檔測試確認通過**

Run: `python -m pytest tests/test_pce_cache_archive.py -v`
Expected: PASS（5 passed）。

- [ ] **Step 9: Commit**

```bash
git add src/pce_cache/archive.py tests/test_pce_cache_archive.py
git commit -m "feat(pce_cache): add ArchiveExporter for incremental JSONL export"
```

---

## Task 3: gzip 舊檔輪替（`_gzip_old_files`）

**Files:**
- Modify: `src/pce_cache/archive.py`
- Test: `tests/test_pce_cache_archive.py`

**Interfaces:**
- Consumes: Task 2 的 `ArchiveExporter._dir` / `self._gzip_after_days`。
- Produces: `_gzip_old_files()` 把 `{archive_dir}` 下 mtime 超過 `gzip_after_days` 且尚未壓縮的 `*.jsonl` 壓成 `*.jsonl.gz`（寫 `.gz` 成功後才刪原檔）；近 `gzip_after_days` 內的 `.jsonl` 不動。

- [ ] **Step 1: 寫失敗測試**

Append to `tests/test_pce_cache_archive.py`:

```python
def test_gzip_rotates_only_old_files(sf, archive_dir):
    from src.pce_cache.archive import ArchiveExporter
    exporter = ArchiveExporter(sf, archive_dir, gzip_after_days=7)

    old_path = os.path.join(archive_dir, "traffic-2026-06-01.jsonl")
    new_path = os.path.join(archive_dir, "traffic-2026-06-30.jsonl")
    with open(old_path, "wb") as fh:
        fh.write(orjson.dumps({"flow_hash": "old", "raw": {"n": 1}}) + b"\n")
    with open(new_path, "wb") as fh:
        fh.write(orjson.dumps({"flow_hash": "new", "raw": {"n": 2}}) + b"\n")

    # 把舊檔 mtime 調成 30 天前；新檔維持現在
    old_mtime = time.time() - 30 * 86400
    os.utime(old_path, (old_mtime, old_mtime))

    exporter._gzip_old_files()

    # 舊檔被壓縮、原檔移除；內容可解回原文
    assert not os.path.exists(old_path)
    gz = old_path + ".gz"
    assert os.path.exists(gz)
    with gzip.open(gz, "rb") as fh:
        restored = [orjson.loads(ln) for ln in fh.read().splitlines() if ln.strip()]
    assert restored[0]["flow_hash"] == "old"

    # 新檔不動
    assert os.path.exists(new_path)
    assert not os.path.exists(new_path + ".gz")


def test_gzip_is_idempotent_and_skips_already_gzipped(sf, archive_dir):
    from src.pce_cache.archive import ArchiveExporter
    exporter = ArchiveExporter(sf, archive_dir, gzip_after_days=7)
    gz = os.path.join(archive_dir, "traffic-2026-06-01.jsonl.gz")
    with gzip.open(gz, "wb") as fh:
        fh.write(b'{"flow_hash": "x"}\n')
    old_mtime = time.time() - 30 * 86400
    os.utime(gz, (old_mtime, old_mtime))
    # 不應拋錯、也不應動既有 .gz
    exporter._gzip_old_files()
    assert os.path.exists(gz)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_pce_cache_archive.py::test_gzip_rotates_only_old_files -v`
Expected: FAIL（`_gzip_old_files` 目前是 no-op，舊檔仍為 `.jsonl`）。

- [ ] **Step 3: 實作 `_gzip_old_files`**

Replace the placeholder `_gzip_old_files` in `src/pce_cache/archive.py` with:

```python
    def _gzip_old_files(self) -> None:
        cutoff = time.time() - self._gzip_after_days * 86400
        try:
            names = os.listdir(self._dir)
        except FileNotFoundError:
            return
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(self._dir, name)
            try:
                if os.path.getmtime(path) >= cutoff:
                    continue
                gz_path = path + ".gz"
                with open(path, "rb") as src, gzip.open(gz_path, "wb") as dst:
                    while True:
                        chunk = src.read(1 << 20)
                        if not chunk:
                            break
                        dst.write(chunk)
                    dst.flush()
                    os.fsync(dst.fileno())
                os.remove(path)  # 只有 .gz 成功寫入後才刪原檔
            except OSError as exc:
                logger.warning("archive gzip skipped {}: {}", path, exc)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_pce_cache_archive.py -v`
Expected: PASS（7 passed）。

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache/archive.py tests/test_pce_cache_archive.py
git commit -m "feat(pce_cache): gzip-rotate archive files older than gzip_after_days"
```

---

## Task 4: Retention archive 守門（`RetentionWorker.run_once`）

**Files:**
- Modify: `src/pce_cache/retention.py:17-63`
- Test: `tests/test_pce_cache_retention.py`

**Interfaces:**
- Consumes: `src/pce_cache/models.py` 的 `IngestionCursor`（讀 `("archiver", source_table)` 的 `last_ingested_at`）。
- Produces: `RetentionWorker.run_once(..., dispatch_days=14, archive_enabled: bool = False)`。當 `archive_enabled=True`：`pce_events`、`pce_traffic_flows_raw` 的實際刪除界線 = `min(時間policy cutoff, archiver_cursor.last_ingested_at)`；cursor 為 None 時該來源**不刪**；`archived_ts < policy_cutoff` 時記 warning。`archive_enabled=False` 時行為與現況完全相同。agg/dlq/dispatch 不受守門影響。

- [ ] **Step 1: 寫失敗測試（守門四情境）**

Append to `tests/test_pce_cache_retention.py`（沿用該檔既有 helpers `_seed_raw_flows`、`_now`、`_old`、`session_factory`）：

```python
def _set_archiver_cursor(sf, source_table, last_ingested_at):
    from src.pce_cache.models import IngestionCursor
    with sf.begin() as s:
        s.add(IngestionCursor(
            consumer="archiver", source_table=source_table,
            last_ingested_at=last_ingested_at, last_row_id=10**9,
            updated_at=_now(),
        ))


def test_guard_withholds_when_nothing_archived(session_factory):
    """archive_enabled 但沒有 archiver cursor（什麼都還沒 archive）→ 不刪任何 raw flow。"""
    from src.pce_cache.retention import RetentionWorker
    _seed_raw_flows(session_factory, old_count=5, new_count=0)
    worker = RetentionWorker(session_factory)
    deleted = worker.run_once(traffic_raw_days=7, archive_enabled=True)
    assert deleted["traffic_raw"] == 0
    with session_factory() as s:
        from sqlalchemy import select
        assert len(s.execute(select(PceTrafficFlowRaw)).scalars().all()) == 5


def test_guard_deletes_when_archive_caught_up(session_factory):
    """archiver cursor 已覆蓋到現在 → 到期列照常刪除。"""
    from src.pce_cache.retention import RetentionWorker
    _seed_raw_flows(session_factory, old_count=5, new_count=2)
    _set_archiver_cursor(session_factory, "pce_traffic_flows_raw", _now())
    worker = RetentionWorker(session_factory)
    deleted = worker.run_once(traffic_raw_days=7, archive_enabled=True)
    assert deleted["traffic_raw"] == 5  # 5 舊列到期且已 archive → 刪；2 新列未到期


def test_guard_withholds_rows_newer_than_cursor(session_factory):
    """archive 落後：cursor 停在很久以前 → 到期但未 archive 的列不刪。"""
    from src.pce_cache.retention import RetentionWorker
    _seed_raw_flows(session_factory, old_count=5, new_count=0)  # 皆為 100 天前、到期
    _set_archiver_cursor(session_factory, "pce_traffic_flows_raw",
                         _now() - __import__("datetime").timedelta(days=200))
    worker = RetentionWorker(session_factory)
    deleted = worker.run_once(traffic_raw_days=7, archive_enabled=True)
    # cursor(200天前) 比舊列(100天前)還早 → 舊列都在 cursor 之後 → 不刪
    assert deleted["traffic_raw"] == 0


def test_guard_off_matches_current_behaviour(session_factory):
    """archive_enabled=False（預設）→ 到期即刪，與現況一致（回歸保護）。"""
    from src.pce_cache.retention import RetentionWorker
    _seed_raw_flows(session_factory, old_count=5, new_count=2)
    worker = RetentionWorker(session_factory)
    deleted = worker.run_once(traffic_raw_days=7)  # 不帶 archive_enabled
    assert deleted["traffic_raw"] == 5
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_pce_cache_retention.py -k guard -v`
Expected: FAIL（`run_once` 不接受 `archive_enabled`，或守門情境不成立）。

- [ ] **Step 3: 實作守門**

Rewrite `src/pce_cache/retention.py` as:

```python
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from loguru import logger
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    DeadLetter, IngestionCursor, PceEvent, PceTrafficFlowAgg,
    PceTrafficFlowRaw, SiemDispatch,
)


class RetentionWorker:
    def __init__(self, session_factory: sessionmaker):
        self._sf = session_factory

    def run_once(
        self,
        events_days: int = 90,
        traffic_raw_days: int = 7,
        traffic_agg_days: int = 90,
        dlq_days: int = 30,
        dispatch_days: int = 14,
        archive_enabled: bool = False,
    ) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        results: dict[str, int] = {}

        with self._sf.begin() as s:
            policy_cutoff = now - timedelta(days=events_days)
            eff = self._effective_cutoff(s, "pce_events", policy_cutoff, archive_enabled)
            if eff is None:
                results["events"] = 0
            else:
                r = s.execute(delete(PceEvent).where(PceEvent.ingested_at < eff))
                results["events"] = r.rowcount

        with self._sf.begin() as s:
            policy_cutoff = now - timedelta(days=traffic_raw_days)
            eff = self._effective_cutoff(s, "pce_traffic_flows_raw", policy_cutoff, archive_enabled)
            if eff is None:
                results["traffic_raw"] = 0
            else:
                r = s.execute(delete(PceTrafficFlowRaw).where(PceTrafficFlowRaw.ingested_at < eff))
                results["traffic_raw"] = r.rowcount

        with self._sf.begin() as s:
            cutoff = now - timedelta(days=traffic_agg_days)
            r = s.execute(delete(PceTrafficFlowAgg).where(PceTrafficFlowAgg.bucket_day < cutoff))
            results["traffic_agg"] = r.rowcount

        with self._sf.begin() as s:
            cutoff = now - timedelta(days=dlq_days)
            r = s.execute(delete(DeadLetter).where(DeadLetter.quarantined_at < cutoff))
            results["dead_letter"] = r.rowcount

        with self._sf.begin() as s:
            # siem_dispatch grows one row per record per destination and is never
            # otherwise pruned — the dispatcher only flips status pending→sent. So
            # delivered rows accumulate forever, long after the underlying raw
            # flows are deleted at 7 days, bloating the DB and the dispatch
            # indexes/COUNT queries. Purge delivered ('sent') rows past the
            # cutoff; leave pending/failed (retry/DLQ candidates) untouched. Their
            # NULL sent_at is excluded by the `< cutoff` comparison anyway.
            cutoff = now - timedelta(days=dispatch_days)
            r = s.execute(delete(SiemDispatch).where(
                SiemDispatch.status == "sent",
                SiemDispatch.sent_at < cutoff,
            ))
            results["siem_dispatch"] = r.rowcount

        return results

    def _effective_cutoff(self, s, source_table, policy_cutoff, archive_enabled):
        """回傳實際刪除界線。archive_enabled=True 時，只刪「到期且已 archive」
        的列：界線取 min(policy_cutoff, archiver cursor 的 last_ingested_at)；
        cursor 為 None（尚未 archive 任何列）→ 回傳 None（該來源不刪）。"""
        if not archive_enabled:
            return policy_cutoff
        cur = s.get(IngestionCursor, ("archiver", source_table))
        archived_ts = cur.last_ingested_at if cur else None
        if archived_ts is None:
            logger.warning(
                "retention guard: nothing archived for {} yet; withholding deletion",
                source_table,
            )
            return None
        if archived_ts < policy_cutoff:
            logger.warning(
                "retention guard: archive behind for {} (archived up to {} < policy {}); "
                "withholding un-archived rows",
                source_table, archived_ts, policy_cutoff,
            )
        return min(policy_cutoff, archived_ts)
```

- [ ] **Step 4: 跑守門測試 + 既有 retention 測試（回歸）**

Run: `python -m pytest tests/test_pce_cache_retention.py -v`
Expected: PASS（原 6 個 + 新增 4 個守門測試全過；既有測試不帶 `archive_enabled`，走預設 False 分支，行為不變）。

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache/retention.py tests/test_pce_cache_retention.py
git commit -m "feat(pce_cache): gate retention deletes behind archiver cursor"
```

---

## Task 5: 排程接線（`run_cache_archive` + retention 傳 `archive_enabled` + 註冊）

**Files:**
- Modify: `src/scheduler/jobs.py:142-156`（`run_cache_retention`）＋新增 `run_cache_archive`
- Modify: `src/scheduler/__init__.py:117-145`（cache 區塊註冊）
- Test: `tests/test_scheduler_cache_archive.py`

**Interfaces:**
- Consumes: Task 2 的 `ArchiveExporter`；Task 1 的 `cm.models.pce_cache.archive_*`；Task 4 的 `RetentionWorker.run_once(archive_enabled=...)`；既有 `_get_cache_engine`（`src/gui/_helpers.py`）。
- Produces: `run_cache_archive(cm) -> None`（建 engine → 跑 `ArchiveExporter.run_once()` → log 結果；例外以 `logger.exception` 收斂）。排程 id `"pce_cache_archive"`，僅在 `cache_cfg.enabled and cache_cfg.archive_enabled` 時以 `_IT(hours=cache_cfg.archive_interval_hours)` 註冊。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_scheduler_cache_archive.py`:

```python
from unittest.mock import patch, MagicMock


def _cm(tmp_path, archive_enabled=True):
    cm = MagicMock()
    cfg = cm.models.pce_cache
    cfg.db_path = str(tmp_path / "cache.sqlite")
    cfg.archive_enabled = archive_enabled
    cfg.archive_dir = str(tmp_path / "archive")
    cfg.archive_gzip_after_days = 7
    return cm


def test_run_cache_archive_invokes_exporter(tmp_path):
    from src.scheduler.jobs import run_cache_archive
    cm = _cm(tmp_path)
    with patch("src.gui._helpers._get_cache_engine"), \
         patch("sqlalchemy.orm.sessionmaker"), \
         patch("src.pce_cache.archive.ArchiveExporter") as mock_exp:
        mock_exp.return_value.run_once.return_value = {}
        run_cache_archive(cm)
    mock_exp.assert_called_once()
    _args, kwargs = mock_exp.call_args
    assert kwargs.get("archive_dir") == cm.models.pce_cache.archive_dir
    assert kwargs.get("gzip_after_days") == 7
    mock_exp.return_value.run_once.assert_called_once()


def test_run_cache_archive_swallows_exceptions(tmp_path):
    from src.scheduler.jobs import run_cache_archive
    cm = _cm(tmp_path)
    with patch("src.gui._helpers._get_cache_engine", side_effect=RuntimeError("boom")):
        run_cache_archive(cm)  # 不得拋出


def test_run_cache_retention_passes_archive_enabled(tmp_path):
    from src.scheduler.jobs import run_cache_retention
    cm = _cm(tmp_path)
    cfg = cm.models.pce_cache
    cfg.events_retention_days = 90
    cfg.traffic_raw_retention_days = 7
    cfg.traffic_agg_retention_days = 90
    with patch("src.gui._helpers._get_cache_engine"), \
         patch("sqlalchemy.orm.sessionmaker"), \
         patch("src.pce_cache.retention.RetentionWorker") as mock_w:
        mock_w.return_value.run_once.return_value = {}
        run_cache_retention(cm)
    _a, kwargs = mock_w.return_value.run_once.call_args
    assert kwargs.get("archive_enabled") is True


def test_archive_job_registered_only_when_enabled(tmp_path):
    from src.scheduler import build_scheduler
    cm = _cm(tmp_path, archive_enabled=False)
    cm.models.pce_cache.enabled = True
    cm.models.pce_cache.events_poll_interval_seconds = 300
    cm.models.pce_cache.traffic_poll_interval_seconds = 3600
    cm.models.siem.enabled = False
    cm.config = {}
    sched = build_scheduler(cm)
    assert sched.get_job("pce_cache_archive") is None
    for j in list(sched.get_jobs()):
        sched.remove_job(j.id)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_scheduler_cache_archive.py -v`
Expected: FAIL（`run_cache_archive` 不存在；`run_cache_retention` 未傳 `archive_enabled`）。

- [ ] **Step 3a: 實作 `run_cache_archive` 並讓 retention 傳 `archive_enabled`**

In `src/scheduler/jobs.py`, 修改 `run_cache_retention`（`src/scheduler/jobs.py:149-153`）加上 `archive_enabled`：

```python
        result = worker.run_once(
            events_days=cfg.events_retention_days,
            traffic_raw_days=cfg.traffic_raw_retention_days,
            traffic_agg_days=cfg.traffic_agg_retention_days,
            archive_enabled=cfg.archive_enabled,
        )
```

並在 `run_cache_retention` 之後新增：

```python
def run_cache_archive(cm) -> None:
    try:
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.archive import ArchiveExporter
        cfg = cm.models.pce_cache
        sf = sessionmaker(_get_cache_engine(cfg.db_path))
        exporter = ArchiveExporter(sf, archive_dir=cfg.archive_dir,
                                   gzip_after_days=cfg.archive_gzip_after_days)
        result = exporter.run_once()
        logger.info("Cache archive exported: {}", result)
    except Exception as exc:
        logger.exception("run_cache_archive failed: {}", exc)
```

- [ ] **Step 3b: 在排程註冊 archive job**

In `src/scheduler/__init__.py`, cache 區塊 import（`src/scheduler/__init__.py:122-125`）加入 `run_cache_archive`：

```python
            from src.scheduler.jobs import (
                run_events_ingest, run_traffic_ingest,
                run_traffic_aggregate, run_cache_retention,
                run_cache_archive,
            )
```

並在 `run_cache_lag_monitor` 註冊（`src/scheduler/__init__.py:142-143`）之後、`except` 之前加入：

```python
            if cache_cfg.archive_enabled:
                sched.add_job(run_cache_archive, _IT(hours=cache_cfg.archive_interval_hours),
                              args=[cm], id="pce_cache_archive", replace_existing=True)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_scheduler_cache_archive.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: 跑相關全套回歸**

Run: `python -m pytest tests/test_pce_cache_archive.py tests/test_pce_cache_retention.py tests/test_config_pce_cache_archive.py tests/test_scheduler_cache_archive.py tests/test_scheduler_engine_cache.py -v`
Expected: PASS（全綠）。

- [ ] **Step 6: Commit**

```bash
git add src/scheduler/jobs.py src/scheduler/__init__.py tests/test_scheduler_cache_archive.py
git commit -m "feat(scheduler): register cache archive job and gate retention"
```

---

## Self-Review（對照 spec 檢查）

**1. Spec 覆蓋度：**
- 格式 JSONL、內嵌 raw → Task 2（`_traffic_record`/`_audit_record` 的 `raw`）。
- 範圍 traffic + audit、不含 agg → Task 2 `_SOURCES` 僅兩來源。
- retention 守門「未 archive 不刪」→ Task 4 `_effective_cutoff`。
- 頻率每日可 config → Task 1 `archive_interval_hours` + Task 5 註冊。
- gzip 近 N 天不壓、更舊壓縮 → Task 3。
- 目錄可 config、預設 `data/archive` → Task 1 `archive_dir`。
- 分檔依事件時間 → Task 2 `_write_batch`（`last_detected`/`timestamp`）。
- 預設 `archive_enabled=False`、關閉時零行為變更 → Task 1 預設 + Task 4 False 分支 + Task 5 條件註冊。
- 先寫檔 fsync 後推進 cursor、崩潰續傳、不重複 → Task 2 `_export_source` + `_write_batch`。
- gzip 寫成功才刪原檔 → Task 3。

**2. Placeholder 掃描：** 每個 code step 均為完整可執行內容；無 TBD/TODO/「類似上一個」。（Task 2 的 `_gzip_old_files` 於 Task 2 明確標示為暫時 no-op 並鎖定簽章，Task 3 再補實作 —— 這是刻意的漸進，不是 placeholder。）

**3. 型別一致性：** `ArchiveExporter(session_factory, archive_dir, gzip_after_days=7)`、`run_once() -> dict[str, ArchiveResult]`（key `"traffic"`/`"audit"`）、cursor `("archiver", source_table)`、`RetentionWorker.run_once(..., archive_enabled=False)` 在 Task 2/4/5 中命名一致；Task 5 測試對 `ArchiveExporter` 以 `archive_dir=`/`gzip_after_days=` 具名呼叫，與 Task 2 建構子相符。

**4. 已知取捨（非缺口）：**
- `archive_enabled=True` 但 archive job 從未成功執行（cursor 恆為 None）時，retention 會**完全不刪** traffic/events，理論上可能無限增長。這是 spec §8「未 archive 不刪」的刻意保守行為；以 `logger.warning` 提供維運可見度。若日後需要「archive 持續失敗則告警升級」，另開需求，本 plan 不做（YAGNI）。
- 未做 agg archive、未做 checksum/manifest 防竄改、未清理 archive 檔本身（spec §11 明確不做）。
