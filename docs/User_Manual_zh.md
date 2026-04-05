# Illumio PCE Ops — 使用手冊

> **[English](User_Manual.md)** | **[繁體中文](User_Manual_zh.md)**

---

## 1. 安裝與前置需求

### 1.1 系統需求
- **Python 3.8+**（已測試至 3.12）
- 可透過 HTTPS 連線至 Illumio PCE（預設埠 `8443`）
- **（選用）** `pip install flask` — 僅 Web GUI 模式需要

### 1.2 安裝步驟

#### Red Hat / CentOS（RHEL 8+）

```bash
git clone <repo-url>
cd illumio_ops
cp config/config.json.example config/config.json

# 從 AppStream 安裝選用相依套件（無需 EPEL）
sudo dnf install python3-flask python3-pandas python3-pyyaml
```

#### Ubuntu / Debian

現代 Ubuntu（22.04+）與 Debian（12+）實施 **PEP 668** 機制，直接執行 `pip install` 會被系統阻擋以保護系統 Python 環境。請使用虛擬環境：

```bash
# 若尚未安裝 venv 支援，先執行
sudo apt install python3-venv

git clone <repo-url>
cd illumio_ops
cp config/config.json.example config/config.json

# 在專案目錄內建立並啟動虛擬環境
python3 -m venv venv
source venv/bin/activate          # bash/zsh
# source venv/bin/activate.fish   # Fish shell

pip install -r requirements.txt
```

> **注意**：每次開啟新的終端機視窗後，執行程式前需先重新啟動虛擬環境（`source venv/bin/activate`）。

#### macOS / 其他（pip）

```bash
git clone <repo-url>
cd illumio_ops
pip install -r requirements.txt
```

### 1.3 設定檔（`config.json`）

複製範例設定檔後填入 PCE API 憑證：

```bash
cp config/config.json.example config/config.json
```

| 欄位 | 說明 | 範例 |
|:---|:---|:---|
| `api.url` | PCE 主機名稱含連接埠 | `https://pce.lab.local:8443` |
| `api.org_id` | 組織 ID | `"1"` |
| `api.key` | API Key 使用者名稱 | `"api_1a2b3c4d5e6f"` |
| `api.secret` | API Key 密鑰 | `"your-secret-here"` |
| `api.verify_ssl` | SSL 憑證驗證 | `true` 或 `false` |

> **如何取得 API Key**：在 PCE 網頁主控台點選 **使用者選單 → My API Keys → Add**。選擇適當角色（監控最低需 `read_only`，隔離操作需 `owner`）。

---

## 2. 執行模式

### 2.1 互動式 CLI

```bash
python illumio_ops.py
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


### 2.2 Web GUI

```bash
python illumio_ops.py --gui
python illumio_ops.py --gui --port 8080    # 自訂連接埠
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

### 2.3 背景常駐模式

```bash
python illumio_ops.py --monitor                 # 預設：每 10 分鐘
python illumio_ops.py --monitor --interval 5     # 每 5 分鐘
```

在背景無人值守運行。可正確處理 `SIGINT`/`SIGTERM` 訊號以進行乾淨關閉。

### 2.4 持續運行模式（Daemon + Web GUI）

```bash
python illumio_ops.py --monitor-gui --interval 10 --port 5001
```

此模式在單一程序中同時執行 **背景常駐模式** 與 **Web GUI**。
- 常駐程序在背景執行緒中運行。
- Flask Web GUI 在主執行緒中運行。
- **強制安全性**：驗證與 IP 過濾機制嚴格執行。
- **受限操作**：此模式下 `/api/shutdown` 端點被停用，以防止意外終止持續運行的服務。

### 2.5 命令列參考

```bash
python illumio_ops.py [OPTIONS]
```

| 參數 | 預設值 | 說明 |
|:---|:---|:---|
| `--monitor` | — | 以無頭常駐模式執行 |
| `--monitor-gui` | — | 同時執行常駐程序 + Web GUI（持續運行模式） |
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
# 產生最近 7 天的 HTML 流量報表並寄送 Email
python illumio_ops.py --report --format html --email

