# Documentation Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依 `docs/superpowers/specs/2026-07-17-docs-overhaul-design.md` 全面重寫專案文件：繁中為主、任務導向操作文件、新增接手開發文件（架構導覽、PCE domain 須知、開發流程），並適配文件守門鏈。

**Architecture:** 兩階段——Phase 1（Task 1–16）在舊文件仍在的情況下逐份建立/重寫新文件（新目錄 `docs/guide/`、`docs/handover/`，`docs/reference/` 與 README 原地重寫）；Phase 2（Task 17–18）刪除舊檔、重寫 INDEX、適配守門鏈（docs_check.py／check_doc_coverage.sh／test_docs_contracts.py）、全案驗證。

**Tech Stack:** Markdown（frontmatter 契約）、Python 守門腳本、pytest 文件契約測試、NotebookLM Illumio 筆記本（vendor 事實查證）。

## Global Constraints

- 語言：`docs/` 內全部繁中單語；僅倉庫根 README.md（精簡英文）/README_zh.md（繁中總覽）成對。
- 任何輸出不得使用 emoji；commit message 用英文 conventional commits。
- 每份新文件必帶 frontmatter（樣板見下），`last_verified: 2026-07-17`，`verified_against` 列出實際查核過的原始碼路徑（不可空）。
- 文件內容以程式碼為 ground truth；舊文件只當素材（轉寫，不照抄過時內容）；vendor 事實須標來源等級 `[真機驗證]`／`[官方文件]`／`[推測待驗]`。
- 絕不出現 `:5000`（GUI 舊埠，契約測試硬擋）；GUI 埠號以 `src/cli/gui_cmd.py` 預設值為準。
- 絕不出現 stale 片段：`HTML + CSV`、`HTML / CSV (15 traffic`、`HTML / CSV（15 traffic`、`HTML / CSV Raw ZIP / Both`、`illumio-ops report --type traffic`、`Python 3.8+`、`siem flush`。
- 表格欄位與長內容的截斷/換行處理要明確（專案 CLAUDE.md 規則）。
- 每個 Task 結尾跑驗證再 commit；驗證指令一律用 `venv/bin/python`。
- **交叉連結規則（Phase 1）**：markdown 連結只准指向當下已存在的檔案；要引用後續 task 才會建立的文件時，先寫純文字檔名（例：「見 monitoring-alerts.md」，不加 `[]()` 連結語法），Task 18 會統一補成連結。

**Frontmatter 樣板**（每份新文件開頭）：

```markdown
---
title: <繁中標題>
audience: [operator]        # 或 [developer]，handover/ 全部用 developer
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - <本文件實際查核過的原始碼/腳本路徑，至少一項>
---
```

**每份文件的共同驗證步驟**（下文以「跑文件驗證」代稱）：

```bash
venv/bin/python scripts/docs_check.py --links --frontmatter
venv/bin/python scripts/check_doc_links.py
```
Expected: 兩者 exit 0（Phase 1 期間舊文件仍在、皆已合規，任何非零都是本次新檔引入的問題）。

---

### Task 1: handover/architecture.md（架構導覽＋模組地圖）

**Files:**
- Create: `docs/handover/architecture.md`

**Interfaces:**
- Produces: 檔案路徑 `docs/handover/architecture.md`（Task 17 的 INDEX 與 Task 16 的 README_zh 會連結它）。

