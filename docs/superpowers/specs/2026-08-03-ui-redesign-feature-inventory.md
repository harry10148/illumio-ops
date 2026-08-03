# UI/UX 重新設計 — 功能盤點（source-first）

> 產生方式：直接掃描原始碼（路由裝飾器、JS 函式面、模組清單），非依 gui-tour.md。
> 用途：新設計的功能覆蓋基準；每一項之後都要在互動樣本中有對應落點，並進守門清單。
> 注意：本文件是「廣度層」。欄位級資料模型在樣本製作階段逐視圖用測試機真快照驗證，不在此臆造。

## 1. Web GUI（單頁應用，8 個主分頁）

### 1.1 Dashboard（`p-dashboard`, dashboard.js, routes/dashboard.py）
- 系統狀態總覽卡（`/api/status`, `/api/dashboard/overview`）：daemon/排程/cache/SIEM 健康
- Posture score 卡 + 詳情彈窗（`m-posture-score`）
- Top Actions 區（`gui_top_actions_heading`）
- 自訂儀表板查詢 CRUD（`/api/dashboard/queries` GET/POST/DELETE, `m-query` 彈窗）
- Top10 查詢（`/api/dashboard/top10`）
- Audit 摘要卡（`/api/dashboard/audit_summary`）
- Policy usage 摘要卡（`/api/dashboard/policy_usage_summary`）
- Dashboard snapshot（`/api/dashboard/snapshot`）
- 報表卡 meta（`loadRcardMeta`：各報表最近產出時間）

### 1.2 Traffic & Workload（`p-traffic-workload`, quarantine.js）
- 流量分析器（`runTrafficAnalyzer`，`/api/quarantine/search`）：KPI 卡（`updateTrafficKpis`）+ 分頁表格
- 流量來源切換（cache/PCE 即時，`onTrafficSourceChange`, `toggleTrafficSource`）
- 進階篩選彈窗（`modal-qt-filters` + FilterBar v2）
- 流量查詢指南彈窗（`modal-qt-guide`）
- Workload 搜尋（`/api/workloads`, `runWorkloadSearch`, 分頁）
- 隔離（quarantine）：單台/批次 apply、lift（`/api/quarantine/apply|bulk_apply|lift`, `m-quarantine`, `_buildQuarantineState`, bulk bar）
- 流量更新加速（accelerate, `/api/workloads/accelerate`, `m-accelerate`, 倒數顯示）
- Cache backfill 彈窗（`m-cache-backfill`）
- Archive 狀態/範圍查詢（`refreshArchiveStatus`, `loadArchiveRange`）

### 1.3 Events（`p-events`, events.js, routes/events.py）
- 事件檢視器（`/api/events/viewer`）：類別→群組→類型三層 catalog 篩選（`/api/event-catalog`）、load-more、詳情卡、狀態 tone/badge
- Shadow compare（`/api/events/shadow_compare`）
- 告警規則測試（`/api/events/rule_test`）

### 1.4 Alerts（`p-rules`, rules.js, routes/rules.py）
- 告警規則清單（`/api/rules`）＋啟停 toggle、刪除（單/批）、highlight（`/api/rules/<idx>/highlight`）
- 四種規則型各自彈窗：Event（`m-event`）/ System health（`m-system`）/ Traffic（`m-traffic`）/ Bandwidth（`m-bw`），含 FilterBar、事件 catalog 連動（`populateEvents`, `updateEventFilters`）
- 編輯規則（`/api/rules/<idx>` PUT）
- 立即執行一次（Run once, `/api/actions/run`）
- Debug 模式（`/api/actions/debug`）
- 測試告警（`/api/actions/test-alert`，含 per-channel 測試 `runPluginTestAlert`）
- 重置 watermark（`/api/actions/reset-watermark`）
- 最佳實務套用（`/api/actions/best-practices`, `confirmBestPractices`）
- 輸出主控台（`gui_output` 區）

