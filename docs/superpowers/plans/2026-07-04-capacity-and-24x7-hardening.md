# 容量擴展與 7/24 常駐執行強化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在維持單一 SQLite + JSONL archive 輕量架構的前提下，消除生產量級（每日 10 萬～100 萬筆 flow）下會依序爆開的應用層上限，並補齊 7/24 常駐執行所需的監控與韌性缺口。

**Architecture:** 不換引擎、不加外部相依。修法集中在四類：(1) 把「固定上限碰頂」從無聲失敗變成可偵測、可自動分割的行為；(2) 把「單一大交易/全表掃描」改成分批與增量；(3) 把同步阻塞的重操作移到背景執行緒；(4) 新增一個唯讀的容量監控 job 統一監看 DB 大小、磁碟、SIEM 佇列與 archiver 落後。

**Tech Stack:** Python 3.11+、SQLAlchemy 2（SQLite/WAL/NullPool）、APScheduler、Flask、loguru、orjson、pytest。

## 背景與診斷摘要（為什麼是這幾個 task）

實測基準：測試機 12,056 筆 raw flow 佔 27.6MB，每列全成本約 2.3KB。以 7 天線上窗口推估：每日 10 萬筆 → 約 1.6GB；每日 100 萬筆 → 約 16GB。SQLite 引擎本身（WAL + `cache_writer` 單一寫入者序列化）到此規模仍可用；會先爆的都是應用層：

| 順位 | 問題 | 位置 | 對應 task |
|---|---|---|---|
| 1 | ingest 單次拉取上限 200k 碰頂時無偵測，watermark 照推進 → 永久漏資料 | `src/pce_cache/ingestor_traffic.py:42-59` | Task 1 |
| 2 | PCE 持續失敗時 lag monitor 不告警（失敗的 ingest 仍 bump `last_sync_at`） | `src/pce_cache/lag_monitor.py:68-76` | Task 2 |
| 3 | retention 單交易大刪除 → WAL 暴漲、writer 長鎖 | `src/pce_cache/retention.py:38-79` | Task 3 |
| 4 | aggregator 每小時全表 GROUP BY | `src/pce_cache/aggregator.py:35-54` | Task 4 |
| 5 | 無磁碟/佇列/archiver 落後監控（archiver 停擺 = DB 無上限成長） | 全域 | Task 5 |
| 6 | cache 讀取路徑無列數上限，大視窗報表可 OOM 常駐 process | `src/pce_cache/reader.py:89-164` | Task 6 |
| 7 | archive 回載為同步 HTTP，31 天範圍在量大時必逾時 | `src/pce_cache/web.py:267-296` | Task 7 |
| 8 | `pce_cache/web.py`、`siem/web.py` 引擎未用 NullPool（與其餘熱路徑不一致，長跑累積連線） | `src/pce_cache/web.py:34`、`src/siem/web.py:40,327` | Task 8 |
| 9 | 營運手冊缺容量 sizing 與 7/24 runbook | `docs/operations-manual*.md` | Task 9 |

7/24 調查中確認**已受控、本計畫不重做**的項目：日誌 rotation（10MB + retention 10 + gzip，`src/loguru_config.py:145-187`）；APScheduler job 例外不中斷排程；graceful shutdown（signal → scheduler.shutdown → cheroot stop → join）；DLQ 已由 retention 每 24h 清理（`src/pce_cache/retention.py:61-64`，先前調查誤判為無清理）；記憶體快取皆有界（label TTLCache、i18n lru_cache、GUI log deque）；systemd `Restart=on-failure` 已配置（`deploy/illumio-ops.service:13`）。

**明確不做（YAGNI / 已有其他計畫）：** dead-man's switch 與告警送達可靠性（已列於 `docs/superpowers/plans/2026-07-04-alert-reliability-and-event-catalog-audit.md`，勿重複實作）；sd_notify watchdog；換 Postgres；archive 檔 manifest/checksum；`tmp/` 目錄清理（為開發產物，不隨部署）。

## Global Constraints

- Commit message 用英文 conventional-commits（repo 慣例）。
- datetime 一律 timezone-aware（CI 檢查 `scripts/check_no_naive_datetime.py`）；SQLite 讀回的 DateTime 是 naive UTC wall-clock，比較前須 `replace(tzinfo=timezone.utc)`（既有慣例，見 `retention.py:97-100`）。
- JSON 序列化一律 orjson。
- 測試只用 `tmp_path`，不碰真實 PCE / `data/`。
- i18n 新 key 必須 `src/i18n_en.json` 與 `src/i18n_zh_TW.json` 兩檔同步（有 parity test）。
- 所有改動在預設設定下必須零行為變更或安全退化（不破壞既有部署）。
- 不新增外部相依、不換 DB 引擎、不新增 process。
- 每個 task 完成後執行 `python -m pytest <該 task 測試檔> -v` 與 `ruff check src tests`。

---

### Task 1: Ingest 碰頂偵測與視窗二分抽乾

拉取窗口內 flow 數達 `max_results`（200k）時，目前 watermark 直接推進到本批 `max(last_detected)`，被截掉的 flow 除非落在 5 分鐘 grace window 否則永久漏掉。修法：`get_traffic_flows_async` 支援 `until` 上界；ingestor 碰頂時把時間窗對半分、遞迴抽乾（深度上限 6），並在無法再分時記 warning。跨半窗的重複列由既有 `flow_hash` upsert 去重吸收。

**Files:**
- Modify: `src/api_client.py:306-312`（`get_traffic_flows_async` 加 `until` 參數）
- Modify: `src/pce_cache/ingestor_traffic.py:39-55`（`run_once` 改走 `_fetch_all`；新增 `_fetch_all`/`_fetch_window`）
- Test: `tests/test_pce_cache_ingestor_traffic.py`（沿用檔內既有 `session_factory` fixture 與 `_mk_flow`）
- Test: `tests/test_api_client_traffic_until.py`（新檔）

**Interfaces:**
- Consumes: 既有 `TrafficIngestor(api, session_factory, watermark, ..., max_results=200000)`、`WatermarkStore`。
- Produces: `ApiClient.get_traffic_flows_async(..., until: str | None = None)`；`TrafficIngestor._fetch_window(since_dt: datetime, until_dt: datetime, depth: int) -> list[dict]`。後續 task 不依賴本 task。

- [ ] **Step 1: 寫失敗測試（二分行為）**

加到 `tests/test_pce_cache_ingestor_traffic.py`：

```python
class BisectFakeApi:
    """第一次（全窗）回滿 max_results 觸發二分；之後每個半窗回 1 筆。"""
    def __init__(self):
        self.windows = []  # (since, until) 呼叫紀錄

    def get_traffic_flows_async(self, max_results=200000, rate_limit=False,
                                since=None, until=None, **kw):
        self.windows.append((since, until))
        if len(self.windows) == 1:
            return [_mk_flow(i) for i in range(max_results)]
        return [_mk_flow(1000 + len(self.windows))]


def test_ingest_bisects_window_on_cap_hit(session_factory):
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    fake = BisectFakeApi()
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory), max_results=5)
    ing.run_once()
    # 1 次全窗（滿載）+ 2 次半窗
    assert len(fake.windows) == 3
    s0, u0 = fake.windows[0]
    s1, u1 = fake.windows[1]
    s2, u2 = fake.windows[2]
    assert s1 == s0 and u2 == u0 and u1 == s2  # 兩個半窗恰好拼回全窗


def test_ingest_single_call_below_cap(session_factory):
    # 回歸：未碰頂時維持單次呼叫
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    flows = [_mk_flow(i) for i in range(3)]
    fake = FakeApiClient(flows)
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory), max_results=5)
    assert ing.run_once() == 3
    assert fake.calls == 1


class AlwaysFullApi:
    """每個窗口都回滿載：驗證遞迴深度有界，不會無限二分。"""
    def __init__(self):
        self.calls = 0

    def get_traffic_flows_async(self, max_results=200000, **kw):
        self.calls += 1
        return [_mk_flow(i) for i in range(max_results)]


def test_ingest_bisect_depth_bounded(session_factory):
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    fake = AlwaysFullApi()
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory), max_results=2)
    ing.run_once()  # 不應 RecursionError / 無限迴圈
    # 深度 6 的完整二元樹：1 + 2 + ... + 64 = 127 次呼叫為上限
    assert fake.calls <= 127
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_pce_cache_ingestor_traffic.py -k "bisect or below_cap" -v`
Expected: FAIL（`get_traffic_flows_async` 收到未預期的 `until`，或 windows 數量不符）

