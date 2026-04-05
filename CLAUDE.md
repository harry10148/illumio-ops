# CLAUDE.md — Illumio PCE Ops 專案參考

## 專案概述

Illumio PCE (Policy Compute Engine) 監控平台，用於即時監控 Illumio 微分段環境的事件、流量與系統健康狀態，並透過多通道發送告警。核心功能完全基於 Python 標準庫（零外部依賴），僅 Web GUI 需要 Flask、報表需要 pandas/pyyaml。

**版本**: 1.0.0 (`src/__init__.py`)
**入口**: `illumio_ops.py` → `src/main.py:main()`
**語言**: 支援 EN / ZH_TW（`src/i18n.py`）

## 三種執行模式

| 模式 | 啟動方式 | 說明 |
|------|---------|------|
| Interactive CLI | `python illumio_ops.py` | 選單驅動，規則管理、手動分析、設定調整 |
| Daemon | `python illumio_ops.py --monitor -i 5` | 無頭監控迴圈，固定間隔執行分析+告警 |
| Web GUI | `python illumio_ops.py --gui` | Flask SPA，~40 個 JSON API endpoint |

## 目錄結構

```
illumio_ops/
├── illumio_ops.py          # 入口，import src.main.main()
├── config.json                 # 執行期設定（API 憑證、規則、告警）── gitignore
├── config.json.example         # 設定範本
├── state.json                  # 持久化狀態（時間戳、告警歷史）── gitignore
├── requirements.txt            # flask + pandas + pyyaml（核心零依賴）
├── .gitattributes              # 強制 LF 換行（跨平台一致性）
│
├── src/                        # 主要程式碼
│   ├── __init__.py             # __version__ = "1.0.0"
│   ├── main.py                 # CLI argparse + daemon loop + interactive menu
│   ├── api_client.py           # Illumio REST API client（urllib, retry, streaming）
│   ├── analyzer.py             # 規則引擎：事件/流量/頻寬比對 + 指標計算
│   ├── reporter.py             # 告警聚合 & 多通道發送（Email/LINE/Webhook）
│   ├── report_scheduler.py     # 排程引擎：tick() 每分鐘評估、run_schedule()、報表保留清理
│   ├── rule_scheduler.py       # PCE 規則集排程器：定時啟用/停用 ruleset（recurring + one-time）
│   ├── rule_scheduler_cli.py   # 規則排程 CLI 互動選單
│   ├── config.py               # ConfigManager：config.json 讀寫、規則 CRUD、PCE Profile 管理、atomic write
│   ├── gui.py                  # Flask Web 後端 + ~40 JSON API endpoints
│   ├── settings.py             # CLI 互動式選單（規則新增/管理 wizard）
│   ├── i18n.py                 # 翻譯字典 EN/ZH_TW，200+ key
│   ├── utils.py                # logging、ANSI color、單位格式化、CJK 寬度
│   │
│   ├── templates/
│   │   └── index.html          # SPA 前端（vanilla JS, Illumio 品牌色, dark/light theme）
│   ├── static/                 # CSS/JS 靜態資源
│   │
│   └── report/                 # 進階報表引擎
│       ├── report_generator.py     # 統一入口：parsing → analysis → export
│       ├── audit_generator.py      # 系統稽核報表
│       ├── ven_status_generator.py  # VEN 清單報表
│       ├── policy_usage_generator.py # 政策使用報表（第 4 種報表類型）
│       ├── rules_engine.py         # 報表層級規則過濾；Finding dataclass 定義於此
│       ├── parsers/
│       │   ├── api_parser.py       # PCE API → pandas DataFrame
│       │   ├── csv_parser.py       # CSV export → 統一格式
│       │   └── validators.py       # 資料驗證
│       ├── exporters/
│       │   ├── html_exporter.py    # 流量報表 → HTML（主要輸出）
│       │   ├── csv_exporter.py     # 任意報表 → CSV ZIP（stdlib, 零依賴）
│       │   ├── audit_html_exporter.py
│       │   ├── ven_html_exporter.py
│       │   ├── policy_usage_html_exporter.py  # 政策使用報表 → HTML
│       │   └── report_i18n.py      # 報表 HTML 雙語字串（EN/ZH_TW），含安全發現項目翻譯
│       └── analysis/               # 15 個流量分析模組 + 4 個稽核模組 + 4 個政策使用模組
│           ├── mod01_traffic_overview.py    # 總流量、連線數、政策覆蓋率
│           ├── mod02_policy_decisions.py    # Allowed/Blocked/PB 分佈
│           ├── mod03_uncovered_flows.py     # 未管理工作負載流量
│           ├── mod04_ransomware_exposure.py # 勒索軟體高風險 port
│           ├── mod05_remote_access.py       # SSH/RDP/VNC/TeamViewer
│           ├── mod06_user_process.py        # 使用者連線分析
│           ├── mod07_cross_label_matrix.py  # 跨環境流量矩陣
│           ├── mod08_unmanaged_hosts.py     # 未納管主機
│           ├── mod09_traffic_distribution.py # 流量分佈
│           ├── mod10_allowed_traffic.py     # 放行流量明細
│           ├── mod11_bandwidth.py           # 頻寬統計 & 異常
│           ├── mod12_executive_summary.py   # KPI 彙整
│           ├── mod13_readiness.py           # Enforcement Readiness 評分
│           ├── mod14_infrastructure.py      # 基礎設施服務評分
│           ├── mod15_lateral_movement.py    # 橫向移動風險分析
│           ├── audit/
│           │   ├── audit_mod00_executive.py # 稽核摘要
│           │   ├── audit_mod01_health.py    # PCE 健康事件
│           │   ├── audit_mod02_users.py     # 使用者登入/驗證
│           │   └── audit_mod03_policy.py    # 政策變更事件
│           └── policy_usage/
│               ├── pu_mod00_executive.py    # 政策使用摘要
│               ├── pu_mod01_overview.py     # 規則集使用概覽
│               ├── pu_mod02_hit_detail.py   # 有流量命中的規則明細
│               └── pu_mod03_unused_detail.py # 未使用規則明細
│
├── config/                     # 報表設定 YAML
│   ├── report_config.yaml      # 勒索軟體 port、閾值、輸出設定
│   ├── semantic_config.yaml    # 自訂語意規則（可選）
│   └── csv_column_mapping.yaml # CSV 欄位對映
│
├── docs/                       # 文件
│   ├── Project_Architecture.md / _zh.md
│   ├── User_Manual.md / _zh.md
│   ├── API_Cookbook.md / _zh.md
│   ├── Dev_Environment_SOP.md  # macOS 集中式 venv 開發環境 SOP
│   ├── REST_APIs_25_2.md       # Illumio API 參考
│   ├── Illumio Core 25.2.10 Administration.md
│   └── illumio_brand_guidelines.md
│
├── deploy/
│   ├── illumio-ops.service       # systemd service（Ubuntu/Debian，使用 venv）
│   ├── illumio-ops-rhel.service  # systemd service（RHEL/CentOS，系統 Python）
│   └── install_service.ps1           # Windows service installer（NSSM，自動偵測 venv）
│
├── reports/                    # 產出報表目錄
├── logs/                       # 應用日誌（rotating 10MB x 5）
├── tests/test_analyzer.py      # 單元測試
├── test_audit.py               # 稽核報表整合測試
└── test_real_events.py         # 真實 API 整合測試
```