### 1.5 Reports（`p-reports`, dashboard.js 報表段, routes/reports.py）
- 11 種報表卡：Traffic / Security & Risk / Network Inventory / Audit / VEN Status / Policy Usage / Rule Hit Count / Enforcement Readiness / Policy Diff / Policy Resolver / App Summary
- 產生彈窗（`m-gen-report`）：各型專屬參數、FilterBar、報表語言切換、進度步驟顯示（`_showGenProgress`/`_updateGenStep`）、async job 輪詢（`/api/reports/jobs/<id>`）、部分結果處理（`_handlePartialReport`）
- Rule hit count 前置：enablement 檢查/啟用（`/api/rule_hit_count/enablement|enable`）
- 已產報表清單：下載（blob）、單刪、勾選批刪（`/api/reports/bulk-delete`）、直接瀏覽（`/reports/<filename>`）
- 報表排程 CRUD（`/api/report-schedules` + toggle/run-now/history，`m-sched` 彈窗；頻率/信箱通知設定）
- Labels 查詢輔助（`/api/labels`, `_populateAppLabelSelects`）

### 1.6 Rule Scheduler（`p-rule-scheduler`, rule-scheduler.js, routes/rule_scheduler.py）
- 狀態列（`/api/rule_scheduler/status`）+ KPI（`rsRenderKpi`）+ 時間軸（`rsRenderTimeline`）
- Ruleset 瀏覽/搜尋（`/api/rule_scheduler/rulesets`, 詳情 `<rs_id>`，左右分欄 + resizer）
- 個別 rule 搜尋（`/api/rule_scheduler/rules/search`）
- 排程 CRUD：雙層目標（ruleset / rule）、one-time 需 `expire_at`、enable/disable 語意（`m-rs-schedule`, `/api/rule_scheduler/schedules` + delete）
- 立即檢查（`/api/rule_scheduler/check`）
- 執行紀錄（`/api/rule_scheduler/logs`）+ 清除（`rsClearLog`）
- PCE 狀態對帳顯示（刪除資源偵測、live state）

### 1.7 Integrations（`p-integrations`, integrations.js）
- 總覽：pipeline 健康（`_buildOvPipelineHealth`）、狀態卡（`_buildOvCards`）、近期事件表、job 健康（`_buildOvJobHealth`）、TLS 卡、資料完整性（`_buildOvDataIntegrity`）、告警管道卡（`_buildAlertChannelCards`）
- PCE cache：狀態卡＋lag 列、設定表單（`buildCacheForm`/`cacheSave`）、重啟 banner + daemon 重啟（`/api/daemon/restart`）、backfill、立即 retention
- 流量過濾器設定（`renderTrafficFilter`, IP 驗證提示）
- 流量取樣設定（`renderTrafficSampling`）
- SIEM：forwarder 設定、目的地清單 CRUD + 條件欄位、測試送出（modal 與 inline）、DLQ（搜尋/分頁/回放/清除/匯出/檢視）

### 1.8 Settings（`p-settings`, settings.js, routes/config.py）
- 子分頁切換（`switchSettingsTab`）：PCE 連線（profiles CRUD/啟用切換）、告警管道（5 插件：Mail/LINE/Webhook/Telegram/Teams，動態表單 `_renderAlertPluginCards`）、顯示（主題亮暗、密度、時區、語言）、安全（`/api/security`：認證、session）、TLS（狀態/設定/續期/CSR 產生下載/憑證匯入）、Cache 分頁
- dirty 追蹤 + 儲存鈕狀態（`_markSettingsDirty`）
- 模組日誌檢視器（module-log.js, `/api/logs`, `/api/logs/<module>`）
- GUI 停止（`stopGui`, `/api/shutdown`）
- 頂欄選單（`hdrMenuToggle`）、說明彈窗（`m-help`：篩選語法/policy decisions）

### 1.9 跨域機制
- FilterBar v2（filter-bar.js 1197 行）：pill 式物件篩選、AND/OR、include/exclude、zone（src/dst/svc）、suggest（`/api/filter-objects/suggest`）、browse（`/api/filter-objects/browse`）、物件選擇彈窗（`modal-obj-browser`, object-browser.js）
- i18n 雙語（`/api/ui_translations`, `applyI18n`）
- 主題亮/暗 + 密度 + 時區（utils.js）
- CSRF 流程（`_csrfToken`/`_withFreshCsrf`）
- Toast、cell popover、表格欄寬拖曳（`initTableResizers`）、skeleton 載入態
- URL 狀態同步（`updateUrlState`）

