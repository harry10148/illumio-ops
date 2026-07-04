# Archive 保存上限（archive_retention_days）Design

**Goal:** 讓 archive 檔可選擇性地在保存 N 天後自動刪除（合規最大保存期 + 磁碟控制），預設 0＝永久保留、不改現況。

## Scope

- **`src/config_models.py`** `PceCacheSettings`：新增 `archive_retention_days: int = Field(default=0, ge=0)`（0＝永久保留；ge=0 允許 0）。
- **`src/pce_cache/archive.py`**：
  - `ArchiveExporter.__init__` 新增 `retention_days: int = 0`，存 `self._retention_days`。
  - 新增 `_purge_old_files()`：`retention_days<=0` 時 no-op；否則刪除「事件日 < 今日(UTC) - retention_days」的 archive 檔。只刪符合 `^(traffic|audit)-YYYY-MM-DD\.jsonl(\.gz)?$` 命名的檔（依**檔名事件日**判斷，非 mtime），不碰目錄其他檔；best-effort，OSError 記 warning。
  - `run_once()` 在 `_gzip_old_files()` 之後呼叫 `_purge_old_files()`。
  - 日期用 `datetime.now(timezone.utc).date()` 與 `date.fromisoformat()`（避免 naive datetime，過 CI 檢查）。
- **`src/scheduler/jobs.py`** `run_cache_archive`：`ArchiveExporter(..., retention_days=cfg.archive_retention_days)`。
- **`src/static/js/integrations.js`**：Archive fieldset 加「保存上限（天，0=永久）」欄位；`cacheSave` payload 加 `archive_retention_days`。
- **i18n**（兩檔同步）：`gui_cache_archive_retention_days` + `_help`。
- **測試**：config default/validation；`_purge_old_files`（預設關閉保留全部、超期刪除、只刪符合命名、.gz 也刪）；scheduler 傳 retention_days；web round-trip。

## 語意與安全

- 預設 0＝永久保留 → 合併不改任何現有行為，不會突然刪掉既有 archive。
- 刪除依檔名事件日（可稽核「保留 N 天事件」），與 gzip 輪替（用 mtime）互不影響。
- 與 cache retention / archive 守門正交：守門管 DB 刪除、此功能管 archive 檔刪除。文件標明 `archive_retention_days` 應遠大於 cache 天數。
- 因會刪除長期保存資料，欄位說明明確寫「0=永久保留」。

## Non-goals

- 不做 archive 檔 checksum/manifest；不做「刪除前搬到二級儲存」；不動 gzip 輪替邏輯。