- [ ] **Step 3: 實作 api_client `until` 參數**

`src/api_client.py:306-312`，簽章與 `end_time` 兩處：

```python
    def get_traffic_flows_async(self, max_results: int = 200000, rate_limit: bool = False, since: str | None = None, until: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        """Pull traffic flows for cache ingestion via the async query endpoint."""
        import contextlib, io
        from datetime import datetime, timezone, timedelta
        end_time = until or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if since is None:
            since = (datetime.now(timezone.utc) - timedelta(hours=24)).replace(microsecond=0).isoformat()
```

其餘（`fetch_traffic_for_report(start_time_str=since, end_time_str=end_time, ...)` 與截斷 warning）不動。

- [ ] **Step 4: 實作 ingestor 二分抽乾**

`src/pce_cache/ingestor_traffic.py`。`run_once` 的 `flows = self._api.get_traffic_flows_async(...)`（:42-46）改成 `flows = self._fetch_all(since)`，其餘（例外處理、insert、watermark、poll log）不動。類別內新增：

```python
    # 二分抽乾參數：深度 6 → 最小窗 = 原窗/64；再配 _MIN_BISECT_SPAN 硬下限，
    # 保證遞迴有界。碰頂但無法再分時記 warning（該窗資料可能不完整）。
    _MAX_BISECT_DEPTH = 6
    _MIN_BISECT_SPAN = timedelta(minutes=1)

    def _fetch_all(self, since: Optional[str]) -> list[dict]:
        until_dt = datetime.now(timezone.utc).replace(microsecond=0)
        if since is not None:
            since_dt = datetime.fromisoformat(since)
        else:
            # 鏡射 api_client 的預設：無 watermark 時往回抓 24 小時
            since_dt = until_dt - timedelta(hours=24)
        return self._fetch_window(since_dt, until_dt, depth=0)

    def _fetch_window(self, since_dt: datetime, until_dt: datetime, depth: int) -> list[dict]:
        flows = self._api.get_traffic_flows_async(
            max_results=self._max_results,
            rate_limit=True,
            since=since_dt.isoformat(),
            until=until_dt.isoformat(),
        )
        if len(flows) < self._max_results:
            return flows
        span = until_dt - since_dt
        if depth >= self._MAX_BISECT_DEPTH or span <= self._MIN_BISECT_SPAN:
            logger.warning(
                "Traffic ingest hit max_results cap ({}) in window {} → {} at depth {}; "
                "cannot bisect further — data in this window may be incomplete",
                self._max_results, since_dt, until_dt, depth,
            )
            return flows
        mid = since_dt + span / 2
        logger.warning(
            "Traffic ingest hit max_results cap ({}); bisecting {} → {} at {}",
            self._max_results, since_dt, until_dt, mid,
        )
        return (self._fetch_window(since_dt, mid, depth + 1)
                + self._fetch_window(mid, until_dt, depth + 1))
```

注意：跨半窗邊界（`mid` 恰好落點）的 flow 兩側都會回，由 `_insert_batch` 的 flow_hash upsert 去重；watermark 仍以合併後全部 flows 的 `max(last_detected)` 推進（`run_once` 既有邏輯，不改）。

- [ ] **Step 5: 寫 api_client until 測試（新檔 `tests/test_api_client_traffic_until.py`）**

```python
def test_get_traffic_flows_async_honors_until():
    from src.api_client import ApiClient

    captured = {}
    client = ApiClient.__new__(ApiClient)  # 跳過建構子（不碰網路/config）

    def fake_fetch(start_time_str, end_time_str, rate_limit=False, **kw):
        captured["start"] = start_time_str
        captured["end"] = end_time_str
        return []

    client.fetch_traffic_for_report = fake_fetch
    client.get_traffic_flows_async(
        since="2026-07-01T00:00:00+00:00", until="2026-07-02T00:00:00+00:00")
    assert captured["end"] == "2026-07-02T00:00:00+00:00"
    assert captured["start"] == "2026-07-01T00:00:00+00:00"
```

- [ ] **Step 6: 跑測試確認通過**

Run: `python -m pytest tests/test_pce_cache_ingestor_traffic.py tests/test_api_client_traffic_until.py -v`
Expected: 全 PASS（含既有回歸測試）

- [ ] **Step 7: Commit**

```bash
git add src/api_client.py src/pce_cache/ingestor_traffic.py tests/test_pce_cache_ingestor_traffic.py tests/test_api_client_traffic_until.py
git commit -m "feat(cache): bisect ingest window on max_results cap hit to prevent silent data loss"
```

---

### Task 2: lag monitor 對 last_status=error 告警

PCE 長期不可達時，失敗的 ingest 仍會 bump `last_sync_at`，時間基準的 lag level 一直是 ok，`run_cache_lag_monitor` 完全不告警（docstring 自己都警告了呼叫端要看 `last_status`，但排程 job 沒看）。補一個純函式 + 接上 job。

**Files:**
- Modify: `src/pce_cache/lag_monitor.py`（新增 `status_alerts`；`run_cache_lag_monitor` 尾端接上）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（新 key `alert_cache_ingest_failing`）
- Test: `tests/test_lag_monitor_status_alerts.py`（新檔）

**Interfaces:**
- Produces: `status_alerts(results: list[dict]) -> list[str]`（供 job 與日後 /api 使用）。

- [ ] **Step 1: 寫失敗測試**

```python
def test_status_alerts_flags_error_status():
    from src.pce_cache.lag_monitor import status_alerts
    results = [
        {"source": "traffic", "level": "ok", "last_status": "error",
         "last_error": "HTTPSConnectionPool timeout"},
        {"source": "events", "level": "ok", "last_status": "ok", "last_error": None},
    ]
    msgs = status_alerts(results)
    assert len(msgs) == 1
    assert "traffic" in msgs[0]


def test_status_alerts_empty_when_all_ok():
    from src.pce_cache.lag_monitor import status_alerts
    assert status_alerts([{"source": "traffic", "last_status": "ok"}]) == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_lag_monitor_status_alerts.py -v`
Expected: FAIL with "cannot import name 'status_alerts'"

- [ ] **Step 3: 實作**

`src/pce_cache/lag_monitor.py` 新增（module level，`check_cache_lag` 之後）：

```python
def status_alerts(results: list[dict]) -> list[str]:
    """last_status=='error' 的來源 → 告警訊息。

    時間基準的 level 看不出「持續失敗」：失敗的 ingest 仍會 bump
    last_sync_at（見 check_cache_lag docstring），所以 PCE 長期不可達時
    lag 永遠正常。此函式補上以結果狀態為準的第二道判斷。"""
    msgs = []
    for r in results:
        if r.get("last_status") == "error":
            msgs.append(t(
                "alert_cache_ingest_failing",
                source=r.get("source", "?"),
                err=(r.get("last_error") or "")[:200],
            ))
    return msgs
```

`run_cache_lag_monitor` 尾端（既有 for 迴圈之後）加：

```python
    for msg in status_alerts(results):
        logger.error(msg)
```

i18n（兩檔，仿 `alert_cache_lag_error` 放置位置）：

```json
"alert_cache_ingest_failing": "Cache ingest keeps failing: source={source} last_error={err}"
```