## 核心架構 & 資料流

```
                    ┌─────────────┐
                    │ config.json │
                    └──────┬──────┘
                           │
              ┌────────────▼────────────┐
              │     ConfigManager       │ (src/config.py)
              │ load / save / CRUD rule │
              └────────────┬────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                  │
  ┌──────▼──────┐  ┌──────▼──────┐  ┌───────▼───────┐
  │  ApiClient  │  │  Analyzer   │  │   Reporter    │
  │ (api_client)│──▶│ (analyzer)  │──▶│  (reporter)   │
  │ REST+retry  │  │ rule engine │  │ Email/LINE/WH │
  └─────────────┘  └─────────────┘  └───────────────┘
                                            │
                                    ┌───────▼────────┐
                                    │ ReportScheduler │
                                    │ tick() / run()  │
                                    └────────────────┘
```

**Daemon 單次循環**: `ApiClient` 取資料 → `Analyzer.run_analysis()` 比對規則 → `Reporter.send_alerts()` 發送告警
**排程報表循環**: `ReportScheduler.tick()` 每分鐘評估 → `run_schedule()` 產生報表 → `_send_report_email()` 寄送 → `_prune_old_reports()` 清理過期檔案

## 關鍵類別 & 方法

### ConfigManager (`src/config.py`)
- `__init__(config_file)` — 載入 config.json，deep merge 預設值
- `save()` — atomic write（tmp + os.replace）
- `add_or_update_rule(rule)` — 依 type+name 或 filter_value 判斷是否覆蓋
- `remove_rules_by_index(index_list)` — 批次刪除
- `load_best_practices()` — 載入 7 個事件規則 + 1 個流量規則作為預設
- `add_pce_profile(profile)` — 新增 PCE 連線設定檔（multi-PCE 管理）
- `remove_pce_profile(profile_id)` — 刪除 PCE 設定檔
- `activate_pce_profile(profile_id)` — 切換活躍 PCE 設定檔，覆寫 `api.*` 欄位