# 產生稽核報表
python illumio_ops.py --report --report-type audit

# 產生 VEN 狀態報表
python illumio_ops.py --report --report-type ven_status

# 從 CSV 匯出檔產生政策使用報表
python illumio_ops.py --report --report-type policy_usage --source csv --file workloader_export.csv

# 從 CSV 匯出檔產生報表，同時儲存 HTML 與原始 CSV
python illumio_ops.py --report --source csv --file traffic_export.csv --format all

# 以自訂連接埠啟動 Web GUI
python illumio_ops.py --gui --port 8080
```

---

## 3. 規則類型與設定

### 3.1 事件規則

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
| 代理健康 | `agent_missed_heartbeats`、`agent_offline`、`agent_tampering` |
| 身份驗證 | `login_failed`、`authentication_failed` |
| 政策變更 | `ruleset_create/update`、`rule_create/delete`、`policy_provision` |
| 工作負載 | `workload_create`、`workload_delete` |

> **登入失敗告警**會在告警內文中包含使用者名稱與來源 IP 位址，以利快速分類處理。

### 3.2 流量規則

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

### 3.3 頻寬與流量量規則

偵測資料外洩模式。

| 類型 | 指標 | 單位 | 計算方式 |
|:---|:---|:---|:---|
| **Bandwidth** | 峰值傳輸速率 | 自動調整（bps/Kbps/Mbps/Gbps） | 所有匹配流量的最大值 |
| **Volume** | 累計資料傳輸量 | 自動調整（B/KB/MB/GB） | 所有匹配流量的總和 |

> **混合計算**：系統優先使用「差量間隔」指標。對於無可測量差量的長期連線，會回退使用「生命週期總量」，以防止外洩行為逃脫偵測。

> **自動調整單位**：頻寬與流量量的值會自動格式化為最適當的單位（例如 1500 bps → "1.5 Kbps"、2048 MB → "2.0 GB"）。

---

## 4. Web GUI 安全性

所有 Web GUI 模式均需要驗證，並支援來源 IP 限制。

### 4.1 身份驗證

存取受 SHA-256 密碼雜湊（含每安裝唯一的 salt）保護。
- **預設帳密**：`illumio` / `illumio`
- **Session 管理**：使用安全簽章 Cookie（密鑰自動產生於 `config.json` 中）。
- **設定方式**：透過 **CLI 選單 7. Web GUI Security** 或 Web GUI **Settings** 頁面變更帳密。

### 4.2 IP 白名單

限制僅特定管理工作站或子網路可存取。
- **格式**：支援單一 IP（例如 `192.168.1.50`）或 CIDR 區塊（例如 `10.0.0.0/24`）。
- **預設**：若清單為空，則所有 IP 皆可存取（前提是通過身份驗證）。
- **執行方式**：中介軟體於每次請求時檢查 `X-Forwarded-For` 或遠端位址。

---

## 5. 告警通道

三個通道可同時運作。在 `config.json` → `alerts.active` 中啟用：

```json
{
    "alerts": {
        "active": ["mail", "line", "webhook"]
    }
}
```

### 5.1 Email（SMTP）

```json
{
    "email": { "sender": "monitor@company.com", "recipients": ["soc@company.com"] },
    "smtp": { "host": "smtp.company.com", "port": 587, "user": "", "password": "", "enable_auth": true, "enable_tls": true }
}
```

### 5.2 LINE Messaging API

```json
{
    "alerts": {
        "line_channel_access_token": "YOUR_TOKEN",
        "line_target_id": "USER_OR_GROUP_ID"
    }
}
```

### 5.3 Webhook

```json
{
    "alerts": {
        "webhook_url": "https://hooks.slack.com/services/xxx/yyy/zzz"
    }
}
```

發送標準化 JSON 酬載，包含 `health_alerts`、`event_alerts`、`traffic_alerts` 及 `metric_alerts` 陣列。相容於 Slack、Microsoft Teams 及自訂 SOAR 端點。

---

## 6. 隔離（工作負載隔離）

隔離功能讓您能以嚴重性標籤標記受損的工作負載，這些標籤可用於 Illumio 政策規則中以限制其網路存取。

### 工作流程

1. 透過 Web GUI → **Workload Search** **搜尋**目標工作負載（依主機名稱、IP 或標籤）
2. **選擇**一個或多個工作負載，然後選擇隔離等級：`Mild`、`Moderate` 或 `Severe`
3. 系統會在 PCE 中**自動建立** Quarantine 標籤類型（若尚不存在）
4. 系統會將 Quarantine 標籤**附加**至每個工作負載的現有標籤上（保留所有其他標籤）

**單一 vs. 批次套用**：選擇單一工作負載後點選 **Apply Quarantine** 進行個別隔離。勾選多個工作負載後點選 **Bulk Quarantine** 以平行方式隔離（最多 5 個並行 API 呼叫）。

> **重要**：隔離標籤本身不會阻擋流量。您必須在 PCE 中建立對應的 **Enforcement Boundaries** 或 **Deny Rules**，引用 `Quarantine` 標籤鍵才能實際限制流量。

---

## 7. 多 PCE 設定檔管理

系統支援透過設定檔管理同時監控多個 PCE 實例。

### 7.1 概觀

設定檔儲存 PCE 連線憑證（URL、org ID、API key、secret），可在執行時切換而無需重新啟動應用程式。

### 7.2 設定方式

透過以下方式管理設定檔：
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

### 7.3 設定檔切換

當您啟用一個設定檔時，系統會：
1. 將該設定檔的憑證複製至頂層 `api` 區段
2. 以新憑證重新初始化 `ApiClient`
3. 後續所有 API 呼叫使用新的 PCE 連線

> **注意**：所有規則與報表排程適用於目前啟用的 PCE 設定檔。切換設定檔不會重設現有規則。

---

## 8. 進階部署

### 8.1 Windows 服務（NSSM）

```powershell
nssm install IllumioOps "C:\Python312\python.exe" "C:\illumio_ops\illumio_ops.py" --monitor --interval 5
nssm set IllumioOps AppDirectory "C:\illumio_ops"
nssm start IllumioOps
```

### 8.2 Linux systemd

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
ExecStart=/usr/bin/python3 illumio_ops.py --monitor --interval 5
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
ExecStart=/opt/illumio_ops/venv/bin/python illumio_ops.py --monitor --interval 5
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now illumio-ops
```