- [ ] **Step 1: 盤點 ground truth**。閱讀：`README.md`（現有架構圖，只當草稿）、`illumio-ops.py`、`src/main.py`、`src/api_client.py`（facade 結構，開頭 100 行＋類別方法清單即可）、`src/api/`（async_jobs/labels/traffic_query/reports 各檔 docstring）、`src/analyzer.py`（類別 docstring 與 query_flows/run_analysis 簽名）、`src/pce_cache/`（models/ingestor/aggregator/retention/backfill/reader 各檔 docstring）、`src/events/`、`src/report/report_generator.py`、`src/report_scheduler.py`、`src/rule_scheduler.py`、`src/reporter.py`、`src/alerts/`、`src/siem/`、`src/gui/routes/`（檔名清單＋每檔第一段註解）、`src/scheduler/jobs.py`、`src/job_health.py`。
- [ ] **Step 2: 撰寫**，章節綱要（繁中，audience: developer）：
  1. 一句話定位與單一進程模型（agentless、只走 PCE REST API）。
  2. 資料流圖（ASCII，重繪不照抄舊 README：PCE → api/ client → pce_cache SQLite 鏡像 → analyzer 規則引擎＋report 家族＋events pipeline → GUI/CLI/排程/告警/SIEM 出口）。
  3. 模組地圖表：`src/` 每個頂層模組一列（模組｜職責一句話｜關鍵入口點｜主要依賴）。表格過長時分「核心鏈」「出口層」「支撐層」三張，避免單格換行擠壓。
  4. 關鍵設計決策的為什麼：為什麼有 pce_cache（PCE 查詢貴且限流）、為什麼報表拆家族、為什麼 ApiClient 是 facade＋composition、為什麼 label cache 用 build-then-swap、為什麼集合 GET 有 async fallback、單一 `_cache_lock` RLock 的理由。每條 2–4 句，附對應原始碼路徑。
  5. 執行模式：`--monitor-gui`、純 CLI、排程 job 一覽（對照 `logs/job_health.json` 的 13 個註冊 job）。
- [ ] **Step 3: 跑文件驗證**。
- [ ] **Step 4: Commit**：`git add docs/handover/architecture.md && git commit -m "docs(handover): architecture guide and module map"`

### Task 2: handover/pce-domain-notes.md（PCE domain 須知）

**Files:**
- Create: `docs/handover/pce-domain-notes.md`

**Interfaces:**
- Produces: 檔案路徑 `docs/handover/pce-domain-notes.md`。

- [ ] **Step 1: 盤點素材**。閱讀：`src/api/traffic_query.py`（policy_decisions 預設註解、`_ASYNC_QUERY_MAX_WAIT_SECONDS`、`MAX_TRAFFIC_RESULTS`）、`src/api_client.py`（`_get_collection`/`_async_collection_get` 註解、POST 429 註解）、`src/api/async_jobs.py`（poll 終態）、`src/report/policy_diff_report.py`、`src/report/policy_resolver_report.py`（deny/override_deny、exclusion、scope 比對）、`src/report/rule_hit_count_generator.py`、舊 `docs/event-rules.md`（pd 值域一節、R 系列 on-demand gate、MITRE 對映——後兩者素材歸 Task 8，這裡只取 pd 值域）。
- [ ] **Step 2: 以下事實清單為底稿撰寫**（每條標來源等級；標 `[官方文件]` 者用 notebooklm skill 對 Illumio 筆記本逐條查證後才可寫入，查證不到就降級 `[推測待驗]`）：
  - Policy 模型：draft vs active（`/sec_policy/draft` vs `/active`）與 provision 生命週期 `[官方文件]`；rule 動作 allow／deny／override_deny 的語意與優先序 `[官方文件]`；enforcement mode 四態 idle／visibility／selective／full `[官方文件]`；**API 調得到但 GUI 看不到的 policy type**——以本專案實例說明：policy diff 的物件層 diff、policy resolver 展開 deny rules（GUI Explorer 不顯示）、draft 物件 API 形狀 `[真機驗證]`。
  - Traffic／Explorer：policy_decision 值域四值 blocked/potentially_blocked/allowed/unknown，unknown 涵蓋 idle/快照模式 VEN 與 Flowlink 未管理流量，預設漏掉它數字會大幅偏低（本專案 2026-07-16 起預設含 unknown）`[真機驗證]`；draft_policy_decision 是查詢時 on-demand 計算 `[官方文件]`；async query 全流程（POST `/traffic_flows/async_queries` → 202 → poll → download gzip JSON）`[真機驗證]`。
  - API 行為：Jobs API 終態是 `done` 不是 `completed` `[真機驗證]`；async query poll 的失敗終態含 `failed`/`cancel_requested`/`cancelled`/`canceled` `[真機驗證]`；集合 GET 同步硬上限 500 筆 `[官方文件]`；`X-Total-Count` 在帶 query filter（如 `workloads?managed=true`）時回**未過濾總數**（PCE 25.2.40 實測 20 列/header 30）`[真機驗證]`；`Prefer: respond-async` fallback 流程（202＋Location＋Retry-After → poll `done` → `result.href` 下載）`[真機驗證]`；帶日期參數需完整 ISO 時戳、純 `YYYY-MM-DD` 會 406 `[真機驗證]`；429 代表 PCE 已回應未處理、單次重試安全，但 POST 絕不可交給傳輸層自動重試（read-timeout 重試會重複 provision/create）`[真機驗證]`；label group 成員展開只在 PCE 端、client 無法本地比對 `[真機驗證]`。
  - Rule Hit Count：版本門檻 SaaS 24.2.0+／地端 23.5.10+／VEN 23.2.30+，計數僅 Active 規則、保留 90 天、規則最佳化可能高估、每 flow 最多歸因 100 條，VEN 實測 hit 與流量近似計數語意不同 `[官方文件]`。
  - 章節末附「本專案對應防護」小節：每條事實指向 repo 內落地位置（例：X-Total-Count → `src/api_client.py` `_get_collection` 錨定 500 上限）。
