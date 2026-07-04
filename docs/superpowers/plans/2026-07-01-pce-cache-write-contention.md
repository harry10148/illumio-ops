# PCE Cache 並發寫鎖根治 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除多個排程 job 對單寫者 SQLite cache DB 的破壞性寫鎖競爭，讓 traffic ingest 不再因 `database is locked` 失敗、watermark 不再凍結、pipeline 不再誤判 error。

**Architecture:** 方案 A —— 新增 `max_workers=1` 的 `cache_writer` APScheduler executor，把重量級 cache 批次寫入 job（events/traffic ingest、aggregate、retention）指派給它，使其彼此永不並發（app 尊重 SQLite 單寫者）；慢速外部 I/O 的 job（`monitor_cycle`、`siem_dispatch`）留在 default executor。另修兩個 churn 缺陷（`lag_monitor` 每 60s 重跑 DDL；`siem_dispatch` 逐列 commit）與一個可觀測性缺陷（ingest insert 失敗時 watermark 未記 error）。

**Tech Stack:** Python 3、APScheduler 3.x（BackgroundScheduler + ThreadPoolExecutor executors）、SQLAlchemy 2.x ORM、SQLite（WAL）、Pydantic v2、pytest。

## Global Constraints

- 對話／回應／說明／程式碼註解一律**繁體中文**；**commit message 用英文 conventional-commits**（照 repo 慣例，如 `feat(...)`/`docs:`/`i18n:`）；**全部一律無 emoji**（使用者全域規則）。
- **Surgical changes**：只動與本功能相關的行；不順手重構、不修其他既有問題。
- **向後相容硬需求**：既有測試不得因本改動而失敗。唯一需同步更新的既有測試是 `tests/test_config_models.py:111`（斷言 `dispatch_tick_seconds` 預設值，隨 Task 1 由 5 改 30）。
- **單一 DB**：不新增資料表/欄位、不換 DB 引擎、無新相依。
- **item 4 語意**：ingest insert 失敗時 `record_error` 後 **re-raise**（不吞例外），保留既有 re-raise 契約與 `jobs.py` 的 `logger.exception`。
- **測試隔離**：單元測試只用 `tmp_path`/`:memory:` 建臨時 SQLite，不碰真實 PCE 或真實 `data/`。
- **序列化不含慢 I/O job**：`monitor_cycle`（打 PCE API）、`siem_dispatch`（送 SIEM）**不得**放進 `cache_writer` executor，否則會反向阻塞 ingest。
- **與 archive plan 的交會**：本 plan 與 `2026-07-01-pce-cache-archive.md` 都改 `src/scheduler/__init__.py` 的 cache 區塊。最終狀態中，`pce_cache_archive` job（archive plan 新增）也必須帶 `executor="cache_writer"`（見 Task 2 Step 6 註記）。

---

## File Structure

- **Modify** `src/config_models.py` — `SiemForwarderSettings.dispatch_tick_seconds` 預設 5→30（`src/config_models.py:318`）。
- **Modify** `tests/test_config_models.py` — 更新預設值斷言（`:111`）。
- **Modify** `src/scheduler/__init__.py` — 新增 `cache_writer` executor（`:32`）、4 個 cache 批次 job 加 `executor="cache_writer"`（`:132-141`）。
- **Create** `tests/test_scheduler_write_serialization.py` — executor 指派測試。
- **Modify** `src/pce_cache/lag_monitor.py` — `run_cache_lag_monitor` 改用 `_get_cache_engine`（`:50-59`）。
- **Create** `tests/test_lag_monitor_cached_engine.py` — lag_monitor 純讀測試。
- **Modify** `src/siem/dispatcher.py` — `_process_batch` 成功路徑批次化（`:69-121`）。
- **Modify** `tests/test_siem_dispatcher.py` — 追加批次化測試（不改既有測試）。
- **Modify** `src/pce_cache/ingestor_traffic.py` — insert 失敗 `record_error`+re-raise（`:52-66`）。
- **Modify** `src/pce_cache/ingestor_events.py` — insert 失敗 `record_error`+re-raise（`:63-68`）。
- **Modify** `tests/test_pce_cache_ingestor_traffic.py`、`tests/test_pce_cache_ingestor_events.py` — 追加 item 4 測試。

