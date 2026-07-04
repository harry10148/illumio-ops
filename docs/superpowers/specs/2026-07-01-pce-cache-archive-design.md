# PCE Cache 長期 Archive 保存 — 設計

- 日期：2026-07-01
- 狀態：已與使用者確認方向，待 spec review
- 範疇：`src/pce_cache/` 新增匯出器 + retention 守門 + 排程 + 設定

## 1. 背景與動機

客戶受法規要求，需**長期保存 traffic 與 audit log**。現行 `pce_cache` 的 retention 機制（`src/pce_cache/retention.py`）是**到期直接刪除**：

- `pce_traffic_flows_raw` 保留 7 天（`traffic_raw_retention_days`）
- `pce_events` 保留 90 天（`events_retention_days`）

因此到期資料會永久消失，無法滿足法規長期保存。需要在資料被刪除前，把它匯出成**長期、純文字可檢視**的檔案。

## 2. 已確認的需求決策

| 面向 | 決策 |
|---|---|
| 格式 | **JSONL**（每行一筆完整 JSON，內嵌原始 `raw_json`，保真、可 `grep`/`less`、欄位演進不破壞舊檔） |
| 範圍 | **`pce_traffic_flows_raw`（traffic）+ `pce_events`（audit）**；不含 agg |
| 與 retention 協調 | **archive 守門刪除**：保留線上 7/90 天查詢窗口，retention 只刪「已確認 archive 過」的資料；archive 落後則少刪並告警 |
| 頻率 | **每日一次**（可 config） |
| 壓縮 | **近 N 天（預設 7）不壓縮；更舊自動 gzip**（`zcat`/`zgrep` 仍純文字可讀） |
| 目錄 | **config 可設定路徑**，預設 `data/archive/`（可指向獨立/掛載儲存） |
| 分檔依據 | **事件時間**（traffic 用 `last_detected`、audit 用 `timestamp` 的日期），法規檢索最直覺 |
| 預設啟用 | **`archive_enabled=False`**，明確開啟才運作；關閉時既有行為完全不變 |

## 3. 架構與資料流

```
PCE ──ingest──> pce_cache.sqlite (traffic_raw 7d / events 90d 線上窗口)
                     │
        ┌────────────┼───────────────┐
   analyzer      ArchiveExporter    RetentionWorker
   consumer=      consumer=          守門：只刪
   "analyzer"     "archiver"         archiver cursor 已覆蓋的資料
                     │
                     ▼
        {archive_dir}/traffic-YYYY-MM-DD.jsonl(.gz)
        {archive_dir}/audit-YYYY-MM-DD.jsonl(.gz)   ← 長期、純文字
```

核心原則：archive 用**獨立 cursor** 增量匯出；retention 刪除受 archive cursor **硬守門**。兩者透過既有 `ingestion_cursors` 表解耦，互不阻塞，但保證「未 archive 不刪」。

沿用既有模式，不新增基礎設施：
- 增量讀取用既有 `CacheSubscriber`（`src/pce_cache/subscriber.py`），analyzer 已以 `consumer="analyzer"` 使用（`src/main.py:37-38`）。archive 用 `consumer="archiver"`。
- cursor 儲存於既有 `ingestion_cursors` 表（`IngestionCursor`，其 docstring 已預留 exporter 用途）。

## 4. 新元件 `ArchiveExporter`（`src/pce_cache/archive.py`）

職責：把 cache 中「archiver cursor 之後的新列」增量匯出成 JSONL。

介面草案：

```python
class ArchiveResult:
    source: str
    rows: int
    files_written: list[str]

class ArchiveExporter:
    def __init__(self, session_factory, archive_dir: str, gzip_after_days: int = 7): ...
    def run_once(self) -> dict[str, ArchiveResult]:
        # 對 traffic、audit 兩個來源各跑一次 _export_source
        ...
    def _export_source(self, source_table, event_time_col, subscriber) -> ArchiveResult: ...
    def _gzip_old_files(self) -> None: ...
```

