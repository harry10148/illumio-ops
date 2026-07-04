# Archive 查閱（Phase 1：流量）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓已匯出的 archive traffic JSONL 能載回一個獨立的 review SQLite，用現有「流量與 Workloads」分析 UI 查閱（live cache 依 retention 刪除後 archive 是唯一來源）。

**Architecture:** 新增 `ArchiveImporter` 把 `traffic-YYYY-MM-DD.jsonl[.gz]` 逐行還原成 `PceTrafficFlowRaw` 灌進「用 `init_schema()` 建的同 schema review DB」（每次載入重建），補 `first_detected`/`report_json` 並跑一次 `TrafficAggregator`。既有 `CacheReader` 為注入 session_factory 設計、archive 的 `raw` 就是原始 flow dict，故 `query_flows → read_flows_raw` 分析路徑原樣重用；route 加 `source=archive` 分支指向 review DB。

**Tech Stack:** Python 3、SQLAlchemy 2.x ORM、SQLite、orjson、Flask（GUI blueprint）、原生 JS 前端、pytest。

## Global Constraints

- 註解一律繁體中文、無 emoji；commit message 用英文 conventional-commits（repo 慣例）。
- datetime 一律 timezone-aware（過 `scripts/check_no_naive_datetime.py`：同一行 `datetime.now()` 必須帶 `timezone`）。
- 序列化一律用 orjson。
- 測試只用 `tmp_path`，不得連真實 PCE 或碰真實 `data/`。
- Surgical：只動與本功能相關的行。i18n 新 key 必須 `i18n_en.json` 與 `i18n_zh_TW.json` **同步、非空**（CI parity 測試 `tests/test_i18n_quality.py` 會擋）。
- 向後相容：所有既有 traffic 查詢在不帶 `source`（或 `source="live"`）時行為完全不變。

---

## Task 1: Config `archive_review_max_days`

**Files:**
- Modify: `src/config_models.py`（`PceCacheSettings`，接在 `archive_retention_days` 之後）
- Test: `tests/test_config_pce_cache_archive.py`

**Interfaces:**
- Produces: `PceCacheSettings.archive_review_max_days: int`（預設 31，ge=1），供 Task 5 讀取範圍上限。

- [ ] **Step 1: 寫失敗測試**

Append to `tests/test_config_pce_cache_archive.py`:

```python
def test_archive_review_max_days_default_and_bounds():
    import pytest
    from pydantic import ValidationError
    assert PceCacheSettings().archive_review_max_days == 31
    assert PceCacheSettings(archive_review_max_days=7).archive_review_max_days == 7
    with pytest.raises(ValidationError):
        PceCacheSettings(archive_review_max_days=0)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_config_pce_cache_archive.py::test_archive_review_max_days_default_and_bounds -v`
Expected: FAIL（`archive_review_max_days` 不存在 → 預設值斷言或建構失敗）。

- [ ] **Step 3: 實作**

在 `src/config_models.py` 的 `PceCacheSettings`、`archive_retention_days` 那行之後新增：

```python
    archive_review_max_days: int = Field(default=31, ge=1)  # archive 查閱單次載入的日期範圍上限
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_config_pce_cache_archive.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/config_models.py tests/test_config_pce_cache_archive.py
git commit -m "feat(pce_cache): add archive_review_max_days config field"
```

---

## Task 2: `_make_cache_reader` 加可選 `db_path`

**Files:**
- Modify: `src/main.py:45-69`（`_make_cache_reader`）
- Test: `tests/test_make_cache_reader.py`（新增）

**Interfaces:**
- Consumes: 無。
- Produces: `_make_cache_reader(cm, db_path: str | None = None) -> CacheReader | None`。`db_path=None` 時行為與現況完全相同（用 `cfg.db_path`、受 `cfg.enabled` 守門）；提供 `db_path` 時對該 DB 建 reader 且**不受** `enabled` 守門（供 archive review 用）。供 Task 6 使用。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_make_cache_reader.py`:

```python
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.pce_cache.schema import init_schema
from src.pce_cache.models import PceTrafficFlowRaw
from datetime import datetime, timezone


def _cm(db_path, enabled=True):
    cache = SimpleNamespace(enabled=enabled, db_path=db_path,
                            events_retention_days=30, traffic_raw_retention_days=30)
    return SimpleNamespace(models=SimpleNamespace(pce_cache=cache))


def test_reader_uses_explicit_db_path_bypassing_enabled(tmp_path):
    from src.main import _make_cache_reader
    live = str(tmp_path / "live.sqlite")
    review = str(tmp_path / "review.sqlite")
    # review DB 有一列、live DB 沒有；即使 enabled=False，帶 db_path 仍應讀 review
    eng = create_engine(f"sqlite:///{review}")
    init_schema(eng)
    with sessionmaker(eng).begin() as s:
        s.add(PceTrafficFlowRaw(
            flow_hash="h1", first_detected=datetime(2026, 6, 30, tzinfo=timezone.utc),
            last_detected=datetime(2026, 6, 30, tzinfo=timezone.utc),
            src_ip="10.0.0.1", dst_ip="10.0.0.2", port=443, protocol="tcp",
            action="allowed", flow_count=1, bytes_in=0, bytes_out=0,
            raw_json="{}", ingested_at=datetime(2026, 6, 30, tzinfo=timezone.utc)))
    reader = _make_cache_reader(_cm(live, enabled=False), db_path=review)
    assert reader is not None
    flows = reader.read_flows_raw(
        datetime(2026, 6, 29, tzinfo=timezone.utc),
        datetime(2026, 7, 1, tzinfo=timezone.utc))
    assert len(list(flows)) == 1


