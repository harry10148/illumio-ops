# PCE 快取

<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](../README.md) | [README_zh.md](../README_zh.md) |
| Installation | [Installation.md](./Installation.md) | [Installation_zh.md](./Installation_zh.md) |
| User Manual | [User_Manual.md](./User_Manual.md) | [User_Manual_zh.md](./User_Manual_zh.md) |
| Report Modules | [Report_Modules.md](./Report_Modules.md) | [Report_Modules_zh.md](./Report_Modules_zh.md) |
| Security Rules | [Security_Rules_Reference.md](./Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](./Security_Rules_Reference_zh.md) |
| SIEM Integration | [SIEM_Integration.md](./SIEM_Integration.md) | [SIEM_Integration_zh.md](./SIEM_Integration_zh.md) |
| Architecture | [Architecture.md](./Architecture.md) | [Architecture_zh.md](./Architecture_zh.md) |
| PCE Cache | [PCE_Cache.md](./PCE_Cache.md) | [PCE_Cache_zh.md](./PCE_Cache_zh.md) |
| API Cookbook | [API_Cookbook.md](./API_Cookbook.md) | [API_Cookbook_zh.md](./API_Cookbook_zh.md) |
<!-- END:doc-map -->

> **[English](PCE_Cache.md)** | **[繁體中文](PCE_Cache_zh.md)**

---

## What It Is

PCE 快取是一個選用的本機 SQLite 資料庫，儲存 PCE 稽核事件和流量記錄的滾動窗口。它作為以下子系統之間的共享緩衝區：

- **SIEM 轉發器** —— 從快取讀取以將事件轉發至機外
- **報表**（Phase 14）—— 從快取讀取以避免重複 PCE API 呼叫
- **告警/監控**（Phase 15）—— 訂閱快取以實現 30 秒週期

## Why Use It

沒有快取時，每次報表產生和監控週期都會直接呼叫 PCE API。PCE 實施 500 req/min 速率限制。有了快取：

- Ingestor 使用共享的令牌桶速率限制器（預設 400/min）
- 報表和告警從 SQLite 讀取（快取範圍內零 PCE API 呼叫）
- 流量取樣器減少 `allowed` 流量量（預設：保留全部；設定 `sample_ratio_allowed=10` 為 1/10 取樣）

## Enabling

新增至 `config/config.json`：

```json
"pce_cache": {
  "enabled": true,
  "db_path": "data/pce_cache.sqlite",
  "events_retention_days": 90,
  "traffic_raw_retention_days": 7,
  "traffic_agg_retention_days": 90,
  "events_poll_interval_seconds": 300,
  "traffic_poll_interval_seconds": 3600,
  "rate_limit_per_minute": 400
}
```

快取在下次 `--monitor` 或 `--monitor-gui` 啟動時開始。根據事件量，首次輪詢可能需要幾分鐘。

## Table Reference

| 表格 | 保留欄位 | 預設 TTL | 備注 |
|---|---|---|---|
| `pce_events` | `ingested_at` | 90 天 | 完整事件 JSON + type/severity/timestamp 索引 |
| `pce_traffic_flows_raw` | `ingested_at` | 7 天 | 每個唯一 src+dst+port+first_detected 的原始流量 |
| `pce_traffic_flows_agg` | `bucket_day` | 90 天 | 每日彙總；冪等 UPSERT |
| `ingestion_watermarks` | — | 永久 | 每來源游標；重啟後存續 |
| `siem_dispatch` | — | — | SIEM 出站佇列；已傳送資料列自動老化 |
| `dead_letter` | `quarantined_at` | 30 天（透過清除） | 達到最大重試次數後的 SIEM 傳送失敗記錄 |

## Disk Sizing

粗略估計（gzip 壓縮 JSON）：
- 1,000 事件/天 × 90 天 × ~1 KB/事件 ≈ **90 MB** 用於 `pce_events`
- 50,000 流量/天 × 7 天 × ~0.5 KB/流量 ≈ **175 MB** 用於原始流量
- 彙總流量小得多；典型每年約 ~5 MB

若出現磁碟壓力，先調整 `traffic_raw_retention_days`。

## Retention Tuning

保留工作程序每日執行，清除超過設定 TTL 的資料列。查看當前保留策略：

```bash
illumio-ops cache retention
```

保留工作程序作為 APScheduler 任務自動執行；沒有 `--run-now` 旗標。若要強制手動清除，重啟 daemon —— 保留任務在啟動時觸發。

## Monitoring

搜尋 loguru 輸出以尋找：
- `Events ingest: N rows inserted` —— 健康的擷取
- `Traffic ingest: N rows inserted` —— 健康的擷取
- `Cache retention purged:` —— 每日清理已執行
- `Global rate limiter timeout` —— PCE 配額耗盡；降低 `rate_limit_per_minute`

## Troubleshooting

