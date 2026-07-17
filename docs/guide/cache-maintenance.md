---
title: pce_cache 維運與容量規劃
audience: [operator]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - src/pce_cache/models.py
  - src/pce_cache/ingestor_traffic.py
  - src/pce_cache/ingestor_events.py
  - src/pce_cache/aggregator.py
  - src/pce_cache/retention.py
  - src/pce_cache/archive.py
  - src/pce_cache/archive_import.py
  - src/pce_cache/backfill.py
  - src/pce_cache/reader.py
  - src/pce_cache/capacity.py
  - src/pce_cache/lag_monitor.py
  - src/pce_cache/schema.py
  - src/pce_cache/traffic_filter.py
  - src/pce_cache_cli.py
  - src/cli/cache.py
  - src/pce_cache/web.py
  - src/scheduler/jobs.py
  - src/config_models.py
  - config/config.json.example
  - CHANGELOG.md
---

# pce_cache 維運與容量規劃

`pce_cache` 是**選用**的本機 SQLite 鏡像（`data/pce_cache.sqlite`，WAL 模式），把 PCE 的 events／traffic
增量拉進本機資料庫，供 SIEM 轉送、報表與告警共用讀取，避免同一份資料被重複打 PCE API。預設**停用**
（`pce_cache.enabled = false`），停用時分析與報表一律回退即時 PCE API。啟用後各設定鍵的完整清單與預設值見
[configuration.md](configuration.md) 「pce_cache」節；本篇聚焦架構、操作與容量規劃。

## 1. 架構一頁圖

```
PCE（events API／traffic flows API）
        │
        │  events_poll_interval_seconds（預設 300s）
        │  traffic_poll_interval_seconds（範本 600s／裸 pydantic 預設 3600s）
        ▼
 ┌────────────────────────────────────────────────────────┐
 │  ingest 層（scheduler job，cache_writer 單一 worker）    │
 │  EventsIngestor          TrafficIngestor                │
 │  （watermark 增量拉取）  （watermark＋200000 上限自動    │
 │                           二分＋TrafficFilter＋Sampler） │
 └───────────────┬───────────────────────┬─────────────────┘
                 ▼                       ▼
         pce_events              pce_traffic_flows_raw
      （明細，保留 90 天）     （明細，保留 7 天；含 report_json
                                 預算 flatten 快取）
                                        │
                                        │ TrafficAggregator（每小時，
                                        │ 增量 3 天視窗＋MAX 合併）
                                        ▼
                              pce_traffic_flows_agg
                             （每日彙總，保留 90 天）
                                        │
        ┌───────────────────────────────┼───────────────────────────┐
        ▼                               ▼                           ▼
  CacheReader（reports／     RetentionWorker（每日刪除    ArchiveExporter（依
  analyzer 讀取，護欄         過期列；archive_enabled     archive_interval_hours，
  cache_read_max_rows）      時只刪「已封存」的列）        增量匯出分日 JSONL）
                                                                    │
                                                          gzip 輪替／archive_retention_days
                                                                    │
                                                          ArchiveImporter（隨選匯入回
                                                          archive_review.sqlite 供 GUI
                                                          查閱已被 retention 清掉的舊資料）

  另有 CacheSubscriber（siem_dispatch 佇列的來源）、LagMonitor（60s 偵測 ingest 落後）、
  capacity_snapshot（30 分鐘記錄 DB 大小／磁碟／SIEM 積壓／archiver 落後）三條旁支，
  都讀同一份 pce_events / pce_traffic_flows_raw，不額外複製資料。
```

對照 [automation.md](automation.md) §3 的 14-job 總表：本圖涉及 `pce_cache_ingest_events`、
`pce_cache_ingest_traffic`、`pce_cache_aggregate`、`pce_cache_retention`、`pce_cache_archive`、
`cache_lag_monitor`、`pce_cache_capacity_monitor`、`siem_dispatch` 共 8 個 job，兩篇資料一致、互不矛盾。

