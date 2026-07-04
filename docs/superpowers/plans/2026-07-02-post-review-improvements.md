# 全專案 Code Review 後改進計劃（2026-07-02）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依 2026-07-02 全專案 code review（核心模組 / pce_cache / web 安全 / scheduler-SIEM / 套件）的 findings，分五個 Phase 收斂：先修影響現行功能的正確性 bug，再補 archive review 的運行時韌性，然後處理熱路徑資源、安全里程碑與套件衛生。

**基準：** main @ b537ed3。另一 session 已修掉的項目（不在本計劃內）：非字串日期回 400（2e45b7b）、archive 時間戳整秒化保 cover_state（b537ed3）、新 UI 採 data-action dispatch（91b7802）、import 端從 raw 回推 first_detected。

## Global Constraints

- 註解一律繁體中文、無 emoji；commit message 用英文 conventional-commits。
- datetime 一律 timezone-aware（過 `scripts/check_no_naive_datetime.py`）。
- 序列化一律用 orjson；測試新檔一律用 `tmp_path`（既有測試檔若整檔慣例為 tempfile.TemporaryDirectory，跟隨既有慣例——2026-07-02 batch-2 final review triage 決定）。
- Surgical：每個 task 一個 commit，只動該 task 相關的行。
- 每個 bug fix 先寫 RED 測試重現，再修（TDD）。

---

## Phase A — 正確性 bug（現行功能已受影響，最優先）

### Task A1: rule_scheduler one_time 時區比較 TypeError（Critical）

**Files:** `src/rule_scheduler.py`、`tests/test_rule_scheduler*.py`

- [ ] RED：engine 測試——one_time entry + timezone `'local'`（預設），驗證 `ScheduleEngine.check` 目前丟 TypeError 被 per-item except 吞掉、規則永不 enable 也永不過期
- [ ] 修 `rule_scheduler.py:265` 附近：比較前正規化 aware/naive（比照 `report_scheduler.py:133-139` 已修過的同型 bug 與 `compute_next_trigger` 的 strip）
- [ ] 驗證：新測試綠、既有 rule_scheduler 測試全綠

### Task A2: cryptography dev/runtime pin 無交集

**Files:** `requirements-dev.txt`

- [ ] 刪除 dev 檔的 `cryptography>=42.0,<46.0`（runtime 的 `>=46.0.7,<48.0` 已涵蓋測試所需自簽憑證功能）
- [ ] 驗證：`pip install -r requirements.txt -r requirements-dev.txt --dry-run` 可解析

### Task A3: aggregator/reader bucket_day 字串格式不一致（午夜 start 漏讀當日 bucket）

**Files:** `src/pce_cache/aggregator.py`、`src/pce_cache/reader.py`、對應測試

- [ ] RED：寫入一筆當日 flow → aggregate → `read_flows_agg(start=當日午夜)` 應回 1 列（目前回 0：`"…00:00:00" < "…00:00:00.000000"` TEXT 比較）
- [ ] 統一格式：`aggregator.py:30` 的 `day_col` 改輸出與 SQLAlchemy bind 相同的 `%Y-%m-%d 00:00:00.000000`（或 reader 端正規化，擇一，以 aggregator 端為佳）
- [ ] 一次性遷移：schema 升級路徑對既有 agg 列 UPDATE 正規化（live cache 與 review DB 都要）
- [ ] 驗證：GUI trend（live/archive 兩種 source）、報表窗口測試全綠

### Task A4: 統一時區處理（report_scheduler cron IANA 偏移 + reporter._resolve_tz）

**Files:** 新 `src/tz_utils.py`（或既有 utils）、`src/report_scheduler.py`、`src/reporter.py`、`src/rule_scheduler.py`、測試

- [ ] RED：cron `0 9 * * *` + `Asia/Taipei` 應在台北 09:00 觸發（目前 09:00 UTC）；`_resolve_tz("Asia/Taipei")` 應回 ZoneInfo（目前靜默退 UTC）
- [ ] 抽統一 util：內部一律 aware UTC，支援 `local`/`UTC±N`/IANA 名稱，只在顯示與比對邊界轉換
- [ ] 三處呼叫端（report_scheduler、rule_scheduler、reporter）改走 util，移除三套半相容邏輯
- [ ] 驗證：freezegun 測 cron 觸發時刻、既有排程測試全綠

---

## Phase B — archive review 運行時韌性（功能已接上 GUI，儘速）

### Task B1: ArchiveImporter 批次寫入（逐列 transaction → chunked upsert）