| 症狀 | 可能原因 | 修正 |
|---|---|---|
| 日誌中出現 `429` 錯誤 | PCE 速率限制命中 | 將 `rate_limit_per_minute` 降至 200–300 |
| DB 增長過快 | `traffic_raw_retention_days` 過高 | 降至 3–5 天 |
| Watermark 未推進 | Events ingest 錯誤 | 在日誌中檢查 `Events ingest failed` |
| 快取 DB 鎖定 | 多個行程 | 確保只有一個 `--monitor` 在執行 |

## 快取未命中語意

當報表產生器請求某個時間範圍的資料時，`CacheReader.cover_state()` 回傳三種狀態之一：

- **`full`** —— 整個範圍都在設定的保留窗口內；資料從快取提供，不呼叫 API。
- **`partial`** —— 範圍起始早於保留截止點，但結束在窗口內；產生器退回至使用 API 取得整個範圍。
- **`miss`** —— 整個範圍早於保留窗口；產生器退回至 API。

### Backfill

若要為歷史範圍填充快取，請使用 CLI：

```bash
illumio-ops cache backfill --source events --since 2026-01-01 --until 2026-03-01
illumio-ops cache backfill --source traffic --since 2026-01-01 --until 2026-03-01
```

Backfill 直接寫入 `pce_events` / `pce_traffic_flows_raw`，繞過正常的 ingestor watermark。若回填資料超出設定的保留窗口，保留工作程序在下次執行時將其清除。

檢查快取狀態和保留策略：

```bash
illumio-ops cache status
illumio-ops cache retention
```

### Data source indicator

產生的 HTML 報表在報表標頭中顯示彩色標籤，指示資料來源：
- **綠色** —— 資料從本機快取提供
- **藍色** —— 資料從即時 PCE API 擷取
- **黃色** —— 混合（部分快取 + API）

## 操作命令

`illumio-ops cache` 子命令群組（實作於 `src/cli/cache.py`）提供所有快取管理操作。

### `illumio-ops cache status`

```
illumio-ops cache status
```

顯示每個快取表（`events`、`traffic_raw`、`traffic_agg`）的資料列計數及最後擷取時間戳記的表格。直接從 SQLite DB 讀取；不需要 daemon 在執行中。

### `illumio-ops cache retention`

```
illumio-ops cache retention
```

以表格顯示已設定的保留策略，列出 TTL 值：

| 設定 | 預設值 |
|---|---|
| `events_retention_days` | 90 |
| `traffic_raw_retention_days` | 7 |
| `traffic_agg_retention_days` | 90 |

### `illumio-ops cache backfill`

```
illumio-ops cache backfill --source events --since YYYY-MM-DD [--until YYYY-MM-DD]
illumio-ops cache backfill --source traffic --since YYYY-MM-DD [--until YYYY-MM-DD]
```

透過從 PCE API 擷取，為歷史日期範圍填充快取。直接寫入 `pce_events` / `pce_traffic_flows_raw`，繞過正常的 ingestor watermark。完成時，印出插入的資料列數、跳過的重複數及耗用時間。若回填資料超出設定的保留窗口，保留工作程序在下次執行時將其清除。

---

## Alerts on Cache

當 `pce_cache.enabled = true` 時，Analyzer 透過 `CacheSubscriber` 訂閱 PCE 快取，而非直接查詢 PCE API。這樣可實現：

- **30 秒告警延遲** —— 快取啟用時，監控週期從 `interval_minutes`（預設 10 分鐘）降至 30 秒。
- **不佔用 API 配額** —— 每次週期僅讀取本機 SQLite；PCE API 呼叫只透過 ingestor 依其自身排程進行。

### How it works

```
PCE API  →  Ingestor  →  pce_cache.db
                              ↓
                        CacheSubscriber
                              ↓
                          Analyzer  →  Reporter  →  Alerts
```

每個消費者（analyzer）在 `ingestion_cursors` 表中持有獨立游標。每 30 秒週期，Analyzer 僅讀取自上次游標位置以來插入的資料列。

### Cache lag monitoring

獨立的 APScheduler 任務（`cache_lag_monitor`）每 60 秒執行一次，並檢查 `ingestion_watermarks.last_sync_at`。若 ingestor 在 `3 × max(events_poll_interval, traffic_poll_interval)` 秒內未同步，則發出 `WARNING` 日誌。若延遲超過該閾值的兩倍，則發出 `ERROR`。這可在告警靜默漂移之前捕捉 ingestor 停頓。

### Fallback

當 `pce_cache.enabled = false`（預設）時，每個程式碼路徑都恢復至原始 PCE API 行為。現有部署無需任何設定變更。

---

## 延伸閱讀

- [Architecture](./Architecture.md) — 系統架構與模組深入剖析
- [User Manual](./User_Manual.md) — `cache` CLI 子命令操作說明
- [README](../README.md) — 專案入口與快速開始