## 2. Ingest 與 Backfill 操作

### 2.1 三種操作入口

| 入口 | 用途 |
|---|---|
| CLI：`illumio-ops cache status` / `cache backfill --source events\|traffic --since YYYY-MM-DD [--until YYYY-MM-DD]` / `cache retention [--run]` | 腳本化操作，`--json` 可輸出結構化結果 |
| 互動選單：`illumio-ops` 不帶參數啟動主選單 → `7. PCE Cache` | View status／Edit settings／Edit traffic filter／Edit traffic sampling／Backfill（互動輸入起訖日）／Run retention now |
| GUI／API：`POST /api/cache/backfill`、`POST /api/cache/retention/run`、`GET /api/cache/status`、`GET /api/cache/lag`、`GET /api/cache/health` | 需登入；Integrations 分頁的 cache 卡片走這組 API |

### 2.2 Backfill 語意（重要：不套用 live ingest 的 traffic_filter）

`BackfillRunner`（`src/pce_cache/backfill.py`）與日常 live ingest（`TrafficIngestor`）是兩條不同路徑：

- **Backfill 不套用 `pce_cache.traffic_filter`**：`traffic_filter.actions` 這道白名單過濾（預設只留
  `blocked`／`potentially_blocked`）只在 `TrafficIngestor.run_once()` 內生效；`BackfillRunner.run_traffic()`
  把 API 查詢回來的每一筆流量原樣寫入 `pce_traffic_flows_raw`，不經過該過濾器。
- **Backfill 不推進 watermark**：`run_events`／`run_traffic` 兩個方法的 docstring 明講「Does NOT advance
  watermark」——backfill 補寫歷史資料，不影響 live ingest 下次該從哪裡繼續拉。
- **去重靠 `flow_hash`／`pce_event_id` 的 unique constraint**：每筆插入各自一個交易，遇 `IntegrityError`
  （代表該筆已存在）記一筆 duplicate 並略過，不中斷整批——同一日期範圍可安全重跑。

### 2.3 案例：重跑 backfill 補齊 unknown flows

背景（見 CHANGELOG「Changed」一節）：2026-07 起，未顯式指定 `policy_decisions` 的流量查詢預設含四值
`blocked`／`potentially_blocked`／`allowed`／`unknown`（`unknown` 涵蓋 idle／快照模式 VEN 與 Flowlink 未管理
流量）；此版本之前寫入 cache 的資料，在當時 fetch 時只含前三值，`unknown` 流量被漏掉。

因為 backfill 不套用 `traffic_filter`、且沿用查詢端的新預設，重跑 backfill 是把「查詢預設已改」這件事一次性
套用回歷史資料視窗的正確做法：

```bash
illumio-ops cache backfill --source traffic --since 2026-06-01 --until 2026-07-16
```

**真機案例**（2026-07-16 測試機，`[真機驗證]`）：對既有 cache 重跑一次 traffic backfill，`policy_decisions`
含 `unknown` 後，補入 **199,711** 列先前因查詢預設不含 `unknown` 而遺漏的流量；因 `flow_hash` 去重，重跑對既有
列不會造成重複。

> **注意範圍**：backfill 只補「歷史」視窗。日常 live ingest（`TrafficIngestor`）仍受
> `pce_cache.traffic_filter.actions` 過濾——預設只留 `blocked`／`potentially_blocked`，`allowed`／`unknown`
> 流量即使查詢端已含四值，也不會被 live ingest 寫入 cache。若要讓「往後」的 live ingest 也持續收
> `allowed`／`unknown`，須另外把 `traffic_filter.actions` 擴大（互動選單「3. Edit traffic filter」或
> `config.json`），否則每次 live ingest 仍只保留 blocked／potentially_blocked，需要靠定期重跑 backfill 補。

### 2.4 Ingest 自動二分抽乾（避免無聲截斷）