**Files:** `src/pce_cache/archive_import.py`、`tests/test_pce_cache_archive_import.py`

- [ ] 仿 `ingestor_events._insert_batch`：500 列/批 `sqlite_insert(...).on_conflict_do_nothing(index_elements=["flow_hash"])`，去重不再靠 IntegrityError；`skipped` 由 rowcount 差額推得
- [ ] 驗證：既有 fidelity/去重測試不變、加一筆「同 flow_hash 跨檔案只留一筆」測試；手動以 1 萬列 archive 對比載入耗時

### Task B2: load 併發防護 + 原子重建 + meta 一致性

**Files:** `src/pce_cache/archive_import.py`、`src/pce_cache/web.py`、測試

- [ ] module-level `threading.Lock` 包住 `load_archive_review`；重入時 web 回 409（i18n key 同步兩語系）
- [ ] 重建改 build-to-temp：灌到 `archive_review.sqlite.tmp` → 成功後 `os.replace` 原子切換（查詢端 NullPool per-query 開連線，切換後自然讀到新檔）
- [ ] meta 寫入改 temp + `os.replace`；失敗路徑不留「meta 說 A、DB 是半個 B」的狀態
- [ ] `review_status` 對損壞 meta 接 `orjson.JSONDecodeError` 回 `{"loaded": False}`；route 補 500 包裝
- [ ] 驗證：併發 load 測試（兩執行緒）、mid-import 例外後 status 一致性測試

### Task B3: 匯入容錯（缺 key / 壞 gzip 不中斷）

**Files:** `src/pce_cache/archive_import.py`、測試

- [ ] `rec["event_time"]` / `rec["ingested_at"]` / `rec["flow_hash"]` 改 per-line try，缺 key 計入 `skipped`
- [ ] `_iter_lines` 檔案層接 `OSError/EOFError/gzip.BadGzipFile`：記 warning、跳過該檔剩餘部分，繼續下一檔
- [ ] 驗證：截斷 .gz 與缺欄位 JSONL 的測試

### Task B4: `_make_cache_reader` engine 洩漏（archive 查詢每 request 觸發）

**Files:** `src/main.py`、`tests/test_make_cache_reader.py`

- [ ] `create_engine(..., poolclass=NullPool)`（與 `review_session_factory` 的既有決策一致；review DB 會被重建，不能用 process 快取 engine）
- [ ] `_make_subscribers` 同步處理（長壽 daemon 每次互動選單呼叫都新建 engine）
- [ ] 驗證：加 NullPool 鎖定測試（比照 `test_review_session_factory_uses_nullpool`）

### Task B5: archive export 補頂層 `first_detected`（格式對稱）

**Files:** `src/pce_cache/archive.py`、`src/pce_cache/archive_import.py`、測試

- [ ] `_traffic_record` 加 `"first_detected"` 頂層欄位；import 端優先取用（現有 raw 回推邏輯留作舊檔 fallback）
- [ ] 驗證：round-trip 測試 first_detected 保真

### Task B6: 文件化 archive undercount 限制（設計決策，不急著改碼)

**Files:** `src/pce_cache/archive.py` docstring、`docs/operations-manual*.md`

- [ ] 明文：upsert 刷新 volatile 欄位不 bump `ingested_at`，已 export 的列之後的成長不再進 archive → review DB 長壽 flow 計數可能低於 live cache
- [ ] 開後續評估項：upsert 時 bump ingested_at（副作用：subscriber 重讀，at-least-once 可接受）vs refresh 標記——與使用者確認需求後另開 plan

---

## Phase C — 熱路徑與資源管理

> **效能背景（2026-07-02 補查）**：專案既有優化已相當到位——ingest chunked upsert、report_json 於 ingest 預算（Tier-2a）、partial index `ix_raw_report_json_null`（fallback 由 ~8s 變即時）、刻意 drop 寫入放大的單欄索引、PRAGMA 調校（WAL / 64MB cache / 256MB mmap / busy_timeout）、set-based aggregator、單 worker `cache_writer` executor。以下 task 是殘餘缺口，不是系統性欠帳。
>
> **查過確認不用動的**：索引配置（src/dst workload、timestamp、`ix_events_ts_type`、dispatch 四索引，查詢模式全對得上）、pandas 報表路徑（真 DataFrame 工作負載）、`earliest_data_timestamp` 的 MIN 走 `ix_raw_last_action` 前導欄 O(log n)、orjson 已一致用於熱路徑。後續 agent 勿重複優化這些。