---

## Task 1: siem `dispatch_tick_seconds` 預設 5→30

**Files:**
- Modify: `src/config_models.py:318`
- Modify: `tests/test_config_models.py:111`

**Interfaces:**
- Consumes: 無。
- Produces: `SiemForwarderSettings().dispatch_tick_seconds == 30`（`src/scheduler/__init__.py` 註冊 `siem_dispatch` 時讀此值決定 tick 間隔）。

- [ ] **Step 1: 更新既有預設值測試（先讓它反映目標值 → 變紅）**

在 `tests/test_config_models.py:111`，把：

```python
    assert cfg.dispatch_tick_seconds == 5
```

改為：

```python
    assert cfg.dispatch_tick_seconds == 30
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_config_models.py::test_siem_forwarder_settings_defaults -v`
Expected: FAIL（目前預設仍為 5，斷言 30 失敗）。

- [ ] **Step 3: 改預設值**

在 `src/config_models.py:318`（`SiemForwarderSettings` 內），把：

```python
    dispatch_tick_seconds: int = Field(default=5, ge=1)
```

改為：

```python
    dispatch_tick_seconds: int = Field(default=30, ge=1)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_config_models.py -v`
Expected: PASS。

- [ ] **Step 5: 確認顯式設定不受影響（回歸）**

Run: `python -m pytest tests/test_siem_forwarder_api.py tests/test_siem_test_endpoint.py -v`
Expected: PASS（這些測試以顯式 `dispatch_tick_seconds` 值送 payload，不依賴預設）。

- [ ] **Step 6: Commit**

```bash
git add src/config_models.py tests/test_config_models.py
git commit -m "feat(siem): raise dispatch_tick_seconds default 5s->30s"
```

---

## Task 2: 排程序列化（`cache_writer` executor）

**Files:**
- Modify: `src/scheduler/__init__.py:32`（executors）、`src/scheduler/__init__.py:132-141`（4 個 add_job）
- Test: `tests/test_scheduler_write_serialization.py`

**Interfaces:**
- Consumes: 無。
- Produces: `build_scheduler(cm)` 產生的 scheduler 中，`pce_cache_ingest_events`/`pce_cache_ingest_traffic`/`pce_cache_aggregate`/`pce_cache_retention` 的 `job.executor == "cache_writer"`；存在 `max_workers=1` 的 `cache_writer` executor；`cache_lag_monitor`/`monitor_cycle` 維持 `executor == "default"`。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_scheduler_write_serialization.py`:

```python
from unittest.mock import MagicMock


def _make_cm():
    cm = MagicMock()
    cm.config = {}                       # 真 dict，讓 .get(...) 走預設
    cm.models.pce_cache.enabled = True
    cm.models.pce_cache.events_poll_interval_seconds = 300
    cm.models.pce_cache.traffic_poll_interval_seconds = 3600
    cm.models.siem.enabled = False       # 跳過 siem 註冊，聚焦 cache 區塊
    return cm


def test_cache_batch_writers_share_single_worker_executor():
    from src.scheduler import build_scheduler
    sched = build_scheduler(_make_cm())
    sched.start(paused=True)             # flush pending jobs 到 jobstore，不實際跑
    try:
        for jid in ("pce_cache_ingest_events", "pce_cache_ingest_traffic",
                    "pce_cache_aggregate", "pce_cache_retention"):
            assert sched.get_job(jid).executor == "cache_writer", jid
        for jid in ("cache_lag_monitor", "monitor_cycle"):
            assert sched.get_job(jid).executor == "default", jid
        assert "cache_writer" in sched._executors
        assert sched._executors["cache_writer"]._pool._max_workers == 1
    finally:
        sched.shutdown(wait=False)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_scheduler_write_serialization.py -v`
Expected: FAIL（尚無 `cache_writer` executor；4 個 job 目前為 `default`；`sched._executors["cache_writer"]` KeyError）。

- [ ] **Step 3: 新增 `cache_writer` executor**

在 `src/scheduler/__init__.py:32`，把：

```python
    executors = {"default": ThreadPoolExecutor(max_workers=5)}