`TrafficIngestor` 單次查詢視窗結果數若碰到 `max_rows_per_batch`（`pce_cache.traffic_sampling`，預設
`200000`，上限 `200000`），不會截斷資料，而是遞迴把該視窗對半二分（最深 6 層、最小視窗 1 分鐘 floor）重新
抽取。若連 1 分鐘 floor 視窗仍碰頂，才會放棄該視窗並記 WARNING，代表該分鐘資料可能不完整——這只會在持續
**每秒約 3,300 筆以上**（200,000 ÷ 60s）的流量下發生。碰頂事件會寫入 `state["traffic_overflow"]`，
Analyzer 的 overflow 告警會據此發出提醒（見 [monitoring-alerts.md](monitoring-alerts.md)）。

## 3. Retention 與 Archive

### 3.1 Retention：分表刪除、批次交易

`RetentionWorker.run_once()` 依 `ingested_at`／`bucket_day` 早於保留期限刪除，每批 10,000 列一個交易（避免單
一大 DELETE 撐爆 WAL、長時間佔住 `cache_writer`）：

| 表 | 保留鍵 | 預設天數 |
|---|---|---|
| `pce_events` | `events_retention_days` | 90 |
| `pce_traffic_flows_raw` | `traffic_raw_retention_days` | 7 |
| `pce_traffic_flows_agg` | `traffic_agg_retention_days` | 90 |
| `dead_letter` | 固定 30 天 | 30 |
| `siem_dispatch`（僅 `status='sent'` 的已送達列） | 固定 14 天 | 14 |

`siem_dispatch` 只會單向從 `pending`→`sent`，從不被其他機制清除，會無限累積；retention 只清「已送達」超過
14 天的列，`pending`／`failed`（重試／DLQ 候選）不動。

一筆持續被 re-pull 的長壽 flow，其 `ingested_at` 會在每次 re-pull 時被 bump 到本次 ingest 時間（見 §3.3），
因而在 retention 眼中自動延壽——語意上合理：仍活躍的 flow 不該被當陳舊資料清掉。

### 3.2 Archive 閘門：`archive_enabled` 時 retention 只刪「已封存」的列

`archive_enabled=true` 時，retention 對 `pce_events`／`pce_traffic_flows_raw` 的實際刪除界線是
`min(保留期限, archiver 已封存到的游標)`；archiver 游標為 `None`（該來源尚未被封存過一筆）時，retention
對該來源**完全不刪**，並記 `retention guard: nothing archived for … yet; withholding deletion`。這是刻意設計
——避免資料在被封存前就被永久刪除。

### 3.3 Archive 交付語意：at-least-once

`ArchiveExporter`（`src/pce_cache/archive.py`）把 `pce_events`／`pce_traffic_flows_raw` 依 `ingested_at` 游標
增量匯出成分日 JSONL（`data/archive/traffic-YYYY-MM-DD.jsonl`、`audit-YYYY-MM-DD.jsonl`）：

- 每批先寫檔並 `fsync` 成功後才推進游標，是 **at-least-once**——正常運作不重複；若在 fsync 後、游標推進前
  崩潰，下次會重寫同一批，JSONL 可能含重複列（無資料遺失；下游用 `flow_hash`／`pce_event_id` 去重）。
- 超過 `archive_gzip_after_days`（預設 7 天）的 `.jsonl` 檔會被 gzip 壓縮成 `.gz`（append 模式保留既有內容）
  並刪除原檔；`archive_retention_days`（預設 `0`＝永久保留、不刪）之外的舊檔才會被清除，依**檔名事件日**
  （非 mtime）判斷。

