# PCE Cache 並發寫鎖根治 — 設計

- 日期：2026-07-01
- 狀態：已與使用者確認方向（方案 A + item 4），待 spec review
- 範疇：`src/scheduler/`、`src/pce_cache/lag_monitor.py`、`src/siem/dispatcher.py`、`src/config_models.py`、`src/pce_cache/ingestor_traffic.py`、`src/pce_cache/ingestor_events.py`

## 1. 背景與已確認根因

測試機出現「管線 error」的根因，經讀原始碼確認為：**多個並發寫入者對單寫者 SQLite（`pce_cache.sqlite`）競爭寫鎖**。

寫入者盤點（皆對同一顆 cache DB 寫）：

| Job（id） | 間隔 | 寫入行為 |
|---|---|---|
| `pce_cache_ingest_traffic` | 3600s | 重量級：每 500 筆一 transaction 的 bulk upsert；10 萬筆 → 200+ 個寫鎖交易，每 chunk 內嵌 `SiemDispatch` insert |
| `pce_cache_ingest_events` | 300s | 類似 bulk 寫入（`on_conflict_do_nothing` + 內嵌 enqueue） |
| `pce_cache_aggregate` | 1h | 全表 GROUP BY + upsert agg |
| `pce_cache_retention` | 24h | 多段 DELETE |
| `siem_dispatch` | **5s** | 高頻：每 tick anti-join SELECT +「每送出一列一個 transaction」更新 `status='sent'`（batch 100 → 每 5s 最多 100 個寫交易/destination） |
| `cache_lag_monitor` | **60s** | **每次都 `create_engine` + `init_schema`（DDL：create_all/ALTER/CREATE INDEX/DROP INDEX）** —— 每分鐘一批 DDL 寫鎖，且未用快取 engine |
| `monitor_cycle` | 30s | 小寫入（analyzer cursor 前進） |

**精確失敗機制**：大筆 traffic ingest 進行時，`_insert_batch` 第一個 chunk 的 `with self._sf.begin()` 搶不到寫鎖，等超過 `busy_timeout=30000`（30s）→ `OperationalError: database is locked` → 例外從 `TrafficIngestor.run_once` 往上拋到 `run_traffic_ingest` 僅被 `logger.exception` 收掉。此路徑**既未 `advance` 也未 `record_error`** → `IngestionWatermark.last_sync_at` 不前進、`last_status` 誤停在上次的 `"ok"` → `check_cache_lag` 由 `last_sync_at` 未前進而算出遞增 lag → `pipeline_verdict` 判 error。

放大競爭的兩個來源：`siem_dispatch`（5s、逐列 commit）與 `cache_lag_monitor`（60s、重跑 DDL）。

### Process 模型（決定序列化是否足夠）

- `--monitor-gui`（正式常駐）為**單一 process**：Flask GUI 在主執行緒（cheroot 多執行緒），`BackgroundScheduler` 在同 process 背景執行緒（`src/cli/_runtime.py:113-173`）。所有排程 job 與 Flask handler 都是同 process 執行緒。
- 正常部署**不會有兩個 process 同時寫** cache（`--gui` 不跑排程；`--monitor` 無 GUI）。
- Flask 對 cache 幾乎只讀（WAL 允許多讀 + 單寫並存）。唯一寫面是報表產生時 `_make_cache_reader/_make_subscribers` 每次 `init_schema` 的 DDL（次要殘留，見 §8）。

因此競爭屬「同 process、多執行緒」等級 —— APScheduler 單 worker executor 的序列化即可根治主要競爭面。

## 2. 已確認的需求決策

| 面向 | 決策 |
|---|---|
| SIEM 延遲容忍 | **可暫緩（eventual 即可）**；ingest 期間 SIEM 延遲數十秒到數分鐘可接受 |
| 方向 | **方案 A**：序列化 cache 批次寫入者 + 修 lag_monitor DDL churn + siem 批次化/降頻 |
| item 4 | **納入**：ingest 失敗時 `record_error`，讓 `last_status` 反映真實。**不做** lock 有界重試（序列化後幾乎不再撞 lock，YAGNI） |
| 架構 | 維持**單一 SQLite DB**，不分離、不換引擎（拒絕方案 C，離線 appliance 過度設計） |