---

## 9. 流量報表與安全發現

### 9.1 產生報表

報表可從以下三處觸發：

| 位置 | 操作方式 |
|:---|:---|
| Web GUI → Reports 分頁 | 點選 **Traffic Report**、**Audit Summary**、**VEN Status** 或 **Policy Usage** |
| CLI → **2. Report Generation** 子選單項目 1–4 | 選擇報表類型與日期範圍 |
| 常駐模式 | 透過 CLI **2. Report Generation → 5. Report Schedule Management** 設定 — 報表自動產生並可透過 Email 寄送 |
| 命令列 | `python illumio_ops.py --report --report-type traffic\|audit\|ven_status\|policy_usage` |

報表儲存至 `reports/` 目錄，依格式設定產生 `.html`（格式化報表）及/或 `_raw.zip`（CSV 原始資料）。

**所需相依套件：**
```bash
pip install pandas pyyaml
```

### 9.2 報表類型總覽

| 報表類型 | 資料來源 | 模組數 | 說明 |
|:---|:---|:---|:---|
| **Traffic** | PCE 非同步流量查詢或 CSV | 15 模組 + 19 安全發現 | 全面的流量安全分析 |
| **Audit** | PCE events API | 4 模組 | 系統健康、使用者活動、政策變更 |
| **VEN Status** | PCE workloads API | 單一產生器 | VEN 清冊含線上/離線分類 |
| **Policy Usage** | PCE rulesets + 流量查詢，或 Workloader CSV | 4 模組 | 逐規則流量命中分析 |

### 9.3 報表章節（Traffic Report）

流量報表包含 **15 個分析模組**加上安全發現章節：