### ApiClient (`src/api_client.py`)
- `_request(url, method, data, headers, timeout, stream)` — 核心 HTTP，retry with exponential backoff
- `check_health()` — PCE 健康狀態（`/health`）
- `get_events(params)` — 審計事件（`/events`）
- `get_traffic_flows(query)` — 流量查詢，**25.2 起僅支援非同步**
- `get_traffic_flows_async(query)` — 非同步流量查詢（回傳 query href）
- `poll_async_query(href)` / `download_async_result(href)` — 輪詢狀態 + 下載結果
- `execute_traffic_query_stream(start, end, policy_decisions, filters, compute_draft)` — **主要流量查詢入口**，4 階段非同步 + 串流解析
  - `compute_draft=True`：在 Download 前呼叫 `PUT .../update_rules`，PCE 計算草稿政策決策，下載結果包含 `draft_policy_decision`、`rules`、`enforcement_boundaries`、`override_deny_rules`
  - `update_rules` 注意：PCE 狀態在運算期間維持 `"completed"`（不會轉回 pending），固定等待 10 秒後再輪詢確認
- `get_traffic_flows_stream(query)` — 串流式流量下載（O(1) 記憶體）
- `get_workloads()` / `get_labels()` / `get_rulesets()` — 工作負載、標籤、規則集
- `batch_get_rule_traffic_counts(rulesets)` — 批次取得規則流量命中數（政策使用報表用）
- `provision_policy(hrefs, note)` — 佈建草稿政策至生效
- 常數：`MAX_TRAFFIC_RESULTS=200000`, `MAX_RETRIES=3`, `RETRY_BACKOFF_BASE=2`

### Analyzer (`src/analyzer.py`)
- `run_analysis()` — 執行所有啟用的規則比對
- 規則類型：`event`（事件）、`traffic`（流量）、`bandwidth`（頻寬）、`volume`（流量量）
- 閾值模式：`immediate`（單次觸發）、`count`（在 window 內累計達 N 次）
- cooldown 機制：避免重複告警
- **流量篩選方向**：`filter_direction` 欄位 — `src_and_dst`（預設，來源 AND 目的地）、`src_only`、`dst_only`、`src_or_dst`
- **標籤排除**：`exclude_labels` 陣列，符合的流量跳過不告警
- **IP 排除**：`exclude_ips` 陣列，支援 CIDR 格式（如 `10.0.0.0/8`）
- **`query_flows(params)`** — GUI Traffic Analysis Query 的核心方法
  - `params.draft_policy_decision`：非空時自動設 `compute_draft=True`，且強制 query_pds 為全三種（避免遺漏 allowed → blocked_by_boundary 的流量）
  - client-side 過濾：`(f.get("draft_policy_decision") or "").lower() != draft_pd_filter`

### Reporter (`src/reporter.py`)
- `send_alerts()` — 依 `config.alerts.active` 發送（支援 `mail`, `line`, `webhook`）
- HTML 表格格式化告警內容
- 告警類型：health、event、traffic、metrics

### ReportScheduler (`src/report_scheduler.py`)
- `tick()` — 每分鐘從 daemon loop 呼叫，評估所有啟用排程是否觸發
- `run_schedule(schedule)` — 執行單一排程：產生報表 + 寄送 Email
- `_send_report_email()` — 建立 HTML 郵件內容；findings 為 `Finding` dataclass，使用 `f.rule_id`、`f.rule_name`、`f.severity`、`f.description` 屬性（非 dict）
- `_prune_old_reports(output_dir)` — 刪除超過 `retention_days` 天的 `.html`/`.zip` 報表
- `should_run(schedule, now)` — 依排程類型（daily/weekly/monthly）與時間判斷
- state 持久化：`logs/state.json` 的 `report_schedule_states` key

