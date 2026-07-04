# Archive 查閱（Phase 1：流量）Design / Spec

**Goal:** 讓已匯出的 archive traffic JSONL 能載回，用現有「流量與 Workloads」分析 UI 查閱 —— 特別是 live cache 已依 retention 刪除（預設 7 天）後，archive 是唯一的資料來源。

**Phase:** 1（流量 only）。事件檢視另立 Phase 2。

## 核心設計

底層 `CacheReader`（`src/pce_cache/reader.py`）是注入 `session_factory` 的設計，且 archive traffic 的 `raw` 欄位就是原始 PCE flow dict（等同 `raw_json` 還原）。因此把 archive 灌進「同 schema 的獨立 SQLite（review DB）」後，現有 `Analyzer.query_flows → CacheReader.read_flows_raw` 分析路徑**原樣重用、reader 不改**。使用者在「流量與 Workloads」面板用「即時快取 / Archive」來源切換查閱。

## 元件與介面

### 1. `ArchiveImporter`（新增 `src/pce_cache/archive_import.py`）
- `ArchiveImporter(archive_dir: str, session_factory)`：session_factory 指向 review DB。
- `import_range(start_date: date, end_date: date) -> dict`：讀 `traffic-YYYY-MM-DD.jsonl[.gz]`（檔名日期落在 [start,end]）逐行還原成 `PceTrafficFlowRaw`：
  - 直接欄位對映：flow_hash, src_ip, src_workload, dst_ip, dst_workload, port, protocol, action, flow_count, bytes_in, bytes_out。
  - `last_detected` = 解析 `event_time`（ISO → aware datetime，`datetime.fromisoformat`）。`ingested_at` = 解析 `ingested_at`。
  - `raw_json` = `orjson.dumps(record["raw"]).decode()`（record["raw"] 為 None 時跳過該列並計數）。
  - `first_detected`：從 `raw` 回推（重用 `src/pce_cache/ingestor_traffic.py` 的 `_ts(flow, "first_detected")` 邏輯；缺則 = last_detected）。
  - `report_json`：`orjson.dumps(flatten_flow_record(raw)).decode()`（重用 `src/report/parsers/api_parser.py:flatten_flow_record`），避免部分索引 `ix_raw_report_json_null` 失效。
  - 逐列 insert，`IntegrityError`（flow_hash unique）→ rollback 該列跳過（仿 `src/pce_cache/backfill.py` `_insert_traffic`）。
  - 回傳 `{"rows": int, "files": int, "skipped": int, "start": iso, "end": iso}`。
- 匯入後由呼叫端（route）跑一次 `TrafficAggregator(session_factory).run_once()` 補 `pce_traffic_flows_agg`（趨勢圖/KPI 用）。

### 2. Review DB 管理
- 路徑：cache `db_path` 同目錄下 `archive_review.sqlite`（helper 由 `cfg.db_path` 推導）。
- 每次載入 **drop + 重建**：刪檔（或 drop_all）後 `init_schema(engine)`。
- **引擎生命週期（關鍵）**：review DB 會被重建，**不得使用 `_get_cache_engine` 的 process 快取引擎**（會持有指向舊檔的連線）。載入與查詢時各自 `create_engine` + 用完 `dispose()`，或維護一個可在重載時 dispose/invalidate 的專用引擎。載入（寫）與查詢（讀）都用「即時建立、用完 dispose」的短命引擎最單純。

### 3. 後端 route（`src/pce_cache/web.py`，cache blueprint，url_prefix `/api/cache`）
- `POST /api/cache/archive/load`，body `{start_date, end_date}`（`YYYY-MM-DD`）：
  - 驗證：日期格式、start<=end、`(end-start).days+1 <= cfg.archive_review_max_days` 否則 422。
  - 重建 review DB → `ArchiveImporter(archive_dir, sf).import_range(...)` → `TrafficAggregator(sf).run_once()` → 回 `{ok, rows, files, skipped, start, end}`。
  - `login_required`。
- `GET /api/cache/archive/status`：回目前 review DB 狀態 `{loaded: bool, rows, start, end, loaded_at}`（無則 loaded=false）。狀態存 review sqlite 旁的 sidecar `archive_review.meta.json`（載入成功時寫入請求範圍 + 筆數 + loaded_at；重建時覆寫；檔不存在 → loaded=false）。不塞進既有 ORM 表，語意最乾淨。
- 既有 `api_quarantine_search`（`src/gui/routes/actions.py`）與 `api_traffic_trend`（同檔）加 `source` 參數（`"live"` 預設 / `"archive"`）：
  - `source=="archive"` → 用 review db_path 建 reader/engine（見下 `_make_cache_reader` 改動），查 review DB；否則維持現況查 `cm.models.pce_cache.db_path`。

