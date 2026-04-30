# Illumio PCE Ops — 使用手冊

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
| Glossary | [Glossary.md](./Glossary.md) | [Glossary_zh.md](./Glossary_zh.md) |
| Troubleshooting | [Troubleshooting.md](./Troubleshooting.md) | [Troubleshooting_zh.md](./Troubleshooting_zh.md) |
<!-- END:doc-map -->

---

## 1. 執行模式

工具有四種執行方式，依需求選擇：

| 您的情境 | 推薦模式 | 啟動方式 |
|---|---|---|
| 一次性 CLI 操作（檢視規則、手動產生報表） | **互動式 CLI** | `python illumio-ops.py` |
| 只需要 Web 儀表板給非 CLI 使用者 | **獨立 Web GUI** | `python illumio-ops.py --gui` |
| 生產環境：持續監控 + 排程報表 + SIEM 派送，不需 GUI | **背景 Daemon** | `python illumio-ops.py --monitor --interval 5` |
| 生產環境：同主機需要持續監控 + Web GUI（建議預設） | **常駐模式** | `python illumio-ops.py --monitor-gui --interval 5 --port 5001` |

如不確定，請使用**常駐模式** — 它以單一程序涵蓋最常見情境（長駐 daemon + Web 存取）。對無瀏覽器存取的 headless server，使用單純的背景 Daemon。