## 3. 架構與資料流

```
BackgroundScheduler
├─ executor "default"       (ThreadPoolExecutor max_workers=5)
│   monitor_cycle / tick_report / tick_rule / ven_summary /
│   posture_summary / siem_dispatch / cache_lag_monitor(改純讀)
│
└─ executor "cache_writer"  (ThreadPoolExecutor max_workers=1)  ← 新增
    pce_cache_ingest_events / pce_cache_ingest_traffic /
    pce_cache_aggregate / pce_cache_retention /
    pce_cache_archive(來自 archive plan，落地時一併指派)
```

核心原則：**所有重量級 cache 批次寫入者共用單一 worker → 彼此永不並發**，讓 app 尊重 SQLite 的單寫者事實，破壞性競爭由結構消除。慢速外部 I/O 的 job（`monitor_cycle` 打 PCE API、`siem_dispatch` 送 SIEM）**不放進序列 worker**，避免反向阻塞 ingest；它們對 DB 的小寫入交給 WAL + `busy_timeout` 吸收，並由 §4.3 把 siem 寫入足跡壓到可忽略。

## 4. 元件改動

### 4.1 排程序列化（`src/scheduler/__init__.py`）

1. executors 由 `{"default": ThreadPoolExecutor(max_workers=5)}` 擴為同時含 `"cache_writer": ThreadPoolExecutor(max_workers=1)`（`src/scheduler/__init__.py:32`）。
2. cache 區塊（`src/scheduler/__init__.py:132-141`）這 4 個 `add_job` 加 `executor="cache_writer"`：`pce_cache_ingest_events`、`pce_cache_ingest_traffic`、`pce_cache_aggregate`、`pce_cache_retention`。
3. `cache_lag_monitor`（`:142-143`）**不移動**（改為純讀，見 §4.2，留在 default 可與寫入並行）。
4. `pce_cache_archive`（由 archive plan 新增）落地時，一併加 `executor="cache_writer"`（跨 plan 註記，兩 plan 皆改到本區塊）。
5. `job_defaults` 既有 `coalesce=True, max_instances=1, misfire_grace_time=60`。序列化後，長 ingest 執行期間，同 executor 的其他 cache 批次 job 會排隊；miss 的 tick 由 coalesce 收斂為一次補跑。可接受（這些 job 本就低頻）。

### 4.2 lag_monitor 去 DDL churn（`src/pce_cache/lag_monitor.py:50-59`）

`run_cache_lag_monitor` 改用 `from src.gui._helpers import _get_cache_engine`，以 `_get_cache_engine(cfg.db_path)` 取得**每 db_path 快取、`init_schema` 只跑一次**的 engine，取代現行「每 tick `create_engine(...)` + `init_schema(engine)`」。→ 移除每 60s 一批 DDL 寫鎖，lag_monitor 變純讀（WAL 安全，不擋寫），與 `test_scheduler_engine_cache.py` 的「一個 db_path 共用一顆 engine」本意一致。

### 4.3 siem_dispatch 降低寫入足跡（`src/siem/dispatcher.py` + `src/config_models.py`）

1. `DestinationDispatcher._process_batch`（`:69-121`）：把**成功路徑**由「每列一個 `with self._sf.begin(): UPDATE ... status='sent'`」改為「送出時收集成功的 `id`，迴圈結束後以**單一 transaction** 一次 `UPDATE SiemDispatch WHERE id IN (sent_ids) SET status='sent', sent_at=now`」。失敗/退避與 quarantine 路徑（`:103-119`、`_quarantine`）維持逐列（是例外、罕見，且各自 `next_attempt_at` 退避值不同）。
   - 網路送出仍逐列（無法批次），只把 DB 狀態更新收斂為一交易。
   - at-least-once 取捨：批次化後，若 process 在部分送出後、最終 UPDATE commit 前崩潰，已送出但未標記的列下輪會**重送**（重複交付窗口變寬）。SIEM 本即 at-least-once、且 eventual 已同意，可接受；於 spec/plan 註明。
2. `SiemForwarderSettings.dispatch_tick_seconds` 預設 `5 → 30`（`src/config_models.py:318`）。只改**預設值**；已顯式設定者尊重其值。