**長壽 flow 的成長會被重新匯出**（承接舊版 §8.1 的已知限制、現已修復——轉寫並比對現行 `archive.py`
docstring 一致）：ingestor 的 upsert 在 conflict 時會把 `ingested_at` bump 到本次 ingest 時間（只要
re-pull 到的 flow 有 volatile 欄位——`last_detected`／`bytes_in`／`bytes_out`／`flow_count`——發生變化），
所以一筆持續成長的長壽 flow 會被下一輪 archive 匯出重新撿到；`ArchiveImporter._flush`（import 端）以
`flow_hash` 為 key upsert，`last_detected`／`bytes_in`／`bytes_out`／`flow_count` 取 **MAX** 合併
（`first_detected` 取 MIN，`raw_json`／`report_json` 取較新 `last_detected` 那一側），因此重複匯入同一 flow
較晚的 export，只會讓 Archive Review DB 的計數往上補齊，不會被凍結或縮小。

**容量規劃註記**：每一筆活躍成長中的長壽 flow，現在每次變化被撿到時都會重寫進當日的 archive 檔，繁忙 PCE 上
archive 目錄的增長率會明顯高於「每 flow 一行」——見第 4 節容量規劃。

### 3.4 Archive Review（查閱已被 retention 清掉的舊資料）

`archive_review.sqlite`（獨立於主 cache DB）由 `ArchiveImporter.import_range()` 隨選建置：GUI／API 呼叫
`POST /api/cache/archive/load`（body 帶 `start_date`／`end_date`，範圍上限 `archive_review_max_days`，預設
31 天）觸發背景匯入，`GET /api/cache/archive/status` 查進度。建置採「build-to-temp + 原子 `os.replace`」，
同時只允許一個 load 在跑（第二個請求立即回 409，不排隊）。用途：查主 cache 已因 `traffic_raw_retention_days`
（預設僅 7 天）被刪除、但仍留在 archive JSONL 裡的舊流量。

### 3.5 首跑錨定（2026-07-14 archive 事故修復）

`pce_cache_aggregate`／`pce_cache_retention`／`pce_cache_archive`（連同 `pce_cache_capacity_monitor`、
`tls_renew_check`）等長間隔 job，過去用 APScheduler `IntervalTrigger` 預設「首跑排在啟動後一整個間隔」，在
頻繁重啟的部署下這些 24 小時級的 job 永遠等不到首跑——`data/archive` 長期是空的、DB 無上限成長也沒被
retention 清理。修復後這些 job 一律帶啟動後錯開的近期首跑 kick，行為細節見
[automation.md](automation.md) §3。

## 4. 容量規劃（Capacity Planning）

> 範圍說明：本節是本機 sidecar 自身的容量（SQLite 大小、磁碟、SIEM backlog、archiver lag）。遠端 PCE 自身
> 事件資料庫的容量（soft/hard limit 清理）是另一套機制——見告警 runbook 的 `pce-capacity` 分類
> （[monitoring-alerts.md](monitoring-alerts.md)）。

### 4.1 容量基準（承接舊版 §8.9 實測，經比對現行 schema 一致，未過時）

實測基準（測試機）：12,056 筆 raw flow 佔 27.6MB——每列全成本約 **2.3KB**（含索引與 `raw_json`／
`report_json` 雙欄位，對照 `models.py` 的 `PceTrafficFlowRaw` 現行 schema 一致）。以 7 天線上窗口
（`traffic_raw_retention_days` 預設 7）推估：

| Flows/day | 7 天 cache 估計大小 |
|---|---|
| 10,000 | 約 160MB |
| 100,000 | 約 1.6GB |
| 1,000,000 | 約 16GB |

archiver 把舊檔 gzip 壓縮後（`archive_gzip_after_days`，預設 7 天），長期 JSONL archive 目錄的成長率約為每
100 萬筆/日 **120MB/天**——這是與上面 cache 大小分開的另一筆預算（且 §3.3 提到的長壽 flow 重複匯出會再推高
此數字）；請據此規劃 archive 磁碟容量，並依賴 `archive_retention_days` 修剪來長期控制上限（預設 `0`＝永久
保留、不刪檔）。

### 4.2 調校旋鈕一覽