```json
"alert_cache_ingest_failing": "Cache 擷取持續失敗：來源={source} 最近錯誤={err}"
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_lag_monitor_status_alerts.py tests/test_lag_monitor_cached_engine.py -v`
Expected: PASS（含既有 lag monitor 回歸）

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache/lag_monitor.py src/i18n_en.json src/i18n_zh_TW.json tests/test_lag_monitor_status_alerts.py
git commit -m "feat(cache): alert on persistent ingest failure via last_status in lag monitor"
```

---

### Task 3: Retention 分批刪除

`RetentionWorker.run_once` 每個表一個交易刪整批到期列；量大時單交易刪百萬列會讓 WAL 暴漲並長時間佔住 `cache_writer`。改成以 PK id 選批（每批 10,000、各自一個交易）的迴圈，語意與一次性 DELETE 等價。

**Files:**
- Modify: `src/pce_cache/retention.py`
- Test: `tests/test_pce_cache_retention.py`（擴充）

**Interfaces:**
- Consumes: 所有 cache model 都有 `id` integer PK（`models.py:17,36,70,120,146`）。
- Produces: `RetentionWorker._batched_delete(model, *where_clauses) -> int`（類別內部）；`run_once` 對外簽章與回傳不變。

- [ ] **Step 1: 寫失敗測試**

加到 `tests/test_pce_cache_retention.py`（沿用檔內既有 fixture；若無現成 raw flow 工廠，用下面這個）：

```python
def _mk_raw(i, ingested_at):
    from src.pce_cache.models import PceTrafficFlowRaw
    return PceTrafficFlowRaw(
        flow_hash=f"batch-h{i}", src_ip="10.9.0.1", dst_ip="10.9.0.2",
        port=443, protocol="tcp", action="allowed", flow_count=1,
        bytes_in=0, bytes_out=0,
        first_detected=ingested_at, last_detected=ingested_at,
        ingested_at=ingested_at, raw_json="{}",
    )


def test_retention_deletes_across_multiple_batches(session_factory, monkeypatch):
    from datetime import datetime, timezone, timedelta
    from src.pce_cache.retention import RetentionWorker

    old = datetime.now(timezone.utc) - timedelta(days=30)
    fresh = datetime.now(timezone.utc)
    with session_factory.begin() as s:
        for i in range(25):
            s.add(_mk_raw(i, old))
        s.add(_mk_raw(999, fresh))  # 未到期，不可被刪

    monkeypatch.setattr(RetentionWorker, "_DELETE_BATCH", 10)  # 強迫跨 3 批
    result = RetentionWorker(session_factory).run_once(traffic_raw_days=7)
    assert result["traffic_raw"] == 25

    from sqlalchemy import select, func
    from src.pce_cache.models import PceTrafficFlowRaw
    with session_factory() as s:
        remaining = s.execute(
            select(func.count()).select_from(PceTrafficFlowRaw)).scalar()
    assert remaining == 1
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_pce_cache_retention.py -k batches -v`
Expected: FAIL with "AttributeError: ... has no attribute '_DELETE_BATCH'"

- [ ] **Step 3: 實作分批刪除**

`src/pce_cache/retention.py`：import 區加 `select`（`from sqlalchemy import delete, select`）。類別內新增：

```python
    # 每批一個交易：避免單一大 DELETE 交易撐爆 WAL、長時間佔住
    # cache_writer。以 PK id 選批（LIMIT 子查詢先取 id 再 IN 刪除），
    # 與索引無關、總效果與一次性 DELETE 等價。
    _DELETE_BATCH = 10000

    def _batched_delete(self, model, *where_clauses) -> int:
        total = 0
        while True:
            with self._sf.begin() as s:
                ids = s.execute(
                    select(model.id).where(*where_clauses).limit(self._DELETE_BATCH)
                ).scalars().all()
                if not ids:
                    return total
                r = s.execute(delete(model).where(model.id.in_(ids)))
                total += r.rowcount
            if len(ids) < self._DELETE_BATCH:
                return total
```

`run_once` 五個刪除區塊改寫（守門邏輯不變，只把 cutoff 讀取移到短 session、刪除改走 `_batched_delete`）：

```python
        with self._sf() as s:
            eff_events = self._effective_cutoff(
                s, "pce_events", now - timedelta(days=events_days), archive_enabled)
        results["events"] = (
            0 if eff_events is None
            else self._batched_delete(PceEvent, PceEvent.ingested_at < eff_events))

        with self._sf() as s:
            eff_raw = self._effective_cutoff(
                s, "pce_traffic_flows_raw", now - timedelta(days=traffic_raw_days), archive_enabled)
        results["traffic_raw"] = (
            0 if eff_raw is None
            else self._batched_delete(PceTrafficFlowRaw, PceTrafficFlowRaw.ingested_at < eff_raw))

        results["traffic_agg"] = self._batched_delete(
            PceTrafficFlowAgg,
            PceTrafficFlowAgg.bucket_day < now - timedelta(days=traffic_agg_days))

        results["dead_letter"] = self._batched_delete(
            DeadLetter, DeadLetter.quarantined_at < now - timedelta(days=dlq_days))

        # siem_dispatch 說明註解保留原文（models 成長行為的 rationale）
        results["siem_dispatch"] = self._batched_delete(
            SiemDispatch,
            SiemDispatch.status == "sent",
            SiemDispatch.sent_at < now - timedelta(days=dispatch_days))
```

- [ ] **Step 4: 跑測試確認通過（含既有回歸）**

Run: `python -m pytest tests/test_pce_cache_retention.py -v`
Expected: 全 PASS（既有守門測試不得變紅）

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache/retention.py tests/test_pce_cache_retention.py
git commit -m "perf(cache): batch retention deletes to bound WAL growth and writer lock time"
```

---

### Task 4: Aggregator 增量視窗

`TrafficAggregator.run_once` 每小時對整個 raw 表 GROUP BY。修法：agg 表非空時只重算近 `_WINDOW_DAYS`（3）天的 bucket。語意等價論證：舊 bucket 的 raw 只會因 retention 減少，而既有 MAX 合併本就把它們凍結在歷史峰值（`aggregator.py:60-67` 註解），略過重算結果相同。兩個必須保留全量的路徑：(a) agg 表為空（首次啟用、archive review DB 重建）→ 自動全量；(b) backfill 灌入舊日期資料 → `run_once(full=True)` 顯式全量。

**Files:**
- Modify: `src/pce_cache/aggregator.py`
- Modify: `src/pce_cache/web.py:69-82`（backfill traffic 分支補跑 `run_once(full=True)`）
- Test: `tests/test_pce_cache_aggregator_window.py`（新檔）

**Interfaces:**
- Produces: `TrafficAggregator.run_once(full: bool = False) -> int`（預設值不變，既有呼叫端 `scheduler/jobs.py:136`、`archive_import.py:313` 零改動）。

- [ ] **Step 1: 寫失敗測試（新檔）**

```python
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowAgg, PceTrafficFlowRaw


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'agg.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _raw(i, ts):
    return PceTrafficFlowRaw(
        flow_hash=f"agg-h{i}", src_ip="1.1.1.1", dst_ip="2.2.2.2",
        port=80, protocol="tcp", action="allowed", flow_count=1,
        bytes_in=1, bytes_out=1,
        first_detected=ts, last_detected=ts, ingested_at=ts, raw_json="{}")


def _bucket_days(sf):
    with sf() as s:
        return sorted(s.execute(select(PceTrafficFlowAgg.bucket_day)).scalars().all())


def test_bootstrap_full_scan_when_agg_empty(session_factory):
    from src.pce_cache.aggregator import TrafficAggregator
    old = datetime.now(timezone.utc) - timedelta(days=10)
    with session_factory.begin() as s:
        s.add(_raw(1, old))
    TrafficAggregator(session_factory).run_once()
    assert len(_bucket_days(session_factory)) == 1  # 視窗外的舊列也被聚合


def test_incremental_window_skips_old_raw(session_factory):
    from src.pce_cache.aggregator import TrafficAggregator
    agg = TrafficAggregator(session_factory)
    now = datetime.now(timezone.utc)
    with session_factory.begin() as s:
        s.add(_raw(1, now))
    agg.run_once()  # agg 已非空
    with session_factory.begin() as s:
        s.add(_raw(2, now - timedelta(days=10)))
    agg.run_once()  # 視窗外舊列不觸發新 bucket
    assert len(_bucket_days(session_factory)) == 1


def test_full_flag_forces_whole_table(session_factory):
    from src.pce_cache.aggregator import TrafficAggregator
    agg = TrafficAggregator(session_factory)
    now = datetime.now(timezone.utc)
    with session_factory.begin() as s:
        s.add(_raw(1, now))
    agg.run_once()
    with session_factory.begin() as s:
        s.add(_raw(2, now - timedelta(days=10)))
    agg.run_once(full=True)
    assert len(_bucket_days(session_factory)) == 2
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_pce_cache_aggregator_window.py -v`
Expected: `test_incremental_window_skips_old_raw` 與 `test_full_flag_forces_whole_table` FAIL（現行永遠全表掃描且無 `full` 參數）