```

改為：

```python
    executors = {
        "default": ThreadPoolExecutor(max_workers=5),
        # 單一 writer：SQLite 本就序列化寫者，強制這些 cache 批次 job 共用一個
        # worker → 消除 traffic/events ingest vs aggregate/retention/archive 的
        # 破壞性寫鎖競爭。慢 I/O 的 monitor_cycle/siem_dispatch 留在 default，
        # 避免反向阻塞 ingest。
        "cache_writer": ThreadPoolExecutor(max_workers=1),
    }
```

- [ ] **Step 4: 把 4 個 cache 批次 job 指派到 `cache_writer`**

在 `src/scheduler/__init__.py:132-141`，把這四個 `add_job` 各加一個 `executor="cache_writer"` 參數：

```python
            sched.add_job(run_events_ingest, _IT(seconds=cache_cfg.events_poll_interval_seconds),
                          args=[cm], id="pce_cache_ingest_events", replace_existing=True,
                          next_run_time=_kick, executor="cache_writer")
            sched.add_job(run_traffic_ingest, _IT(seconds=cache_cfg.traffic_poll_interval_seconds),
                          args=[cm], id="pce_cache_ingest_traffic", replace_existing=True,
                          next_run_time=_kick, executor="cache_writer")
            sched.add_job(run_traffic_aggregate, _IT(hours=1),
                          args=[cm], id="pce_cache_aggregate", replace_existing=True,
                          executor="cache_writer")
            sched.add_job(run_cache_retention, _IT(hours=24),
                          args=[cm], id="pce_cache_retention", replace_existing=True,
                          executor="cache_writer")
```

`run_cache_lag_monitor`（`:142-143`）**不加** `executor`（Task 3 後變純讀，留在 default 可與寫入並行）。

- [ ] **Step 5: 跑測試確認通過**

Run: `python -m pytest tests/test_scheduler_write_serialization.py -v`
Expected: PASS。

- [ ] **Step 6: 回歸 + archive job 交會註記**

Run: `python -m pytest tests/test_scheduler_engine_cache.py -v`
Expected: PASS。

註記（不在本 Task 動手，供實作者知悉）：若 `2026-07-01-pce-cache-archive.md` 已落地，其新增的 `sched.add_job(run_cache_archive, ..., id="pce_cache_archive", ...)` 也應加 `executor="cache_writer"`。兩 plan 落地順序不拘，最終狀態需確保 archive job 在 `cache_writer` 上。

- [ ] **Step 7: Commit**

```bash
git add src/scheduler/__init__.py tests/test_scheduler_write_serialization.py
git commit -m "feat(scheduler): serialize cache batch writers on single-worker executor"
```

---

## Task 3: `lag_monitor` 去 DDL churn

**Files:**
- Modify: `src/pce_cache/lag_monitor.py:50-59`
- Test: `tests/test_lag_monitor_cached_engine.py`

**Interfaces:**
- Consumes: `src/gui/_helpers.py` 的 `_get_cache_engine`（每 db_path 快取、`init_schema` 只跑一次）。
- Produces: `run_cache_lag_monitor(cm)` 每 tick 走 `_get_cache_engine`，不再每 tick `create_engine + init_schema`。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_lag_monitor_cached_engine.py`:

```python
from unittest.mock import MagicMock, patch


def test_lag_monitor_uses_cached_engine_and_skips_per_tick_ddl(tmp_path):
    from src.pce_cache import lag_monitor
    cm = MagicMock()
    cm.models.pce_cache.db_path = str(tmp_path / "c.sqlite")
    cm.models.pce_cache.events_poll_interval_seconds = 300
    cm.models.pce_cache.traffic_poll_interval_seconds = 3600

    with patch("src.gui._helpers._get_cache_engine") as mock_ge, \
         patch("src.pce_cache.schema.init_schema") as mock_init, \
         patch("src.pce_cache.lag_monitor.check_cache_lag", return_value=[]) as mock_check:
        lag_monitor.run_cache_lag_monitor(cm)
        lag_monitor.run_cache_lag_monitor(cm)

    assert mock_ge.call_count == 2      # 每 tick 取快取 engine（cache hit，便宜）
    assert mock_init.call_count == 0    # lag_monitor 自己不再跑 init_schema DDL
    assert mock_check.call_count == 2
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_lag_monitor_cached_engine.py -v`
Expected: FAIL（現行程式每 tick `create_engine + init_schema`：`mock_ge` 0 次、`mock_init` 2 次，皆不符）。

- [ ] **Step 3: 改用 `_get_cache_engine`**

把 `src/pce_cache/lag_monitor.py:50-59` 的：

```python
def run_cache_lag_monitor(cm) -> None:
    """APScheduler job: check ingestor lag, log if stalled."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker as _SM
    from src.pce_cache.schema import init_schema

    cfg = cm.models.pce_cache
    engine = create_engine(f"sqlite:///{cfg.db_path}")
    init_schema(engine)
    sf = _SM(engine)
```

改為：

```python
def run_cache_lag_monitor(cm) -> None:
    """APScheduler job: check ingestor lag, log if stalled."""
    from sqlalchemy.orm import sessionmaker as _SM
    from src.gui._helpers import _get_cache_engine

    cfg = cm.models.pce_cache
    sf = _SM(_get_cache_engine(cfg.db_path))
```

（`_get_cache_engine` 內部已在每 db_path 首次建立時跑一次 `init_schema`；後續 tick 命中快取，不再重跑 DDL。）

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_lag_monitor_cached_engine.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache/lag_monitor.py tests/test_lag_monitor_cached_engine.py
git commit -m "fix(pce_cache): lag_monitor reuses cached engine, stops per-tick DDL"
```

---

## Task 4: `siem_dispatch` 成功路徑批次化

**Files:**
- Modify: `src/siem/dispatcher.py:69-121`（`_process_batch`）
- Test: `tests/test_siem_dispatcher.py`

**Interfaces:**
- Consumes: 既有 `SiemDispatch` model、`session_factory`。
- Produces: `_process_batch` 對成功送出的列，改為**單一 transaction** 一次 `UPDATE ... SET status='sent', sent_at=<batch time>`（失敗/退避/quarantine 維持逐列）。回傳 `{"sent","failed","quarantined"}` 語意不變。

- [ ] **Step 1: 寫失敗測試（批次化：N 筆成功只開一個寫交易）**

Append to `tests/test_siem_dispatcher.py`:

```python
class _CountingSF:
    """包住 sessionmaker，計數 .begin() 呼叫次數（= 寫交易數）。"""
    def __init__(self, sf):
        self._sf = sf
        self.begin_calls = 0
    def __call__(self, *a, **k):
        return self._sf(*a, **k)
    def begin(self, *a, **k):
        self.begin_calls += 1
        return self._sf.begin(*a, **k)


class _FakeFormatter:
    def format_event(self, data): return "PAYLOAD"
    def format_flow(self, data): return "PAYLOAD"


