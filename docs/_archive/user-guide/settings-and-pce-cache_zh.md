---
title: Settings and PCE Cache
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - src/pce_cache/
  - src/settings/
  - data/pce_cache.sqlite (path)
  - python illumio-ops.py cache --help
  - commit 2437209
related_docs:
  - ../getting-started.md
  - multi-pce.md
  - ../architecture/overview.md
  - troubleshooting.md
---

> **[English](settings-and-pce-cache.md)** | **[繁體中文](settings-and-pce-cache_zh.md)**
> 📍 [INDEX](../INDEX.md) › 使用者指引 › 設定與 PCE 快取
> 🔍 最後驗證日期 **2026-05-15**，對應 commit `2437209` — 詳見 frontmatter 來源清單

# 設定與 PCE 快取

---

## 設定總覽

設定頁面分為四個子頁籤，每個子頁籤各自追蹤未儲存狀態；**儲存**按鈕標籤會動態顯示目前哪個頁籤有待存變更（例如「儲存 PCE 設定」）。支援 URL 深度連結，透過 `stab` 參數可直接開啟指定頁籤，例如 `?stab=security`。

| 子頁籤 | 內容 |
|--------|------|
| **PCE** | PCE 連線 Profile、作用中 PCE 選擇、API 連線設定 |
| **Channels** | 通知頻道外掛（Slack、Email、Webhook 等） |
| **Display** | 介面顯示偏好設定 |
| **Security** | 網頁介面密碼、確認密碼欄位、TLS 設定 |

---

## 密碼與認證資訊

**Security** 子頁籤包含網頁介面密碼區塊。自 commit `2d99dc5` 起，新密碼欄位旁新增了**確認新密碼**欄位，用戶端驗證若偵測到不一致，將以本地化提示訊息警示，並在送出前中止儲存動作。

重點行為：
- 不一致由用戶端攔截，不會發出 API 請求。
- i18n 鍵值已同步涵蓋英文與繁體中文的欄位標籤與錯誤訊息。
- TLS 啟用/停用切換也位於此子頁籤。

---

## PCE 連線設定

**PCE** 子頁籤用於管理一個或多個 PCE Profile，每個 Profile 儲存以下欄位：

| 欄位 | 說明 |
|------|------|
| Profile Name | 顯示名稱 |
| URL | 例如 `https://pce.example.com:8443` |
| Org ID | 預設為 `1` |
| API Key | PCE API 金鑰 ID |
| API Secret | PCE API 密鑰（遮罩顯示） |
| Verify SSL | 核取方塊；僅在開發環境使用自簽憑證時取消勾選 |

可同時設定多個 Profile，並透過**啟用**按鈕切換。作用中的 Profile 顯示綠色勾號。儲存 PCE 子頁籤的任何欄位，將更新目前作用中的 Profile。

多 PCE 環境的 Profile 切換與範圍說明，請參閱 [多 PCE](multi-pce.md)。

---

## 流量採樣設定

流量採樣控制快取擷取器保留多少比例的允許流量，設定位於 `config/config.json` 的 `pce_cache.traffic_sampling` 節，也可在整合頁面（快取區塊）中編輯。

| 欄位 | 預設值 | 說明 |
|------|--------|------|
| `sample_ratio_allowed` | `1`（全部保留）| 每 N 筆允許流量保留 1 筆。`1` = 不採樣；`10` = 保留約 10 %。使用 flow tuple 的確定性 SHA-256 雜湊，確保同一筆流量在重啟後始終被包含或排除。 |
| `max_rows_per_batch` | `200000` | 每次輪詢週期最多抓取的列數上限，防止高流量期間的 API 呼叫失控。 |

> **採樣僅影響允許流量。** 無論 `sample_ratio_allowed` 為何值，封鎖流量與稽核事件永遠全量擷取。

commit `6c3382e` 新增的 CLI 說明文字，在每個提示前以內嵌方式說明確定性雜湊行為與批次大小建議。