### RuleScheduler (`src/rule_scheduler.py`)
- PCE 規則集定時啟用/停用排程器
- 排程類型：`recurring`（每日/每週/每月重複，支援午夜跨日 wraparound）、`one_time`（單次執行後自動標記完成）
- `tick()` — 每分鐘從 daemon loop 呼叫，評估所有排程是否觸發
- 草稿保護：操作 ruleset 後檢查是否需要 provision
- state 持久化：`state.json` 的 `rule_schedules` key

### Web GUI (`src/gui.py`)
- Flask app，~40 JSON endpoints
- 主要路由群組：
  - `/api/rules` — 規則 CRUD（event/traffic/bandwidth）
  - `/api/settings` — GET/POST 涵蓋：api、email、smtp、alerts、settings、report
  - `/api/pce-profiles` — Multi-PCE 設定檔管理
  - `/api/dashboard/*` — 儀表板查詢、快照、Top10
  - `/api/reports/*` — 報表列表、刪除、產生（traffic/audit/ven_status/policy_usage）
  - `/api/report-schedules/*` — 報表排程 CRUD + 手動執行 + 歷史
  - `/api/quarantine/*` — 隔離搜尋、套用、批次套用
  - `/api/workloads` — 工作負載查詢與更新
  - `/api/rule_scheduler/*` — PCE 規則集排程管理
  - `/api/actions/*` — 手動觸發分析、測試告警、測試連線、載入最佳實踐
- 前端：`src/templates/index.html`（SPA, vanilla JS）

### 報表引擎 (`src/report/`)
- `report_generator.py` — 統一入口，支援 API 或 CSV 資料來源
- **四種報表**：Traffic（15 分析模組）、Audit（4 模組）、VEN Status、**Policy Usage（4 模組）**
- 輸出：**HTML**（主要）/ **CSV ZIP**（stdlib, 零依賴）；已移除 Excel/.xlsx 匯出
- 依賴：pandas, pyyaml（僅報表功能需要；openpyxl 已不再需要）
- `Finding` dataclass 定義於 `rules_engine.py`，欄位：`rule_id`, `rule_name`, `severity`, `category`, `description`, `recommendation`, `evidence`
- `report_i18n.py` — 報表 HTML 的雙語字串（安全發現項目分類名稱、說明、規則 how-text B001-B009/L001-L010 均已完整翻譯）
- `policy_usage_generator.py` — 政策使用報表入口，透過 `batch_get_rule_traffic_counts` 取得規則命中數，分析未使用規則
- Traffic 模組 13-15：Enforcement Readiness 評分、基礎設施服務評分、橫向移動風險分析

### VEN Status Generator (`src/report/ven_status_generator.py`)
- 線上/離線判斷使用 `hours_since_last_heartbeat`（PCE 計算值）或 `last_heartbeat_on` 時間戳年齡，**非** `agent.status.status`
- `_ONLINE_HEARTBEAT_THRESHOLD_HOURS = 1.0`：超過 1 小時無心跳 → 視為離線（即使管理狀態為 active）
- 原因：PCE `agent.status.status = "active"` 是管理狀態，VEN 失聯後仍可能維持 active

## 設定檔結構 (config.json)

```json
{
  "api": { "url", "org_id", "key", "secret", "verify_ssl" },
  "pce_profiles": [ { "id", "name", "url", "org_id", "key", "secret", "verify_ssl" } ],
  "alerts": { "active": ["mail"|"line"|"webhook"], "line_*", "webhook_url" },
  "email": { "sender", "recipients" },
  "smtp": { "host", "port", "user", "password", "enable_auth", "enable_tls" },
  "settings": { "enable_health_check", "language", "theme", "timezone" },
  "rules": [ { "id", "type", "name", "filter_*", "threshold_*", "cooldown_minutes", ... } ],
  "report": {
    "enabled", "schedule", "source", "format": ["html"],
    "output_dir": "reports/",
    "retention_days": 30,
    "api_query": { "start_date", "end_date", "max_results" }
  },
  "report_schedules": [
    {
      "id": 1700000000, "name": "Weekly Traffic Report", "enabled": true,
      "report_type": "traffic|audit|ven_status|policy_usage",
      "schedule_type": "daily|weekly|monthly",
      "day_of_week": "monday", "day_of_month": 1,
      "hour": 8, "minute": 0,
      "lookback_days": 7, "format": ["html"],
      "email_report": true, "email_recipients": [],
      "output_dir": "reports/"
    }
  ],
  "rule_schedules": [ { "id", "name", "enabled", "ruleset_href", "action", "schedule_type", "hour", "minute", ... } ]
}
```