def test_reader_default_path_still_gated_by_enabled(tmp_path):
    from src.main import _make_cache_reader
    assert _make_cache_reader(_cm(str(tmp_path / "x.sqlite"), enabled=False)) is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_make_cache_reader.py -v`
Expected: FAIL（`_make_cache_reader()` 不接受 `db_path`）。

- [ ] **Step 3: 實作**

Rewrite `_make_cache_reader` in `src/main.py` as:

```python
def _make_cache_reader(cm, db_path: str | None = None):
    """Return a CacheReader for the pce_cache DB (or an explicit db_path).

    db_path=None: use cm.models.pce_cache.db_path and honor the `enabled` gate
    (existing behavior). An explicit db_path (e.g. the archive review DB) builds
    a reader unconditionally — archive review does not depend on live cache being
    enabled.
    """
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.reader import CacheReader
        from src.pce_cache.schema import init_schema
        cfg = cm.models.pce_cache
        if db_path is None:
            if not cfg.enabled:
                return None
            db_path = cfg.db_path
        engine = create_engine(f"sqlite:///{db_path}")
        init_schema(engine)
        sf = sessionmaker(engine)
        return CacheReader(
            session_factory=sf,
            events_retention_days=int(getattr(cfg, "events_retention_days", 30)),
            traffic_raw_retention_days=int(getattr(cfg, "traffic_raw_retention_days", 30)),
        )
    except Exception as exc:
        logger.warning("Could not create cache reader: {}", exc)
        return None
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_make_cache_reader.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_make_cache_reader.py
git commit -m "feat(pce_cache): allow _make_cache_reader to target an explicit db_path"
```

---

## Task 3: `ArchiveImporter.import_range`

**Files:**
- Create: `src/pce_cache/archive_import.py`
- Test: `tests/test_pce_cache_archive_import.py`

**Interfaces:**
- Consumes: `src/pce_cache/models.py` `PceTrafficFlowRaw`；`src/report/parsers/api_parser.py` `flatten_flow_record`；`src/pce_cache/schema.py` `init_schema`（測試用）。
- Produces:
  - `ArchiveImporter(archive_dir: str, session_factory)`。
  - `ArchiveImporter.import_range(start: date, end: date) -> dict`，回 `{"rows","files","skipped","start","end"}`。
  - module 級 `_parse_dt(s: str) -> datetime`（aware，處理 Z/offset/naive）。
  - 供 Task 4 使用。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_pce_cache_archive_import.py`:

```python
import gzip
import os
from datetime import date, datetime, timezone

import orjson
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.schema import init_schema
from src.pce_cache.models import PceTrafficFlowRaw


@pytest.fixture
def sf(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'review.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


@pytest.fixture
def archive_dir(tmp_path):
    d = tmp_path / "archive"
    d.mkdir()
    return str(d)


def _traffic_line(flow_hash, event_day, raw):
    return orjson.dumps({
        "event_time": f"{event_day}T12:00:00+00:00",
        "ingested_at": f"{event_day}T12:00:00+00:00",
        "flow_hash": flow_hash,
        "src_ip": "10.0.0.1", "src_workload": "/w/web",
        "dst_ip": "10.0.0.2", "dst_workload": "/w/db",
        "port": 443, "protocol": "tcp", "action": "blocked",
        "flow_count": 1, "bytes_in": 100, "bytes_out": 200,
        "raw": raw,
    })


def _write(archive_dir, name, lines):
    path = os.path.join(archive_dir, name)
    opener = gzip.open if name.endswith(".gz") else open
    with opener(path, "wb") as fh:
        for ln in lines:
            fh.write(ln + b"\n")


def _rows(sf):
    with sf() as s:
        return s.execute(select(PceTrafficFlowRaw)).scalars().all()


def test_import_restores_rows_with_fidelity(sf, archive_dir):
    from src.pce_cache.archive_import import ArchiveImporter
    raw = {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2",
           "first_detected": "2026-06-30T11:00:00+00:00", "port": 443, "action": "blocked"}
    _write(archive_dir, "traffic-2026-06-30.jsonl", [_traffic_line("h1", "2026-06-30", raw)])

    res = ArchiveImporter(archive_dir, sf).import_range(date(2026, 6, 1), date(2026, 6, 30))
    assert res["rows"] == 1 and res["files"] == 1
    rows = _rows(sf)
    assert len(rows) == 1
    r = rows[0]
    assert r.flow_hash == "h1"
    assert r.port == 443 and r.action == "blocked"
    assert orjson.loads(r.raw_json) == raw            # raw 保真
    assert r.report_json is not None                  # 已補 report_json
    # first_detected 從 raw 回推（11:00），last_detected = event_time（12:00）
    assert r.first_detected.replace(tzinfo=timezone.utc).hour == 11
    assert r.last_detected.replace(tzinfo=timezone.utc).hour == 12


def test_import_reads_gzip_and_filters_by_range(sf, archive_dir):
    from src.pce_cache.archive_import import ArchiveImporter
    raw = {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 80, "action": "allowed"}
    _write(archive_dir, "traffic-2026-06-15.jsonl.gz", [_traffic_line("g1", "2026-06-15", raw)])
    _write(archive_dir, "traffic-2026-05-01.jsonl", [_traffic_line("out", "2026-05-01", raw)])

    res = ArchiveImporter(archive_dir, sf).import_range(date(2026, 6, 1), date(2026, 6, 30))
    assert res["rows"] == 1                            # 只匯入範圍內的 .gz
    assert {r.flow_hash for r in _rows(sf)} == {"g1"}


def test_import_skips_null_raw_and_dedups(sf, archive_dir):
    from src.pce_cache.archive_import import ArchiveImporter
    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 22, "action": "allowed"}
    lines = [
        _traffic_line("dup", "2026-06-10", raw),
        _traffic_line("dup", "2026-06-10", raw),          # 同 flow_hash → 去重
        orjson.dumps({"event_time": "2026-06-10T12:00:00+00:00",
                      "ingested_at": "2026-06-10T12:00:00+00:00",
                      "flow_hash": "nullraw", "raw": None}),  # raw=None → skip
    ]
    _write(archive_dir, "traffic-2026-06-10.jsonl", lines)

    res = ArchiveImporter(archive_dir, sf).import_range(date(2026, 6, 1), date(2026, 6, 30))
    assert res["rows"] == 1 and res["skipped"] == 2
    assert {r.flow_hash for r in _rows(sf)} == {"dup"}


def test_import_ignores_non_traffic_files(sf, archive_dir):
    from src.pce_cache.archive_import import ArchiveImporter
    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 1, "action": "allowed"}
    _write(archive_dir, "audit-2026-06-10.jsonl", [b'{"pce_event_id":"e1"}'])   # audit 不匯入
    _write(archive_dir, "notes.txt", [b"ignore"])
    _write(archive_dir, "traffic-2026-06-10.jsonl", [_traffic_line("t1", "2026-06-10", raw)])

    res = ArchiveImporter(archive_dir, sf).import_range(date(2026, 6, 1), date(2026, 6, 30))
    assert res["rows"] == 1 and res["files"] == 1
    assert {r.flow_hash for r in _rows(sf)} == {"t1"}
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_pce_cache_archive_import.py -v`
Expected: FAIL（`ModuleNotFoundError: src.pce_cache.archive_import`）。

- [ ] **Step 3: 實作**

Create `src/pce_cache/archive_import.py`:

```python
from __future__ import annotations

import gzip
import os
import re
from datetime import date, datetime, timezone

import orjson
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowRaw

_TRAFFIC_FILE = re.compile(r"^traffic-(\d{4}-\d{2}-\d{2})\.jsonl(?:\.gz)?$")


def _parse_dt(s: str) -> datetime:
    """archive ISO 時間戳 → aware UTC datetime。處理結尾 Z、明確 offset、
    以及 naive（早期未帶 offset 的 archive）→ 視為 UTC。"""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _iter_lines(path: str):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rb") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield line


class ArchiveImporter:
    """把 archive 的 traffic JSONL 逐行還原成 PceTrafficFlowRaw 灌進指定的 review DB。"""

    def __init__(self, archive_dir: str, session_factory: sessionmaker):
        self._dir = archive_dir
        self._sf = session_factory

    def import_range(self, start: date, end: date) -> dict:
        from src.report.parsers.api_parser import flatten_flow_record
        rows = files = skipped = 0
        try:
            names = sorted(os.listdir(self._dir))
        except OSError as exc:
            logger.warning("archive import: listdir {} failed: {}", self._dir, exc)
            names = []
        for name in names:
            m = _TRAFFIC_FILE.match(name)
            if not m:
                continue
            try:
                file_date = date.fromisoformat(m.group(1))
            except ValueError:
                continue
            if file_date < start or file_date > end:
                continue
            files += 1
            path = os.path.join(self._dir, name)
            for line in _iter_lines(path):
                try:
                    rec = orjson.loads(line)
                except orjson.JSONDecodeError:
                    skipped += 1
                    continue
                raw = rec.get("raw")
                if raw is None:
                    skipped += 1
                    continue
                last_detected = _parse_dt(rec["event_time"])
                ingested_at = _parse_dt(rec["ingested_at"])
                ts_range = raw.get("timestamp_range") or {}
                fd_raw = raw.get("first_detected") or ts_range.get("first_detected", "")
                first_detected = _parse_dt(fd_raw) if fd_raw else last_detected
                # 與即時 ingest / backfill 一致：預先算好 report_json，維持
                # ix_raw_report_json_null 的「幾乎無 NULL」不變量；flatten 失敗不阻斷。
                try:
                    report_json = orjson.dumps(flatten_flow_record(raw)).decode("utf-8")
                except Exception:  # noqa: BLE001
                    report_json = None
                try:
                    with self._sf.begin() as s:
                        s.add(PceTrafficFlowRaw(
                            flow_hash=rec["flow_hash"],
                            src_ip=rec.get("src_ip", ""),
                            src_workload=rec.get("src_workload"),
                            dst_ip=rec.get("dst_ip", ""),
                            dst_workload=rec.get("dst_workload"),
                            port=rec.get("port") or 0,
                            protocol=rec.get("protocol", "tcp"),
                            action=rec.get("action", "unknown"),
                            flow_count=rec.get("flow_count") or 1,
                            bytes_in=rec.get("bytes_in") or 0,
                            bytes_out=rec.get("bytes_out") or 0,
                            first_detected=first_detected,
                            last_detected=last_detected,
                            raw_json=orjson.dumps(raw).decode("utf-8"),
                            report_json=report_json,
                            ingested_at=ingested_at,
                        ))
                    rows += 1
                except IntegrityError:
                    skipped += 1
        return {"rows": rows, "files": files, "skipped": skipped,
                "start": start.isoformat(), "end": end.isoformat()}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_pce_cache_archive_import.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: naive-datetime 檢查**

Run: `python3 scripts/check_no_naive_datetime.py`
Expected: `OK: no naive datetime.now() outside the allowlist.`

- [ ] **Step 6: Commit**

```bash
git add src/pce_cache/archive_import.py tests/test_pce_cache_archive_import.py
git commit -m "feat(pce_cache): add ArchiveImporter to restore traffic archive into a DB"
```

---

## Task 4: Review DB 編排（重建 + 匯入 + 聚合 + sidecar meta）

**Files:**
- Modify: `src/pce_cache/archive_import.py`
- Test: `tests/test_pce_cache_archive_import.py`

**Interfaces:**
- Consumes: Task 3 `ArchiveImporter`；`src/pce_cache/aggregator.py` `TrafficAggregator`；`src/pce_cache/schema.py` `init_schema`。
- Produces（都吃一個 `cfg`＝`cm.models.pce_cache`，用 `cfg.db_path`/`cfg.archive_dir`）：
  - `review_db_path(cfg) -> str`
  - `load_archive_review(cfg, start: date, end: date) -> dict`（回 meta：`{"loaded","rows","files","skipped","start","end"}`）
  - `review_status(cfg) -> dict`（`{"loaded": False}` 或已存 meta）
  - `review_session_factory(cfg)`（供 Task 6 查詢用；對 review DB 建短命 engine 的 sessionmaker）
  - 供 Task 5/6 使用。

- [ ] **Step 1: 寫失敗測試**

Append to `tests/test_pce_cache_archive_import.py`:

```python
from types import SimpleNamespace


def _cfg(tmp_path, archive_dir):
    # review DB 會放在 db_path 同目錄；archive_review_max_days 由 route 用，這裡不需要
    return SimpleNamespace(db_path=str(tmp_path / "cache.sqlite"), archive_dir=archive_dir)


def test_load_review_rebuilds_imports_and_aggregates(tmp_path, archive_dir):
    from src.pce_cache.archive_import import (
        load_archive_review, review_status, review_db_path, review_session_factory)
    from src.pce_cache.models import PceTrafficFlowAgg
    from sqlalchemy import select
    raw = {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 443, "action": "blocked"}
    _write(archive_dir, "traffic-2026-06-20.jsonl", [_traffic_line("a1", "2026-06-20", raw)])
    cfg = _cfg(tmp_path, archive_dir)

    meta = load_archive_review(cfg, date(2026, 6, 1), date(2026, 6, 30))
    assert meta["loaded"] is True and meta["rows"] == 1
    assert os.path.exists(review_db_path(cfg))
    # status 反映 meta
    st = review_status(cfg)
    assert st["loaded"] is True and st["rows"] == 1 and st["start"] == "2026-06-01"
    # 聚合表有列（趨勢圖/KPI 用）
    with review_session_factory(cfg)() as s:
        assert len(s.execute(select(PceTrafficFlowAgg)).scalars().all()) >= 1


def test_load_review_rebuilds_on_second_load(tmp_path, archive_dir):
    from src.pce_cache.archive_import import load_archive_review, review_session_factory
    from src.pce_cache.models import PceTrafficFlowRaw
    from sqlalchemy import select
    raw = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 1, "action": "allowed"}
    _write(archive_dir, "traffic-2026-06-05.jsonl", [_traffic_line("first", "2026-06-05", raw)])
    _write(archive_dir, "traffic-2026-07-05.jsonl", [_traffic_line("second", "2026-07-05", raw)])
    cfg = _cfg(tmp_path, archive_dir)

    load_archive_review(cfg, date(2026, 6, 1), date(2026, 6, 30))   # 只含 first
    load_archive_review(cfg, date(2026, 7, 1), date(2026, 7, 31))   # 重建後只含 second
    with review_session_factory(cfg)() as s:
        hashes = {r.flow_hash for r in s.execute(select(PceTrafficFlowRaw)).scalars().all()}
    assert hashes == {"second"}   # 前一次載入已被重建清掉