---

## PCE 快取簡介

PCE 快取是一個**選用**的本機 SQLite 資料庫，路徑為 `data/pce_cache.sqlite`（由 `config/config.json` 中的 `pce_cache.db_path` 設定，以上為預設值）。`data/` 目錄若不存在，會在首次啟動時自動建立。

快取儲存以下資料的滾動保留視窗：
- **PCE 稽核事件** — 每 `events_poll_interval_seconds`（預設 300 秒）輪詢一次
- **流量流程** — 每 `traffic_poll_interval_seconds`（預設 3600 秒）輪詢一次

快取的消費者：

| 消費者 | 使用方式 |
|--------|----------|
| SIEM 轉發器 | 透過 `CacheSubscriber` 從 `pce_events` / `pce_traffic_flows_raw` 讀取列，推進各消費者的遊標 |
| 報表（Phase 14） | `CacheReader.cover_state()` 判斷 full / partial / miss，避免重複呼叫 PCE API |
| 告警 / 監控（Phase 15） | 以 30 秒節拍訂閱快取 |

快取**預設為停用**（`pce_cache.enabled = false`）。停用時所有程式碼路徑均退回直接呼叫 PCE API。

啟用方式，在 `config/config.json` 新增：

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

擷取器將於下一次以 `--monitor` 或 `--monitor-gui` 啟動時開始運作。依事件量而定，首次輪詢可能需要數分鐘。

---

## 快取更新模式

快取採用**增量式、浮水印驅動**的輪詢機制，不提供手動「完整重新整理」模式。每個來源（`events`、`traffic`）各自有一筆 `IngestionWatermark` 記錄，儲存 `last_timestamp` 與 `last_href`。每次輪詢只抓取比浮水印更新的記錄。

**快取遺漏語意**（`CacheReader.cover_state()`）：

| 狀態 | 意義 | 報表行為 |
|------|------|----------|
| `full` | 請求範圍完全在保留視窗內 | 從快取提供資料，不呼叫 PCE API |
| `partial` | 範圍起點早於保留截止點 | 退回呼叫 PCE API 取得完整範圍 |
| `miss` | 整個範圍早於保留視窗 | 退回呼叫 PCE API |

**隨需回填** — 使用 `illumio-ops cache backfill`（見下節）填充正常輪詢週期以外的歷史資料。

**保留期清除** — 每日 APScheduler 任務呼叫 `RetentionWorker.run_once()` 刪除超過設定 TTL 的資料列。`cache retention --run` 指令可隨時觸發此操作。

**落後監控** — 獨立任務（`cache_lag_monitor`）每 60 秒執行一次，檢查 `ingestion_watermarks.last_sync_at`。若擷取器在 `3 × max(events_poll_interval, traffic_poll_interval)` 秒內未同步，發出 `WARNING`；達到兩倍閾值時發出 `ERROR`。

---

## 快取管理 CLI

`illumio-ops cache` 子指令群提供所有快取管理操作，已針對 commit `2437209` 驗證：

```
illumio-ops cache [OPTIONS] COMMAND [ARGS]...

  PCE cache management — backfill, status, retention.

Commands:
  backfill   Backfill the PCE cache from the API for a historical date range.
  retention  Show configured cache retention policy, or run it.
  status     Show cache row counts and last-sync timestamps.
```

### `illumio-ops cache status`

```bash
illumio-ops cache status
```

顯示各快取資料表（`events`、`traffic_raw`、`traffic_agg`）的資料列數量與最後擷取時間戳。直接讀取 SQLite 資料庫，不需要 daemon 正在執行。

### `illumio-ops cache backfill`

```bash
illumio-ops cache backfill --source events --since 2026-04-01
illumio-ops cache backfill --source traffic --since 2026-04-01 --until 2026-04-30
illumio-ops cache backfill --source events --since 2026-04-01 --json
```