| 章節 | 說明 |
|:---|:---|
| Executive Summary | KPI 卡片：總流量數、政策覆蓋率 %、重要發現 |
| 1 - Traffic Overview | 總流量數、允許/阻擋/PB 分佈、熱門埠 |
| 2 - Policy Decisions | 逐決策分佈含入站/出站拆分及逐埠覆蓋率 % |
| 3 - Uncovered Flows | 無允許規則的流量；埠缺口排名；未覆蓋服務（應用程式+埠） |
| 4 - Ransomware Exposure | **調查目標**（在關鍵/高風險埠上有 ALLOWED 流量的目的主機）醒目標示；逐埠明細；主機暴露排名 |
| 5 - Remote Access | SSH/RDP/VNC/TeamViewer 流量分析 |
| 6 - User & Process | 流量記錄中出現的使用者帳號與程序 |
| 7 - Cross-Label Matrix | 環境/應用/角色標籤組合間的流量矩陣 |
| 8 - Unmanaged Hosts | 來自/前往非 PCE 管理主機的流量；逐應用與逐埠明細 |
| 9 - Traffic Distribution | 埠與協定分佈 |
| 10 - Allowed Traffic | 熱門允許流量；稽核旗標 |
| 11 - Bandwidth & Volume | 依位元組排名的熱門流量 + 頻寬（自動調整單位）；Max/Avg/P95 統計卡片；異常偵測（多連線流量的 P95） |
| 13 - Enforcement Readiness | 0–100 分含因子分解與修復建議 |
| 14 - Infrastructure Scoring | 節點中心性評分以識別關鍵服務（入度、出度、介數中心性） |
| 15 - Lateral Movement Risk | 橫向移動模式分析與高風險路徑 |
| **Security Findings** | **自動化規則評估 — 詳見第 9.5 節** |

### 9.4 安全發現規則

安全發現章節對每個流量資料集執行 **19 條自動偵測規則**，並依嚴重性（CRITICAL → INFO）與分類群組顯示結果。

**規則系列概觀：**

| 系列 | 規則 | 重點 |
|:---|:---|:---|
| **B 系列** | B001–B009 | 勒索軟體暴露、政策覆蓋缺口、行為異常 |
| **L 系列** | L001–L010 | 橫向移動、憑證竊取、爆炸半徑路徑、資料外洩 |

**快速參考：**

| 規則 | 嚴重性 | 偵測內容 |
|:---|:---|:---|
| B001 | CRITICAL | 勒索軟體常用埠（SMB/RDP/WinRM/RPC）未阻擋 |
| B002 | HIGH | 遠端存取工具（TeamViewer/VNC/NetBIOS）被允許 |
| B003 | MEDIUM | 勒索軟體常用埠處於測試模式 — 未執行阻擋 |
| B004 | MEDIUM | 來自未管理（非 PCE）主機的大量流量 |
| B005 | MEDIUM | 政策覆蓋率低於閾值 |
| B006 | HIGH | 單一來源在橫向移動埠上的扇出行為 |
| B007 | HIGH | 單一使用者觸及異常大量的目的端 |
| B008 | MEDIUM | 高頻寬異常（潛在外洩/備份） |
| B009 | INFO | 跨環境流量量超過閾值 |
| L001 | HIGH | 使用明文協定（Telnet/FTP） |
| L002 | MEDIUM | 網路探索協定未阻擋（LLMNR/NetBIOS/mDNS） |
| L003 | HIGH | 資料庫埠可從過多應用層級存取 |
| L004 | HIGH | 資料庫流量跨越環境邊界 |
| L005 | HIGH | Kerberos/LDAP 可從過多來源應用存取 |
| L006 | HIGH | 高爆炸半徑橫向路徑（BFS 圖分析） |
| L007 | HIGH | 未管理主機存取資料庫/身份/管理埠 |
| L008 | HIGH | 橫向移動埠處於測試模式 — 政策存在但未執行 |
| L009 | HIGH | 資料外洩模式（管理 → 未管理，高位元組數） |
| L010 | CRITICAL | 橫向移動埠跨環境邊界被允許 |