**`report.retention_days`**：排程執行後自動清理超過此天數的 `.html`/`.zip` 報表，設為 `0` 停用。可從 GUI Settings → Report Output 或 CLI 設定選單 [5] 調整。

## 規則結構

### Event Rule
```json
{
  "id": 1234567890, "type": "event", "name": "Rule Name",
  "filter_key": "event_type", "filter_value": "user.sign_in",
  "filter_status": "failure|success|all", "filter_severity": "error|warning|all",
  "threshold_type": "immediate|count", "threshold_count": 5,
  "threshold_window": 10, "cooldown_minutes": 30,
  "desc": "Description", "rec": "Recommendation"
}
```

### Traffic Rule
```json
{
  "id": 1234567890, "type": "traffic", "name": "Rule Name",
  "pd": 2, "port": 445, "proto": 6,
  "src_label": "env:Production", "dst_label": null,
  "filter_direction": "src_and_dst|src_only|dst_only|src_or_dst",
  "exclude_labels": ["env:Development"],
  "exclude_ips": ["10.0.0.0/8"],
  "threshold_type": "count", "threshold_count": 25,
  "threshold_window": 10, "cooldown_minutes": 30
}
```
`pd` (policy decision): 0=allowed, 1=potentially_blocked, 2=blocked
`filter_direction`（預設 `src_and_dst`）：控制 src_label/dst_label 的比對邏輯

## 依賴

| 套件 | 用途 | 必要性 |
|------|------|--------|
| Python 3.7+ stdlib | 核心全部功能 | 必要 |
| flask | Web GUI (`--gui`) | 可選 |
| pandas | 報表資料分析 | 可選（僅報表） |
| pyyaml | 報表設定 YAML | 可選（僅報表） |

> **Ubuntu/Debian 安裝注意（PEP 668）**：系統層級 `pip install` 被封鎖，必須使用 venv：
> ```bash
> python3 -m venv venv
> venv/bin/pip install flask pandas pyyaml
> ```
> systemd service (`illumio-ops.service`) 已設定為使用 `venv/bin/python`。
>
> **RHEL/CentOS**：使用系統 Python，套件透過 `dnf install python3-flask python3-pandas python3-PyYAML` 安裝，使用 `illumio-ops-rhel.service`。

## 檔案路徑常數

- `CONFIG_FILE`: `{ROOT_DIR}/config.json`（定義於 `src/config.py`）
- `STATE_FILE`: `{ROOT_DIR}/state.json`
- `LOG_DIR`: `{ROOT_DIR}/logs/`
- `REPORTS_DIR`: 由 `config.report.output_dir` 決定，預設 `reports/`；可從 GUI/CLI 設定
- `ROOT_DIR`: `illumio_ops.py` 所在目錄（`src/` 的父目錄）

## CLI 設定選單結構

`settings_menu()` in `src/settings.py` 有 5 個選項（0=返回）：

| 選項 | 內容 |
|------|------|
| [1] | API 設定（URL, Key, Secret, Org ID）|
| [2] | 告警通道（Mail/LINE/Webhook）& 語言 |
| [3] | SSL 憑證驗證開關 |
| [4] | SMTP 設定（Host, Port, TLS, Auth）|
| [5] | **報表輸出**（output_dir, retention_days）|

排程管理另有獨立選單 `manage_report_schedules_menu()`，使用 **1-based** 索引（0=返回，避免與 `safe_input` 的 0=back 衝突）。

## 開發注意事項