def test_process_batch_marks_all_sent_in_one_transaction(sf):
    from src.siem.dispatcher import DestinationDispatcher
    for i in range(1, 4):
        _seed_event(sf, i)               # 3 筆 pending，destination="test-dest"
    counting = _CountingSF(sf)
    d = DestinationDispatcher("test-dest", counting, _FakeFormatter(), SuccessTransport())

    result = d.tick()

    assert result["sent"] == 3
    with sf() as s:
        rows = s.execute(select(SiemDispatch)).scalars().all()
    assert all(r.status == "sent" for r in rows)
    assert all(r.sent_at is not None for r in rows)
    assert counting.begin_calls == 1     # 3 筆成功 → 僅一個寫交易
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_siem_dispatcher.py::test_process_batch_marks_all_sent_in_one_transaction -v`
Expected: FAIL（現行逐列 commit → `begin_calls == 3`，斷言 1 失敗）。

- [ ] **Step 3: 批次化成功路徑**

把 `src/siem/dispatcher.py` 的 `_process_batch`（`:69-121`）改為（成功收集 id、迴圈後單一 UPDATE；失敗/quarantine 維持逐列）：

```python
    def _process_batch(self) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        sent = failed = quarantined = 0
        sent_ids: list[int] = []

        with self._sf() as s:
            rows = s.execute(
                select(SiemDispatch)
                .where(SiemDispatch.destination == self._name)
                .where(SiemDispatch.status == "pending")
                .where(
                    (SiemDispatch.next_attempt_at == None) |  # noqa: E711
                    (SiemDispatch.next_attempt_at <= now)
                )
                .order_by(SiemDispatch.queued_at)
                .limit(self._batch_size)
            ).scalars().all()

        for dispatch_row in rows:
            payload = self._build_payload(dispatch_row)
            if payload is None:
                # Route build failures through the DLQ (not a bare status='failed')
                # so the dropped event stays inspectable and replayable.
                self._quarantine(dispatch_row, None, "payload_build_failed")
                quarantined += 1
                continue
            try:
                self._transport.send(payload)
                sent_ids.append(dispatch_row.id)
                sent += 1
            except Exception as exc:
                logger.warning("SIEM dispatch failed for row {}: {}", dispatch_row.id, exc)
                new_retries = dispatch_row.retries + 1
                if new_retries >= self._max_retries:
                    self._quarantine(dispatch_row, payload, str(exc))
                    quarantined += 1
                else:
                    next_at = datetime.now(timezone.utc) + timedelta(
                        seconds=_backoff_seconds(new_retries)
                    )
                    with self._sf.begin() as s:
                        s.execute(
                            update(SiemDispatch)
                            .where(SiemDispatch.id == dispatch_row.id)
                            .values(retries=new_retries, next_attempt_at=next_at)
                        )
                    failed += 1

        # Mark all successfully-sent rows in ONE transaction (was one commit per
        # row — the dominant write-lock churn under a concurrent ingest). Crash
        # between the network sends and this commit leaves those rows 'pending' →
        # re-sent next tick: still at-least-once (SIEM is at-least-once anyway),
        # only the duplicate window widens.
        if sent_ids:
            sent_at = datetime.now(timezone.utc)
            with self._sf.begin() as s:
                s.execute(
                    update(SiemDispatch)
                    .where(SiemDispatch.id.in_(sent_ids))
                    .values(status="sent", sent_at=sent_at)
                )

        return {"sent": sent, "failed": failed, "quarantined": quarantined}
```

- [ ] **Step 4: 跑測試確認通過（含既有 dispatcher 測試回歸）**

Run: `python -m pytest tests/test_siem_dispatcher.py tests/test_siem_runtime.py -v`
Expected: PASS（新批次化測試 + 既有 `test_dispatcher_sends_pending_row`/`increments_retries_on_failure`/`quarantines_after_max_retries`/`marks_failed_when_payload_none` 全綠：成功路徑結束狀態一致，失敗/quarantine 路徑未改）。

- [ ] **Step 5: 跑 siem e2e 回歸**

Run: `python -m pytest tests/test_siem_e2e.py tests/test_phase_13_e2e.py -v`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/siem/dispatcher.py tests/test_siem_dispatcher.py
git commit -m "perf(siem): batch 'sent' updates into one transaction per tick"
```

---

## Task 5: ingest insert 失敗記 error（item 4，traffic + events）

**Files:**
- Modify: `src/pce_cache/ingestor_traffic.py:52-66`
- Modify: `src/pce_cache/ingestor_events.py:63-68`
- Test: `tests/test_pce_cache_ingestor_traffic.py`、`tests/test_pce_cache_ingestor_events.py`