def test_review_status_empty_when_never_loaded(tmp_path, archive_dir):
    from src.pce_cache.archive_import import review_status
    assert review_status(_cfg(tmp_path, archive_dir)) == {"loaded": False}
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_pce_cache_archive_import.py -k "review" -v`
Expected: FAIL（`load_archive_review` 等未定義）。

- [ ] **Step 3: 實作**

Append to `src/pce_cache/archive_import.py`:

```python
def review_db_path(cfg) -> str:
    """review DB 放在 cache db_path 同目錄下，固定檔名。"""
    base = os.path.dirname(os.path.abspath(cfg.db_path))
    return os.path.join(base, "archive_review.sqlite")


def _meta_path(cfg) -> str:
    return review_db_path(cfg) + ".meta.json"


def review_session_factory(cfg):
    """對 review DB 建一個 sessionmaker（短命 engine，不用 process 快取，
    避免 review DB 被重建後抓到舊連線）。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{review_db_path(cfg)}")
    init_schema(engine)
    return sessionmaker(engine)


def load_archive_review(cfg, start: date, end: date) -> dict:
    """重建 review DB → 匯入範圍內 traffic archive → 跑聚合 → 寫 sidecar meta。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.aggregator import TrafficAggregator
    db = review_db_path(cfg)
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(db + suffix)
        except FileNotFoundError:
            pass
    engine = create_engine(f"sqlite:///{db}")
    try:
        init_schema(engine)
        sf = sessionmaker(engine)
        result = ArchiveImporter(cfg.archive_dir, sf).import_range(start, end)
        TrafficAggregator(sf).run_once()
    finally:
        engine.dispose()  # 釋放檔案 handle，讓下次重建能安全刪檔
    meta = {"loaded": True, "rows": result["rows"], "files": result["files"],
            "skipped": result["skipped"], "start": result["start"], "end": result["end"]}
    with open(_meta_path(cfg), "wb") as fh:
        fh.write(orjson.dumps(meta))
    return meta


def review_status(cfg) -> dict:
    try:
        with open(_meta_path(cfg), "rb") as fh:
            return orjson.loads(fh.read())
    except FileNotFoundError:
        return {"loaded": False}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_pce_cache_archive_import.py -v`
Expected: PASS（Task 3 的 4 個 + 本任務 3 個 = 7 passed）。

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache/archive_import.py tests/test_pce_cache_archive_import.py
git commit -m "feat(pce_cache): add archive review DB rebuild/load/status helpers"
```

---

## Task 5: 後端 route `/archive/load` 與 `/archive/status`

**Files:**
- Modify: `src/pce_cache/web.py`（cache blueprint，url_prefix `/api/cache`）
- Test: `tests/test_cache_web.py`

**Interfaces:**
- Consumes: Task 1 `cfg.archive_review_max_days`；Task 4 `load_archive_review`/`review_status`。
- Produces:
  - `POST /api/cache/archive/load` body `{"start_date","end_date"}`（`YYYY-MM-DD`）→ `{ok, rows, files, skipped, start, end}`；驗證失敗回 422/400。
  - `GET /api/cache/archive/status` → `review_status(cfg)`。
  - 供 Task 8 前端使用。

**注意**：沿用該檔既有 route 風格（`@bp.route`, `@login_required`, `current_app.config['CM']`）。參考同檔既有 `put_cache_settings`（`src/pce_cache/web.py` 內）的 blueprint/裝飾子寫法。

- [ ] **Step 1: 寫失敗測試**

Append to `tests/test_cache_web.py`（沿用該檔既有 `client` fixture）：

```python
def _seed_archive(tmp_path):
    import gzip  # noqa: F401
    import orjson
    d = tmp_path / "arch"
    d.mkdir()
    rec = orjson.dumps({
        "event_time": "2026-06-20T12:00:00+00:00",
        "ingested_at": "2026-06-20T12:00:00+00:00",
        "flow_hash": "aw1", "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2",
        "port": 443, "protocol": "tcp", "action": "blocked",
        "flow_count": 1, "bytes_in": 1, "bytes_out": 1,
        "raw": {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 443, "action": "blocked"},
    })
    with open(d / "traffic-2026-06-20.jsonl", "wb") as fh:
        fh.write(rec + b"\n")
    return str(d)


def test_archive_load_and_status_roundtrip(client, tmp_path):
    arch = _seed_archive(tmp_path)
    # 先把 archive_dir 指到種好的目錄（review DB 會放在 db_path 同目錄）
    client.put("/api/cache/settings", json={"archive_dir": arch},
               environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    resp = client.post("/api/cache/archive/load",
                       json={"start_date": "2026-06-01", "end_date": "2026-06-30"},
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True and body["rows"] == 1
    st = client.get("/api/cache/archive/status",
                    environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert st["loaded"] is True and st["rows"] == 1


def test_archive_load_rejects_range_over_cap(client):
    resp = client.post("/api/cache/archive/load",
                       json={"start_date": "2026-01-01", "end_date": "2026-12-31"},
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 422


def test_archive_load_rejects_bad_dates(client):
    resp = client.post("/api/cache/archive/load",
                       json={"start_date": "nope", "end_date": "2026-06-30"},
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 400
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_cache_web.py -k archive -v`
Expected: FAIL（route 尚未存在 → 404）。