### 4. `_make_cache_reader` 參數化（`src/main.py`）
- `_make_cache_reader(cm, db_path: str | None = None)`：`db_path` 預設 `cm.models.pce_cache.db_path`；archive 分支傳 review db_path。**這是唯一為換源所需的參數化改動；`CacheReader` 不改。**

### 5. 前端（`src/static/js/`：流量面板 `q-panel-traffic`；`quarantine.js` / `dashboard.js` / `index.html`）
- 在流量查詢面板加：
  - 「資料來源」切換：即時快取 / Archive。
  - Archive 日期範圍（start/end）+「載入 archive」按鈕 → `POST /api/cache/archive/load`，顯示筆數/範圍或錯誤。
  - 「目前載入：<範圍>（N 筆）」狀態（`GET /api/cache/archive/status`）。
  - `runTrafficAnalyzer()`（`quarantine.js`）與趨勢圖請求：來源=Archive 時 payload 帶 `source=archive`。

### 6. config（`src/config_models.py` `PceCacheSettings`）
- `archive_review_max_days: int = Field(default=31, ge=1)`。

### 7. i18n（`src/i18n_en.json` / `src/i18n_zh_TW.json` 同步）
- 來源切換、日期範圍、載入鈕、狀態、錯誤訊息的 key。

## 資料流

使用者選 Archive + 日期範圍 → `POST /load` → 重建 review DB → 逐行讀 JSONL → 補 first_detected/report_json → insert（去重）→ 跑 aggregator → 回筆數。之後在同一面板查詢（`source=archive`）→ route 用 review db 建 `CacheReader` → `query_flows`/`read_flows_raw` 原樣分析 → 結果回面板。

## 測試

- `ArchiveImporter`：sample archive dir（含 .jsonl 與 .gz）→ import_range → review DB 有正確列數、`raw` 保真、`first_detected` 非空、`report_json` 已填、範圍外檔案不匯入、`raw` 為 null 的列被 skip 計數；跨日同 flow_hash 去重。
- aggregator：匯入後 agg 表有列。
- route：`/load` 回筆數；範圍超上限 422；`/status` 反映載入範圍；`api_quarantine_search` 帶 `source=archive` 查到 review 資料、不帶則查 live（互不污染）。
- `_make_cache_reader(cm, db_path=...)` 指向指定 DB。
- config default/validation for `archive_review_max_days`。
- i18n parity。

## 檔案結構

- **Create** `src/pce_cache/archive_import.py` — `ArchiveImporter` + review DB helper。
- **Create** `tests/test_pce_cache_archive_import.py`。
- **Modify** `src/config_models.py` — `archive_review_max_days`。
- **Modify** `src/main.py` — `_make_cache_reader(cm, db_path=None)`。
- **Modify** `src/pce_cache/web.py` — `/archive/load`、`/archive/status`。
- **Modify** `src/gui/routes/actions.py` — `api_quarantine_search` / `api_traffic_trend` 加 `source` 分支。
- **Modify** `src/static/js/quarantine.js`、`src/static/js/dashboard.js`、`src/templates/index.html` — 來源切換 + 載入控制 + 狀態。
- **Modify** `src/i18n_en.json`、`src/i18n_zh_TW.json`。
- **Modify** 對應測試檔（web/actions/config/i18n）。

## Non-goals（Phase 1）

- 事件檢視 archive（Phase 2；event viewer 目前 100% 直連 PCE API、未接 cache）。
- audit archive 匯入。
- 多使用者同時載入的併發保護（單一 review DB，後載覆蓋前載）。
- Dashboard Overview 的 Top10 archive 來源（只做流量面板 + 其趨勢圖）。
- 背景載入（Phase 1 同步 + 範圍上限；日後可升級）。

## 全域約束

- 註解／commit 繁中規範適用對話；commit 用英文 conventional-commits（repo 慣例）。
- datetime 一律 aware（過 `scripts/check_no_naive_datetime.py`）。
- 序列化用 orjson。測試只用 tmp_path，不碰真實 PCE/data。
