# PCE Cache Archive UI 開關 Design

**Goal:** 在 Web UI「整合 → 快取」設定表單暴露 archive 的 4 個 config 欄位，讓使用者不必手改設定檔即可開關與設定長期 archive。

**Background:** 後端 archive 功能（ArchiveExporter、retention 守門、排程 job、config 欄位）已於 feat/pce-cache-archive 完成並在 main。`GET/PUT /api/cache/settings`（`src/pce_cache/web.py:250-269`）已透過 `model_dump`/`save_section` 連 `archive_*` 四欄一起 round-trip；缺的只是前端沒渲染這四欄。

## Scope

**純前端 + i18n + 測試，後端零改動。**

- **`src/static/js/integrations.js`**
  - `buildCacheForm(s)`：在 Retention fieldset 之後、Polling 之前，新增 `Archive` fieldset：
    - `archive_enabled` — checkbox（沿用同表單既有 `enabled` checkbox 寫法）
    - `archive_dir` — 文字輸入（`escapeAttr`）
    - `archive_interval_hours` — number，min=1
    - `archive_gzip_after_days` — number，min=1
  - `cacheSave()`：payload 加入 `archive_enabled`(checkbox.checked)、`archive_dir`、`archive_interval_hours`(Number)、`archive_gzip_after_days`(Number)。PUT 走既有 `/api/cache/settings`，成功沿用 `showRestartBanner`。
- **`src/i18n_en.json` 與 `src/i18n_zh_TW.json`**：同步新增（依字母序，兩檔都要非空值，否則 CI parity 測試擋）：
  - `gui_cache_sec_archive`
  - `gui_cache_archive_enabled`
  - `gui_cache_archive_dir` + `gui_cache_archive_dir_help`
  - `gui_cache_archive_interval_hours` + `gui_cache_archive_interval_hours_help`
  - `gui_cache_archive_gzip_after_days` + `gui_cache_archive_gzip_after_days_help`
- **`tests/test_cache_web.py`**：`test_put_cache_settings_happy` payload 補 4 欄；新增 `test_put_cache_archive_roundtrip`（PUT 後 GET 讀回四欄值）與 `test_put_cache_archive_invalid`（`archive_interval_hours=0` → 422）。

## Non-goals (YAGNI)

- 不加 archive 狀態卡/狀態 API（使用者要的是開關；目前也無 archive 狀態端點）。
- 不動後端 route / config model。
- config model 的 default/validation 測試已存在（`tests/test_config_pce_cache_archive.py`），不重複。

## Verification

- `tests/test_cache_web.py`、`tests/test_i18n_quality.py` 綠。
- 前端無 JS 單元測試框架 → archive 欄位渲染/送出由後端 round-trip 測試間接保證，最終在測試機 UI 目視驗收。

## Notes

- 存檔會觸發 `requires_restart`（排程 archive job 需重啟才註冊），與現有 cache 設定行為一致。