- [ ] **Step 3: 實作**

在 `src/pce_cache/web.py` 檔尾（blueprint `bp` 已定義）新增：

```python
@bp.route("/archive/load", methods=["POST"])
@login_required
def load_archive():
    from datetime import date
    from src.pce_cache.archive_import import load_archive_review
    cm = current_app.config['CM']
    cfg = cm.models.pce_cache
    body = request.get_json(silent=True) or {}
    try:
        start = date.fromisoformat(body.get("start_date", ""))
        end = date.fromisoformat(body.get("end_date", ""))
    except ValueError:
        return jsonify({"ok": False, "error": "invalid date (YYYY-MM-DD)"}), 400
    if end < start:
        return jsonify({"ok": False, "error": "end before start"}), 400
    span = (end - start).days + 1
    if span > int(cfg.archive_review_max_days):
        return jsonify({"ok": False,
                        "error": f"range {span}d exceeds max {cfg.archive_review_max_days}d"}), 422
    try:
        meta = load_archive_review(cfg, start, end)
    except Exception as exc:  # noqa: BLE001
        logger.exception("archive load failed: {}", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, **meta})


@bp.route("/archive/status", methods=["GET"])
@login_required
def archive_status():
    from src.pce_cache.archive_import import review_status
    cm = current_app.config['CM']
    return jsonify(review_status(cm.models.pce_cache))
```

（確認該檔頂部已 import `jsonify`, `request`, `current_app`, `login_required`, `logger`；若缺則比照同檔既有 route 補上。）

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_cache_web.py -k archive -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache/web.py tests/test_cache_web.py
git commit -m "feat(pce_cache): add archive review load/status API endpoints"
```

---

## Task 6: `source=archive` 分支（`api_quarantine_search` + `api_traffic_trend`）

**Files:**
- Modify: `src/gui/routes/actions.py`（`api_quarantine_search` 約 `:41-106`；`api_traffic_trend` 約 `:425-489`）
- Test: `tests/test_actions_archive_source.py`（新增）

**Interfaces:**
- Consumes: Task 2 `_make_cache_reader(cm, db_path=...)`；Task 4 `review_db_path`；既有 `_get_cache_engine`（僅 live 用）。
- Produces: 兩個 route 讀 request 的 `source`（`"live"` 預設 / `"archive"`）。`archive` 時對 review DB 查詢：
  - `api_quarantine_search`：`_make_cache_reader(cm, db_path=review_db_path(cfg))` 取代 `_make_cache_reader(cm)`。
  - `api_traffic_trend`：`sf = sessionmaker(create_engine(f"sqlite:///{review_db_path(cfg)}"))`（**不用** `_get_cache_engine`，用完 `engine.dispose()`）取代既有 `sessionmaker(_get_cache_engine(cfg.db_path))`。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_actions_archive_source.py`:

```python
from datetime import date

import pytest
from src.config import ConfigManager


@pytest.fixture
def client(tmp_path):
    import json, os, tempfile
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    arch = tmp_path / "arch"; arch.mkdir()
    import orjson
    rec = orjson.dumps({
        "event_time": "2026-06-20T12:00:00+00:00", "ingested_at": "2026-06-20T12:00:00+00:00",
        "flow_hash": "src1", "src_ip": "10.0.0.9", "dst_ip": "10.0.0.8",
        "port": 443, "protocol": "tcp", "action": "blocked", "flow_count": 1,
        "bytes_in": 1, "bytes_out": 1,
        "raw": {"src_ip": "10.0.0.9", "dst_ip": "10.0.0.8", "port": 443, "action": "blocked"}})
    with open(arch / "traffic-2026-06-20.jsonl", "wb") as fh:
        fh.write(rec + b"\n")
    with open(path, "w") as f:
        json.dump({"web_gui": {"username": "admin", "password": "pw", "secret_key": "s",
                               "allowed_ips": ["127.0.0.1"]},
                   "pce_cache": {"enabled": True, "db_path": str(tmp_path / "cache.sqlite"),
                                 "archive_dir": str(arch)}}, f)
    cm = ConfigManager(config_file=path)
    from src.gui import _create_app
    app = _create_app(cm, persistent_mode=True)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/api/login", json={"username": "admin", "password": "pw"},
               environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        yield c, cm
    os.unlink(path)


def test_quarantine_search_archive_source_reads_review_db(client):
    c, cm = client
    from src.pce_cache.archive_import import load_archive_review
    load_archive_review(cm.models.pce_cache, date(2026, 6, 1), date(2026, 6, 30))
    resp = c.post("/api/quarantine/search",
                  json={"source": "archive", "start": "2026-06-01T00:00:00+00:00",
                        "end": "2026-06-30T23:59:59+00:00"},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    # 回應中應含 review DB 那筆 flow（以 src_ip 佐證來自 archive）
    assert "10.0.0.9" in resp.get_data(as_text=True)
```