### 4.4 ingest 失敗可觀測性（item 4）

`TrafficIngestor.run_once`（`src/pce_cache/ingestor_traffic.py:52-66`）與 `EventsIngestor.run_once`（`src/pce_cache/ingestor_events.py:63-68`）的 insert 路徑加 `except`：`_insert_batch`（或後續 advance）拋例外時，呼叫 `self._wm.record_error(self.SOURCE, str(exc))` 後 **re-raise**（不吞例外）。→ lock 失敗時 `last_status="error"` 反映真實，不再誤停 `"ok"`；同時**保留既有 re-raise 契約**（`run_traffic_ingest`/`run_events_ingest` 仍以 `logger.exception` 大聲記錄），且相容既有回歸測試 `tests/test_pce_cache_ingestor_traffic.py:113-132`（它以 `pytest.raises(RuntimeError)` 鎖定 insert 失敗會往上拋、且 poll log 仍輸出）。**不加**重試。

## 5. 設定

- 僅改 `dispatch_tick_seconds` 預設值（既有欄位）。
- 不新增資料表/欄位（`cache_writer` executor 為排程內部結構，無需 config）。

## 6. 測試策略（TDD）

- **executor 指派**（新 `tests/test_scheduler_write_serialization.py`）：`build_scheduler(cm)` 後，斷言 `pce_cache_ingest_events/ingest_traffic/aggregate/retention` 的 `job.executor == "cache_writer"`；`monitor_cycle/siem_dispatch/cache_lag_monitor` 的 `job.executor == "default"`；且 scheduler 有名為 `cache_writer`、`max_workers==1` 的 executor。（用既有 `MagicMock cm`、`pce_cache.enabled=True`、`siem.enabled` 兩種情況。）
- **lag_monitor 純讀**（新測試）：patch `src.gui._helpers._get_cache_engine`，呼叫 `run_cache_lag_monitor(cm)`，斷言走 `_get_cache_engine`、且**不**每 tick 呼叫 `init_schema`（呼叫次數 0）。
- **siem 批次化**（擴 `tests/` siem dispatcher 測試）：seed N 筆 `pending` + 假 transport 全成功 → `tick()` 後 N 筆皆 `sent`，且 `status='sent'` 的寫入僅開**一個** transaction（以 session spy／commit 計數驗證）。
- **item 4**（擴 ingestor 測試）：mock `_insert_batch` 拋 `OperationalError("database is locked")` → 斷言 `run_once` 往上拋（`pytest.raises`）、且 watermark `last_status=="error"`（`record_error` 已被呼叫）。既有 `test_run_once_emits_poll_log_even_when_insert_batch_raises` 維持綠。
- **回歸**：`tests/test_scheduler_engine_cache.py`、既有 siem dispatcher 測試、`tests/test_pce_cache_retention.py` 全綠。

## 7. 影響範圍與相容性

- 修改：`src/scheduler/__init__.py`、`src/pce_cache/lag_monitor.py`、`src/siem/dispatcher.py`、`src/config_models.py`、`src/pce_cache/ingestor_traffic.py`、`src/pce_cache/ingestor_events.py`。
- 不新增資料表/欄位、不換 DB 引擎、無新相依；離線 appliance 零額外負擔。
- 與 archive plan 唯一交會點：兩者都改 `src/scheduler/__init__.py` cache 區塊。落地順序不拘，但先落地者需在最終狀態確保 `pce_cache_archive` 也帶 `executor="cache_writer"`。

## 8. 明確不做（YAGNI）與已知殘留

- 不改用 Postgres、不分離 siem DB（方案 C）。
- 不做跨 process 分散鎖（正常部署單 process）。
- 不對 ingest lock 做有界重試（序列化後幾乎不再撞 lock）。
- **已知殘留（不在本次範圍）**：Flask 端 `_make_cache_reader`/`_make_subscribers`（`src/main.py:24-69`）每次呼叫都 `create_engine + init_schema`，與 lag_monitor 同類 DDL-per-call 反模式，報表產生期間仍可能與 ingest 短暫競爭。列為後續：若序列化後報表期間仍見零星 lock，再比照 §4.2 改用 `_get_cache_engine`。