- [ ] **Step 3: 跑文件驗證**。
- [ ] **Step 4: Commit**：`git commit -m "docs(handover): PCE domain notes (verified vendor facts)"`

### Task 3: handover/development.md（開發流程）

**Files:**
- Create: `docs/handover/development.md`

- [ ] **Step 1: 盤點素材**。閱讀：舊 `docs/contributing/dev-setup.md`、`i18n-workflow.md`、`release-process.md`（三篇合併轉寫）、`.github/workflows/ci.yml`（守門順序：pip-audit 在 pytest 前）、`pytest.ini`、`mypy.ini`、`scripts/docs_check.py`、`scripts/bump_version.sh`、根目錄 `CLAUDE.md`。
- [ ] **Step 2: 撰寫**，章節：開發環境建置（venv、requirements、pre-flight）；測試與守門（全套 pytest、i18n audit 是硬閘、lint 家族、文件守門鏈四件套與觸發方式）；i18n workflow（新增字串的流程、en/zh_TW 兩檔、JS 引用鍵稽核）；**常見斷鏈坑**：新增 filter key 要過的七層白名單（`actions.py` params dict → `analyzer.py query_flows` whitelist → `_TRAFFIC_FILTER_CAPABILITIES` → build_traffic_query_spec → …，以 repo 內既有註解為準逐層列出實際位置）、報表 sidecar `report_type` 與檔名 prefix 的關係、JS 禁行尾 CJK 註解；release 流程（版本號三檔同步、tag、offline bundle 重建）。
- [ ] **Step 3: 跑文件驗證**。
- [ ] **Step 4: Commit**：`git commit -m "docs(handover): development workflow and gotchas"`

### Task 4: guide/installation.md（安裝與部署）

**Files:**
- Create: `docs/guide/installation.md`

**Interfaces:**
- Produces: Task 17 的 `check_doc_coverage.sh` 與 `test_docs_contracts.py` 會斷言本檔內容（必含字串見 Step 2）。

- [ ] **Step 1: 盤點素材**。閱讀：舊 `docs/getting-started.md` 與 `_zh`、`scripts/install.sh`、`scripts/install.ps1`、`scripts/preflight.sh`、`scripts/preflight.ps1`、`scripts/uninstall.sh`、`scripts/build_offline_bundle.sh`、`deploy/illumio-ops.service`、`deploy/install_service.ps1`。
- [ ] **Step 2: 撰寫**，章節：系統需求（Python「3.10 以上」；offline bundle 內建「CPython 3.12」）；從原始碼安裝；offline bundle（Linux RHEL/Ubuntu＋Windows，含 preflight、systemd/服務註冊、downgrade 守衛與服務停機行為）；升級（必含小節標題「升級後保留的檔案」，明列 `config.json`、`alerts.json`、`rule_schedules.json`）；移除（uninstall.sh 保留 data/）。**必含字串**（守門鏈斷言）：`3.10 以上`、`CPython 3.12`、`升級後保留的檔案`、`config.json`、`alerts.json`、`rule_schedules.json`、`build_offline_bundle.sh`、`preflight.sh`、`install.sh`、`uninstall.sh`、`preflight.ps1`、`install.ps1`。**禁**：`Python 3.8`、`:5000`。
- [ ] **Step 3: 跑文件驗證**。
- [ ] **Step 4: Commit**：`git commit -m "docs(guide): installation and deployment"`