systemd / NSSM 服務註冊請見 [§7 進階部署](#7-進階部署)。

### 1.1 互動式 CLI

```bash
python illumio-ops.py
```

啟動文字選單介面，可管理規則、設定及手動執行檢查。

```text
╭── Illumio PCE Ops
│ API: https://pce.lab.local:8443 | Rules: 16
│ Shortcuts: Enter=default | 0=back | -1=cancel | h/?=help
├────────────────────────────────────────────────────
│  1. Alert Rules
│  2. Report Generation
│  3. Rule Scheduler
│  4. System Settings
│  5. Launch Web GUI
│  6. View System Logs
│  7. Web GUI Security
│  0. Exit
╰────────────────────────────────────────────────────
```

選擇 **1. Alert Rules** 進入子選單：

```text
│ 1. Add Event Rule
│ 2. Add Traffic Rule
│ 3. Add Bandwidth & Volume Rule
│ 4. Manage Rules
│ 5. Load Official Best Practices
│ 6. Send Test Alert
│ 7. Run Analysis & Send Alerts
│ 8. Rule Simulation & Debug Mode
│ 0. Back
```

選擇 **2. Report Generation** 進入子選單：

```text
│ 1. Generate Traffic Flow Report
│ 2. Generate Audit Log Report
│ 3. Generate VEN Status Report
│ 4. Generate Policy Usage Report
│ 5. Report Schedule Management
│ 0. Back
```

選擇 **3. Rule Scheduler** 進入子選單：

```text
│ 1. Schedule Management (Add/Delete)
│ 2. Run Schedule Check Now
│ 3. Scheduler Settings (Enable/Disable Daemon, Interval)
│ 0. Back
```

> **注意**：**4. System Settings**、**5. Launch Web GUI** 與 **6. View System Logs** 為單步驟操作，無子選單。


### 1.2 Web GUI

```bash
python illumio-ops.py --gui
python illumio-ops.py --gui --port 8080    # 自訂連接埠
```

於 `http://127.0.0.1:5001` 開啟瀏覽器儀表板，包含以下分頁：

| 分頁 | 功能 |
|:---|:---|
| **Dashboard** | API 連線狀態、規則摘要、PCE 健康檢查；流量分析器含 Top-10 小工具（依頻寬 / 流量量 / 連線數）；已儲存的儀表板查詢 |
| **Rules** | Event/Traffic/Bandwidth/Volume 規則的完整 CRUD 操作、批次刪除、行內編輯 |
| **Reports** | 產生 Traffic、Audit、VEN Status 及 **Policy Usage** 報表；**批次刪除**支援多選；下載 HTML/CSV 原始資料 ZIP；保留期管理 |
| **Report Schedules** | 建立/編輯/切換週期排程（每日/每週/每月）含 Email 寄送；可手動觸發；查看執行歷史 |
| **Rule Scheduler** | 瀏覽所有 PCE 規則集；啟用/停用個別規則並可設定 TTL；佈建變更 |
| **Workload Search** | 依主機名稱/IP/標籤搜尋；套用隔離標籤（單一或批次） |
| **Settings** | API 憑證、告警通道、時區、語言/主題切換、**PCE 設定檔管理** |
| **Actions** | 執行單次監控、除錯模式、測試告警、載入最佳實務 |

### 1.3 背景 Daemon

```bash
python illumio-ops.py --monitor                 # 預設：每 10 分鐘
python illumio-ops.py --monitor --interval 5     # 每 5 分鐘
```

在背景無人值守運行。可正確處理 `SIGINT`/`SIGTERM` 訊號以進行乾淨關閉。

### 1.4 持續運行模式（Daemon + Web GUI）

```bash
python illumio-ops.py --monitor-gui --interval 10 --port 5001
```

此模式在單一程序中同時執行**背景 Daemon** 與 **Web GUI**。
- Daemon 在背景執行緒中運行。
- Flask Web GUI 在主執行緒中運行。
- **強制安全性**：驗證與 IP 過濾機制嚴格執行。
- **受限操作**：此模式下 `/api/shutdown` 端點被停用，以防止意外終止持續運行的服務。

### 1.5 命令列參考

```bash
python illumio-ops.py [OPTIONS]
```

| 參數 | 預設值 | 說明 |
|:---|:---|:---|
| `--monitor` | — | 以無頭 Daemon 模式執行 |
| `--monitor-gui` | — | 同時執行 Daemon + Web GUI（持續運行模式） |
| `-i` / `--interval N` | `10` | 監控間隔（分鐘） |
| `--gui` | — | 啟動獨立 Web GUI |
| `-p` / `--port N` | `5001` | Web GUI 連接埠 |
| `--report` | — | 從命令列產生報表 |
| `--report-type TYPE` | `traffic` | 報表類型：`traffic`、`audit`、`ven_status`、`policy_usage` |
| `--source api\|csv` | `api` | 報表資料來源 |
| `--file PATH` | — | CSV 檔案路徑（搭配 `--source csv` 使用） |
| `--format html\|csv\|all` | `html` | 報表輸出格式 |
| `--email` | — | 產生報表後透過 Email 寄送 |
| `--output-dir PATH` | `reports/` | 報表輸出目錄 |

**範例：**

```bash
# Generate HTML traffic report for the last 7 days and email it
python illumio-ops.py --report --format html --email

# Generate audit report
python illumio-ops.py --report --report-type audit

# Generate VEN status report
python illumio-ops.py --report --report-type ven_status

# Generate policy usage report from CSV export
python illumio-ops.py --report --report-type policy_usage --source csv --file workloader_export.csv

# Generate report from CSV export and save both HTML + raw CSV
python illumio-ops.py --report --source csv --file traffic_export.csv --format all

# Web GUI on a custom port
python illumio-ops.py --gui --port 8080
```

#### `illumio-ops` click 子命令

此套件同時提供 `illumio-ops` 入口點 CLI，包含以下子命令：

| 子命令 | 說明 | 範例 |
|---|---|---|
| `cache` | 管理本地 PCE 快取：backfill、狀態、保留期 | `illumio-ops cache backfill --source events --since 2026-01-01` |
| `monitor` | 執行單次監控循環（非 Daemon） | `illumio-ops monitor` |
| `gui` | 啟動獨立 Web GUI | `illumio-ops gui --port 8080` |
| `report` | 從 CLI 產生報表 | `illumio-ops report --type traffic --format html` |
| `rule` | 檢視已設定的監控規則 | `illumio-ops rule list --type traffic` |
| `siem` | 管理 SIEM 目的地：測試、清空、狀態 | `illumio-ops siem test splunk-hec` |
| `workload` | 取得並顯示 PCE workloads | `illumio-ops workload list --env prod --limit 100` |
| `config` | 驗證或顯示 `config.json` | `illumio-ops config validate` |
| `status` | 顯示 Daemon / 排程器 / 設定狀態 | `illumio-ops status` |
| `version` | 列印已安裝版本 | `illumio-ops version` |

> **Daemon 模式注意：** 使用 `--monitor-gui` 同時啟動排程器與 Web GUI（持續運行模式，建議用於正式環境）。僅使用 `--monitor` 時為不含 GUI 的無頭排程器。

> **SIEM 操作命令：** `illumio-ops siem test`、`illumio-ops siem flush`、`illumio-ops siem status`。

#### `illumio-ops cache` 子命令

| 命令 | 選項 | 說明 |
|---|---|---|
| `cache backfill` | `--source events\|traffic`、`--since YYYY-MM-DD`、`--until YYYY-MM-DD` | 從 PCE API 將歷史日期範圍的資料回填至本地 SQLite 快取 |
| `cache status` | — | 顯示 events、traffic_raw 及 traffic_agg 表的行數與最後攝入時間戳 |
| `cache retention` | — | 顯示已設定的保留政策（events、raw、aggregated） |

```bash
# Backfill the last 30 days of audit events
illumio-ops cache backfill --source events --since 2026-03-28

# Backfill traffic flows for a specific window
illumio-ops cache backfill --source traffic --since 2026-03-01 --until 2026-03-31

# Check cache health
illumio-ops cache status
```

快取必須在 `config.json` 中啟用（`pce_cache.enabled: true`）後，backfill 命令才能成功執行。

#### `illumio-ops siem` 子命令

| 命令 | 選項 | 說明 |
|---|---|---|
| `siem test <name>` | 目的地名稱引數 | 傳送合成 `siem.test` 事件至指定目的地；成功時回報延遲 |
| `siem status` | — | 顯示各目的地的待傳送 / 已傳送 / 失敗數量及 DLQ 深度 |
| `siem dlq --dest <name>` | `--limit N`（預設 50） | 列出指定目的地的死信佇列項目 |
| `siem replay --dest <name>` | `--limit N`（預設 100） | 將 DLQ 項目重新排入待傳送佇列 |
| `siem purge --dest <name>` | `--older-than N`（預設 30 天） | 刪除超過 N 天的 DLQ 項目 |

```bash
# Test a Splunk HEC destination
illumio-ops siem test splunk-hec

# Check dispatch health
illumio-ops siem status

# Inspect the DLQ
illumio-ops siem dlq --dest splunk-hec --limit 20

# Replay up to 500 entries after fixing the root cause
illumio-ops siem replay --dest splunk-hec --limit 500

# Clean up entries older than 7 days
illumio-ops siem purge --dest splunk-hec --older-than 7
```

#### `illumio-ops rule` 子命令

| 命令 | 選項 | 說明 |
|---|---|---|
| `rule list` | `--type event\|traffic\|bandwidth\|volume\|system\|all`、`--enabled-only` | 列出所有已設定的監控規則，可依類型過濾 |

```bash
# List all rules
illumio-ops rule list

# List only traffic rules
illumio-ops rule list --type traffic

# List only enabled traffic rules
illumio-ops rule list --type traffic --enabled-only
```

#### `illumio-ops workload` 子命令

| 命令 | 選項 | 說明 |
|---|---|---|
| `workload list` | `--env <value>`、`--limit N`（預設 50）、`--enforcement full\|selective\|visibility_only\|idle\|all`、`--managed-only` | 從 PCE 取得並顯示 workloads，可選擇性過濾 |

```bash
# List production workloads
illumio-ops workload list --env prod

# List all VEN-managed workloads in full enforcement
illumio-ops workload list --enforcement full --managed-only --limit 200
```

#### `illumio-ops config` 子命令

| 命令 | 選項 | 說明 |
|---|---|---|
| `config validate` | `--file <path>` | 依 Pydantic schema 驗證 `config.json`；成功時退出代碼 0，失敗時列印錯誤 |
| `config show` | `--section <name>` | 格式化列印目前設定（或指定區段：`api`、`smtp`、`web_gui` 等） |

```bash
# Validate the default config.json
illumio-ops config validate

# Validate a specific file
illumio-ops config validate --file /opt/illumio_ops/config/config.json

# Show only the web_gui section
illumio-ops config show --section web_gui
```

---

## 2. 規則類型與設定

### 規則、警示、報表的關係

三條 runtime 流程共用相同資料來源，但產出不同：

```text
                        ┌─ 事件規則 ──────► event_alerts ─┐
   PCE 事件 ──► 快取 ─────┤                                  ├─► Reporter ──► Email / LINE / Webhook
                        └─ 流量規則 ──────► traffic_alerts ─┘
   PCE 流量 ──► 快取 ─────┐
                        └─ 頻寬規則 ──────► metric_alerts ────► Reporter
   健康檢查        ──────► health_alerts ────────────────────► Reporter

   快取 ──► 報表引擎 ──► HTML / CSV（15 traffic + 4 audit + Policy Usage + VEN Status）
   快取 ──► SIEM 派送器 ──► CEF / JSON / HEC out
```

- **規則**（本節）決定*何時*發出警示（基於 PCE 資料）。
- **[警示通道](#4-警示通道)** 決定*發到哪裡*（Email / LINE / Webhook）。
- **[報表](Report_Modules_zh.md)** 與規則無關 — 不論規則是否觸發，都依排程匯總資料。
- **[SIEM 派送](SIEM_Integration_zh.md)** 也與規則無關 — 將快取中的原始事件 / 流量轉送到 SIEM。

典型生產設定三者並用：規則觸發警示給 Email/LINE 做事件回應；報表每週寄給利害關係人；SIEM 持續接收以便事後鑑識。

### 2.1 事件規則

監控 PCE 稽核事件（例如 `agent.tampering`、`user.sign_in`）。

| 參數 | 說明 | 範例 |
|:---|:---|:---|
| **Event Type** | PCE 事件識別碼 | `agent.tampering` |
| **Threshold Type** | `immediate`（首次出現即告警）或 `count`（累計） | `count` |
| **Threshold Count** | 觸發告警前需達到的次數 | `5` |
| **Time Window** | 滾動時間窗口（分鐘） | `10` |
| **Cooldown** | 重複告警的最小間隔 | `30` |

**內建事件目錄**（可透過 CLI/GUI 存取）：

| 分類 | 事件 |
|:---|:---|
| Agent Health | `agent_missed_heartbeats`、`agent_offline`、`agent_tampering` |
| Authentication | `login_failed`、`authentication_failed` |
| Policy Changes | `ruleset_create/update`、`rule_create/delete`、`policy_provision` |
| Workloads | `workload_create`、`workload_delete` |

> **登入失敗告警**會在告警內文中包含使用者名稱與來源 IP 位址，以利快速分類處理。

### 2.2 流量規則

透過計算匹配的流量記錄來偵測連線異常。

| 參數 | 說明 |
|:---|:---|
| **Policy Decision** | `Blocked (2)`、`Potentially Blocked (1)`、`Allowed (0)` 或 `All (3)` |
| **Port / Protocol** | 依目的埠（例如 `443`）或 IP 協定號（例如 TCP 為 `6`）過濾 |
| **Source/Dest Label** | 精確標籤匹配，格式為 `key=value`（例如 `role=Web`） |
| **Source/Dest IP** | IP 位址或 CIDR 範圍（例如 `10.0.0.0/24`） |
| **Filter Direction** | `src_and_dst`（預設，雙方皆須匹配）或 `src_or_dst`（任一方匹配） |
| **Excludes** | 排除過濾器：標籤（`ex_src_labels`、`ex_dst_labels`）、IP（`ex_src_ip`、`ex_dst_ip`）或埠 |

**過濾方向選項：**

| 模式 | 行為 |
|:---|:---|
| **Src AND Dst**（預設） | 來源與目的端的標籤/IP 須同時匹配各自的過濾條件 |
| **Src only** | 僅指定來源過濾條件 — 目的端不限 |
| **Dst only** | 僅指定目的端過濾條件 — 來源端不限 |
| **Src OR Dst** | 指定的標籤出現在來源端或目的端任一方即匹配 |

### 2.3 頻寬與流量量規則

偵測資料外洩模式。

| 類型 | 指標 | 單位 | 計算方式 |
|:---|:---|:---|:---|
| **Bandwidth** | 峰值傳輸速率 | 自動調整（bps/Kbps/Mbps/Gbps） | 所有匹配流量的最大值 |
| **Volume** | 累計資料傳輸量 | 自動調整（B/KB/MB/GB） | 所有匹配流量的總和 |

> **混合計算**：系統優先使用「差量間隔」指標。對於無可測量差量的長期連線，會回退使用「生命週期總量」，以防止外洩行為逃脫偵測。

> **自動調整單位**：頻寬與流量量的值會自動格式化為最適當的單位（例如 1500 bps → "1.5 Kbps"、2048 MB → "2.0 GB"）。

---

## 3. Web GUI 安全性

所有 Web GUI 模式均需要驗證，並支援來源 IP 限制。

### 首次登入

**預設帳號：** `illumio`。首次啟動時若 `web_gui.password` 為空，系統會自動產生隨機初始密碼（URL-safe，12 byte），存於 `config.json` 的 `web_gui._initial_password` 欄位，並將帳號標記為 `must_change_password=true`，強制使用者於首次登入後變更密碼方可使用其他功能。

1. 從 console banner / log 輸出（或直接從 `config/config.json` → `web_gui._initial_password`）取得初始密碼。
2. 登入後 GUI 會自動導向 **Settings → Web GUI Security** 設定新密碼。
3. 建議設定 **IP 允許清單**以限制存取來源。

> **密碼重設**：若遺失密碼，請刪除 `config/config.json` 中的 `web_gui.password` 與（若存在）`web_gui._initial_password`。下次啟動時會重新產生初始密碼並重新觸發強制變更流程。

### 3.1 身份驗證

- **密碼儲存**：以 Argon2id 雜湊（`$argon2id$…`）儲存於 `config.json` 的 `web_gui.password`，由 `argon2-cffi` 產生（`time_cost=3`、`memory_cost=64MiB`、`parallelism=4`）。若管理員手動填入明文，下次載入會自動被雜湊。
- **首次登入強制變更**：當 `web_gui.must_change_password` 為 true 時，除登出/變更密碼端點外，所有 GUI 端點皆回傳 HTTP 423，直到使用者完成變更。
- **登入速率限制**：每個 IP 每分鐘最多 5 次嘗試（超過回傳 HTTP 429），由 flask-limiter 管理。
- **CSRF 防護**：flask-wtf CSRFProtect — token 透過 `X-CSRF-Token` 回應標頭及 `<meta>` 標籤傳遞；所有變更請求（POST/PUT/DELETE）均需驗證。
- **安全標頭**：flask-talisman 自動設定 `Content-Security-Policy`（每請求 nonce、移除 `unsafe-inline`）、`X-Frame-Options: DENY`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: strict-origin-when-cross-origin`；啟用 TLS 時自動開啟 HSTS。
- **Session 管理**：flask-login session 保護（strong 模式）；安全簽章 Cookie（密鑰自動產生於 `config.json` 中）。
- **設定方式**：透過 **CLI 選單 7. Web GUI Security** 或 Web GUI **Settings** 頁面變更帳密。
- **SMTP 憑證**：可設定 `ILLUMIO_SMTP_PASSWORD` 環境變數，避免在設定檔中儲存密碼

### 3.2 IP 允許清單

限制僅特定管理工作站或子網路可存取。
- **格式**：支援單一 IP（例如 `192.168.1.50`）或 CIDR 區塊（例如 `10.0.0.0/24`）。
- **預設**：若清單為空，則所有 IP 皆可存取（前提是通過身份驗證）。
- **執行方式**：中介軟體於每次請求時檢查 `X-Forwarded-For` 或遠端位址。

---

## 4. 告警通道

三個通道可同時運作。在 `config.json` → `alerts.active` 中啟用：

```json
{
    "alerts": {
        "active": ["mail", "line", "webhook"]
    }
}
```

### 4.1 Email（SMTP）

```json
{
    "email": { "sender": "monitor@company.com", "recipients": ["soc@company.com"] },
    "smtp": { "host": "smtp.company.com", "port": 587, "user": "", "password": "", "enable_auth": true, "enable_tls": true }
}
```

### 4.2 LINE Messaging API

```json
{
    "alerts": {
        "line_channel_access_token": "YOUR_TOKEN",
        "line_target_id": "USER_OR_GROUP_ID"
    }
}
```

### 4.3 Webhook

```json
{
    "alerts": {
        "webhook_url": "https://hooks.slack.com/services/xxx/yyy/zzz"
    }
}
```

傳送標準化 JSON 酬載，包含 `health_alerts`、`event_alerts`、`traffic_alerts` 及 `metric_alerts` 陣列。相容於 Slack、Microsoft Teams 及自訂 SOAR 端點。

---

## 5. 隔離（Workload 隔離）

隔離功能讓您能以嚴重性標籤標記受損的 workloads，這些標籤可用於 Illumio 政策規則中以限制其網路存取。

### 工作流程

1. 透過 Web GUI → **Workload Search** **搜尋**目標 workload（依主機名稱、IP 或標籤）
2. **選擇**一個或多個 workloads，然後選擇隔離等級：`Mild`、`Moderate` 或 `Severe`
3. 系統會在 PCE 中**自動建立** Quarantine 標籤類型（若尚不存在）
4. 系統會將 Quarantine 標籤**附加**至每個 workload 的現有標籤上（保留所有其他標籤）

**單一 vs. 批次套用**：選擇單一 workload 後點選 **Apply Quarantine** 進行個別隔離。勾選多個 workloads 後點選 **Bulk Quarantine** 以平行方式隔離（最多 5 個並行 API 呼叫）。

> **重要**：隔離標籤本身不會阻擋流量。您必須在 PCE 中建立對應的 **Enforcement Boundaries** 或 **Deny Rules**，引用 `Quarantine` 標籤鍵才能實際限制流量。

---

## 6. 多 PCE Profile 管理

系統支援透過 Profile 管理同時監控多個 PCE 實例。

### 6.1 概觀

Profile 儲存 PCE 連線憑證（URL、org ID、API key、secret），可在執行時切換而無需重新啟動應用程式。

### 6.2 設定

透過以下方式管理 Profile：
- **Web GUI**：Settings → PCE Profiles 區段（新增、編輯、刪除、啟用）
- **CLI**：System Settings 選單
- **config.json**：直接編輯 `pce_profiles` 陣列與 `active_pce_id`

```json
{
    "active_pce_id": "production",
    "pce_profiles": [
        {
            "name": "production",
            "url": "https://pce-prod.company.com:8443",
            "org_id": "1",
            "key": "api_xxx",
            "secret": "xxx"
        },
        {
            "name": "lab",
            "url": "https://pce-lab.company.com:8443",
            "org_id": "1",
            "key": "api_yyy",
            "secret": "yyy"
        }
    ]
}
```

### 6.3 Profile 切換

當您啟用一個 Profile 時，系統會：
1. 將該 Profile 的憑證複製至頂層 `api` 區段
2. 以新憑證重新初始化 `ApiClient`
3. 後續所有 API 呼叫使用新的 PCE 連線

> **注意**：所有規則與報表排程適用於目前啟用的 PCE Profile。切換 Profile 不會重設現有規則。

---

## 7. 進階部署

### 7.1 Windows 服務（NSSM）

```powershell
nssm install IllumioOps "C:\Python312\python.exe" "C:\illumio-ops\illumio-ops.py" --monitor --interval 5
nssm set IllumioOps AppDirectory "C:\illumio-ops"
nssm start IllumioOps
```

### 7.2 Linux systemd

> **建議的 Daemon 參數：** 使用 `--monitor-gui` 在單一程序中同時執行排程器與 Web GUI（持續運行模式）。僅使用 `--monitor` 時為不含 GUI 的無頭 Daemon。

#### RHEL / CentOS（系統 Python）

```ini
# /etc/systemd/system/illumio-ops.service
[Unit]
Description=Illumio PCE Ops
After=network.target

[Service]
Type=simple
User=illumio
WorkingDirectory=/opt/illumio_ops
ExecStart=/usr/bin/python3 /opt/illumio_ops/illumio-ops.py --monitor-gui --interval 5
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

#### Ubuntu / Debian（venv）

先建立 venv，然後將 `ExecStart` 指向 venv 直譯器：

```bash
cd /opt/illumio_ops
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

```ini
# /etc/systemd/system/illumio-ops.service
[Unit]
Description=Illumio PCE Ops
After=network.target

[Service]
Type=simple
User=illumio
WorkingDirectory=/opt/illumio_ops
ExecStart=/opt/illumio_ops/venv/bin/python illumio-ops.py --monitor-gui --interval 5
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now illumio-ops
```


---

## 8. 規則排程器

規則排程器根據時間窗口自動啟用或停用 PCE 安全規則（Rule 或 Ruleset）。適用場景包括維護窗口、僅限營業時間的存取政策，以及具自動到期功能的暫時允許規則。

### 8.1 排程類型

| 類型 | 說明 | 範例 |
|:---|:---|:---|
| **Recurring** | 在指定日期的時間窗口內重複執行 | 週一至週五 09:00–17:00 |
| **One-time** | 在指定到期日時間前有效，之後自動還原 | 於 2026-04-10 18:00 到期 |

> **午夜跨越**：循環排程支援跨越午夜的時間窗口（例如 22:00–06:00）。系統可正確判斷「現在」是否位於跨越窗口內。

### 8.2 CLI

透過 CLI 主選單 **3. Rule Scheduler** 存取：
- **1. Schedule Management** — 瀏覽所有 Rulesets/Rules 並新增/移除排程
- **2. Run Schedule Check Now** — 手動觸發排程引擎
- **3. Scheduler Settings** — 啟用/停用背景 Daemon 並設定檢查間隔

### 8.3 Web GUI

透過 **Rule Scheduler** 分頁存取：
- 瀏覽所有 Rulesets 並展開個別 Rules
- 依名稱快速搜尋 Rulesets
- 建立 **Recurring**（基於時間窗口）或 **One-time**（自動到期）排程
- 在 **Logs** 子分頁中查看即時排程日誌

### 8.4 Draft 政策保護

> **重要**：Illumio PCE 的 Provision 操作會**一次性部署所有 draft 政策變更**。若排程執行 Provision 時某條規則處於 Draft 狀態（表示有人正在編輯），**該政策版本中所有未完成的 draft 變更都會被部署** — 這是潛在的嚴重安全風險。

系統實作了**多層 Draft 狀態保護**：

| 保護層 | 位置 | 行為 |
|:---|:---|:---|
| **CLI — Add Schedule** | `rule_scheduler_cli.py` | 若規則**或其父 Ruleset** 處於 Draft 狀態，則阻止排程建立；顯示錯誤訊息 |
| **Web GUI — Add Schedule** | `gui.py` API | 相同檢查；以 `Unprovisioned rules cannot be scheduled` 拒絕 POST 請求 |
| **Scheduler Engine — At Runtime** | `rule_scheduler.py` | 若排程的規則在執行時被發現處於 Draft 狀態，跳過 Provision 並寫入 `[SKIP]` 日誌 |
| **API Client Layer** | `api_client.has_draft_changes()` | 核心輔助方法：檢查規則本身**及**其父 Ruleset 是否有待定的 Draft 變更 |

#### 偵測邏輯（父 Ruleset 優先）

```
1. 取得規則的 Draft 版本 → 若 update_type 非空 → DRAFT（停止）
2. 若為子規則（href 包含 /sec_rules/）→ 取得父 Ruleset 的 Draft 版本
   → 若父 Ruleset 的 update_type 非空 → DRAFT（停止）
3. 兩者皆無 Draft 變更 → 可安全繼續
```

#### 日誌輸出

- Draft 阻止排程**設定嘗試** → 僅在畫面上顯示錯誤，不寫入日誌檔
- Draft 阻止排程**執行** → 寫入 `WARNING` 等級日誌條目以供稽核

```
[SKIP] CoreServices_Rule_1499 (ID:1499) is in DRAFT state. Operation aborted.
```

---

## 9. 設定參考

所有設定都在 `config/config.json`。下方為頂層結構，後續小節說明非顯而易見的區塊。

```text
{
  "pce_profiles":   [ … ]            // 多 PCE profile 槽位（見 §6）
  "active_pce_id":  …                // 目前選用的 profile id
  "api":            { … }            // 啟用 profile 的鏡像（自動同步）
  "alerts":         { active: [], line_*, webhook_url }   // §4 通道
  "email":          { sender, recipients }                // §4.1
  "smtp":           { host, port, user, password, … }     // §4.1
  "settings":       { timezone, language, theme, … }      // §9.1、§9.2
  "rules":          [ … ]            // 事件 / 流量 / 頻寬規則（§2）
  "report":         { schedule, format, retention_days, … }  // §9.3
  "report_schedules": [ … ]                               // 排程報表（§8 / §9.5）
  "rule_scheduler": { enabled, check_interval_seconds }   // §8
  "web_gui":        { username, password (Argon2id), tls, allowed_ips }  // §3 / §9.4
  "pce_cache":      { enabled, db_path, *_retention_days, … }  // §9.6 / PCE_Cache_zh.md
  "siem":           { … }            // SIEM forwarder（SIEM_Integration_zh.md）
  "logging":        { json_sink, level }                  // §5 / Troubleshooting_zh.md
}
```

### 最小設定 — 起步

讓工具可運作的最小檔案內容只需 PCE 認證 + 一個告警收件人。把以下內容放入 `config/config.json`，工具首次啟動時會自動補齊其他欄位的預設值：

```json
{
    "pce_profiles": [
        {
            "id": 1,
            "name": "Production PCE",
            "url": "https://pce.example.com:8443",
            "org_id": "1",
            "key": "api_xxxxxxxxxxxxxx",
            "secret": "your-api-secret-here",
            "verify_ssl": true
        }
    ],
    "active_pce_id": 1,
    "email": { "sender": "monitor@example.com", "recipients": ["soc@example.com"] },
    "smtp":  { "host": "smtp.example.com", "port": 587, "enable_auth": true, "enable_tls": true }
}
```

首次啟動後，檔案會自動補上 `web_gui.password`（Argon2id）、`web_gui.secret_key`、預設 TLS 設定等。完整範本請見 `config/config.json.example`。

### 9.1 時區

時區設定控制報表及排程輸入欄位中時間戳的顯示方式。可在 Web GUI → **Settings → Timezone** 中設定，或直接編輯 `config.json`：

```json
{
    "settings": {
        "timezone": "UTC+8"
    }
}
```

支援格式：`local`（系統時區）、`UTC`、`UTC+8`、`UTC-5`、`UTC+5.5`

> 排程時間在內部始終以 **UTC 儲存**。CLI 精靈與 Web GUI 排程視窗會自動轉換至您設定的時區進行顯示。

### 9.2 儀表板查詢

Dashboard 分頁支援儲存自訂流量查詢以供重複使用。每個已儲存的查詢會記錄過濾參數（政策決策、埠、標籤、IP 範圍、過濾方向），並可從 Dashboard 隨時執行以填入 Top-10 小工具。

查詢儲存於 `config.json` → `settings.dashboard_queries`，完全透過 Web GUI 管理。

### 9.3 報表輸出

控制報表的儲存位置與保留時間。

| 設定 | 預設值 | 說明 |
|:---|:---|:---|
| `report.output_dir` | `reports/` | 產生報表的目錄（相對於專案根目錄，或絕對路徑） |
| `report.retention_days` | `30` | 每次排程執行後，自動刪除超過此天數的 `.html`/`.zip` 報表。設為 `0` 停用。 |

**從 Web GUI 設定**：Settings → **Report Output** 欄位群組
**從 CLI 設定**：System Settings 選單 → **4. System Settings**
**從 `config.json` 設定**：
```json
{
    "report": {
        "output_dir": "reports/",
        "retention_days": 30
    }
}
```

### 9.4 Web GUI

`config.json` 中的 `web_gui` 區塊控制驗證與網頁伺服器綁定設定。

| 鍵 | 類型 | 預設值 | 說明 |
|---|---|---|---|
| `web_gui.username` | string | `illumio` | 單一管理員帳號的登入使用者名稱 |
| `web_gui.password` | string | *(空 → 自動產生)* | **Argon2id 雜湊**（`$argon2id$…`）。手動填入的明文於下次載入時自動雜湊。空值會觸發初始密碼產生 + 強制變更流程。 |
| `web_gui._initial_password` | string | *(自動)* | 自動產生的初始密碼明文副本；首次成功登入後即被消耗並移除。 |
| `web_gui.must_change_password` | bool | *(自動)* | 強制變更旗標；使用者完成變更後清除。 |
| `web_gui.allowed_ips` | list | `[]` | IP 允許清單 — 空清單允許所有來源 |
| `web_gui.tls.enabled` | bool | `true` | 啟用 HTTPS。若未提供 `cert_file`/`key_file`，自動產生自簽憑證。 |
| `web_gui.tls.key_algorithm` | string | `ecdsa-p256` | 自簽憑證金鑰演算法。支援：`ecdsa-p256`、`rsa-2048`、`rsa-3072`。 |
| `web_gui.tls.min_version` | string | `TLSv1.2` | 最低 TLS 協定版本。 |
| `web_gui.tls.validity_days` | int | `397` | 自簽憑證有效期（CA/B Forum 對公開信任憑證的最大值）。 |
| `web_gui.tls.auto_renew` | bool | `true` | 距到期日 `auto_renew_days` 內自動續簽。 |
| `web_gui.tls.http_redirect_port` | int | `80` | 重新導向至 HTTPS 的 HTTP 連接埠（設為 `0` 停用導向）。 |

**連接埠：** GUI 連接埠透過命令列 `--port N` 設定（預設 `5001`）；不儲存於 `config.json`。

**綁定主機：** GUI 綁定位址透過命令列 `--host` 設定（預設 `127.0.0.1`）；不儲存於 `config.json`。

> **首次登入流程：** 啟動時若 `web_gui.password` 為空，系統會產生初始密碼寫入 `web_gui._initial_password`，並強制使用者於首次登入後變更。可從 console banner / log 或 `config.json` 直接讀取此值。

### 9.5 報表智能

這些鍵位於 `config.json` 的 `report` 區塊下，控制進階報表行為。

| 鍵 | 類型 | 預設值 | 說明 |
|---|---|---|---|
| `report.snapshot_retention_days` | int | `90` | 變更影響（`mod_change_impact`）KPI 快照在自動刪除前保留的天數 |
| `report.draft_actions_enabled` | bool | `true` | `mod_draft_actions` 是否在 Traffic Report 中產生逐流量的修復建議 |

`config.json` 範例片段：

```json
{
    "report": {
        "snapshot_retention_days": 90,
        "draft_actions_enabled": true
    }
}
```

### 9.6 PCE 快取

`pce_cache` 區塊控制本地 SQLite 快取，用於儲存事件與流量記錄以供快速離線分析。鍵參考：

| 鍵 | 類型 | 預設值 | 說明 |
|---|---|---|---|
| `pce_cache.enabled` | bool | `false` | 啟用從 PCE 的背景擷取 |
| `pce_cache.db_path` | string | `data/pce_cache.sqlite` | SQLite 資料庫檔案（相對於專案根目錄或絕對路徑） |
| `pce_cache.events_retention_days` | int | `90` | 保留稽核事件的天數 |
| `pce_cache.traffic_raw_retention_days` | int | `7` | 保留原始逐流量記錄的天數 |
| `pce_cache.traffic_agg_retention_days` | int | `90` | 保留小時聚合流量 |
| `pce_cache.events_poll_interval_seconds` | int | `300` | 事件輪詢器頻率 |
| `pce_cache.traffic_poll_interval_seconds` | int | `3600` | 流量輪詢器頻率（非同步查詢） |
| `pce_cache.rate_limit_per_minute` | int | `400` | 每分鐘最大 PCE API 呼叫數（最多 500） |

完整啟用 JSON、表格參考、磁碟空間規畫、監控、保留調校（`cache retention --run`）、backfill 流程、cache 警示機制請見 **[PCE 快取](PCE_Cache_zh.md)** — 該文件為此子系統的單一真相源。

> **SIEM 相依性：** SIEM 轉送器需要啟用 PCE 快取。流量與事件資料先擷取至 `pce_cache.sqlite`，再從 `siem_dispatch` 表發送至 SIEM 目的地。

### 9.7 告警通道參考

| 通道 | 設定鍵 | 驗證需求 |
|---|---|---|
| Email（SMTP） | `smtp.host`、`smtp.port`、`smtp.user`、`smtp.password`、`smtp.enable_tls` | 視伺服器而定；`smtp.enable_auth: false` 用於未驗證的中繼 |
| LINE Messaging API | `alerts.line_channel_access_token`、`alerts.line_target_id` | LINE Developer Console：Channel Access Token + User/Group ID |
| Webhook | `alerts.webhook_url` | 呼叫端提供包含任何 auth token 的完整 URL |

透過將識別碼加入 `alerts.active` 來啟用通道：

```json
{
    "alerts": {
        "active": ["mail", "line", "webhook"]
    }
}
```

未列入 `alerts.active` 的通道即使已填入憑證也會靜默跳過。

**告警內文欄位**（無論通道為何，每則告警均包含）：

| 欄位 | 說明 |
|---|---|
| `rule_name` | 觸發規則的名稱 |
| `rule_type` | `event`、`traffic`、`bandwidth` 或 `volume` |
| `trigger_value` | 導致告警的測量值 |
| `threshold` | 已超過的設定閾值 |
| `timestamp` | 觸發事件的 UTC ISO-8601 時間戳 |
| `pce_url` | 提供背景資訊的活躍 PCE Profile URL |

> **登入失敗告警**包含來自 PCE 稽核事件的來源 IP 與使用者名稱，無需另外查詢 PCE Console 即可快速分類。

> **Cooldown：** 每條規則均有可設定的 cooldown 期間（分鐘）。在 cooldown 到期前，相同規則不會再次觸發告警，防止重複相同事件造成告警風暴。

> **測試告警：** 使用 CLI 選項 **1. Alert Rules → 6. Send Test Alert** 或 `illumio-ops` Web GUI → **Actions → Test Alert** 在正式環境使用前驗證告警通道已正確設定且可連線。

---

## 10. 疑難排解

| 症狀 | 原因 | 解決方案 |
|:---|:---|:---|
| `Connection refused` | PCE 無法連線 | 確認 `api.url` 與網路連線 |
| `401 Unauthorized` | API 憑證無效 | 在 PCE Console 重新產生 API Key |
| `410 Gone` | 非同步查詢已過期 | 流量查詢結果已被清理；重新執行查詢 |
| `429 Too Many Requests` | API 速率限制 | 系統會自動以退避策略重試；若持續發生請降低查詢頻率 |
| Web GUI 無法啟動 | 相依套件未安裝 | **Ubuntu/Debian**：使用 venv — `venv/bin/pip install -r requirements.txt`。**RHEL**：`python3 -m venv venv && venv/bin/pip install -r requirements.txt` |
| `externally-managed-environment` pip 錯誤 | Ubuntu/Debian PEP 668 | 建立 venv：`python3 -m venv venv && venv/bin/pip install -r requirements.txt` |
| 未收到告警 | 通道未啟用 | 確認 `alerts.active` 陣列包含您的通道 |
| 報表顯示所有 VEN 均為線上 | 舊的快取狀態 | 確認您的 PCE 版本有回傳 `hours_since_last_heartbeat`；檢查 PCE API 回應中的 `agent.status` 欄位 |
| Rule Scheduler 顯示 `[SKIP]` 日誌 | 規則或父 Ruleset 處於 Draft 狀態 | 在 PCE Console 完成並 Provision 政策編輯；排程將自動恢復 |
| PCE Profile 切換無效果 | ApiClient 未重新初始化 | 使用 GUI「Activate」按鈕或 CLI Profile 切換，會觸發重新初始化 |
| Policy Usage 報表顯示 0 命中 | 規則僅為 draft 狀態 | 僅查詢 active（已佈建）的規則；請先佈建 draft 規則 |
| `PDF export is not available in this build` | 離線 bundle 排除了 reportlab（純 Python；不需要 WeasyPrint/Pango/Cairo/GTK） | 改用 `--format html` 或 `--format xlsx` |
| 升級後：載入舊設定 | `config.json` 依原樣保留 | 與 `config.json.example` 比較並新增任何新欄位 |
| Windows：`nssm.exe not found` | NSSM 不在 PATH 或 bundle deploy\ 中 | 將 `nssm.exe` 加入 PATH 或放置於 bundle `deploy\` 資料夾 |
| `Cache database not configured` | `pce_cache.enabled` 為 false 或 `db_path` 不正確 | 設定 `pce_cache.enabled: true` 並確認 `db_path` 可寫入 |
| SIEM 測試事件失敗顯示 `Destination not found` | 目的地名稱不符或 `enabled: false` | 確認 `siem.destinations[].name` 與引數一致；確認 `enabled: true` |
| `mod_change_impact` 顯示 `skipped: no_previous_snapshot` | 首次報表執行或快照已刪除 | 在首次報表後再產生一次；快照保留 `report.snapshot_retention_days` 天 |
| `config validate` 以非零退出並出現 pydantic 錯誤 | `config.json` 中有未知鍵或類型錯誤 | 修正回報的欄位；參閱 `config.json.example` 作為參考 |
| 解除安裝後重新安裝，Web GUI 登入失敗 | 保留了含舊 Argon2id `web_gui.password` 的 `config.json` | 雜湊密碼在升級間保留；使用先前設定的密碼登入，或刪除 `web_gui.password`（與 `_initial_password`，若存在）以重新觸發初始密碼產生流程。 |
| `--purge` 意外移除設定 | 執行了 `uninstall.sh --purge` | `--purge` 旗標文件記載為具破壞性；請從備份還原。不含 `--purge` 時設定始終保留。 |


## 延伸閱讀

- [安裝指南](./Installation_zh.md) — 系統需求、各平台安裝步驟、config.json
- [報表模組](./Report_Modules_zh.md) — 流量報表、安全發現、R3 智能、policy usage
- [SIEM 整合](./SIEM_Integration_zh.md) — SIEM 轉送設定、DLQ、傳輸層選擇
- [Security Rules Reference](./Security_Rules_Reference_zh.md) — R-Series 規則與 `compute_draft` 行為
