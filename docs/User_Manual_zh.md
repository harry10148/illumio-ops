# Illumio PCE Ops — 完整使用手冊

![Version](https://img.shields.io/badge/Version-v3.1.0-blue?style=flat-square)

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

### 1.3 設定檔 (`config.json`)

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
│ 快捷: Enter預設 | 0返回 | -1取消 | h/?說明
├────────────────────────────────────────────────────
│  1. 告警規則
│  2. 報表產生
│  3. 規則排程器
│  4. 系統設定
│  5. 啟動 Web 介面
│  6. 查看系統日誌
│  7. Web GUI 安全設定
│  0. 離開
╰────────────────────────────────────────────────────
```

選擇 **1. 告警規則** 後進入子選單：

```text
│ 1. 新增事件規則
│ 2. 新增流量規則
│ 3. 新增頻寬與傳輸量規則
│ 4. 管理規則
│ 5. 載入官方最佳實踐
│ 6. 發送測試告警
│ 7. 執行分析並發送告警
│ 8. 規則模擬與除錯模式
│ 0. 返回
```

選擇 **2. 報表產生** 後進入子選單：

```text
│ 1. 產生流量分析報表
│ 2. 產生稽核日誌報表
│ 3. 產生 VEN 狀態盤點報表
│ 4. 報表排程管理
│ 0. 返回
```

選擇 **3. 規則排程器** 後進入子選單：

```text
│ 1. 排程管理 (新增/刪除排程)
│ 2. 立即執行排程檢查
│ 3. 排程設定 (啟用/停用 Daemon、間隔)
│ 0. 返回
```

> **說明**：**4. 系統設定**、**5. 啟動 Web 介面**、**6. 查看系統日誌** 為單步驟直接操作，不含子選單。


```bash
python illumio_ops.py --gui
python illumio_ops.py --gui --port 8080    # 自訂連接埠
```

在 `http://127.0.0.1:5001` 開啟瀏覽器介面，包含以下功能頁籤：

| 頁籤 | 功能 |
|:---|:---|
| **Dashboard** | API 連線狀態、規則摘要、PCE 健康檢查；流量分析器含 Top-10 小工具（頻寬/流量/連線數）；可儲存自訂查詢 |
| **Rules** | 完整的事件/流量/頻寬/流量規則 CRUD，支援批次刪除與行內編輯 |
| **Reports** | 手動產生流量、稽核、VEN 狀態報表；下載 HTML 報表或 CSV 原始資料 ZIP；刪除舊報表 |
| **Report Schedules** | 建立/編輯/啟停週期性排程（每日/每週/每月）；立即觸發執行；檢視執行歷史；可設定 Email 附件寄送 |
| **Rule Scheduler** | 瀏覽所有 PCE 規則集；啟用/停用個別規則（含可選 TTL）；部署變更 |
| **Workload Search** | 依主機名/IP/標籤搜尋工作負載；支援單筆或批次套用隔離標籤 |
| **Settings** | API 憑證設定、告警通道設定、時區、語言/主題切換 |
| **Actions** | 執行監控、除錯模式、測試告警、載入最佳實踐 |

### 2.3 背景 Daemon

```bash
python illumio_ops.py --monitor                 # 預設：每 10 分鐘
python illumio_ops.py --monitor --interval 5     # 每 5 分鐘
```

在背景無人值守運行，可透過 `SIGINT`/`SIGTERM` 優雅關閉。

### 2.4 命令列參數參考

```bash
python illumio_ops.py [OPTIONS]
```

| 參數 | 預設值 | 說明 |
|:---|:---|:---|
| `--monitor` | — | 以無頭 Daemon 模式執行 |
| `--monitor-gui` | — | 同時啟動監控與 Web GUI (常駐模式) |
| `-i` / `--interval N` | `10` | 監控間隔（分鐘） |
| `--gui` | — | 啟動獨立 Web GUI |
| `-p` / `--port N` | `5001` | Web GUI 連接埠 |
| `--report` | — | 從命令列直接產生流量報表 |
| `--source api\|csv` | `api` | 報表資料來源 |
| `--file PATH` | — | CSV 檔案路徑（搭配 `--source csv`） |
| `--format html\|csv\|all` | `html` | 報表輸出格式 |
| `--email` | — | 產生報表後自動寄送 Email |
| `--output-dir PATH` | `reports/` | 報表輸出目錄 |

**範例：**

```bash
# 產生 HTML 報表並 Email 寄送
python illumio_ops.py --report --format html --email

# 從 CSV 匯出檔產生報表，同時輸出 HTML 與原始 CSV
python illumio_ops.py --report --source csv --file traffic_export.csv --format all

# 在自訂連接埠啟動 Web GUI
python illumio_ops.py --gui --port 8080
```

---

## 3. 規則類型與設定

### 3.1 事件規則（Event Rule）

監控 PCE 稽核事件（如 `agent.tampering`、`user.sign_in`）。

| 參數 | 說明 | 範例 |
|:---|:---|:---|
| **事件類型** | PCE 事件識別碼 | `agent.tampering` |
| **門檻類型** | `immediate`（立即告警）或 `count`（累計次數） | `count` |
| **門檻次數** | 累計幾次後觸發告警 | `5` |
| **時間視窗** | 滾動視窗（分鐘） | `10` |
| **冷卻時間** | 重複告警的最短間隔（分鐘） | `30` |

**內建事件目錄**（透過 CLI/GUI 可檢視）：

| 分類 | 事件 |
|:---|:---|
| Agent 健康 | `agent_missed_heartbeats`、`agent_offline`、`agent_tampering` |
| 認證 | `login_failed`、`authentication_failed` |
| 政策變更 | `ruleset_create/update`、`rule_create/delete`、`policy_provision` |
| 工作負載 | `workload_create`、`workload_delete` |

### 3.2 流量規則（Traffic Rule）

偵測連線異常，計算匹配的流量筆數。

| 參數 | 說明 |
|:---|:---|
| **Policy Decision** | `Blocked (2)`、`Potentially Blocked (1)`、`Allowed (0)` 或 `All (3)` |
| **Port / Protocol** | 依目的端口（如 `443`）或 IP 協定號（如 `6` = TCP）篩選 |
| **來源/目的 Label** | 精確標籤匹配，格式為 `key=value`（如 `role=Web`） |
| **來源/目的 IP** | IP 位址或 IP List 名稱 |
| **排除條件** | 針對 Port、Label、IP 的反向篩選 |

### 3.3 頻寬與流量規則（Bandwidth/Volume Rule）

偵測資料外洩模式。

| 類型 | 指標 | 單位 | 計算方式 |
|:---|:---|:---|:---|
| **Bandwidth** | 傳輸峰值速率 | Mbps | 取所有匹配流量中的最大值 |
| **Volume** | 累計資料傳輸量 | MB | 加總所有匹配流量 |

> **混合計算機制**：系統優先使用「Delta 區間」指標。對於無法測量到 Delta 的長效連線，自動退回使用「生命週期總量」，防止大量資料外洩漏網。

---

## 4. Web GUI 安全規範

所有 Web GUI 存取均強制要求身分驗證，並支援來源 IP 限制。

### 4.1 身分驗證 (Authentication)

存取受到 SHA-256 密碼雜湊保護，並結合每套安裝唯一的 Salt（鹽值）。
- **預設憑證**：`illumio` / `illumio`
- **連線階段管理**：使用安全簽署的 Cookies（Session Secret 會自動產生於 `config.json`）。
- **設定方式**：可透過 **CLI 選單 7. Web GUI Security** 或 Web GUI 的 **Settings** 頁面進行修改。

### 4.2 IP 白名單 (IP Allowlisting)

限制僅特定管理站或網段可存取網頁介面。
- **格式**：支援單一 IP（如 `192.168.1.50`）或 CIDR 網段（如 `10.0.0.0/24`）。
- **預設行為**：若清單為空，則允許所有 IP 存取（仍需登入）。
- **強制執行**：Middleware 會在每次請求時檢查 `X-Forwarded-For` 或來源位址。

---

## 5. 告警通道

三個通道同時運作，在 `config.json` → `alerts.active` 中啟用：

```json
{
    "alerts": {
        "active": ["mail", "line", "webhook"]
    }
}
```

### 4.1 Email (SMTP)

```json
{
    "email": { "sender": "monitor@company.com", "recipients": ["soc@company.com"] },
    "smtp": { "host": "smtp.company.com", "port": 587, "user": "", "password": "", "enable_auth": true, "enable_tls": true }
}
```

### 4.2 LINE 通知 API

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

傳送標準化 JSON 酬載，包含 `health_alerts`、`event_alerts`、`traffic_alerts` 和 `metric_alerts` 陣列。相容 Slack、Microsoft Teams、自訂 SOAR 端點。

---

## 5. 工作負載隔離（Quarantine）

隔離功能可以將遭入侵的工作負載標記上嚴重等級標籤，再配合 PCE 中的政策規則來限制其網路存取。

### 操作流程

1. 在 Web GUI → **Workload Search** 中 **搜尋** 目標主機（依主機名、IP 或標籤）
2. 選取一台或多台工作負載，**選擇** 隔離等級：`Mild`（輕微）、`Moderate`（中度）、`Severe`（嚴重）
3. 系統 **自動建立** Quarantine 標籤類別（若 PCE 中尚不存在）
4. 系統 **追加** 隔離標籤至工作負載的現有標籤（保留所有原始標籤）

**單筆與批次隔離**：選取單筆工作負載後點選 **Apply Quarantine** 進行個別隔離。勾選多筆後點選 **Bulk Quarantine** 可平行發送 API 請求同時隔離多台主機。

> **重要提示**：單純標記 Quarantine 標籤不會自動阻擋流量。您必須在 PCE 中建立對應的 **Enforcement Boundary** 或 **Deny Rule** 來參照 `Quarantine` 標籤鍵，才能真正限制流量。

---

## 6. 進階部署

### 6.1 Windows 服務（NSSM）

```powershell
nssm install IllumioOps "C:\Python312\python.exe" "C:\illumio_ops\illumio_ops.py" --monitor --interval 5
nssm set IllumioOps AppDirectory "C:\illumio_ops"
nssm start IllumioOps
```

### 6.2 Linux systemd

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

先建立虛擬環境，再將 `ExecStart` 指向 venv 內的 Python 直譯器：

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

## 7. 流量報表與安全發現

### 7.1 產生報表

報表可從三個地方觸發：

| 位置 | 操作方式 |
|:---|:---|
| Web GUI → Reports 分頁 | 點選 **Traffic Report**、**Audit Summary** 或 **VEN Status** |
| CLI → 選單項目 **[9–11]** | 選擇報表類型與日期範圍 |
| Daemon 模式 | 透過 **[12] 報表排程** 設定排程，報表自動產生，可選擇以 Email 寄送 |

報表依格式設定儲存為 `.html`（格式化報表）及/或 `_raw.zip`（CSV 原始資料）至 `reports/` 目錄。

**所需相依套件：**
```bash
pip install pandas pyyaml
```

### 7.2 報表章節（流量報表）

流量報表包含 **15 個分析模組**及安全發現章節：

| 章節 | 說明 |
|:---|:---|
| 執行摘要 | KPI 卡片：總流量數、政策覆蓋率、重要發現 |
| 1 · 流量概覽 | 總流量、放行/封鎖/PB 分布、頂端連接埠 |
| 2 · 政策決策 | 各決策分類明細、入向/出向分流及各連接埠覆蓋率 |
| 3 · 未覆蓋流量 | 無放行規則的流量、連接埠缺口排名、未覆蓋服務（應用程式+連接埠） |
| 4 · 勒索軟體風險 | **需調查目標**（高風險 Port 上的允許流量）醒目顯示；各 Port 明細；主機暴露排名 |
| 5 · 遠端存取 | SSH/RDP/VNC/TeamViewer 流量分析 |
| 6 · 使用者與程序 | 流量記錄中出現的使用者帳號及程序 |
| 7 · 跨標籤矩陣 | 環境/應用程式/角色標籤組合間的流量矩陣 |
| 8 · 非受管主機 | 非 PCE 管理主機的進/出流量；各應用程式及連接埠細節 |
| 9 · 流量分布 | 連接埠與協定分布 |
| 10 · 允許流量 | Top 允許流量；稽核標記 |
| 11 · 頻寬與傳輸量 | Top 傳輸量流量 + 頻寬（Mbps）欄位；Max/Avg/P95 統計卡；異常偵測（多連線 P95） |
| 13 · 執行就緒評分 | 0–100 分評估，含各因子細項與修補建議 |
| 14 · 基礎架構評分 | 節點中心性評分，識別關鍵基礎架構服務 |
| 15 · 橫向移動風險 | 橫向移動模式分析與高風險路徑 |
| **安全發現** | **自動化規則評估，詳見 7.3 章節** |

### 7.3 安全發現規則

安全發現章節針對每份流量資料集執行 **19 條自動化偵測規則**，依嚴重性（CRITICAL → INFO）和類別分組呈現結果。

**規則系列概覽：**

| 系列 | 規則 | 焦點 |
|:---|:---|:---|
| **B 系列** | B001–B009 | 勒索軟體暴露、政策覆蓋缺口、行為異常 |
| **L 系列** | L001–L010 | 橫向移動、憑證竊取、爆炸半徑路徑、資料外洩 |

**快速參考：**

| 規則 | 嚴重性 | 偵測內容 |
|:---|:---|:---|
| B001 | CRITICAL | 勒索軟體連接埠（SMB/RDP/WinRM/RPC）未封鎖 |
| B002 | HIGH | 遠端存取工具（TeamViewer/VNC/NetBIOS）被放行 |
| B003 | MEDIUM | 勒索軟體連接埠處於測試模式，封鎖未生效 |
| B004 | MEDIUM | 未受管（非 PCE）主機的高流量活動 |
| B005 | MEDIUM | 政策覆蓋率低於閾值 |
| B006 | HIGH | 單一來源在橫向移動連接埠上的扇出行為 |
| B007 | HIGH | 單一使用者連接異常大量目的地 |
| B008 | MEDIUM | 高頻寬異常（可能的外洩/備份） |
| B009 | INFO | 跨環境流量超過閾值 |
| L001 | HIGH | 明文協定（Telnet/FTP）正在使用 |
| L002 | MEDIUM | 網路探索協定未封鎖（LLMNR/NetBIOS/mDNS） |
| L003 | HIGH | 資料庫連接埠可被過多應用程式層存取 |
| L004 | HIGH | 資料庫流量跨越環境邊界 |
| L005 | HIGH | Kerberos/LDAP 可被過多來源應用程式存取 |
| L006 | HIGH | 高爆炸半徑橫向路徑（BFS 圖形分析） |
| L007 | HIGH | 未受管主機存取資料庫/身分識別/管理連接埠 |
| L008 | HIGH | 橫向連接埠處於測試模式，政策存在但未強制執行 |
| L009 | HIGH | 資料外洩模式（受管→未受管，高位元組量） |
| L010 | CRITICAL | 橫向連接埠跨環境邊界被放行 |

每條規則的完整說明（含觸發條件、攻擊技術背景及調整指引）請參閱 **[安全規則參考手冊](Security_Rules_Reference_zh.md)**。

### 7.3 稽核報表章節

稽核報表包含 **4 個模組**：

| 模組 | 說明 |
|:---|:---|
| 執行摘要 | 依嚴重性和類別統計事件數；Top 事件類型 |
| 1 · 系統健康事件 | `agent.tampering`、Agent 離線、心跳失敗 |
| 2 · 使用者活動 | 認證事件、登入失敗、帳號變更 |
| 3 · 政策變更 | Ruleset 與 Rule 的新增/修改/刪除、政策部署 |

### 7.3b VEN 狀態報表

VEN 狀態報表盤點所有 PCE 管理的工作負載，並依 VEN 連線狀態分類：

| 章節 | 說明 |
|:---|:---|
| KPI 摘要 | 總 VEN 數、線上數量、離線數量 |
| 線上 VENs | Agent 狀態為 active **且**最後心跳 ≤ 1 小時前的 VEN |
| 離線 VENs | 已暫停/停止，或 active 但心跳超過 1 小時前的 VEN |
| 斷線（近 24 小時） | 離線 VEN 中最後心跳在過去 24 小時內的 |
| 斷線（24–48 小時前） | 離線 VEN 中最後心跳在 24–48 小時前的 |

每筆資料包含：主機名稱、IP、標籤、VEN 狀態、距上次心跳小時數、最後心跳時間、政策接收時間、VEN 版本。

> **線上判斷邏輯**：PCE 的 `agent.status.status = "active"` 只反映**管理狀態**，VEN 失去連線後仍可能維持 active。報表改用 `hours_since_last_heartbeat` 判斷，與 PCE Web Console 顯示行為一致：最後心跳超過 1 小時即視為離線。

### 7.4 調整安全規則閾值

所有偵測閾值均在 `config/report_config.yaml` 中設定：

```yaml
thresholds:
  min_policy_coverage_pct: 30         # B005
  lateral_movement_outbound_dst: 10   # B006
  db_unique_src_app_threshold: 5      # L003
  blast_radius_threshold: 5           # L006
  exfil_bytes_threshold_mb: 100       # L009
  cross_env_lateral_threshold: 5      # L010
  # ... 完整清單請參閱安全規則參考手冊
```

編輯此檔案後重新產生報表即可套用新閾值，無需重啟服務。

### 7.5 報表排程

透過 CLI **2. 報表產生 → 4. 報表排程管理** 或 Web GUI **Report Schedules** 分頁設定自動定期報表：

| 欄位 | 說明 |
|:---|:---|
| 報表類型 | 流量 / 稽核 / VEN 狀態 |
| 執行頻率 | 每日 / 每週（指定星期幾）/ 每月（指定日期） |
| 執行時間 | 小時與分鐘 — 以**設定中的時區**輸入（自動換算儲存為 UTC） |
| 回溯天數 | 報表包含的歷史資料天數 |
| 輸出格式 | HTML / CSV 原始 ZIP / 兩者皆輸出 |
| 以 Email 寄送 | 使用 SMTP 設定附件寄送報表 |
| 自訂收件人 | 覆寫此排程的預設收件人清單 |

> **時區說明**：CLI 精靈和 Web GUI 的時間欄位均以「設定 → 時區」中設定的時區顯示與輸入，底層儲存為 UTC，時區設定變更後排程時間仍然正確。

Daemon 迴圈每 60 秒檢查一次排程，在到達設定時間時自動執行。

每次排程成功執行後，系統會依**報表保留政策**自動清理過期的報表檔案，詳見第 9.3 節。

---

## 8. 規則排程器（Rule Scheduler）

規則排程器可依時間區間自動啟用/停用 PCE 上的安全規則（Rule 或 Ruleset），適用於定期維護視窗、業務時間授權等場景。

### 8.1 CLI 操作

透過 CLI 主選單 **3. 規則排程器** 進入，包含：
- **1. 排程管理**：瀏覽所有 Ruleset / Rule，設定定期或一次性排程
- **2. 立即執行檢查**：手動觸發一次排程引擎，確認狀態
- **3. 排程設定**：啟用/停用 Daemon 自動排程、設定檢查間隔

### 8.2 Web GUI 操作

透過 Web GUI **規則排程器** 頁籤可完整操作：
- 瀏覽所有 Ruleset 及其子規則
- 快速搜尋 Ruleset，點選後展開個別 Rule 清單
- 對 Ruleset 或任一 Rule 建立「定期排程 (Recurring)」或「一次性排程 (One-time)」
- 排程日誌即時顯示 (`日誌` 頁籤)

### 8.3 Draft Policy 安全防護機制

> **重要**：Illumio PCE 的 Provision 操作會將「所有 Draft 中的規則」一次性部署。若在某條規則尚在 Draft 狀態（代表有人正在進行設定修改）時執行排程 Provision，**整個 Policy 版本中所有未完成的 Draft 變更都會被派送出去**，可能造成嚴重的安全風險。

系統因此實作了**多層 Draft 狀態保護**：

| 保護層級 | 觸發位置 | 處理方式 |
|:---|:---|:---|
| **CLI 加入排程** | `rule_scheduler_cli.py` | 若規則或其母 Ruleset 處於 Draft，禁止加入排程，顯示錯誤訊息 |
| **Web GUI 加入排程** | `gui.py` API | 同上，拒絕 POST 請求並返回 `未 provision 的規則無法加入排程` |
| **排程引擎執行時** | `rule_scheduler.py` | 若已排程規則在執行時被發現處於 Draft，跳過本次 Provision 並記錄 `[SKIP]` 日誌 |
| **API 呼叫層** | `api_client.has_draft_changes()` | 統一的 Draft 檢查函式：自動檢查規則本身 + 母 Ruleset 的 Draft 狀態 |

#### 判斷邏輯（母規則優先）

```
1. 取得規則的 Draft 版本 → 若 update_type 不為空 → DRAFT（停止）
2. 若為子規則（含 /sec_rules/ 路徑）→ 向上取得母 Ruleset 的 Draft 版本
   → 若母 Ruleset 的 update_type 不為空 → DRAFT（停止）
3. 兩者皆無 Draft 變更 → 可安全執行
```

#### 日誌記錄

- Draft 阻止排程設定時：僅在操作介面顯示錯誤，不寫入系統日誌
- Draft 阻止排程**執行時**：記錄 `WARNING` 級別日誌，方便追蹤

```
[SKIP] CoreServices_Rule_1499 (ID:1499) 處於 DRAFT 狀態。已中止操作。
```

---

## 9. 設定參考

### 9.1 時區設定

時區設定控制報表中時間戳記的顯示格式，以及排程時間的輸入基準。可在 Web GUI → **Settings → Timezone** 修改，或直接編輯 `config.json`：

```json
{
    "settings": {
        "timezone": "UTC+8"
    }
}
```

支援格式：`local`（系統時區）、`UTC`、`UTC+8`、`UTC-5`、`UTC+5.5`

> 排程時間在內部一律以 **UTC** 儲存。CLI 精靈與 Web GUI 排程視窗會自動依設定時區進行換算顯示。

### 9.2 Dashboard 自訂查詢

Dashboard 頁籤支援儲存自訂流量查詢以便重複使用。每個查詢可儲存篩選條件（Policy Decision、Port、Label、IP 範圍），並可從 Dashboard 隨時執行以更新 Top-10 小工具的資料。

查詢儲存於 `config.json` → `settings.dashboard_queries`，完全透過 Web GUI 管理。

### 9.3 報表輸出

控制報表的儲存位置與保留期限。

| 設定 | 預設值 | 說明 |
|:---|:---|:---|
| `report.output_dir` | `reports/` | 報表儲存目錄（相對於專案根目錄，或絕對路徑） |
| `report.retention_days` | `30` | 排程執行後自動刪除超過此天數的 `.html`/`.zip` 報表，設為 `0` 停用 |

**從 Web GUI 設定**：Settings → **Report Output** 區塊
**從 CLI 設定**：設定選單 → **4. 系統設定**
**直接編輯 `config.json`**：
```json
{
    "report": {
        "output_dir": "reports/",
        "retention_days": 30
    }
}
```

---

## 10. 疑難排解

| 症狀 | 原因 | 解決方式 |
|:---|:---|:---|
| `Connection refused` | PCE 無法連線 | 檢查 `api.url` 和網路連通性 |
| `401 Unauthorized` | API 憑證無效 | 在 PCE 主控台重新產生 API Key |
| `410 Gone` | 非同步查詢已過期 | 查詢結果已被清除，請重新執行查詢 |
| `429 Too Many Requests` | API 速率限制 | 系統會自動重試並退避；若持續發生請降低查詢頻率 |
| Web GUI 無法啟動 | Flask 未安裝 | **Ubuntu/Debian**：使用 venv — `venv/bin/pip install flask pandas pyyaml`；**RHEL**：`dnf install python3-flask` |
| `externally-managed-environment` pip 錯誤 | Ubuntu/Debian PEP 668 封鎖 | 建立虛擬環境：`python3 -m venv venv && venv/bin/pip install flask pandas pyyaml` |
| 未收到告警 | 通道未啟用 | 確認 `alerts.active` 陣列包含您的通道名稱 |
| VEN 報表全部顯示為線上 | 舊版 PCE 未回傳心跳資訊 | 確認 PCE API 回應中 `agent.status` 包含 `hours_since_last_heartbeat` 或 `last_heartbeat_on` 欄位 |
| 排程 Email 失敗：`'Finding' object has no attribute 'get'` | 程式碼過舊 | 更新至最新版本（commit `98c0b47` 已修正） |
| 規則排程顯示 `[SKIP]` 日誌 | 規則或母 Ruleset 處於 Draft | 在 PCE 主控台完成政策設定並 Provision 後，排程將自動恢復執行 |