完整規則文件 — 包含觸發條件、攻擊技術背景及調整指南 — 請參閱 **[Security Rules Reference](Security_Rules_Reference.md)**。

### 9.5 稽核報表章節

稽核報表包含 **4 個模組**：

| 模組 | 說明 |
|:---|:---|
| Executive Summary | 依嚴重性與分類的事件數量；熱門事件類型 |
| 1 - System Health Events | `agent.tampering`、離線代理、心跳失敗 |
| 2 - User Activity | 身份驗證事件、登入失敗、帳號變更 |
| 3 - Policy Changes | 規則集與規則的建立/更新/刪除、政策佈建 |

### 9.6 VEN 狀態報表

VEN 狀態報表盤點所有 PCE 管理的工作負載，並分類 VEN 連線狀態：

| 章節 | 說明 |
|:---|:---|
| KPI Summary | VEN 總數、線上數、離線數 |
| Online VENs | 代理狀態為 active **且**最後心跳 ≤ 1 小時前的 VEN |
| Offline VENs | 已暫停/停止的 VEN，或 active 但心跳 > 1 小時前 |
| Lost (last 24 h) | 最後心跳在過去 24 小時內的離線 VEN |
| Lost (24–48 h ago) | 最後心跳在 24–48 小時前的離線 VEN |

每一列包含：主機名稱、IP、標籤、VEN 狀態、距上次心跳的小時數、最後心跳時間戳、政策接收時間戳、VEN 版本。

> **線上偵測**：PCE 的 `agent.status.status = "active"` 僅反映**管理**狀態。VEN 可能在無法連線（無心跳）時仍維持 `"active"`。報表使用 `hours_since_last_heartbeat` — VEN 僅在最後心跳 ≤ 1 小時前時才被視為線上。此行為與 PCE Web Console 一致。

### 9.7 政策使用報表

政策使用報表分析每條 PCE 安全規則的實際使用情況，透過比對實際流量記錄來評估。

| 模組 | 說明 |
|:---|:---|
| Executive Summary | 規則總數、有流量命中的規則數、覆蓋率百分比 |
| Overview | 啟用/停用分佈、active/draft 狀態 |
| Hit Detail | 有匹配流量的規則；每條規則的熱門流量 |
| Unused Detail | 流量命中為零的規則；清理候選項 |

**資料來源：**
- **API 模式**：從 PCE 取得活躍規則集，然後對每條規則執行平行非同步流量查詢以計算匹配流量數
- **CSV 模式**：匯入含預先計算流量數的 Workloader CSV 匯出檔（供離線分析使用）

### 9.8 調整安全規則

所有偵測閾值位於 `config/report_config.yaml`：

```yaml
thresholds:
  min_policy_coverage_pct: 30         # B005
  lateral_movement_outbound_dst: 10   # B006
  db_unique_src_app_threshold: 5      # L003
  blast_radius_threshold: 5           # L006
  exfil_bytes_threshold_mb: 100       # L009
  cross_env_lateral_threshold: 5      # L010
  # ...（完整清單請參閱 Security_Rules_Reference.md）
```

編輯此檔案後重新產生報表即可套用新閾值 — 無需重新啟動。

### 9.9 報表排程

透過 CLI **2. Report Generation → 5. Report Schedule Management** 或 Web GUI **Report Schedules** 分頁設定自動週期報表：

| 欄位 | 說明 |
|:---|:---|
| Report Type | Traffic Flow / Audit / VEN Status / **Policy Usage** |
| Frequency | Daily / Weekly（星期幾） / Monthly（每月幾號） |
| Time | 小時與分鐘 — 以您**設定的時區**輸入（自動以 UTC 儲存） |
| Lookback Days | 包含多少天的流量資料 |
| Output Format | HTML / CSV Raw ZIP / Both |
| Send by Email | 使用 SMTP 設定將報表附加至 Email 寄送 |
| Custom Recipients | 覆寫此排程的預設收件者 |

> **時區注意**：CLI 與 Web GUI 中的時間欄位始終以 Settings → Timezone 設定的時區顯示。底層以 UTC 儲存，因此即使變更時區設定，排程仍會正確執行。