### Task 5: guide/configuration.md（設定參照）

**Files:**
- Create: `docs/guide/configuration.md`

- [ ] **Step 1: 盤點 ground truth**。閱讀：`config/config.json.example`、`src/config_models.py`（pydantic models 全部欄位與預設值）、舊 `docs/operations-manual.md` §2、`src/settings/`（若存在 GUI settings 對映）。
- [ ] **Step 2: 撰寫**，章節：config.json 結構總覽；區塊逐節（api／多 PCE、analysis、rules 指到 monitoring-alerts.md、events、reports、alerts 通道、siem、pce_cache、gui/TLS、語言）。每個鍵一列表格：鍵｜型別｜預設｜說明；表格太寬時拆多張、說明欄長句換行。TLS 一節含自簽憑證每日續期 job（更新後需重啟才生效）。
- [ ] **Step 3: 跑文件驗證**。
- [ ] **Step 4: Commit**：`git commit -m "docs(guide): configuration reference"`

### Task 6: guide/gui-tour.md（Web GUI 導覽）

**Files:**
- Create: `docs/guide/gui-tour.md`

- [ ] **Step 1: 盤點 ground truth**。8 個分頁（`src/templates/index.html` data-tab）：dashboard、traffic-workload、rules、events、reports、rule-scheduler、integrations、settings。逐分頁對照 `src/gui/routes/` 對應檔案與舊 operations-manual §3。特別補齊全庫從未記錄的：**FilterBar v2 物件選擇器**（labels/label groups/iplists/workloads/services pill、include/exclude、`src/gui/routes/filter_objects.py` 後端）、dashboard tile 資料新鮮度變灰、Integrations 的 Job Health 表格（never-ran/overdue 旗標）與 TLS 憑證卡、告警通道卡片的 test-send 按鈕。
- [ ] **Step 2: 撰寫**：登入與 session；逐分頁一節（做什麼、關鍵操作、對應設定）；FilterBar 獨立一節（物件選擇器操作、pill 語意、同 key OR 跨 key AND）；quarantine 操作與確認流程。
- [ ] **Step 3: 跑文件驗證**。
- [ ] **Step 4: Commit**：`git commit -m "docs(guide): web GUI tour"`

### Task 7: guide/reports.md（報表家族）

**Files:**
- Create: `docs/guide/reports.md`

- [ ] **Step 1: 盤點 ground truth**。9 種報表逐一對照原始碼：traffic（`src/report/report_generator.py`）、security、audit（`audit_generator.py`）、policy-usage（`policy_usage_generator.py`）、ven-status、readiness（`readiness_report.py`）、rule-hit-count（`rule_hit_count_generator.py`，含啟用精靈與版本門檻）、policy-diff（`policy_diff_report.py`）、policy-resolver（`policy_resolver_report.py`）。加：`src/report_scheduler.py`（排程）、`src/cli/report.py`（CLI 產生）、匯出格式（html/csv/pdf/xlsx/all）、cache vs live 資料來源與 clip-to-cache。
- [ ] **Step 2: 撰寫**：報表總覽表（報表｜回答什麼問題｜資料來源｜輸出格式）；每種報表一節（用途、產生方式 GUI/CLI 各一例、關鍵欄位、注意事項——traffic 類要註明 2026-07 起預設含 unknown、舊 cache 需重跑 backfill 才有）；排程與寄送；**必含字串**：`illumio-ops report traffic --format html`。**禁** stale 片段（見 Global Constraints）。
- [ ] **Step 3: 跑文件驗證**。
- [ ] **Step 4: Commit**：`git commit -m "docs(guide): report family"`

### Task 8: guide/monitoring-alerts.md（監控規則、告警、事件規則）

**Files:**
- Create: `docs/guide/monitoring-alerts.md`