| 設定 | 預設 | 作用 |
|---|---|---|
| `traffic_poll_interval_seconds` | 600（隨附 `config.json.example` 範本值；裸 pydantic schema 預設是 `3600`，key 完全省略時生效） | 流量輪詢間隔 |
| `traffic_sampling.max_rows_per_batch` | 200000（上限亦為 200000） | 單次 PCE 流量查詢視窗的硬上限；碰頂時自動二分抽乾（見 §2.4），不會無聲丟資料 |
| `siem.destinations[].batch_size` × `siem.dispatch_tick_seconds` | 100 × 5（範本值） | 每個目的地的 SIEM 吞吐上限約束在 100 × (86400s / 5s) ≈ **173 萬筆/天**；若 key 完全省略，裸 pydantic 預設是 `dispatch_tick_seconds=30`（≈ 28.8 萬筆/天）；需要更高吞吐可調大 `batch_size`（上限 10000） |
| `cache_read_max_rows` | 500000 | 每次報表 cache 讀取的列數護欄（防 OOM）；超過時 `CacheReadTooLarge` fallback 走即時 PCE API 並記 WARNING |
| `disk_free_warn_gb` | 10 | 容量監控對磁碟剩餘空間的 WARNING 門檻 |
| `siem_pending_warn_rows` | 50000 | 容量監控對 SIEM 派送積壓的 WARNING 門檻 |
| `archive_retention_days` | 0（＝永久保留） | JSONL archive 修剪視窗；`0` 代表完全不修剪——若維持 0，務必確保 `disk_free_warn_gb` 真的有開啟並被盯著 |

> 即時（非 cache）流量查詢有自己另一道硬上限 `MAX_TRAFFIC_RESULTS = 200000`（`src/api/traffic_query.py`）。
> 碰到此上限同樣會記 WARNING，代表上限之外可能還有更多 flow。

各鍵完整型別／驗證範圍見 [configuration.md](configuration.md) 「pce_cache」節。

### 4.3 7/24 營運注意

- 正式常駐一律只用 **`--monitor-gui`**。systemd unit（`deploy/illumio-ops.service`）啟動指令為
  `--monitor-gui --interval 10`，並配 `Restart=on-failure`。
- **絕不可**用 `--gui`（GUI-only 模式）常駐正式環境：該模式不啟動任何排程，cache 的 ingestion／
  aggregation／retention 都不會自動觸發——cache 只能靠手動 Backfill 填入，也不再被清理。程式碼本身即有
  明確警語（`src/cli/_runtime.py`）：
  > 「GUI-only mode: PCE cache is enabled but no scheduler runs here — automatic
  > ingestion/aggregation/retention will NOT fire (manual Backfill only). Use 'monitor-gui' for live cache
  > ingestion.」
- 修改 `config.json` 中屬於**排程類**的設定（輪詢間隔、archive 開關等）後，需讓 daemon 重新載入才生效：
  呼叫 `POST /api/daemon/restart`，或重啟服務（`sudo systemctl restart illumio-ops`）。此重啟端點僅在 daemon
  由 GUI 行程內管理時可用（即 `--monitor-gui` 模式）；其他情況會回傳 `409`，須改用完整服務重啟。
- 所有會寫 cache DB 的 job 走專用單一 worker 的 `cache_writer` executor（序列化寫入，避免 SQLite 寫鎖互
  撞）；容量監控（`pce_cache_capacity_monitor`）走預設 executor，不佔用 `cache_writer`（見
  [automation.md](automation.md) §3）。
- 日誌 rotation 已內建——每檔 10MB × 10 份輪替，輪替時自動 gzip 壓縮——不需外部 logrotate 設定。

### 4.4 要盯的三個預警數字

一併呈現於 `GET /api/cache/health` 的 `capacity` 欄位（容量監控 job 每 30 分鐘也會記一次 log）；若 snapshot
本身失敗會降級為 `null`，因此 `capacity` 欄位缺席本身就值得追查：