（注意：`/api/quarantine/search` 的請求/回應精確欄位以該 route 既有實作為準；實作本任務時先讀 `src/gui/routes/actions.py:41-106` 確認參數名與回應格式，必要時調整測試斷言為「archive 來源時查到那筆、live 來源時查不到」。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_actions_archive_source.py -v`
Expected: FAIL（`source=archive` 未生效 → 查不到 review 資料）。

- [ ] **Step 3: 實作**

先讀 `src/gui/routes/actions.py` 的 `api_quarantine_search` 與 `api_traffic_trend`。在 `api_quarantine_search` 內，取得 `cm`/`cfg` 後、建 reader 前，加：

```python
    source = (request.get_json(silent=True) or {}).get("source", "live")
    from src.pce_cache.archive_import import review_db_path
    reader_db = review_db_path(cm.models.pce_cache) if source == "archive" else None
    # 原本： cache_reader=_make_cache_reader(cm)
    base_ana = Analyzer(cm, api, Reporter(cm), cache_reader=_make_cache_reader(cm, db_path=reader_db))
```

在 `api_traffic_trend` 內，把取得 `sf` 的那行改為依 `source` 切換：

```python
    source = request.args.get("source") or (request.get_json(silent=True) or {}).get("source", "live")
    if source == "archive":
        from sqlalchemy import create_engine
        from src.pce_cache.archive_import import review_db_path
        engine = create_engine(f"sqlite:///{review_db_path(cfg)}")
        sf = sessionmaker(engine)
        try:
            ...  # 既有查詢邏輯
        finally:
            engine.dispose()
    else:
        sf = sessionmaker(_get_cache_engine(cfg.db_path))
        ...  # 既有查詢邏輯
```

（實作時保持既有查詢主體不動，只在來源上分岔；若既有主體較長，抽一個小 helper `_trend_from_sf(sf, ...)` 避免重複，符合 DRY。）

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_actions_archive_source.py -v`
Expected: PASS。

- [ ] **Step 5: 回歸**

Run: `python3 -m pytest tests/test_actions_quarantine.py tests/test_actions.py -v`（若存在；以實際檔名為準）
Expected: 既有 traffic 查詢/趨勢測試不因新增 `source` 分支而失敗（不帶 source 走 live）。

- [ ] **Step 6: Commit**

```bash
git add src/gui/routes/actions.py tests/test_actions_archive_source.py
git commit -m "feat(gui): route traffic query/trend to archive review DB when source=archive"
```

---

## Task 7: i18n key

**Files:**
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_i18n_quality.py`（既有 parity，不新增測試碼）

**Interfaces:**
- Produces: 供 Task 8 前端 `data-i18n` 使用的 key（兩檔同步、非空）。

- [ ] **Step 1: 加 key（兩檔同步、依字母序）**

在 `src/i18n_en.json` 適當字母序位置加入：

```json
  "gui_traffic_source": "Data source",
  "gui_traffic_source_live": "Live cache",
  "gui_traffic_source_archive": "Archive",
  "gui_traffic_archive_range": "Archive date range",
  "gui_traffic_archive_load": "Load archive",
  "gui_traffic_archive_loaded_fmt": "Loaded: {start} to {end} ({n} rows)",
  "gui_traffic_archive_none": "No archive loaded",
  "gui_traffic_archive_load_error": "Archive load failed: {err}",
```

在 `src/i18n_zh_TW.json` 相同字母序位置加入對應繁中（非空）：

```json
  "gui_traffic_source": "資料來源",
  "gui_traffic_source_live": "即時快取",
  "gui_traffic_source_archive": "封存 (Archive)",
  "gui_traffic_archive_range": "封存日期範圍",
  "gui_traffic_archive_load": "載入封存",
  "gui_traffic_archive_loaded_fmt": "已載入：{start} 至 {end}（{n} 筆）",
  "gui_traffic_archive_none": "尚未載入封存",
  "gui_traffic_archive_load_error": "封存載入失敗：{err}",
```

- [ ] **Step 2: 驗 JSON + parity**

Run:
```bash
python3 -c "import json; json.load(open('src/i18n_en.json')); json.load(open('src/i18n_zh_TW.json')); print('valid')"
python3 -m pytest tests/test_i18n_quality.py -v
```
Expected: valid + PASS。

- [ ] **Step 3: Commit**

```bash
git add src/i18n_en.json src/i18n_zh_TW.json
git commit -m "i18n: add archive-review traffic source strings"
```

---

## Task 8: 前端來源切換 + 載入控制 + 狀態

**Files:**
- Modify: `src/templates/index.html`（`q-panel-traffic` 流量查詢面板，約 `:807`）
- Modify: `src/static/js/quarantine.js`（`runTrafficAnalyzer` 約 `:237`，趨勢圖載入約 `:13-14`）
- （若面板由 `dashboard.js` 組裝，對應調整；實作前先讀這兩檔確認 DOM 與請求建構點。）

**Interfaces:**
- Consumes: Task 5 `/api/cache/archive/load`、`/api/cache/archive/status`；Task 7 i18n key。
- Produces: 使用者可見的來源切換與載入 UI；查詢請求帶 `source`。

**注意**：本專案前端無 JS 單元測試框架；本任務以 `node --check` 驗語法，功能由 Task 5 的後端 round-trip 測試間接保證，最終在測試機目視驗收。實作前務必先讀 `q-panel-traffic` 既有 markup 與 `runTrafficAnalyzer` 既有 payload 建構，沿用既有樣式/請求慣例。

- [ ] **Step 1: 在流量面板加來源切換 + 載入控制**

在 `q-panel-traffic` 查詢控制區加入（沿用面板既有 class）：

```html
<div class="form-group">
  <label data-i18n="gui_traffic_source">Data source</label>
  <select id="traffic-source">
    <option value="live" data-i18n="gui_traffic_source_live">Live cache</option>
    <option value="archive" data-i18n="gui_traffic_source_archive">Archive</option>
  </select>