- **atomic write**: config.json 寫入使用 tmp + `os.replace()` 防止損壞
- **streaming**: 大量流量資料使用 generator 串流下載（`get_traffic_flows_stream`）
- **retry**: API 呼叫自動 exponential backoff（429/502/503/504）
- **state management**: `state.json` 記錄 `last_check` 時間戳避免重複處理
- **i18n**: 所有 UI 文字透過 `t("key")` 取得翻譯，新增文字需在 `i18n.py` 同時加 EN/ZH_TW（有兩個 zh_TW block，需同時更新）
- **報表模組命名**: `mod{NN}_{name}.py`，NN 為兩位數序號
- **config 預設值 merge**: 使用 `_deep_merge` 確保舊設定檔自動補齊新欄位
- **Windows 相容**: 日誌用 `os.name == "nt"` 判斷清屏指令，路徑用 `os.path.join`
- **Finding dataclass**: `rules_engine.py` 定義，欄位為 Python 屬性（`f.severity`），不是 dict（不可用 `f.get()`）
- **報表格式**: 預設輸出 HTML；CSV ZIP 使用 stdlib `zipfile`（零外部依賴）；Excel/.xlsx 已移除
- **VEN 離線偵測**: 使用 `hours_since_last_heartbeat` ≤ 1h，而非 `agent.status.status`
- **排程索引**: CLI 排程選單使用 1-based 顯示（`[{i+1}]`），`safe_input` 回傳後 `idx = int(input) - 1`
- **非同步流量查詢**: Illumio 25.2 起僅支援 async traffic query，**含草稿政策分析為 4 階段**：Submit → Poll → PUT update_rules（固定等 10s）→ Poll → Download；`draft_policy_decision` 欄位只在 update_rules 後才出現
- **draft_policy_decision 值**：`allowed` / `allowed_across_boundary` / `blocked_by_boundary` / `blocked_by_override_deny` / `blocked_no_rule` / `potentially_blocked_by_boundary` / `potentially_blocked_by_override_deny` / `potentially_blocked_no_rule`（動作 + 原因公式）
- **boundary_decision 值**（reported）：`blocked` / `blocked_by_override_deny` / `blocked_non_illumio_rule`
- **Draft PD filter UI**（Traffic Analysis Query）：Blocked (`blocked_by_boundary`) / Override Deny (`blocked_by_override_deny`) / Potentially Blocked / PB by Blocked (`potentially_blocked_by_boundary`) / PB by Override Deny (`potentially_blocked_by_override_deny`) / Allowed / All
- **config.json 路徑**：`config/config.json`（非根目錄），`ConfigManager()` 預設路徑為 `CONFIG_FILE = ROOT_DIR/config/config.json`
- **Multi-PCE**: `pce_profiles` 陣列儲存多組 PCE 憑證，`activate_pce_profile()` 切換時覆寫 `api.*`
- **規則排程器**: `rule_scheduler.py` 獨立於報表排程，管理 PCE ruleset 的定時啟用/停用
- **政策使用報表**: 第 4 種報表類型，透過 `batch_get_rule_traffic_counts` API 取得規則命中統計

## 部署檔案

| 檔案 | 適用平台 | 說明 |
|------|---------|------|
| `deploy/illumio-ops.service` | Ubuntu / Debian | ExecStart 指向 `venv/bin/python` |
| `deploy/illumio-ops-rhel.service` | RHEL / CentOS | ExecStart 指向 `/usr/bin/python3` |
| `deploy/install_service.ps1` | Windows | NSSM；自動偵測 `venv\Scripts\python.exe` |

Windows PS1 的 `$ProjectRoot` 是 `Split-Path -Parent $PSScriptRoot`（一層，`deploy/` → 專案根目錄）。

---

## 相關文件索引

| 需求 | 參考文件 |
|------|---------|
| 系統架構圖 | `docs/Project_Architecture.md` / `_zh.md` |
| 使用手冊 | `docs/User_Manual.md` / `_zh.md` |
| **安全偵測規則完整說明** | `docs/Security_Rules_Reference.md` / `_zh.md` |
| API 整合範例 | `docs/API_Cookbook.md` / `_zh.md` |
| Illumio REST API 參考 | `docs/REST_APIs_25_2.md` |
| Illumio 管理指南 | `docs/Illumio Core 25.2.10 Administration.md` |
| 品牌設計規範 | `docs/illumio_brand_guidelines.md` |
| 報表閾值設定 | `config/report_config.yaml` |
| CSV 欄位對映 | `config/csv_column_mapping.yaml` |
| macOS 開發環境 SOP | `docs/Dev_Environment_SOP.md` |

## 測試

```bash
# 單元測試
pytest tests/test_analyzer.py

# 稽核報表整合測試（使用 DummyApiClient）
python test_audit.py

# 真實 API 整合測試（需要 config.json 有效憑證）
python test_real_events.py
```