- [ ] **Step 3: 實作**

`src/pce_cache/aggregator.py`：import 區加 `from datetime import datetime, timedelta, timezone`。類別改動：

```python
    # 增量視窗：agg 非空時只重算近 N 天的 bucket。更舊 bucket 的 raw 只會因
    # retention 減少，而 MAX 合併本就把它們凍結在歷史峰值——略過重算與 MAX
    # 守門結果等價，把每小時全表掃描縮成 O(近幾天)。3 天 > ingest grace(5m)
    # 與跨午夜 bucket 移動的任何情境。
    _WINDOW_DAYS = 3

    def run_once(self, full: bool = False) -> int:
```

`sel` 組完（`.group_by(...)` 之後）、`stmt` 建立之前插入：

```python
        if not full and self._has_agg_rows():
            cutoff = datetime.now(timezone.utc) - timedelta(days=self._WINDOW_DAYS)
            sel = sel.where(PceTrafficFlowRaw.last_detected >= cutoff)
```

類別內新增：

```python
    def _has_agg_rows(self) -> bool:
        with self._sf() as s:
            return s.execute(
                select(PceTrafficFlowAgg.id).limit(1)).first() is not None
```

`src/pce_cache/web.py` `api_cache_backfill`（:73-76）traffic 分支改為：

```python
        if source == "events":
            result = runner.run_events(since_dt, until_dt)
        else:
            result = runner.run_traffic(since_dt, until_dt)
            # backfill 會灌入舊日期資料，落在 aggregator 增量視窗之外，
            # 必須顯式全量重算一次，否則趨勢圖看不到 backfill 的 bucket。
            from src.pce_cache.aggregator import TrafficAggregator
            TrafficAggregator(sf).run_once(full=True)
```

- [ ] **Step 4: 跑測試確認通過（含 archive import 回歸——review DB 走 bootstrap 全量路徑）**

Run: `python -m pytest tests/test_pce_cache_aggregator_window.py tests/test_pce_cache_archive_import.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache/aggregator.py src/pce_cache/web.py tests/test_pce_cache_aggregator_window.py
git commit -m "perf(cache): incremental aggregation window with full-scan bootstrap and backfill override"
```

---

### Task 5: 容量與磁碟監控

新增唯讀的 `capacity_snapshot` / `capacity_warnings`（DB 檔案大小、磁碟剩餘、SIEM pending 佇列深度、archiver 落後秒數），由新排程 job 每 30 分鐘檢查並記告警 log，同時掛進 `/api/cache/health` 回應。這三個數字是量變大時最早的預警訊號；archiver 落後告警同時是「retention 守門導致 DB 無上限成長」的前哨。

**Files:**
- Create: `src/pce_cache/capacity.py`
- Modify: `src/config_models.py:262` 之後（`PceCacheSettings` 加 `disk_free_warn_gb`、`siem_pending_warn_rows`）
- Modify: `src/scheduler/jobs.py`（新增 `run_capacity_monitor`）
- Modify: `src/scheduler/__init__.py:142-144` 附近（cache 區塊註冊 job，default executor）
- Modify: `src/pce_cache/web.py:208-214`（`/health` 回應加 `capacity`）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（3 個新 key）
- Test: `tests/test_pce_cache_capacity.py`（新檔）

**Interfaces:**
- Produces: `capacity_snapshot(session_factory, cfg) -> dict`（keys: `db_bytes:int`、`disk_free_bytes:int|None`、`siem_pending:int`、`archiver_lag_seconds:dict[str,int|None]`）；`capacity_warnings(snap: dict, cfg) -> list[str]`；`run_capacity_monitor(cm) -> None`。

- [ ] **Step 1: 寫失敗測試（新檔）**

```python
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowRaw


@pytest.fixture
def cache_db(tmp_path):
    from src.pce_cache.schema import init_schema
    db_path = str(tmp_path / "cap.sqlite")
    engine = create_engine(f"sqlite:///{db_path}")
    init_schema(engine)
    return db_path, sessionmaker(engine)


def test_capacity_snapshot_shape_and_lag(cache_db):
    from src.pce_cache.capacity import capacity_snapshot
    db_path, sf = cache_db
    now = datetime.now(timezone.utc)
    with sf.begin() as s:
        s.add(PceTrafficFlowRaw(
            flow_hash="cap-h1", src_ip="1.1.1.1", dst_ip="2.2.2.2",
            port=80, protocol="tcp", action="allowed", flow_count=1,
            bytes_in=0, bytes_out=0, first_detected=now, last_detected=now,
            ingested_at=now, raw_json="{}"))
    cfg = SimpleNamespace(db_path=db_path, archive_enabled=True)
    snap = capacity_snapshot(sf, cfg)
    assert snap["db_bytes"] > 0
    assert snap["siem_pending"] == 0
    # 有資料但 archiver 從未推進 cursor → None（全部未封存）
    assert snap["archiver_lag_seconds"]["traffic"] is None


def test_capacity_warnings_thresholds():
    from src.pce_cache.capacity import capacity_warnings
    cfg = SimpleNamespace(disk_free_warn_gb=10, siem_pending_warn_rows=100,
                          archive_interval_hours=24)
    snap = {
        "db_bytes": 1,
        "disk_free_bytes": 1 << 30,               # 1 GB < 10 GB 門檻
        "siem_pending": 500,                       # > 100
        "archiver_lag_seconds": {"traffic": 999999},  # > 48h
    }
    msgs = capacity_warnings(snap, cfg)
    assert len(msgs) == 3


def test_capacity_warnings_quiet_when_healthy():
    from src.pce_cache.capacity import capacity_warnings
    cfg = SimpleNamespace(disk_free_warn_gb=10, siem_pending_warn_rows=100,
                          archive_interval_hours=24)
    snap = {"db_bytes": 1, "disk_free_bytes": 100 << 30,
            "siem_pending": 0, "archiver_lag_seconds": {"traffic": 60}}
    assert capacity_warnings(snap, cfg) == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_pce_cache_capacity.py -v`
Expected: FAIL with "No module named 'src.pce_cache.capacity'"

- [ ] **Step 3: 實作 `src/pce_cache/capacity.py`**

```python
"""容量監控：DB 大小、磁碟剩餘、SIEM 佇列深度、archiver 落後。

全部唯讀且輕量（COUNT 走 status 索引、getsize/disk_usage 是 stat 呼叫），
供排程 job（run_capacity_monitor）與 /api/cache/health 共用。"""
from __future__ import annotations

import os
import shutil

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.i18n import t
from src.pce_cache.models import (
    IngestionCursor, PceEvent, PceTrafficFlowRaw, SiemDispatch,
)

_ARCHIVE_SOURCES = (
    ("traffic", PceTrafficFlowRaw, "pce_traffic_flows_raw"),
    ("audit", PceEvent, "pce_events"),
)


def capacity_snapshot(session_factory: sessionmaker, cfg) -> dict:
    db_path = cfg.db_path
    db_bytes = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            db_bytes += os.path.getsize(db_path + suffix)
        except OSError:
            pass
    try:
        disk_free_bytes = shutil.disk_usage(
            os.path.dirname(os.path.abspath(db_path))).free
    except OSError:
        disk_free_bytes = None

    with session_factory() as s:
        siem_pending = s.execute(
            select(func.count()).select_from(SiemDispatch)
            .where(SiemDispatch.status == "pending")).scalar() or 0
        archiver_lag: dict[str, int | None] = {}
        if getattr(cfg, "archive_enabled", False):
            for source, model, table in _ARCHIVE_SOURCES:
                newest = s.execute(select(func.max(model.ingested_at))).scalar()
                cur = s.get(IngestionCursor, ("archiver", table))
                archived = cur.last_ingested_at if cur else None
                if newest is None:
                    archiver_lag[source] = 0       # 沒資料就沒有落後
                elif archived is None:
                    archiver_lag[source] = None    # 有資料但從未封存
                else:
                    # SQLite 讀回皆為 naive UTC wall-clock，直接相減即可
                    archiver_lag[source] = max(
                        0, int((newest - archived).total_seconds()))

    return {
        "db_bytes": db_bytes,
        "disk_free_bytes": disk_free_bytes,
        "siem_pending": siem_pending,
        "archiver_lag_seconds": archiver_lag,
    }


def capacity_warnings(snap: dict, cfg) -> list[str]:
    msgs = []
    free = snap.get("disk_free_bytes")
    warn_gb = int(getattr(cfg, "disk_free_warn_gb", 10))
    if free is not None and free < warn_gb * (1 << 30):
        msgs.append(t("alert_cache_disk_low",
                      free_gb=round(free / (1 << 30), 1), warn_gb=warn_gb))

    pending_warn = int(getattr(cfg, "siem_pending_warn_rows", 50000))
    if snap.get("siem_pending", 0) > pending_warn:
        msgs.append(t("alert_siem_backlog",
                      pending=snap["siem_pending"], warn=pending_warn))

    # 落後超過 2 個 archive 週期，或從未封存（None），都要告警——
    # retention 守門會因此完全停刪，DB 將無上限成長。
    lag_warn = int(getattr(cfg, "archive_interval_hours", 24)) * 2 * 3600
    for source, lag in (snap.get("archiver_lag_seconds") or {}).items():
        if lag is None or lag > lag_warn:
            msgs.append(t("alert_archiver_behind", source=source,
                          hours=("n/a" if lag is None else round(lag / 3600, 1))))
    return msgs
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_pce_cache_capacity.py -v`
Expected: PASS