- [ ] **Step 1: 盤點素材**。舊 `docs/event-rules.md`＋`_zh`（**must-preserve：MITRE ATT&CK 對映表、R 系列 on-demand gate 說明、附錄誠實標註的 code gaps——全部轉寫進來**）、舊 operations-manual §6、`src/analyzer.py`（Monitor 規則 5 型）、`src/report/rules_engine.py`（B/L/R 系列）、`src/events/`（pipeline：poll→normalize→dedup→throttle→classify→shadow→stats→runbooks；vendor catalog 兩層）、`src/reporter.py`＋`src/alerts/`（5 種通道、DLQ 3 次重試、watchdog、溢出 meta-alert、LINE 截斷 footer）、`config/alerts.json` 結構。
- [ ] **Step 2: 撰寫**：即時監控規則 5 型（含 pd 值域四值、unknown 語意）；B/L/R 報表安全規則（模組對照表、MITRE 對映）；事件規則與 vendor catalog；告警通道設定與 test-send；可靠性機制（DLQ/watchdog/節流）。
- [ ] **Step 3: 跑文件驗證**。
- [ ] **Step 4: Commit**：`git commit -m "docs(guide): monitoring rules, alerts, and event rules"`

### Task 9: guide/automation.md（rule scheduler、quarantine、排程）

**Files:**
- Create: `docs/guide/automation.md`

- [ ] **Step 1: 盤點 ground truth**。`src/rule_scheduler.py`＋`src/gui/routes/rule_scheduler.py`（enable/disable 排程、per-schedule last-run 狀態）、`src/rule_scheduler_cli.py`、quarantine（`src/gui/routes/actions.py` `/api/quarantine/*`、CLI `workload`）、`rule_schedules.json`、sacred constraints（排程未啟用只 warning 絕不自動 enable、CLI/GUI 雙顯式確認）。
- [ ] **Step 2: 撰寫**：rule scheduler（用途、建立排程、時窗語意、安全約束）；quarantine（套用/解除、影響、稽核紀錄）；背景排程 job 總表（名稱、頻率、對應 job_health 鍵）。
- [ ] **Step 3: 跑文件驗證**。
- [ ] **Step 4: Commit**：`git commit -m "docs(guide): rule scheduler, quarantine, automation"`

### Task 10: guide/siem.md（SIEM 轉送）

**Files:**
- Create: `docs/guide/siem.md`

- [ ] **Step 1: 盤點 ground truth**。`src/siem/`、`src/siem_cli.py`、舊 operations-manual §7、pipeline health 的 `siem_idle` 旗標（CHANGELOG [Unreleased]）。
- [ ] **Step 2: 撰寫**：destinations 設定、格式、佇列與重試、DLQ 三命令（**必含字串** `siem dlq`、`siem replay`、`siem purge`；**禁** `siem flush`）、健康判讀（enabled-but-idle 呈現 warn）。
- [ ] **Step 3: 跑文件驗證**。
- [ ] **Step 4: Commit**：`git commit -m "docs(guide): SIEM forwarding"`

### Task 11: guide/cache-maintenance.md（pce_cache 維運）

**Files:**
- Create: `docs/guide/cache-maintenance.md`

- [ ] **Step 1: 盤點素材**。`src/pce_cache/`（ingestor_traffic/ingestor_events/aggregator/retention/backfill/reader/schema）、`src/pce_cache_cli.py`（互動選單）、舊 operations-manual §8.1 與 **§8.9 容量規劃（must-preserve：2.3KB/flow-row 實測基線、7 天外推表、archiver_lag 判讀——全部轉寫）**、archive 排程（IntervalTrigger 首跑錨定，CHANGELOG）。
- [ ] **Step 2: 撰寫**：cache 架構一頁圖（raw→agg→archive）；ingest 與 backfill 操作（含「重跑 backfill 補 unknown flows」案例）；retention/archive；容量規劃；WAL 模式注意。
- [ ] **Step 3: 跑文件驗證**。
- [ ] **Step 4: Commit**：`git commit -m "docs(guide): pce_cache maintenance and capacity planning"`

### Task 12: guide/troubleshooting.md（故障排除）

**Files:**
- Create: `docs/guide/troubleshooting.md`

- [ ] **Step 1: 盤點素材**。舊 operations-manual §9 全部（must-preserve：既有 runbook 條目與「Older docs stated…」歷史校正，校正內容以更正後為準轉寫）、`src/job_health.py`＋`logs/job_health.json`、`logs/` 目錄結構、`illumio-ops status`、`/health`。
- [ ] **Step 2: 撰寫**，症狀導向條目（每條：症狀→判讀→處置）：服務起不來；PCE 連不上/憑證；GUI 502/埠衝突；報表數字異常（含「traffic 數字突然變多＝unknown 納入預設」與「cache 源報表少 unknown＝重跑 backfill」）；job health 表 never-ran/overdue 判讀；DB 肥大與 archive 沒跑；告警沒送到（DLQ/watchdog 鏈）；TLS 憑證到期；日誌怎麼看（loguru 檔案、journalctl）。
- [ ] **Step 3: 跑文件驗證**。
- [ ] **Step 4: Commit**：`git commit -m "docs(guide): troubleshooting runbook"`