### Task C1: api_client rate-limit 路徑移除 per-request ConfigManager 重建

**Files:** `src/api_client.py`、測試

- [ ] `_request(rate_limit=True)` 改用 `self.cm.models.pce_cache.rate_limit_per_minute`（建構時快取），移除 `ConfigManager()` 重建（`api_client.py:194-204`）
- [ ] 順修 `get_events` 的 `rate_limit` 參數與 `get_traffic_flows_async` 的 `max_results` 靜默忽略：接通或移除簽名（`api_client.py:292-311`）

### Task C2: config/alerts 暫存檔權限（機密短暫 0644 暴露）

**Files:** `src/config.py`、測試

- [ ] 比照 `state_store.py`：`mkstemp`（0600）或 `os.open(..., 0o600)` 先建再寫（`config.py:388-398, 448-455`）
- [ ] 驗證：測試斷言 tmp 檔與最終檔權限

### Task C3: config 驗證 fallback 分岔（TLS guard 失效）

**Files:** `src/config.py`、`src/config_models.py`、測試

- [ ] 決策（使用者 2026-07-02 已定）：`api` 區塊驗證失敗 fail-hard——直接拒絕啟動並印明確錯誤
- [ ] RED：`verify_ssl=False + profile=production` 的 config 不得讓 ApiClient 以關閉驗證運行

### Task C4: SIEM 安全網補登語意修正

**Files:** `src/siem/dispatcher.py`、`src/scheduler/jobs.py`、測試

- [ ] anti-join 改 per-(destination, source_table) 過濾（新啟用 destination 能補到歷史）
- [ ] 依各 destination `source_types` 分別補登（與 ingest 端 `_enabled_siem_destinations` 共用同一函式）
- [ ] 批次 insert 單一 transaction（取代逐 source_id enqueue）

### Task C5: scheduler 雜項

**Files:** `src/scheduler/__init__.py`、`src/scheduler/jobs.py`、`src/report_scheduler.py`

- [ ] `persist=true` + `args=[cm]` pickle 必炸：決策（使用者 2026-07-02 已定）——移除 persist 選項與 SQLAlchemyJobStore 分支，config schema 標記 deprecated（不拒絕舊 config，僅忽略並警告）
- [ ] 全 repo 掃 `logger.error(..., exc_info=True)` → `logger.exception(...)`（loguru 下 exc_info 被靜默忽略）
- [ ] report_scheduler due 判定改 catch-up 語意（`now >= 排程時刻且 last_run < 該時刻`），解「重報表阻塞 60s tick 錯過整週排程」與 `_MIN_RERUN_GAP` 靜默限流 sub-hourly cron
- [ ] `report_scheduler.py:232` 裸建 ApiClient 改 `with ApiClient(cm)`

### Task C6: analyzer top_matches 有界累積

**Files:** `src/analyzer.py`、測試

- [ ] `_run_rule_engine` 累積階段維持 bounded top-N（heapq），取代「全量 copy 到 dispatch 才裁前 10」——O(flows×rules) 記憶體，大流量環境單次查詢可達數十萬筆
- [ ] hybrid 補洞查詢（`analyzer.py:921-942`）：`gap_list + cached` 全量物化改分段處理；順修 `cache_start` 邊界兩側皆含端點的重複計數（一側改半開區間）
- [ ] Follow-up（C6 實作時發現，2026-07-02）：同型 inclusive/inclusive 邊界雙算存在於 `src/report/report_generator.py` 與 `src/report/audit_generator.py`——報表統計面，非告警面，另開 task 修

### Task C7: 讀取路徑 per-request 開銷（2026-07-02 效能補查新增）

**Files:** `src/main.py`、`src/pce_cache/archive_import.py`、`src/pce_cache/reader.py`、測試

- [ ] `init_schema` 每次呼叫都跑（`_make_cache_reader`、`review_session_factory` per-query）：PRAGMA + create_all 反射 + table_info + 3 個 CREATE INDEX + 5 個 DROP INDEX，約十來個 DDL/metadata 語句進到每個 request。改為 per-db_path 記憶「schema 已確保」（review DB 只在 rebuild 後 init 一次），比照 `gui/_helpers._get_cache_engine` 的「engine 建立時跑一次」模式
- [ ] `read_flows_raw` / `read_events` 用 `select(整個 entity)` 但只取 `raw_json`：每列多搬 `report_json`（~等量 blob）＋ ORM 實體化開銷。改 column-only select（比照 `read_flows_df` 快路徑既有做法）
- [ ] SIEM `dispatcher._build_payload` 逐列開 session（NullPool 下 batch 100 = 100 條新 SQLite 連線）：`_process_batch` 改單一 session 批次載入 source rows；`cli/siem.py` status 的 per-destination 4 個 count 查詢改一次 GROUP BY