**Interfaces:**
- Consumes: `WatermarkStore.record_error(source, error)`（既有）。
- Produces: `TrafficIngestor.run_once` / `EventsIngestor.run_once` 在 `_insert_batch`（或後續 advance）拋例外時，先 `self._wm.record_error(self.SOURCE, str(exc))` 再 **re-raise**（不吞例外）。→ watermark `last_status="error"`。

- [ ] **Step 1: 寫失敗測試（traffic）**

Append to `tests/test_pce_cache_ingestor_traffic.py`:

```python
def test_traffic_run_once_records_error_status_on_insert_failure(session_factory):
    import pytest
    from sqlalchemy.exc import OperationalError
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore
    from src.pce_cache.models import IngestionWatermark

    fake = FakeApiClient([_mk_flow(1)])
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory))

    def _boom(_flows):
        raise OperationalError("INSERT", {}, Exception("database is locked"))
    ing._insert_batch = _boom

    with pytest.raises(OperationalError):        # re-raise 契約保留
        ing.run_once()

    with session_factory() as s:
        row = s.get(IngestionWatermark, "traffic")
    assert row is not None                        # 目前為 None（未 record_error）→ 紅
    assert row.last_status == "error"
    assert "database is locked" in (row.last_error or "")
```

- [ ] **Step 2: 寫失敗測試（events）**

Append to `tests/test_pce_cache_ingestor_events.py`:

```python
def test_events_run_once_records_error_status_on_insert_failure(session_factory):
    import pytest
    from sqlalchemy.exc import OperationalError
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore
    from src.pce_cache.models import IngestionWatermark

    ts = datetime.now(timezone.utc)
    fake = FakeApiClient(events=[_mk_event(1, ts)])
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                         watermark=WatermarkStore(session_factory), async_threshold=10000)

    def _boom(_events):
        raise OperationalError("INSERT", {}, Exception("database is locked"))
    ing._insert_batch = _boom

    with pytest.raises(OperationalError):
        ing.run_once()

    with session_factory() as s:
        row = s.get(IngestionWatermark, "events")
    assert row is not None and row.last_status == "error"
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `python -m pytest tests/test_pce_cache_ingestor_traffic.py::test_traffic_run_once_records_error_status_on_insert_failure tests/test_pce_cache_ingestor_events.py::test_events_run_once_records_error_status_on_insert_failure -v`
Expected: FAIL（例外雖已 re-raise，但目前未呼叫 `record_error`，watermark 列不存在 → `assert row is not None` 失敗）。

- [ ] **Step 4: 實作（traffic）**

把 `src/pce_cache/ingestor_traffic.py` `run_once` 的 insert 區塊（`:52-66`）：

```python
        inserted = 0
        watermark_advanced = False
        try:
            inserted = self._insert_batch(flows)
            if flows:
                last = max(_ts(f, "last_detected") for f in flows)
                if last:
                    self._wm.advance(self.SOURCE, last_timestamp=_parse_iso(last))
                    watermark_advanced = True
            return inserted
        finally:
            logger.info(
                "Traffic ingest poll: fetched={} inserted={} watermark_advanced={} since={}",
                len(flows), inserted, watermark_advanced, since,
            )
```

改為（在 `finally` 前插入 `except`）：

```python
        inserted = 0
        watermark_advanced = False
        try:
            inserted = self._insert_batch(flows)
            if flows:
                last = max(_ts(f, "last_detected") for f in flows)
                if last:
                    self._wm.advance(self.SOURCE, last_timestamp=_parse_iso(last))
                    watermark_advanced = True
            return inserted
        except Exception as exc:
            # insert/advance 失敗（如 database is locked）：記 error 讓 last_status
            # 反映真實，再 re-raise（run_traffic_ingest 仍以 logger.exception 記錄）。
            self._wm.record_error(self.SOURCE, str(exc))
            raise
        finally:
            logger.info(
                "Traffic ingest poll: fetched={} inserted={} watermark_advanced={} since={}",
                len(flows), inserted, watermark_advanced, since,
            )