### Task 13: reference/cli.md 重寫（繁中）

**Files:**
- Modify: `docs/reference/cli.md`（原地重寫為繁中單語）

- [ ] **Step 1: 盤點 ground truth**。13 個 subcommand：cache、completion、config、gui、monitor、monitor-gui、report、rule、shell、siem、status、version、workload（`venv/bin/python -c "from src.cli import cli; print(sorted(cli.commands.keys()))"` 驗證）。逐命令讀 `src/cli/` 對應檔的 options/help。legacy argparse flags（`--monitor`、`--gui`、`--report`）一節。
- [ ] **Step 2: 撰寫**：synopsis、全域旗標、每個 subcommand 一節（用途、選項表、至少一個實例）。**必含字串**：`illumio-ops report traffic --format html`、`--host 0.0.0.0`、`siem dlq`、`siem replay`、`siem purge`，以及 coverage 腳本要求的 10 個子命令名（cache monitor gui report rule siem workload config status version）。**禁**：`siem flush`、`:5000`、stale 片段。
- [ ] **Step 3: 跑文件驗證**。
- [ ] **Step 4: Commit**：`git commit -m "docs(reference): rewrite CLI reference in zh"`

### Task 14: reference/rest-api.md 重寫（繁中）

**Files:**
- Modify: `docs/reference/rest-api.md`（原地重寫為繁中單語）

- [ ] **Step 1: 盤點 ground truth**。列出 `src/gui/routes/` 全部檔案，逐檔萃取 route decorators（`grep -n "@.*route(" src/gui/routes/*.py`）。舊檔漏掉的必補：`filter_objects.py` 全部端點、job health 端點、readiness/rule-hit-count/policy-diff/policy-resolver 報表產生端點。認證模型（session cookie＋CSRF，`src/auth_models.py`）。
- [ ] **Step 2: 撰寫**：認證一節；按分頁分區列端點（方法｜路徑｜用途｜關鍵參數）；長路徑不截斷、表格分區塊。frontmatter `verified_against` 列出 `src/gui/routes/` 全部檔名（含 filter_objects.py）。
- [ ] **Step 3: 跑文件驗證**。
- [ ] **Step 4: Commit**：`git commit -m "docs(reference): rewrite REST API reference in zh"`

### Task 15: reference/glossary.md 重寫（繁中）

**Files:**
- Modify: `docs/reference/glossary.md`（原地重寫為繁中單語）

- [ ] **Step 1: 盤點素材**。舊 glossary.md＋`_zh`（術語 must-preserve）、`src/i18n/data/zh_explicit.json`（決策術語保留英文原文的慣例）。
- [ ] **Step 2: 撰寫**：術語表（術語｜定義｜相關文件）；PCE/VEN/Workload/Label/Label Group/IP List/Ruleset/Enforcement/policy_decision 四值/draft vs active/pce_cache 等；清掉舊 frontmatter 指向 `../user-guide/` 的死連結。
- [ ] **Step 3: 跑文件驗證**。
- [ ] **Step 4: Commit**：`git commit -m "docs(reference): rewrite glossary in zh"`

### Task 16: README.md（精簡英文）＋ README_zh.md（繁中總覽）重寫

**Files:**
- Modify: `README.md`、`README_zh.md`