- [ ] **Step 5: 接上 config、job、排程、/health、i18n**

`src/config_models.py` `PceCacheSettings`（`archive_review_max_days` 之後）：

```python
    disk_free_warn_gb: int = Field(default=10, ge=1)        # 磁碟剩餘低於此 GB 數告警
    siem_pending_warn_rows: int = Field(default=50000, ge=1000)  # SIEM 佇列積壓告警門檻
```

`src/scheduler/jobs.py` 新增（仿 `run_cache_lag_monitor` 的取 engine 模式）：

```python
def run_capacity_monitor(cm) -> None:
    """容量監控：唯讀，走 default executor（不佔 cache_writer）。"""
    from sqlalchemy.orm import sessionmaker as _SM
    from src.gui._helpers import _get_cache_engine
    from src.pce_cache.capacity import capacity_snapshot, capacity_warnings
    try:
        cfg = cm.models.pce_cache
        sf = _SM(_get_cache_engine(cfg.db_path))
        snap = capacity_snapshot(sf, cfg)
        logger.info(
            "Capacity: db={}MB free={}GB siem_pending={} archiver_lag={}",
            round(snap["db_bytes"] / (1 << 20), 1),
            (round(snap["disk_free_bytes"] / (1 << 30), 1)
             if snap["disk_free_bytes"] is not None else "n/a"),
            snap["siem_pending"], snap["archiver_lag_seconds"],
        )
        for msg in capacity_warnings(snap, cfg):
            logger.warning(msg)
    except Exception:
        logger.exception("Capacity monitor failed")
```

`src/scheduler/__init__.py` cache 區塊，`cache_lag_monitor` 註冊（:142-144）之後：

```python
            from src.scheduler.jobs import run_capacity_monitor
            sched.add_job(run_capacity_monitor, _IT(minutes=30),
                          args=[cm], id="pce_cache_capacity_monitor",
                          replace_existing=True)
```

（唯讀 job，不加 `executor="cache_writer"`。）

`src/pce_cache/web.py` `api_cache_health` 的 `return jsonify({...})`（:208-214）改為：

```python
        from src.pce_cache.capacity import capacity_snapshot
        capacity = capacity_snapshot(sf, current_app.config["CM"].models.pce_cache)
        return jsonify({
            "verdict": verdict,
            "lag_levels": levels,
            "cache_lag": cache_lag,
            "siem_success_1h": success_1h,
            "dlq": totals["dlq"],
            "capacity": capacity,
        })
```

i18n（兩檔同步）：

```json
"alert_cache_disk_low": "Low disk space: {free_gb} GB free (threshold {warn_gb} GB)",
"alert_siem_backlog": "SIEM dispatch backlog: {pending} pending rows (threshold {warn})",
"alert_archiver_behind": "Archive exporter behind for {source}: {hours} hours of data not yet archived — retention is withholding deletion"
```

```json
"alert_cache_disk_low": "磁碟剩餘空間不足：僅 {free_gb} GB（門檻 {warn_gb} GB）",
"alert_siem_backlog": "SIEM 派送積壓：{pending} 筆待送（門檻 {warn}）",
"alert_archiver_behind": "封存匯出落後（{source}）：約 {hours} 小時資料尚未封存——retention 守門已暫停刪除"
```

- [ ] **Step 6: 補排程註冊測試 + 全部驗證**

加到 `tests/test_pce_cache_capacity.py`：

```python
def test_scheduler_registers_capacity_monitor():
    # 仿 tests/test_scheduler_write_serialization.py 的 MagicMock cm 模式
    from unittest.mock import MagicMock
    from src.scheduler import build_scheduler
    cm = MagicMock()
    cm.models.pce_cache.enabled = True
    cm.models.pce_cache.events_poll_interval_seconds = 300
    cm.models.pce_cache.traffic_poll_interval_seconds = 3600
    cm.models.pce_cache.archive_enabled = False
    cm.models.siem.enabled = False
    sched = build_scheduler(cm)
    job = sched.get_job("pce_cache_capacity_monitor")
    assert job is not None
    assert job.executor == "default"
```

（若 `build_scheduler` 的 MagicMock 佈置與既有 `tests/test_scheduler_write_serialization.py` 不同，以該檔實際佈置為準複製。）

Run: `python -m pytest tests/test_pce_cache_capacity.py tests/test_scheduler_write_serialization.py tests/test_i18n*.py -v`
Expected: 全 PASS（含 i18n parity）

- [ ] **Step 7: Commit**

```bash
git add src/pce_cache/capacity.py src/config_models.py src/scheduler/jobs.py src/scheduler/__init__.py src/pce_cache/web.py src/i18n_en.json src/i18n_zh_TW.json tests/test_pce_cache_capacity.py
git commit -m "feat(cache): capacity monitor for db size, disk, siem backlog and archiver lag"
```

---

### Task 6: 報表 cache 讀取 OOM 護欄

`CacheReader.read_flows_raw` / `read_flows_df` 一次載入整個時間窗，無上限；大視窗在量大時會 OOM 掉整個 7/24 常駐 process。修法：reader 建構時接受 `read_max_rows`，讀取前先 COUNT，超限拋 `CacheReadTooLarge`；兩個呼叫端（`analyzer._fetch_query_flows`、`report_generator._fetch_traffic`/`._fetch_traffic_df`）接住後記 warning 並改走 live API 路徑（API 路徑由 `MAX_TRAFFIC_RESULTS=200000` 硬上限保護，且 `api_client.py:317-321` 已有截斷 warning）。互動查詢路徑（`QUERY_RESULT_CAP` + `last_query_stats.truncated`）已於 7/3 Phase 0 完成，本 task 不碰。

**Files:**
- Modify: `src/pce_cache/reader.py`（`CacheReadTooLarge`、`count_flows`、`_guard_window`、建構子）
- Modify: `src/config_models.py`（`PceCacheSettings.cache_read_max_rows`）
- Modify: `src/main.py`（`_make_cache_reader` 內建 `CacheReader(...)` 呼叫處傳 `read_max_rows=int(cfg.cache_read_max_rows)`）
- Modify: `src/analyzer.py:959-1006`（full 與 partial 兩處 cache 讀取包 try/except）
- Modify: `src/report/report_generator.py:183-189、220-223、260-265、289-295`（同上，四處）
- Test: `tests/test_pce_cache_reader_guard.py`（新檔）

**Interfaces:**
- Produces: `CacheReadTooLarge(RuntimeError)`（屬性 `count`、`cap`）；`CacheReader.count_flows(start, end, workload_hrefs=None) -> int`；`CacheReader.__init__(..., read_max_rows: int | None = None)`。

- [ ] **Step 1: 寫失敗測試（新檔）**