1. **磁碟剩餘空間**——低於 `disk_free_warn_gb`（預設 10GB）時 WARNING。
2. **`siem_pending`**——SIEM 派送佇列中的待處理列數；超過 `siem_pending_warn_rows`（預設 50000）時
   WARNING。
3. **`archiver_lag_seconds`**（分 `traffic`／`audit` 兩來源）——超過 `archive_interval_hours` 的 2 倍（預設
   24 小時 → 48 小時告警），或某來源有資料但從未被封存過時 WARNING。**這是三者中最急迫的一個**：
   `archive_enabled` 開啟時，retention 的刪除步驟只會刪「已封存」的列（見 §3.2）——`archiver_lag_seconds`
   持續上升，代表 DB 正卡在一個停滯的 archiver 後面無上限成長，須立即查 `pce_cache_archive` job（`logs/
   job_health.json` 的 `pce_cache_archive` key）。

## 5. WAL 模式注意事項

`schema.py` 的 `init_schema()` 在每個連線建立時套用一組 PRAGMA：

| PRAGMA | 值 | 目的 |
|---|---|---|
| `journal_mode` | `WAL` | 讀寫並行；DB 檔旁會多出 `-wal`／`-shm` 兩個伴隨檔 |
| `foreign_keys` | `ON` | 外鍵約束 |
| `synchronous` | `NORMAL` | WAL 模式下的效能／耐久性折衷 |
| `busy_timeout` | `30000`（30 秒） | ingestor／aggregator／SIEM dispatcher 都寫同一個 DB，寫鎖衝突時等待而非立即報 `database is locked` |
| `cache_size` | `-65536`（64MB） | 大表掃描的頁快取 |
| `mmap_size` | `268435456`（256MB） | 讀效能，僅 per-connection、離線無影響 |

**備份**：WAL 模式下單獨複製 `pce_cache.sqlite` 可能撕裂（未包含 `-wal` 裡尚未 checkpoint 的變更）。兩種安全
做法：

```bash
# 熱備（服務持續運行）：走 SQLite backup API，會自動處理 WAL
sqlite3 data/pce_cache.sqlite ".backup /backup/pce_cache_$(date +%Y%m%d).sqlite"

# 或停服務後直接複製三個檔（db + -wal + -shm）
sudo systemctl stop illumio-ops
cp data/pce_cache.sqlite data/pce_cache.sqlite-wal data/pce_cache.sqlite-shm /backup/ 2>/dev/null
sudo systemctl start illumio-ops
```

> 直接 `cp` 主 DB 檔而不連 `-wal`／`-shm` 一起複製、或不先停服務／不走 backup API，複製到的檔案可能缺少最
> 近一批尚未 checkpoint 進主檔的寫入。

**無內建 schema 遷移工具**：cache schema 若在版本間變動欄位，沒有自動遷移機制——升級前請看 release notes；
若不相容，刪除 DB 檔（含 `-wal`／`-shm`）後以 backfill 重建（見 §2）。`init_schema()` 本身對「新增欄位／新增
索引／刪除已棄用索引」是冪等且會自動套用（`_ensure_added_columns`／`_ensure_added_indexes`／
`_drop_deprecated_indexes`），但這是同一 schema 版本內的小幅演進，不等於跨版本大改的遷移工具。

## 延伸閱讀

- 各設定鍵完整參照：[configuration.md](configuration.md)
- 背景 job 總表、executor 分工、長間隔 job 首跑錨定：[automation.md](automation.md)
- cache lag／容量監控觸發的告警與 runbook 分類：[monitoring-alerts.md](monitoring-alerts.md)
- SIEM dispatch、DLQ 與轉送健康判讀：[siem.md](siem.md)
- traffic 報表 unknown 值域與 2026-07 查詢預設變更：[reports.md](reports.md)、
  [pce-domain-notes.md](../handover/pce-domain-notes.md)
- job never-ran／overdue、DB 肥大、archive 沒跑等症狀排查：見 [troubleshooting.md](troubleshooting.md)