- [ ] **Step 1: 撰寫 README.md（精簡英文，目標 <120 行）**：badges（**必含** `Version-v4.1.0-blue`——實際值以 `src/__init__.py` `__version__` 為準、`Python-3.10%2B`）；一段定位（agentless、PCE REST API only）；功能一覽 bullet（9 報表家族、B/L/R 規則引擎、FilterBar v2 物件選擇器、5 告警通道、SIEM、rule scheduler、quarantine、pce_cache、job health 可觀測性、offline bundle）；quickstart 三步；「Full documentation (Traditional Chinese): docs/INDEX.md」。**禁**：`Python 3.8`、stale 片段。
- [ ] **Step 2: 撰寫 README_zh.md（繁中總覽）**：badges 同上；這專案在做什麼（給第一次接觸的人，含 PCE 一句話科普）；架構圖（與 Task 1 的圖一致、可簡化）；功能一覽；文件導航表（指向 docs/INDEX.md 與各篇）。
- [ ] **Step 3: 驗證**：跑文件驗證＋`venv/bin/python -m pytest tests/test_docs_contracts.py -q`。Expected: 兩個 README 相關斷言（python38、version badge）PASS；指向舊路徑的其他測試此時仍讀舊檔也 PASS（舊檔未刪）。
- [ ] **Step 4: Commit**：`git commit -m "docs: rewrite README (slim EN) and README_zh (full zh overview)"`

### Task 17: 刪舊檔＋INDEX 重寫＋守門鏈適配

**Files:**
- Delete: `docs/getting-started.md`、`docs/getting-started_zh.md`、`docs/operations-manual.md`、`docs/operations-manual_zh.md`、`docs/event-rules.md`、`docs/event-rules_zh.md`、`docs/INDEX_zh.md`、`docs/contributing/`（整目錄 6 檔）、`docs/reference/cli_zh.md`、`docs/reference/rest-api_zh.md`、`docs/reference/glossary_zh.md`、`docs/reference/i18n-contract_zh.md`
- Modify: `docs/reference/i18n-contract.md`（不重寫僅轉繁中？——**否**：i18n-contract 是開發規範，內容併入 Task 3 的 development.md 後刪除本檔）→ Delete: `docs/reference/i18n-contract.md`
- Modify: `docs/INDEX.md`、`scripts/docs_check.py`、`scripts/check_doc_coverage.sh`、`tests/test_docs_contracts.py`

**Interfaces:**
- Consumes: Task 1–16 產出的全部新文件路徑。

- [ ] **Step 1: 確認 development.md 已涵蓋 i18n-contract 的規範要點**（desc_key/rec_key 鍵值約定）；未涵蓋則先補進 `docs/handover/development.md` 再繼續。
- [ ] **Step 2: 刪除上列舊檔**：`git rm docs/getting-started*.md docs/operations-manual*.md docs/event-rules*.md docs/INDEX_zh.md docs/reference/*_zh.md docs/reference/i18n-contract.md && git rm -r docs/contributing`
- [ ] **Step 3: 重寫 `docs/INDEX.md`**（繁中總目錄）：三區——操作（guide/ 9 篇）、接手開發（handover/ 3 篇）、參考（reference/ 3 篇）；每條一句話說明；保留「文件如何保鮮」一節（docs_check 用法，改寫為單語新語意）。
- [ ] **Step 4: 改 `scripts/docs_check.py` 的 `check_bilingual`**，整函式替換為：

```python
def check_bilingual(md: list[Path], issues: list[tuple[str, str, str]]) -> None:
    """2026-07 docs overhaul 後 docs/ 為繁中單語；僅倉庫根 README.md 與
    README_zh.md 仍要求成對（md 清單掃的是 docs/，故直接檢查 repo 根）。"""
    repo_root = Path(__file__).resolve().parent.parent
    readme = repo_root / "README.md"
    readme_zh = repo_root / "README_zh.md"
    if readme.is_file() != readme_zh.is_file():
        missing = "README_zh.md" if readme.is_file() else "README.md"
        present = "README.md" if readme.is_file() else "README_zh.md"
        issues.append((present, "bilingual", f"missing counterpart: {missing}"))
```

- [ ] **Step 5: 改 `scripts/check_doc_coverage.sh` 的映射**：

```bash
declare -A DOC_FOR_FAMILY=(
  ["subcommand"]="docs/reference/cli.md"
  ["script"]="docs/guide/installation.md"
)
```