常駐迴圈每 60 秒檢查排程，並執行任何已到達設定時間的排程。

每次成功執行後，舊報表檔案會根據**保留政策**自動清理 — 詳見第 11.3 節。

---

## 10. 規則排程器

規則排程器根據時間窗口自動啟用或停用 PCE 安全規則（Rule 或 Ruleset）。適用場景包括維護窗口、僅限營業時間的存取政策，以及具自動到期功能的暫時允許規則。

### 10.1 排程類型

| 類型 | 說明 | 範例 |
|:---|:---|:---|
| **Recurring** | 在指定日期的時間窗口內重複執行 | 週一至週五 09:00–17:00 |
| **One-time** | 在指定到期日時間前有效，之後自動還原 | 於 2026-04-10 18:00 到期 |

> **午夜跨越**：循環排程支援跨越午夜的時間窗口（例如 22:00–06:00）。系統可正確判斷「現在」是否位於跨越窗口內。

### 10.2 CLI

透過 CLI 主選單 **3. Rule Scheduler** 存取：
- **1. Schedule Management** — 瀏覽所有 Rulesets/Rules 並新增/移除排程
- **2. Run Schedule Check Now** — 手動觸發排程引擎
- **3. Scheduler Settings** — 啟用/停用背景常駐程序並設定檢查間隔

### 10.3 Web GUI

透過 **Rule Scheduler** 分頁存取：
- 瀏覽所有 Rulesets 並展開個別 Rules
- 依名稱快速搜尋 Rulesets
- 建立 **Recurring**（基於時間窗口）或 **One-time**（自動到期）排程
- 在 **Logs** 子分頁中查看即時排程日誌

### 10.4 Draft 政策保護

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

## 11. 設定參考

### 11.1 時區

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

### 11.2 儀表板查詢

Dashboard 分頁支援儲存自訂流量查詢以供重複使用。每個已儲存的查詢會記錄過濾參數（政策決策、埠、標籤、IP 範圍、過濾方向），並可從 Dashboard 隨時執行以填入 Top-10 小工具。

查詢儲存於 `config.json` → `settings.dashboard_queries`，完全透過 Web GUI 管理。

### 11.3 報表輸出

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

---

## 12. 疑難排解

| 症狀 | 原因 | 解決方案 |
|:---|:---|:---|
| `Connection refused` | PCE 無法連線 | 確認 `api.url` 與網路連線 |
| `401 Unauthorized` | API 憑證無效 | 在 PCE Console 重新產生 API Key |
| `410 Gone` | 非同步查詢已過期 | 流量查詢結果已被清理；重新執行查詢 |
| `429 Too Many Requests` | API 速率限制 | 系統會自動以退避策略重試；若持續發生請降低查詢頻率 |
| Web GUI 無法啟動 | Flask 未安裝 | **Ubuntu/Debian**：使用 venv — `venv/bin/pip install flask pandas pyyaml`。**RHEL**：`dnf install python3-flask` |
| `externally-managed-environment` pip 錯誤 | Ubuntu/Debian PEP 668 | 建立 venv：`python3 -m venv venv && venv/bin/pip install flask pandas pyyaml` |
| 未收到告警 | 通道未啟用 | 確認 `alerts.active` 陣列包含您的通道 |
| 報表顯示所有 VEN 均為線上 | 舊的快取狀態 | 確認您的 PCE 版本有回傳 `hours_since_last_heartbeat`；檢查 PCE API 回應中的 `agent.status` 欄位 |
| Rule Scheduler 顯示 `[SKIP]` 日誌 | 規則或父 Ruleset 處於 Draft 狀態 | 在 PCE Console 完成並 Provision 政策編輯；排程將自動恢復 |
| PCE 設定檔切換無效果 | ApiClient 未重新初始化 | 使用 GUI「Activate」按鈕或 CLI 設定檔切換，會觸發重新初始化 |
| Policy Usage 報表顯示 0 命中 | 規則僅為 draft 狀態 | 僅查詢 active（已佈建）的規則；請先佈建 draft 規則 |