---

## Phase D — 安全里程碑

### Task D1: inline onclick 全面遷移 data-action + 收緊 CSP

**Files:** `src/static/js/*.js`、`src/templates/index.html`、`src/gui/__init__.py`

- [ ] 掃除既有 inline `onclick="...('${...}')"` 模式（`events.js:228` 的 escapeHtml-in-attribute 等效未跳脫、`quarantine.js:463` href 完全未跳脫），全部改 `data-action` + `_event_dispatcher.js`（91b7802 已示範新 UI 的做法）
- [ ] 遷移完成後移除 CSP `script-src 'unsafe-inline'`（`gui/__init__.py:402-410`），改 nonce 或純 'self'
- [ ] 驗證：全 GUI tab 手動煙霧測試 + `grep -rn "onclick=" src/static src/templates` 歸零

### Task D2: session cookie 與輸入驗證雜項

**Files:** `src/gui/__init__.py`、`src/templates/login.html`、`src/gui/routes/`、docs

> **範圍排除（使用者 2026-07-02 決定）**：預設帳號密碼機制與 IP allowlist 行為一律不動——不改強制改密、不動 `_initial_password`、不加登入頁警示、不改 allowlist 預設。以下僅保留其餘項目。

- [ ] `SESSION_COOKIE_SECURE=True` 在 HTTP 模式的行為：刻意逼 TLS 就加註解與文件，否則改 `use_https` 條件
- [ ] `login.html` `minlength=8` → 12（與後端一致）
- [ ] GUI 裸 `int()` 轉型統一 try + clamp 回 400（`actions.py:274,327`、`rules.py:100`、`config.py:373` 等）
- [ ] `pce_cache/web.py` / `siem/web.py` 的 `str(e)` 500 body 改 `_err_with_log` 慣例
- [ ] config 寫入未持鎖的兩處（`gui/routes/config.py:51-88`、`api_tls_config`）補 `with cm.write_lock:`

---

## Phase E — 套件與維護衛生

### Task E1: plotly 決策（死功能）

- [ ] 決策（使用者 2026-07-02 已定）：(b) 移除 plotly Python 依賴——`_spec_to_plotly_figure` 改手組 dict 或連同 chart endpoint 一併移除死路徑，requirements 三檔同步刪 plotly
- [ ] 無論何者：移除 `dashboard.js:2028` 永遠 false 的 `typeof Plotly` 死守衛或使其生效

### Task E2: requirements-offline.txt 同步上界

- [ ] pandas `<4.0`→`<3.0`、cheroot 對齊 `>=10.0`、補 numpy pin

### Task E3: 觀察名單與小清理

- [ ] flask-talisman（上游 archived）：記入維護文件，預備 ~100 行 `after_request` 自寫退場路徑，暫不動
- [ ] `siem_cli.py:245` DLQ replay/purge 假選單：接上 `dlq.py` 既有實作
- [ ] `humanize_ext.py` 統一 bytes 格式化入口（binary/decimal 並存）
- [ ] 明確不換：requests、APScheduler 3.x、loguru、pandas、pydantic、SQLAlchemy（review 結論：換了純成本）

---

## 建議執行順序與粒度

| 批次 | 內容 | 理由 |
|---|---|---|
| 1 | A1、A2 | 一小一中，Critical + 一行修，當天可完 |
| 2 | A3、B1–B3 | archive review 已上 GUI，資料正確性與韌性是同一批驗證；B1（批次寫入）是全計劃投報比最高的效能項 |
| 3 | B4 + C7 | 「讀取路徑」一批：NullPool、init_schema 只跑一次、column-only select、SIEM 批次載入——低風險高頻收益，共用驗證 |
| 4 | A4、C5 | 時區 + 排程語意一起動，共用測試基建（freezegun） |
| 5 | C1–C4、C6、B5 | 熱路徑/資源，彼此獨立可平行派工 |
| 6 | D1（獨立里程碑）、D2 | D1 動面大，單獨一個 branch |
| 7 | E1–E3、B6 | 套件決策需使用者輸入（plotly）、archive undercount 設計決策，其餘隨手 |