```

- [ ] **Step 5: 實作（events）**

把 `src/pce_cache/ingestor_events.py` `run_once` 的 insert 區塊（`:63-68`）：

```python
        inserted = self._insert_batch(events)
        if events:
            last = max(e["timestamp"] for e in events)
            last_href = events[-1].get("href", "")
            self._wm.advance(self.SOURCE, last_timestamp=_parse_iso(last), last_href=last_href)
        return inserted
```

改為：

```python
        try:
            inserted = self._insert_batch(events)
            if events:
                last = max(e["timestamp"] for e in events)
                last_href = events[-1].get("href", "")
                self._wm.advance(self.SOURCE, last_timestamp=_parse_iso(last), last_href=last_href)
            return inserted
        except Exception as exc:
            # insert/advance 失敗：記 error 再 re-raise（run_events_ingest 會 logger.exception）。
            self._wm.record_error(self.SOURCE, str(exc))
            raise
```

- [ ] **Step 6: 跑測試確認通過（含既有 ingestor 回歸）**

Run: `python -m pytest tests/test_pce_cache_ingestor_traffic.py tests/test_pce_cache_ingestor_events.py -v`
Expected: PASS（新測試綠；既有 `test_run_once_emits_poll_log_even_when_insert_batch_raises` 仍綠 —— 例外照樣 re-raise、poll log 照樣輸出）。

- [ ] **Step 7: Commit**

```bash
git add src/pce_cache/ingestor_traffic.py src/pce_cache/ingestor_events.py \
        tests/test_pce_cache_ingestor_traffic.py tests/test_pce_cache_ingestor_events.py
git commit -m "fix(pce_cache): record error status when ingest insert fails"
```

---

## 全套回歸（所有 Task 完成後）

Run: `python -m pytest tests/test_config_models.py tests/test_scheduler_write_serialization.py tests/test_scheduler_engine_cache.py tests/test_lag_monitor_cached_engine.py tests/test_siem_dispatcher.py tests/test_siem_runtime.py tests/test_siem_e2e.py tests/test_pce_cache_ingestor_traffic.py tests/test_pce_cache_ingestor_events.py -v`
Expected: PASS（全綠）。

---

## Self-Review（對照 spec 檢查）

**1. Spec 覆蓋度：**
- §4.1 序列化 executor → Task 2。
- §4.2 lag_monitor 去 DDL → Task 3。
- §4.3 siem 批次化 → Task 4；`dispatch_tick_seconds` 預設 → Task 1。
- §4.4 item 4 record_error+re-raise → Task 5。
- §5 設定（僅改預設值）→ Task 1。
- §6 測試策略（executor 指派/lag_monitor 純讀/siem 單交易/item 4/回歸）→ Task 2-5 各對應 + 末段全套回歸。

**2. Placeholder 掃描：** 每個 code step 均為完整可執行內容；無 TBD/TODO/「類似上一個」。

**3. 型別一致性：** executor 別名字串 `"cache_writer"`（Task 2 定義、測試斷言一致）；`record_error(self.SOURCE, str(exc))`（Task 5 traffic/events 一致，符合 `WatermarkStore.record_error(source, error)` 既有簽章）；`_process_batch` 回傳 `{"sent","failed","quarantined"}`（Task 4 未變）。

**4. 相容性與已知取捨：**
- 唯一需改的既有測試：`tests/test_config_models.py:111`（Task 1 Step 1）。其餘既有測試皆不需改，且在各 Task 的回歸 step 驗證。
- Task 4 at-least-once 窗口變寬（崩潰於送出後、批次 commit 前 → 重送）：SIEM 本即 at-least-once、eventual 已由使用者同意，可接受（程式碼註解已記）。
- 與 archive plan 的 `pce_cache_archive` executor 指派交會，已於 Task 2 Step 6 註記。