| 選項 | 必填 | 說明 |
|------|------|------|
| `--source` | 是 | `events` 或 `traffic` |
| `--since` | 是 | 開始日期 `YYYY-MM-DD` |
| `--until` | 否 | 結束日期 `YYYY-MM-DD`；預設為今天 |
| `--json` | 否 | 以 JSON 格式輸出結果 |

### `illumio-ops cache retention`

```bash
illumio-ops cache retention          # 僅顯示政策（唯讀）
illumio-ops cache retention --run    # 顯示政策 + 立即執行清除
```

顯示政策時的預設 TTL：

| 設定 | 預設值 |
|------|--------|
| `events_retention_days` | 90 天 |
| `traffic_raw_retention_days` | 7 天 |
| `traffic_agg_retention_days` | 90 天 |

---

## 快取結構概覽

資料庫共有六張資料表，完整欄位定義請見 `src/pce_cache/models.py`。資料庫以 WAL 模式開啟（`PRAGMA journal_mode = WAL`），並啟用外鍵約束（`PRAGMA foreign_keys = ON`）。

| 資料表 | 用途 | 保留期限 |
|--------|------|----------|
| `pce_events` | 稽核事件，含完整 JSON 原文與索引後設資料 | 90 天（依 `ingested_at`） |
| `pce_traffic_flows_raw` | 每筆唯一流程（src+dst+port）一列，7 天滾動視窗 | 7 天（依 `ingested_at`） |
| `pce_traffic_flows_agg` | 原始流程的每日彙總，冪等 UPSERT | 90 天（依 `bucket_day`） |
| `ingestion_watermarks` | 每來源的輪詢遊標（`last_timestamp`、`last_href`、`last_sync_at`） | 永久保留 |
| `siem_dispatch` | SIEM 輸出佇列，已送出列自動老化淘汰 | 自動 |
| `dead_letter` | 超過最大重試次數的失敗 SIEM 傳送 | 30 天（依 `quarantined_at`） |

> **提示：** `ingestion_cursors` 是獨立資料表，供 `CacheSubscriber` 追蹤各消費者在 `pce_events` 與 `pce_traffic_flows_raw` 中的讀取位置，與 `ingestion_watermarks` 相互獨立。

內部資料流詳情請參閱[架構總覽](../architecture/overview.md)。

---

## 備份與遷移

快取資料庫是標準 SQLite 檔案，備份或搬移至其他主機的步驟如下：

**本機備份：**

```bash
# 使用 SQLite backup API 進行安全熱備份
sqlite3 data/pce_cache.sqlite ".backup data/pce_cache_backup.sqlite"
```

**複製至其他主機：**

```bash
# 先停止 daemon 避免 WAL 不完整
systemctl stop illumio-ops   # 或您使用的 process manager
cp data/pce_cache.sqlite /mnt/backup/pce_cache_$(date +%Y%m%d).sqlite
systemctl start illumio-ops
```

**搬移至新主機：**

1. 將 `data/pce_cache.sqlite` 複製至新主機。
2. 若路徑不同，更新 `config/config.json` 中的 `pce_cache.db_path`。
3. 應用程式啟動時會呼叫 `init_schema()`，此操作為冪等 — 只建立缺少的資料表，不會刪除現有資料。

**變更資料庫路徑：**

```json
"pce_cache": {
  "db_path": "/opt/illumio-ops/cache/pce_cache.sqlite"
}
```

上層目錄會自動建立（`os.makedirs(..., exist_ok=True)`）。

> **注意：** 目前沒有內建的 Schema 升級遷移工具。若版本更新改變了資料表結構，需刪除舊資料庫並透過回填重新填充。升級前請務必查閱版本說明。

---

## 相關文件

- [快速開始](../getting-started.md) — 初始設定流程
- [多 PCE](multi-pce.md) — 各 PCE 的設定範圍
- [架構總覽](../architecture/overview.md) — 內部資料模型（B2）
- [疑難排解](troubleshooting.md) — 快取損毀 / 過期資料