### 1.10 登入（login.html, login.js, routes/auth.py）
- 登入表單（`/api/login`）、登出、首次登入強制改密碼流程

## 2. HTML 報表（11 型，print-first、可 PDF、雙語）

| 報表 | 產生器 | Exporter |
|---|---|---|
| Traffic（20+ 分析模組：mod01 流量總覽、mod02 policy decisions、mod03 uncovered、mod04 ransomware、mod06 user/process、mod07 cross-label、mod08 unmanaged、mod09 分佈、mod11 頻寬、mod12 executive、mod13 readiness、mod14 infrastructure、mod15 lateral movement、app baseline、change impact、draft actions/summary、drift、labels、ringfence、vuln、attack posture、MITRE map、estate inventory） | report_generator.py + analysis/ | html_exporter.py（99K）+ chart_renderer |
| Security & Risk | security_risk_report.py | （traffic 家族） |
| Network Inventory | network_inventory_report.py | （traffic 家族） |
| Audit | audit_generator.py | audit_html_exporter.py |
| VEN Status | ven_status_generator.py | ven_html_exporter.py |
| Policy Usage | policy_usage_generator.py | policy_usage_html_exporter.py |
| Rule Hit Count | rule_hit_count_generator.py | rule_hit_count_html_exporter.py |
| Enforcement Readiness | readiness_report.py | readiness_html_exporter.py |
| Policy Diff | policy_diff_report.py | policy_diff_html_exporter.py |
| Policy Resolver | policy_resolver_report.py | policy_resolver_exporter.py |
| App Summary | app_summary_report.py | app_summary_html_exporter.py |

- 共用件：report_css.py（53K）、report_i18n.py、cover_page、concern_card、table_renderer、grade_colors、section_guidance、csv/xlsx 匯出
- 偵測規則 r01–r05（draft deny、override deny、visibility boundary breach、allowed across boundary、draft/reported mismatch）
- 專案硬規則（CLAUDE.md）：欄位長度上限與截斷邏輯必須明確；交付前實際樣本逐頁檢查

## 3. CLI

### 3.1 Click 子指令（cli/root.py）
`cache` / `config` / `monitor`（終端即時監控）/ `monitor-gui` / `gui` / `report`（41.8K，各型報表產生）/ `rule` / `siem` / `status` / `workload` / `completion` + 全域旗標（--json/--quiet/-v）、exit codes、物件選擇器（object_picker.py）

### 3.2 互動選單（cli/menus/）
- 主選單（main.py 入口）→ settings_menu（_root.py）
- 規則管理（manage_rules）、四型規則新增/編輯精靈（event/traffic/bandwidth/system_health）
- 告警設定（alert）、報表排程管理（report_schedule）、Web GUI 安全/TLS 選單（web_gui）

## 4. 背景子系統（GUI 需可視化其狀態）
- Scheduler jobs：alert 檢查、cache events/traffic ingest、aggregate、retention、lag monitor、capacity monitor、archive、SIEM dispatch（scheduler/__init__.py）
- PCE cache pipeline：ingestor→aggregator→retention/archive/backfill→reader；watermark、rate limiter、capacity、flow deltas、archive import
- Events 子系統：catalog（26K）、normalizer、matcher、poller、runbooks（16K）、shadow、stats、throttle
- SIEM：dispatcher、DLQ、mask（遮罩）、formatters/transports
- Alerts：5 管道插件 + 模板 + metadata
- API 層：traffic_query（95K）、labels、async_jobs、reports

## 5. 已知非功能約束
- 離線部署 bundle（Linux/Windows、NSSM）必須照常運作 → 前端資產須可離線打包
- i18n 雙語全覆蓋（守門測試既有）
- 報表 print/PDF 相容（A4、雙寬度檢查）
- CSRF、session、TLS、首次登入改密碼等安全流程不可退化
- 效能：cache 表可達大量資料（分頁、skeleton、X-Total-Count 語意=未過濾總數）