```python
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowRaw


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'g.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _seed(sf, n):
    now = datetime.now(timezone.utc)
    with sf.begin() as s:
        for i in range(n):
            s.add(PceTrafficFlowRaw(
                flow_hash=f"g-h{i}", src_ip="1.1.1.1", dst_ip="2.2.2.2",
                port=80, protocol="tcp", action="allowed", flow_count=1,
                bytes_in=0, bytes_out=0, first_detected=now,
                last_detected=now, ingested_at=now, raw_json="{}"))
    return now


def test_reader_raises_when_window_exceeds_cap(session_factory):
    from src.pce_cache.reader import CacheReader, CacheReadTooLarge
    now = _seed(session_factory, 3)
    reader = CacheReader(session_factory, events_retention_days=90,
                         traffic_raw_retention_days=7, read_max_rows=2)
    win = (now - timedelta(hours=1), now + timedelta(hours=1))
    with pytest.raises(CacheReadTooLarge) as ei:
        reader.read_flows_raw(*win)
    assert ei.value.count == 3 and ei.value.cap == 2
    with pytest.raises(CacheReadTooLarge):
        reader.read_flows_df(*win)


def test_reader_unlimited_by_default(session_factory):
    from src.pce_cache.reader import CacheReader
    now = _seed(session_factory, 3)
    reader = CacheReader(session_factory, events_retention_days=90,
                         traffic_raw_retention_days=7)
    rows = reader.read_flows_raw(now - timedelta(hours=1), now + timedelta(hours=1))
    assert len(rows) == 3


def test_analyzer_falls_back_to_api_on_too_large():
    from src.analyzer import Analyzer
    from src.pce_cache.reader import CacheReadTooLarge

    class FakeReader:
        def cover_state(self, *a):
            return "full"
        def read_flows_raw(self, *a, **k):
            raise CacheReadTooLarge(10, 5)

    class FakeApi:
        def execute_traffic_query_stream(self, *a, **k):
            return iter([{"x": 1}])

    a = Analyzer.__new__(Analyzer)  # 跳過建構子，只測 _fetch_query_flows
    a._cache_reader = FakeReader()
    a.api = FakeApi()
    flows, source = a._fetch_query_flows(
        "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z",
        query_pds=["allowed"], query_spec=None, needs_draft=False)
    assert source == "api"
    assert list(flows) == [{"x": 1}]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_pce_cache_reader_guard.py -v`
Expected: FAIL with "cannot import name 'CacheReadTooLarge'"

- [ ] **Step 3: 實作 reader 護欄**

`src/pce_cache/reader.py`：

```python
class CacheReadTooLarge(RuntimeError):
    """查詢窗列數超過 read_max_rows 護欄。

    呼叫端應接住並改走 live API 路徑（該路徑由 MAX_TRAFFIC_RESULTS=200k
    硬上限保護），而不是把整個視窗載入記憶體撐爆常駐 process。"""

    def __init__(self, count: int, cap: int):
        super().__init__(f"cache window has {count} rows > cap {cap}")
        self.count = count
        self.cap = cap
```

`CacheReader.__init__` 加參數 `read_max_rows: int | None = None`，存 `self._read_max_rows = read_max_rows`。新增：

```python
    def count_flows(self, start: datetime, end: datetime,
                    workload_hrefs: list[str] | None = None) -> int:
        with self._sf() as s:
            q = (select(func.count()).select_from(PceTrafficFlowRaw)
                 .where(PceTrafficFlowRaw.last_detected >= start,
                        PceTrafficFlowRaw.last_detected <= end))
            if workload_hrefs:
                hrefs = list(workload_hrefs)
                q = q.where(or_(PceTrafficFlowRaw.src_workload.in_(hrefs),
                                PceTrafficFlowRaw.dst_workload.in_(hrefs)))
            return s.execute(q).scalar() or 0

    def _guard_window(self, start: datetime, end: datetime,
                      workload_hrefs: list[str] | None = None) -> None:
        if self._read_max_rows is None:
            return
        n = self.count_flows(start, end, workload_hrefs)
        if n > self._read_max_rows:
            raise CacheReadTooLarge(n, self._read_max_rows)
```

`read_flows_raw` 與 `read_flows_df` 開頭（docstring 之後）各加：

```python
        self._guard_window(start, end, workload_hrefs)
```

`src/config_models.py` `PceCacheSettings`（Task 5 兩欄之後）：

```python
    cache_read_max_rows: int = Field(default=500000, ge=10000)  # cache 讀取單次視窗列數護欄
```

`src/main.py` `_make_cache_reader` 內建 `CacheReader(...)` 的呼叫處加 `read_max_rows=int(cfg.cache_read_max_rows)`（`cfg` 即該函式既有的 pce_cache 設定變數）。

- [ ] **Step 4: 實作呼叫端 fallback**

`src/analyzer.py`：import 區加 `from src.pce_cache.reader import CacheReadTooLarge`。

full 分支（:959-961）改為：

```python
        if state == "full":
            try:
                logger.info("query_flows: flows from cache ({} → {})", start_dt, end_dt)
                return self._cache_reader.read_flows_raw(start_dt, end_dt), "cache"
            except CacheReadTooLarge as exc:
                logger.warning(
                    "query_flows: {} — falling back to live API (bounded)", exc)
                state = "cache_too_large"  # 落到函式底部的 API 路徑
```

partial 分支（:1003-1006）改為：

```python
                if gap_list is not None:
                    try:
                        cached = self._cache_reader.read_flows_raw(cache_start, end_dt)
                    except CacheReadTooLarge as exc:
                        logger.warning(
                            "query_flows hybrid: {} — falling back to full API path", exc)
                    else:
                        source = "mixed" if gap_list else "cache"
                        return gap_list + cached, source
```

`src/report/report_generator.py`：import 區加 `from src.pce_cache.reader import CacheReadTooLarge`。

`_fetch_traffic` full 分支（:183-189）改為：

```python
            if state == "full":
                try:
                    raw = self._cache.read_flows_raw(
                        start, end, workload_hrefs=cache_workload_hrefs)
                except CacheReadTooLarge as exc:
                    logger.warning("Traffic report: {} — falling back to live API", exc)
                else:
                    logger.info("Traffic report: flows from cache ({} → {})", start, end)
                    return {"raw": raw,
                            "agg": self._cache.read_flows_agg(start, end),
                            "source": "cache"}
```

`_fetch_traffic` partial 分支的 `cached = self._cache.read_flows_raw(...)`（:220）與 `_fetch_traffic_df` 的兩處 `read_flows_df`（:261、:289）比照：包 `try/except CacheReadTooLarge`，except 記 warning 後不 return、讓控制流落到函式底部既有的 live API 分支（partial 分支需把「except 時跳出 if 區塊」寫成與 analyzer 相同的 try/else 結構）。

- [ ] **Step 5: 跑測試確認通過（含報表與 analyzer 回歸）**

Run: `python -m pytest tests/test_pce_cache_reader_guard.py tests/ -k "reader or report_generator or fetch_query" -v`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add src/pce_cache/reader.py src/config_models.py src/main.py src/analyzer.py src/report/report_generator.py tests/test_pce_cache_reader_guard.py
git commit -m "feat(cache): read_max_rows guard with live-API fallback to protect daemon memory"
```

---

### Task 7: Archive 回載背景化

`POST /api/cache/archive/load` 目前同步跑完「重建 review DB → 匯入 → 聚合」，31 天範圍在量大時必逾時。改成：route 立即回 202，實際工作在背景執行緒；`GET /archive/status` 回傳載入進度狀態（`idle/running/done/error`）；前端輪詢。既有 `_LOAD_LOCK` 語意（同時只允許一個 load、第二個 409）完整保留；`load_archive_review` 同步版保留給測試與潛在 CLI 呼叫。

**Files:**
- Modify: `src/pce_cache/archive_import.py`（拆出 `_load_archive_review_locked`；新增 `start_archive_load`、`load_progress`）
- Modify: `src/pce_cache/web.py:267-308`（load 回 202；status 併入 progress）
- Modify: `src/static/js/quarantine.js:848-866`（載入後輪詢 status）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（`gui_traffic_archive_loading`）
- Test: `tests/test_pce_cache_archive_load_async.py`（新檔）

**Interfaces:**
- Consumes: 既有 `load_archive_review(cfg, start, end)`、`ArchiveLoadBusy`、`_LOAD_LOCK`、`review_status(cfg)`。
- Produces: `start_archive_load(cfg, start: date, end: date) -> dict`（立即回 `{"started": True, "start": ..., "end": ...}`；busy 拋 `ArchiveLoadBusy`）；`load_progress() -> dict`（`{"state": "idle"|"running"|"done"|"error", ...}`）。

- [ ] **Step 1: 寫失敗測試（新檔）**

```python
import time
from datetime import date, datetime, timezone
from types import SimpleNamespace