</div>
<div id="traffic-archive-controls" style="display:none;">
  <label data-i18n="gui_traffic_archive_range">Archive date range</label>
  <input type="date" id="archive-start">
  <input type="date" id="archive-end">
  <button type="button" class="btn" onclick="loadArchiveRange()" data-i18n="gui_traffic_archive_load">Load archive</button>
  <span id="archive-status" style="font-size:.8rem;color:var(--dim);"></span>
</div>
```

- [ ] **Step 2: JS — 切換顯示、載入、狀態、查詢帶 source**

在 `src/static/js/quarantine.js` 加入（並在面板初始化時綁定 `#traffic-source` 的 change 事件呼叫 `_syncTrafficSource()`、載入時呼叫 `refreshArchiveStatus()`）：

```javascript
function _syncTrafficSource() {
  var sel = document.getElementById('traffic-source');
  var box = document.getElementById('traffic-archive-controls');
  if (box) box.style.display = (sel && sel.value === 'archive') ? '' : 'none';
  if (sel && sel.value === 'archive') refreshArchiveStatus();
}

async function refreshArchiveStatus() {
  var el = document.getElementById('archive-status');
  if (!el) return;
  try {
    var st = await (await fetch('/api/cache/archive/status')).json();
    el.textContent = st.loaded
      ? _t('gui_traffic_archive_loaded_fmt').replace('{start}', st.start).replace('{end}', st.end).replace('{n}', st.rows)
      : _t('gui_traffic_archive_none');
  } catch (e) { el.textContent = ''; }
}

async function loadArchiveRange() {
  var start = document.getElementById('archive-start').value;
  var end = document.getElementById('archive-end').value;
  var el = document.getElementById('archive-status');
  el.textContent = '...';
  try {
    var resp = await fetch('/api/cache/archive/load', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
      body: JSON.stringify({start_date: start, end_date: end}),
    });
    var body = await resp.json();
    if (body.ok) { refreshArchiveStatus(); }
    else { el.textContent = _t('gui_traffic_archive_load_error').replace('{err}', body.error || resp.status); }
  } catch (e) {
    el.textContent = _t('gui_traffic_archive_load_error').replace('{err}', String(e));
  }
}
```

在 `runTrafficAnalyzer()` 建構查詢 payload 處，加入來源：

```javascript
  var srcSel = document.getElementById('traffic-source');
  payload.source = srcSel ? srcSel.value : 'live';   // payload = 既有查詢物件
```

（趨勢圖請求同理：若來源為 archive，於 `/api/traffic/trend` 帶 `?source=archive`。）

- [ ] **Step 3: 語法檢查**

Run: `node --check src/static/js/quarantine.js`
Expected: 無輸出（語法 OK）。

- [ ] **Step 4: Commit**

```bash
git add src/templates/index.html src/static/js/quarantine.js
git commit -m "feat(gui): add live/archive source toggle and archive load controls to traffic panel"
```

---

## Task 9: 整合回歸 + 收尾

**Files:** 無（純驗證）

- [ ] **Step 1: 相關全套回歸**

Run:
```bash
python3 -m pytest tests/test_config_pce_cache_archive.py tests/test_make_cache_reader.py \
  tests/test_pce_cache_archive_import.py tests/test_cache_web.py \
  tests/test_actions_archive_source.py tests/test_i18n_quality.py -v
```
Expected: 全綠。

- [ ] **Step 2: naive-datetime 檢查**

Run: `python3 scripts/check_no_naive_datetime.py`
Expected: OK。

- [ ] **Step 3: 完整套件**

Run: `python3 -m pytest tests/ -q`
Expected: 全綠（新增測試通過、無回歸）。

---

## Self-Review（對照 spec）

- Importer 還原保真 + first_detected/report_json 補齊 + gzip + 範圍過濾 + 去重 + null-raw skip → Task 3。
- review DB 重建 + 聚合 + sidecar meta + status → Task 4。
- 範圍上限、載入/狀態 API → Task 1 + Task 5。
- 換源（reader 參數化 + route 分支）→ Task 2 + Task 6。
- 前端來源切換 + 載入 + 狀態 → Task 7 + Task 8。
- 引擎生命週期（review DB 重建不用 process 快取、用完 dispose）→ Task 4 `load_archive_review`/`review_session_factory`、Task 6 `api_traffic_trend` 的 `engine.dispose()`。
- 向後相容（不帶 source 走 live、db_path=None 維持 enabled 守門）→ Task 2 + Task 6。

**已知取捨（非缺口）：** 單一 review DB、後載覆蓋前載、無多使用者併發保護（Non-goal）；事件檢視 archive 留 Phase 2；Dashboard Top10 不吃 archive（使用者確認不做）。