流程（每個 source）：
1. 用 `CacheSubscriber(sf, consumer="archiver", source_table=source_table)` 取得上次 cursor（`last_ingested_at` / `last_row_id`）。
2. 讀取 cursor 之後、依 `ingested_at`/`id` 排序的新列（分批，避免一次載入過多）。
3. 每列序列化為一行 JSON：攤平常用欄位（ts、workload、port、protocol、action、bytes…）+ 內嵌完整 `raw`（原始 `raw_json` 解析後物件）。
4. 依**事件時間**（traffic=`last_detected`、audit=`timestamp`）決定目標檔 `{source}-YYYY-MM-DD.jsonl`，append 寫入；一批可落在多個日期檔。
5. `flush + fsync` 成功後，才透過 subscriber 推進 cursor。
6. 全部來源完成後，`_gzip_old_files()` 把「修改時間超過 `gzip_after_days` 且尚未 gzip」的 `.jsonl` 壓成 `.jsonl.gz`（寫 `.gz` 成功後才刪原檔）。

保證：cursor-based → 至少一次、不遺漏；崩潰重跑從 cursor 續傳；先寫檔後推進 cursor → 不會「cursor 前進但檔沒寫成」。同一 `flow_hash`/`pce_href` 已由 ingest 端去重，archive 不重複匯出既有列。

## 5. Retention 守門整合（`src/pce_cache/retention.py`）

改動 `pce_traffic_flows_raw`、`pce_events` 兩段刪除邏輯：

1. 刪除前，讀 `archiver` cursor 的 `last_ingested_at`（該來源）。
2. 實際刪除界線 `effective_cutoff = min(時間policy cutoff, archiver_cursor_ingested_at)`——**只刪「到期且已 archive」的列**。
3. 若 `archiver_cursor < 時間policy cutoff`（archive 沒跟上），少刪的部分保留在 DB，並記一筆 warning（接既有 alert 管道），供維運介入。
4. 僅在 `archive_enabled=True` 時套用守門；關閉時 retention 行為與現況完全相同。
5. 其他表（agg / siem_dispatch / dlq）不受守門影響。

## 6. 設定（`src/config_models.py` `PceCacheSettings` 新增）

```python
archive_enabled: bool = False
archive_dir: str = "data/archive"
archive_interval_hours: int = Field(default=24, ge=1)
archive_gzip_after_days: int = Field(default=7, ge=1)
```

## 7. 排程（`src/scheduler/__init__.py` + `src/scheduler/jobs.py`）

- `jobs.py` 新增 `run_cache_archive(cm)`：建 engine（沿用 `_get_cache_engine`）、跑 `ArchiveExporter.run_once()`、log 各來源匯出行數；例外以 `logger.exception` 收斂（不 crash 排程）。
- `scheduler/__init__.py` 在 cache 區塊、`archive_enabled=True` 時 `sched.add_job(run_cache_archive, _IT(hours=archive_interval_hours), ...)`。
- 排在 retention job 之前（例：archive 03:00 / retention 03:30）；即便順序偶爾錯開，守門邏輯仍是硬保證，不依賴排程先後。

## 8. 錯誤處理與法規完整性

- 匯出以 cursor 為準，天然「至少一次、不遺漏」；崩潰重跑續傳。
- append + fsync 後才推進 cursor。
- gzip「寫 .gz 成功後才刪 .jsonl」，壓縮中斷不丟資料。
- 每次 log 匯出行數與檔名，供稽核。
- 守門確保「未 archive 的資料永不被 retention 刪」。

## 9. 測試策略（TDD）

- 單元（temp sqlite + temp 目錄，不碰真 PCE）：
  - cursor 增量正確：只匯出新列、cursor 正確前進、重跑續傳不重複。
  - 跨日分檔：同批資料依事件時間落到正確日期檔。
  - JSONL 保真：原始 `raw_json` 完整內嵌、可解析。
  - gzip 輪替：超過門檻的舊檔被壓縮、`.gz` 內容可解回原文。
- 整合：
  - archive→retention 守門：archive 落後時 retention 不刪該部分；archive 追上後才刪。
  - `archive_enabled=False` 時，retention 與排程行為與現況一致（回歸保護）。

## 10. 影響範圍

- 新增：`src/pce_cache/archive.py` 及其測試。
- 修改：`src/scheduler/jobs.py`（`run_cache_archive`）、`src/scheduler/__init__.py`（註冊）、`src/pce_cache/retention.py`（守門）、`src/config_models.py`（設定欄位）。
- 相容性：所有改動在 `archive_enabled=False` 時為 no-op，既有部署零行為變更。

## 11. 明確不做（YAGNI）

- 不做 agg 表 archive、不做 checksum/manifest 防竄改層（若日後法規要求再加）、不做 archive 檔自身的清理（長期保存由外部備份/儲存policy負責）。