import orjson


def _write_archive(dir_path, day: str, n: int):
    ts = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    lines = []
    for i in range(n):
        lines.append(orjson.dumps({
            "flow_hash": f"a-h{day}-{i}", "src_ip": "10.0.0.1",
            "dst_ip": "10.0.0.2", "src_workload": None, "dst_workload": None,
            "port": 443, "protocol": "tcp", "action": "allowed",
            "flow_count": 1, "bytes_in": 10, "bytes_out": 20,
            "event_time": ts.isoformat(), "ingested_at": ts.isoformat(),
            "first_detected": ts.isoformat(),
            "raw": {"src_ip": "10.0.0.1"},
        }))
    (dir_path / f"traffic-{day}.jsonl").write_bytes(b"\n".join(lines) + b"\n")


def _cfg(tmp_path):
    return SimpleNamespace(
        archive_dir=str(tmp_path / "arch"),
        db_path=str(tmp_path / "cache.sqlite"),
        archive_review_max_days=31,
    )


def _wait_terminal(timeout=15):
    from src.pce_cache.archive_import import load_progress
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = load_progress()
        if st.get("state") in ("done", "error"):
            return st
        time.sleep(0.1)
    raise AssertionError(f"load did not finish: {load_progress()}")


def test_start_archive_load_runs_in_background(tmp_path):
    from src.pce_cache.archive_import import start_archive_load
    (tmp_path / "arch").mkdir()
    _write_archive(tmp_path / "arch", "2026-07-01", 5)
    res = start_archive_load(_cfg(tmp_path), date(2026, 7, 1), date(2026, 7, 1))
    assert res["started"] is True
    st = _wait_terminal()
    assert st["state"] == "done"
    assert st["rows"] == 5


def test_start_archive_load_busy_raises(tmp_path):
    import pytest
    from src.pce_cache import archive_import as ai
    (tmp_path / "arch").mkdir()
    assert ai._LOAD_LOCK.acquire(blocking=False)  # 模擬另一個 load 進行中
    try:
        with pytest.raises(ai.ArchiveLoadBusy):
            ai.start_archive_load(_cfg(tmp_path), date(2026, 7, 1), date(2026, 7, 1))
    finally:
        ai._LOAD_LOCK.release()