- [ ] **Step 6: 改寫 `tests/test_docs_contracts.py`**（8 個測試，斷言邏輯不變、路徑與語言改新制）：
  - `test_docs_do_not_advertise_python38_source_runtime`：docs dict 改為 `README.md`、`README_zh.md`、`docs/guide/installation.md`；斷言 `"Python-3.10%2B" in` 兩個 README、`"3.10 以上" in` 與 `"CPython 3.12" in` installation.md。
  - `test_docs_list_alerts_json_as_preserved_operator_config`：docs dict 改為 `docs/guide/installation.md`、`docs/guide/monitoring-alerts.md`；保留 trio 斷言（config.json/alerts.json/rule_schedules.json 在 installation.md）；`"Files preserved across upgrades"` 斷言改 `"升級後保留的檔案"`。
  - `test_version_badges_match_runtime_version`：不變。
  - `test_gui_port_and_bind_host_docs_match_runtime_defaults`：doc_paths 改為 `docs/guide/installation.md`、`docs/guide/gui-tour.md`、`docs/reference/cli.md`；`--host 0.0.0.0` 斷言只留 `docs/reference/cli.md`（刪 cli_zh 行）。
  - `test_report_format_and_click_examples_match_cli_contracts`：docs dict 改為 `README.md`、`README_zh.md`、`docs/reference/cli.md`、`docs/guide/reports.md`；`illumio-ops report traffic --format html` 斷言改為 in `docs/reference/cli.md` 與 `docs/guide/reports.md`（刪 cli_zh 行）。
  - `test_siem_docs_do_not_list_nonexistent_flush_command`：路徑 tuple 改 `("docs/reference/cli.md", "docs/guide/siem.md")`。
  - `test_preflight_upgrade_warnings_include_alerts_json`、`test_legacy_argparse_examples_use_actual_entrypoint_name`：不變。
- [ ] **Step 7: 驗證（此時必須全綠）**：

```bash
venv/bin/python scripts/docs_check.py --all
venv/bin/python scripts/check_doc_links.py
bash scripts/check_doc_coverage.sh
venv/bin/python -m pytest tests/test_docs_contracts.py -q
```
Expected: 全部 exit 0／PASS。docs_check 的 freshness 對舊 `ux-review-2026-05-14/` 若報過期，加 `--exclude 'ux-review*'`（並把該 exclude 寫進 INDEX「文件如何保鮮」一節的建議指令）。
- [ ] **Step 8: 全 repo 殘連結掃描**：`grep -rn "getting-started\|operations-manual\|event-rules\|contributing/\|_zh.md" --include='*.md' docs/ README.md README_zh.md | grep -v superpowers | grep -v _archive`。Expected: 無輸出（有就修）。
- [ ] **Step 9: Commit**：`git commit -m "docs: remove legacy bilingual docs, rewrite INDEX, adapt doc gates to zh-primary tree"`

### Task 18: 全案驗證＋CHANGELOG＋人工走查

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 全套測試**：`venv/bin/python -m pytest tests/ -q --tb=short`。Expected: 全綠（基準 3182 passed；docs contracts 已改新路徑）。
- [ ] **Step 2: 四件守門重跑一次**（同 Task 17 Step 7 四指令）。Expected: 全綠。
- [ ] **Step 3: CHANGELOG [Unreleased] 補 Changed 條目**：Documentation rebuilt zh-primary——task-oriented guides under docs/guide/, developer handover docs under docs/handover/ (architecture, PCE domain notes, development), rewritten references; legacy bilingual doc pairs removed (English retained as a slim README only)。
- [ ] **Step 4: 補交叉連結**：`grep -rn "見 [a-z-]*\.md" docs/guide docs/handover docs/reference` 找出 Phase 1 以純文字寫的檔名引用，全部改為相對路徑 markdown 連結，重跑 `venv/bin/python scripts/check_doc_links.py`。Expected: exit 0。
- [ ] **Step 5: 人工走查**：開 `docs/INDEX.md` 逐條點連結確認可達且標題對得上；抽查 3 份文件的表格在窄畫面 markdown render 不溢出（長內容有換行或拆表）；`git status` 乾淨。
- [ ] **Step 6: Commit**：`git add CHANGELOG.md docs/ && git commit -m "docs(changelog): documentation overhaul delivery"`

---

## 收尾（executing 端）

- controller 親跑全套＋四件守門；最終全分支 docs review（一個 subagent 以「新進開發者」視角走 INDEX→architecture→pce-domain-notes→installation 動線，回報讀不懂/斷鏈處）→ 修 → 合 main → push → `gh run watch`。
- 部署測試機非必要（文件不影響 runtime），但 push 後照常確認 CI 綠。
