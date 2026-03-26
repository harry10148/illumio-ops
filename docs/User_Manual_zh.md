# Illumio PCE Monitor — 完整使用手冊

> **[English](User_Manual.md)** | **[繁體中文](User_Manual_zh.md)**

---

## 1. 安裝與前置需求

### 1.1 系統需求
- **Python 3.8+**（已測試至 3.12）
- 可透過 HTTPS 連線至 Illumio PCE（預設埠 `8443`）
- **（選用）** `pip install flask` — 僅 Web GUI 模式需要

### 1.2 安裝步驟

```bash
git clone <repo-url>
cd illumio_monitor
pip install -r requirements.txt    # 安裝 Flask（選用相依套件）
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
python illumio_monitor.py
```

啟動文字選單介面，可管理規則、設定及手動執行檢查。

```text
=== Illumio PCE Monitor ===
API: https://pce.lab.local:8443 | Rules: 5
----------------------------------------
 1. 新增事件規則
 2. 新增流量規則
 3. 新增頻寬/流量規則
 4. 管理規則
 5. 設定
 6. 載入最佳實踐
 7. 測試告警
 8. 執行一次監控
 9. 除錯模式
10. 啟動 Web GUI
 0. 離開
```

### 2.2 Web GUI

```bash
python illumio_monitor.py --gui
python illumio_monitor.py --gui --port 8080    # 自訂連接埠
```

在 `http://127.0.0.1:5001` 開啟瀏覽器介面，包含以下功能頁籤：

| 頁籤 | 功能 |
|:---|:---|
| **Dashboard** | API 連線狀態、規則摘要、PCE 健康檢查、流量分析器含 Top-10 小工具 |
| **Rules** | 完整的事件/流量/頻寬/流量規則 CRUD，支援批次刪除與行內編輯 |
| **Reports** | 手動產生流量、稽核、VEN 狀態報表；下載 HTML 或 Excel |
| **Report Schedules** | 建立/編輯/啟停週期性排程（每日/每週/每月），可設定自動 Email 寄送 |
| **Workload Search** | 依主機名/IP/標籤搜尋工作負載，套用隔離標籤 |
| **Settings** | API 憑證設定、告警通道設定、時區、語言/主題切換 |
| **Actions** | 執行監控、除錯模式、測試告警、載入最佳實踐 |

### 2.3 背景 Daemon

```bash
python illumio_monitor.py --monitor                 # 預設：每 10 分鐘
python illumio_monitor.py --monitor --interval 5     # 每 5 分鐘
```

在背景無人值守運行，可透過 `SIGINT`/`SIGTERM` 優雅關閉。

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

## 4. 告警通道

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
2. **選擇** 隔離等級：`Mild`（輕微）、`Moderate`（中度）、`Severe`（嚴重）
3. 系統 **自動建立** Quarantine 標籤類別（若 PCE 中尚不存在）
4. 系統 **追加** 隔離標籤至工作負載的現有標籤（保留所有原始標籤）

> **重要提示**：單純標記 Quarantine 標籤不會自動阻擋流量。您必須在 PCE 中建立對應的 **Enforcement Boundary** 或 **Deny Rule** 來參照 `Quarantine` 標籤鍵，才能真正限制流量。

---

## 6. 進階部署

### 6.1 Windows 服務（NSSM）

```powershell
nssm install IllumioMonitor "C:\Python312\python.exe" "C:\illumio_monitor\illumio_monitor.py" --monitor --interval 5
nssm set IllumioMonitor AppDirectory "C:\illumio_monitor"
nssm start IllumioMonitor
```

### 6.2 Linux systemd

```ini
# /etc/systemd/system/illumio-monitor.service
[Unit]
Description=Illumio PCE Monitor
After=network.target

[Service]
Type=simple
User=illumio
WorkingDirectory=/opt/illumio_monitor
ExecStart=/usr/bin/python3 illumio_monitor.py --monitor --interval 5
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now illumio-monitor
```

---

## 7. 流量報表與安全發現

### 7.1 產生報表

報表可從三個地方觸發：

| 位置 | 操作方式 |
|:---|:---|
| Web GUI → Reports 分頁 | 點選 **Traffic Report**、**Audit Summary** 或 **VEN Status** |
| CLI → 選單項目 **[13] 產生報表** | 選擇報表類型與日期範圍 |
| Daemon 模式 | 透過 **[15] 報表排程** 設定排程，報表自動產生，可選擇以 Email 寄送 |

報表依格式設定儲存為 `.html` 及/或 `.xlsx` 至 `reports/` 目錄。

**所需相依套件：**
```bash
pip install pandas openpyxl pyyaml
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

透過 CLI 選單 **[15]** 或 Web GUI **Report Schedules** 分頁設定自動定期報表：

| 欄位 | 說明 |
|:---|:---|
| 報表類型 | 流量 / 稽核 / VEN 狀態 |
| 執行頻率 | 每日 / 每週（指定星期幾）/ 每月（指定日期） |
| 執行時間 | 小時與分鐘 — 以**設定中的時區**輸入（自動換算儲存為 UTC） |
| 回溯天數 | 報表包含的歷史資料天數 |
| 輸出格式 | Excel / HTML / 兩者皆輸出 |
| 以 Email 寄送 | 使用 SMTP 設定附件寄送報表 |
| 自訂收件人 | 覆寫此排程的預設收件人清單 |

> **時區說明**：CLI 精靈和 Web GUI 的時間欄位均以「設定 → 時區」中設定的時區顯示與輸入，底層儲存為 UTC，時區設定變更後排程時間仍然正確。

Daemon 迴圈每 60 秒檢查一次排程，在到達設定時間時自動執行。

---

## 8. 疑難排解

| 症狀 | 原因 | 解決方式 |
|:---|:---|:---|
| `Connection refused` | PCE 無法連線 | 檢查 `api.url` 和網路連通性 |
| `401 Unauthorized` | API 憑證無效 | 在 PCE 主控台重新產生 API Key |
| `410 Gone` | 非同步查詢已過期 | 查詢結果已被清除，請重新執行查詢 |
| `429 Too Many Requests` | API 速率限制 | 系統會自動重試並退避；若持續發生請降低查詢頻率 |
| Web GUI 無法啟動 | Flask 未安裝 | 執行 `pip install flask` |
| 未收到告警 | 通道未啟用 | 確認 `alerts.active` 陣列包含您的通道名稱 |