def test_load_error_reported_in_progress(tmp_path):
    from src.pce_cache.archive_import import start_archive_load
    (tmp_path / "arch").mkdir()
    (tmp_path / "arch" / "traffic-2026-07-01.jsonl").write_bytes(b"")
    cfg = _cfg(tmp_path)
    cfg.db_path = str(tmp_path / "no-such-dir" / "x" / "cache.sqlite")  # 逼出錯誤
    start_archive_load(cfg, date(2026, 7, 1), date(2026, 7, 1))
    st = _wait_terminal()
    assert st["state"] == "error"
    assert st["error"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_pce_cache_archive_load_async.py -v`
Expected: FAIL with "cannot import name 'start_archive_load'"

- [ ] **Step 3: 實作背景載入**

`src/pce_cache/archive_import.py`：

(a) 既有 `load_archive_review` 拆成殼與本體——殼保留原簽章與 lock 語意：

```python
def load_archive_review(cfg, start: date, end: date) -> dict:
    """同步版：取得 lock 後執行（語意與 docstring 同 _load_archive_review_locked）。"""
    if not _LOAD_LOCK.acquire(blocking=False):
        raise ArchiveLoadBusy()
    try:
        return _load_archive_review_locked(cfg, start, end)
    finally:
        _LOAD_LOCK.release()


def _load_archive_review_locked(cfg, start: date, end: date) -> dict:
    <原 load_archive_review 的完整本體，去掉開頭 acquire 與結尾 finally release，
     docstring 原文搬過來>
```

(b) 新增進度狀態與背景啟動（module level，`_LOAD_LOCK` 定義之後）：

```python
_PROGRESS_LOCK = threading.Lock()
_PROGRESS: dict = {"state": "idle"}


def _set_progress(**kw) -> None:
    with _PROGRESS_LOCK:
        _PROGRESS.clear()
        _PROGRESS.update(kw)


def load_progress() -> dict:
    with _PROGRESS_LOCK:
        return dict(_PROGRESS)


def start_archive_load(cfg, start: date, end: date) -> dict:
    """背景執行 archive 載入，立即回 {"started": True}。

    lock 在此取得、由背景執行緒 finally 釋放——同時只允許一個 load，
    第二個呼叫立即拋 ArchiveLoadBusy（與同步版一致，web 端回 409）。"""
    if not _LOAD_LOCK.acquire(blocking=False):
        raise ArchiveLoadBusy()
    _set_progress(state="running", start=start.isoformat(), end=end.isoformat(),
                  started_at=datetime.now(timezone.utc).isoformat())

    def _worker() -> None:
        try:
            meta = _load_archive_review_locked(cfg, start, end)
            _set_progress(state="done", **meta)
        except Exception as exc:  # noqa: BLE001 — 背景執行緒的最外層收斂
            logger.exception("archive background load failed")
            _set_progress(state="error", error=str(exc)[:500])
        finally:
            _LOAD_LOCK.release()

    threading.Thread(target=_worker, name="archive-load", daemon=True).start()
    return {"started": True, "start": start.isoformat(), "end": end.isoformat()}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_pce_cache_archive_load_async.py tests/test_pce_cache_archive_import.py -v`
Expected: 全 PASS（同步版 `load_archive_review` 的既有測試不得變紅）

- [ ] **Step 5: 接上 web route 與前端**

`src/pce_cache/web.py` `load_archive`（:288-296）改為：

```python
    try:
        from src.pce_cache.archive_import import start_archive_load
        res = start_archive_load(cfg, start, end)
    except ArchiveLoadBusy:
        return jsonify({"ok": False,
                        "error": t("gui_traffic_archive_load_busy", lang=lang)}), 409
    except Exception as exc:  # noqa: BLE001
        return _err_with_log("cache_archive_load", exc, lang=lang)
    return jsonify({"ok": True, **res}), 202
```

（import 行的 `load_archive_review` 改為不再需要。）

`archive_status`（:299-308）改為：

```python
    from src.pce_cache.archive_import import review_status, load_progress
    ...
        st = review_status(cm.models.pce_cache)
        st["load"] = load_progress()
        return jsonify(st)
```

`src/static/js/quarantine.js`：載入按鈕 handler（:848-866）改為送出後輪詢：

```javascript
// 載入指定日期範圍的 archive（背景執行）：POST 立即回 202，之後輪詢 status。
async function loadArchiveRange() {
  const el = document.getElementById('archive-status');
  const start = (document.getElementById('archive-start') || {}).value;
  const end = (document.getElementById('archive-end') || {}).value;
  try {
    const body = await post('/api/cache/archive/load', { start_date: start, end_date: end });
    if (!body || body.ok === false) {
      if (el) el.textContent = _t('gui_traffic_archive_load_error').replace('{err}', (body && body.error) || '');
      return;
    }
    if (el) el.textContent = _t('gui_traffic_archive_loading');
    for (;;) {
      await new Promise((r) => setTimeout(r, 2000));
      const st = await get('/api/cache/archive/status');
      const load = (st && st.load) || {};
      if (load.state === 'running') continue;
      if (load.state === 'error') {
        if (el) el.textContent = _t('gui_traffic_archive_load_error').replace('{err}', load.error || '');
        return;
      }
      if (load.no_files) {
        if (el) el.textContent = _t('gui_traffic_archive_no_files');
        return;
      }
      break; // done → 以既有 status 呈現邏輯刷新
    }
  } catch (e) {
    if (el) el.textContent = _t('gui_traffic_archive_load_error').replace('{err}', String(e));
    return;
  }
  // 沿用既有「載入成功後刷新狀態」的函式（quarantine.js:837-845 一帶的 status 顯示邏輯）
  await refreshArchiveStatus();
}
```

（函式名以 quarantine.js 現況為準：把既有同步版 handler 的函式體換成上面內容、保留原函式名與綁定；`refreshArchiveStatus` 對應 :837-845 既有的狀態刷新函式名。）

i18n（兩檔）：

```json
"gui_traffic_archive_loading": "Loading archive in background..."
```

```json
"gui_traffic_archive_loading": "Archive 背景載入中..."
```

同時更新既有 web 測試：搜 `tests/` 中呼叫 `/api/cache/archive/load` 的測試，斷言從「200 + rows」改為「202 + `started: true`」，並在測試內輪詢 `/api/cache/archive/status` 至 `load.state == "done"` 後驗證 rows。

- [ ] **Step 6: 跑測試 + 前端 lint**

Run: `python -m pytest tests/ -k "archive" -v && ruff check src`
Expected: 全 PASS（若 repo 有 JS 檢查腳本一併跑）

- [ ] **Step 7: Commit**

```bash
git add src/pce_cache/archive_import.py src/pce_cache/web.py src/static/js/quarantine.js src/i18n_en.json src/i18n_zh_TW.json tests/test_pce_cache_archive_load_async.py
git commit -m "feat(archive): run review load in background thread with progress polling"
```

---

### Task 8: Web 路徑引擎一致化（NullPool + 快取引擎）

`src/pce_cache/web.py:34` 與 `src/siem/web.py:40,327` 用 `create_engine` 預設 pool（QueuePool），與其餘熱路徑（NullPool 或 `_get_cache_engine`）不一致，長跑 web 請求會累積連線。比照 lag_monitor 的修法（write-contention 設計 §4.2 的先例）改用 `_get_cache_engine`（per-db_path 快取、NullPool、schema 只 init 一次）。

**Files:**
- Modify: `src/pce_cache/web.py:14-37`（`_get_sf` 改用 `_get_cache_engine`，移除自帶的 double-checked lock 快取）
- Modify: `src/siem/web.py:40`、`src/siem/web.py:327`（同法）
- Test: `tests/test_web_engine_nullpool.py`（新檔）

**Interfaces:**
- Consumes: `src.gui._helpers._get_cache_engine(db_path)`（process 級快取 + NullPool + `_ensure_schema_once`）。

- [ ] **Step 1: 寫失敗測試（新檔）**

```python
from types import SimpleNamespace


def test_cache_web_sf_uses_cached_engine(monkeypatch, tmp_path):
    import flask
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    from src.pce_cache import web as cache_web

    calls = []

    def fake_get_engine(path):
        calls.append(path)
        return create_engine(f"sqlite:///{tmp_path / 'w.sqlite'}", poolclass=NullPool)

    monkeypatch.setattr("src.gui._helpers._get_cache_engine", fake_get_engine)
    app = flask.Flask(__name__)
    app.config["CM"] = SimpleNamespace(models=SimpleNamespace(
        pce_cache=SimpleNamespace(db_path=str(tmp_path / "w.sqlite"))))
    with app.test_request_context():
        sf = cache_web._get_sf()
    assert calls == [str(tmp_path / "w.sqlite")]
    assert sf is not None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_web_engine_nullpool.py -v`
Expected: FAIL（`_get_sf` 未經 `_get_cache_engine`，`calls` 為空）

- [ ] **Step 3: 實作**

`src/pce_cache/web.py` `_get_sf`（:14-37 的自帶快取整段）改為：

```python
def _get_sf():
    """cache DB 的 sessionmaker。引擎走 _get_cache_engine：per-db_path
    process 快取 + NullPool + schema 只 init 一次——與 lag_monitor、
    scheduler jobs 相同的取用模式，避免 web 路徑用預設 QueuePool 長跑
    累積連線。"""
    from sqlalchemy.orm import sessionmaker
    from src.gui._helpers import _get_cache_engine
    db_path = current_app.config["CM"].models.pce_cache.db_path
    return sessionmaker(_get_cache_engine(db_path))
```

`src/siem/web.py` 的兩處 `create_engine(...)`（:40、:327）同法：改 `from src.gui._helpers import _get_cache_engine` 後以 `_get_cache_engine(該處原本的 db_path 變數)` 取代（`_get_cache_engine` 是 per-path 快取，即使 siem 端指向不同檔案也正確）。若該處只是建 engine 後包 sessionmaker，直接替換 engine 來源即可，周邊邏輯不動。

- [ ] **Step 4: 跑測試確認通過（含 cache/siem web 回歸）**

Run: `python -m pytest tests/test_web_engine_nullpool.py tests/ -k "cache_web or siem_web or pce_cache_web" -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache/web.py src/siem/web.py tests/test_web_engine_nullpool.py
git commit -m "refactor(web): route cache/siem web engines through cached NullPool engine"
```

---

### Task 9: 營運手冊容量 sizing 與 7/24 runbook

把本計畫的容量推估、調校旋鈕與 7/24 營運注意事項寫進中英文營運手冊。純文件 task，放最後（引用前面 task 落地後的實際設定名）。

**Files:**
- Modify: `docs/operations-manual.md`（新章節 "Capacity Planning & 24/7 Operation"）
- Modify: `docs/operations-manual_zh.md`（同步中文）

**Interfaces:** 無程式碼介面。內容須涵蓋（兩語言同構）：

- [ ] **Step 1: 撰寫章節內容**

必含小節與事實（數字直接沿用，勿改寫）：

1. **容量基準**：每列 raw flow 全成本約 2.3KB（含索引與 raw/report JSON）；7 天窗口推估表——每日 1 萬筆 → 約 160MB、10 萬 → 約 1.6GB、100 萬 → 約 16GB；archive gzip 後約每 100 萬筆/日 120MB/天。
2. **調校旋鈕一覽**（表格）：`traffic_poll_interval_seconds`（預設 3600）、ingest `max_results`（200000，碰頂會自動二分抽乾並記 warning）、SIEM `batch_size`（預設 100）× `dispatch_tick_seconds`（預設 30）→ 預設吞吐上限約 28.8 萬筆/日/目的地，超過須調 `batch_size`、`cache_read_max_rows`（預設 500000）、`disk_free_warn_gb`（預設 10）、`siem_pending_warn_rows`（預設 50000）、`archive_retention_days`（預設 0=永久，須確保磁碟監控開啟）。
3. **7/24 營運注意**：正式常駐一律用 `--monitor-gui`（systemd unit 已配 `Restart=on-failure`）；**絕不可**用 `--gui` 模式常駐（不跑 ingestion/retention，cache 會停更且不清理，見 `src/cli/_runtime.py:97-106` 警語）；改排程類設定（interval、archive 開關）後需 `/api/daemon/restart` 或重啟服務才生效；日誌 rotation 已內建（10MB × 10 份 gzip）。
4. **要盯的三個預警數字**（來自 `/api/cache/health` 的 `capacity` 欄位與容量監控告警）：磁碟剩餘、`siem_pending`、`archiver_lag_seconds`——最後者告警代表 retention 守門已停刪、DB 正在無上限成長，須立即查 archive job。
5. **交叉引用**：告警送達可靠性與 dead-man's switch 屬另一計畫（`docs/superpowers/plans/2026-07-04-alert-reliability-and-event-catalog-audit.md`）。

- [ ] **Step 2: 驗證文件一致性**

Run: `python -m pytest tests/ -k "docs or manual" -v; grep -c "Capacity Planning" docs/operations-manual.md docs/operations-manual_zh.md`
Expected: 兩檔各至少 1 處命中；若無 docs 相關測試則以 grep 驗證為準

- [ ] **Step 3: Commit**

```bash
git add docs/operations-manual.md docs/operations-manual_zh.md
git commit -m "docs(ops): capacity planning and 24/7 operation runbook"
```

---

## 完工驗證（全計畫）

- [ ] `python -m pytest tests/ -x -q` 全綠。
- [ ] `ruff check src tests` 通過。
- [ ] `python scripts/check_no_naive_datetime.py` 通過。
- [ ] i18n parity 測試通過（en/zh_TW key 同步）。
- [ ] 手動冒煙：`--monitor-gui` 啟動後，`/api/cache/health` 回應含 `capacity` 欄位；GUI archive 載入按鈕按下後顯示「背景載入中」並在完成後刷新狀態。
