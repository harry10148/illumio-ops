# Illumio PCE Ops

<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](README.md) | [README_zh.md](README_zh.md) |
| Installation | [Installation.md](docs/Installation.md) | [Installation_zh.md](docs/Installation_zh.md) |
| User Manual | [User_Manual.md](docs/User_Manual.md) | [User_Manual_zh.md](docs/User_Manual_zh.md) |
| Report Modules | [Report_Modules.md](docs/Report_Modules.md) | [Report_Modules_zh.md](docs/Report_Modules_zh.md) |
| Security Rules | [Security_Rules_Reference.md](docs/Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](docs/Security_Rules_Reference_zh.md) |
| SIEM Integration | [SIEM_Integration.md](docs/SIEM_Integration.md) | [SIEM_Integration_zh.md](docs/SIEM_Integration_zh.md) |
| Architecture | [Architecture.md](docs/Architecture.md) | [Architecture_zh.md](docs/Architecture_zh.md) |
| PCE Cache | [PCE_Cache.md](docs/PCE_Cache.md) | [PCE_Cache_zh.md](docs/PCE_Cache_zh.md) |
| API Cookbook | [API_Cookbook.md](docs/API_Cookbook.md) | [API_Cookbook_zh.md](docs/API_Cookbook_zh.md) |
<!-- END:doc-map -->

![Version](https://img.shields.io/badge/Version-v3.20.0--report--intelligence-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

針對 **Illumio Core (PCE)** 的進階 **agentless** 監控與自動化工具，透過 REST API 提供即時安全事件偵測、智慧流量分析、含自動化資安發現的進階報表產生、報表排程派送、以及多通道警示。

---

## 核心特色

| 功能 | 說明 |
|:---|:---|
| **執行模式** | 背景 daemon (`--monitor`)、互動式 CLI、獨立 Web GUI (`--gui`)，或 **常駐監控 + UI** (`--monitor-gui`) |
| **企業級安全** | **Web GUI 連線安全**：**登入速率限制**（5/分鐘）、**CSRF synchronizer token**、**IP 白名單**（CIDR / Subnet）。密碼以明碼儲存於 `config.json`（離線隔離部署模型）。 |
| **安全事件監控** | 透過 anchor-based timestamp 追蹤 PCE audit 事件 — 保證零重複警示 |
| **高效能流量引擎** | 將規則合併為單一 bulk API query；對大資料集採 O(1) memory streaming |
| **進階報表引擎** | 15 模組的 Traffic 報表附 **Bulk-Delete** 管理；4 模組 Audit 報表、Policy Usage 報表，以及 VEN Status 庫存報表 — HTML + CSV |
| **資安發現** | 19 條自動化規則：B 系列（勒索軟體、覆蓋率）+ L 系列（橫向移動、外洩） |
| **報表排程** | Cron 風格的循環報表（每日/每週/每月）並自動以 Email 派送 |
| **規則排程器** | 自動啟用/停用 PCE 規則；**三層 Draft 保護**避免誤 provision |
| **Workload Quarantine** | 以 Quarantine label 隔離受感染 workload；支援 IP/CIDR/subnet 搜尋 |
| **多通道警示** | Email (SMTP)、LINE Notifications、Webhook 同時派送 |
| **多語系** | CLI、Web GUI、報表、警示完整支援英文 + 繁體中文 |

---

## SIEM 狀態（Preview）

> [!WARNING]
> 內建 SIEM 轉送器目前處於 **Preview** 階段。
> 既有部署可繼續沿用以維持相容性，但在 runtime pipeline 缺口補齊前，不建議新環境上線。

## 快速開始

### 1. 系統需求

- **Python 3.8+**（已測試至 3.12）
- **安裝：** `pip install -r requirements.txt` — 約 25 個鎖定套件，涵蓋 Flask + 安全中介層（`flask-wtf`、`flask-limiter`、`flask-talisman`、`flask-login`）、報表 + 圖表（`pandas`、`pyyaml`、`openpyxl`、`reportlab`、`matplotlib`、`plotly`、`pygments`）、HTTP 客戶端（`requests`、`orjson`、`cachetools`）、設定驗證（`pydantic`）、排程 + 快取（`APScheduler`、`SQLAlchemy`）、結構化日誌（`loguru`）、CLI UX（`rich`、`questionary`、`click`、`humanize`）。
- **離線隔離目標：** 使用 `scripts/build_offline_bundle.sh` 產生含所有預建 wheel 的自包含 tarball；完整 bundle 工作流程請見[使用手冊 §1](docs/User_Manual_zh.md)。
- **PDF 匯出：** `reportlab` 預設包含（純 Python；不需 WeasyPrint / Pango / Cairo / GTK / GDK-PixBuf）。PDF 內容為靜態英文摘要；HTML 與 XLSX 是完整本地化內容的建議格式。

### 2. 安裝與啟動

```bash
git clone <repo-url>
cd illumio_ops
cp config/config.json.example config/config.json    # 編輯填入 PCE 認證資訊

# 互動式 CLI：
python illumio_ops.py

# Web 視覺化介面：
python illumio_ops.py --gui

# 常駐模式（Daemon + Web GUI）：
python illumio_ops.py --monitor-gui --interval 5 --port 5001

# 純背景 Daemon：
python illumio_ops.py --monitor --interval 5

# 新版 subcommand 風格（Phase 1+）：
python illumio_ops.py monitor -i 5
python illumio_ops.py status
python illumio_ops.py version
```

### Shell Tab Completion (bash)

```bash
# 開發時手動 source
source scripts/illumio-ops-completion.bash

# 全域安裝（RPM 會自動完成）：
sudo cp scripts/illumio-ops-completion.bash /etc/bash_completion.d/illumio-ops
```

### 3. 首次登入

預設帳密：**username `illumio`** / **password `illumio`**。

1. 以預設帳密登入。
2. **立即在「設定」頁變更密碼**。
3. 設定 **IP 白名單** 限制信任網段存取。

> [!WARNING]
> 若忘記密碼，請直接編輯 `config/config.json` 中的 `web_gui.password` 為新值（或刪除該欄位以回退至預設值 `illumio`）。該值為明文。

### 4. 安全機制

| 功能 | 細節 |
|:---|:---|
| **Web GUI 密碼** | 明文儲存於 `config.json` 的 `web_gui.password`。專為離線隔離部署設計；其他密鑰（PCE API key/secret、LINE token、SMTP 密碼、webhook URL）同樣以明文儲存以保持一致性。首次登入後請變更預設值 `illumio`。 |
| **速率限制** | 每 IP 每 60 秒最多 5 次登入嘗試；超量回 HTTP 429 |
| **CSRF 保護** | Synchronizer token 模式，透過 `<meta>` tag 注入（避免 XSS-readable cookie） |
| **IP 白名單** | 支援單一 IP、CIDR 範圍、subnet mask |
| **SMTP 認證** | 設定 `ILLUMIO_SMTP_PASSWORD` 環境變數，避免將密碼寫入 config |

### 5. Logging (loguru)

日誌寫入 `logs/illumio_ops.log`，10 MB 自動 rotate、保留最近 10 個檔案。

**SIEM / JSON sink** — 在 `config/config.json` 加入下列設定即可啟用結構化 JSON log：
```json
{
  "logging": {
    "json_sink": true,
    "level": "INFO"
  }
}
```
此功能會將每行 JSON 物件寫入 `logs/illumio_ops.json.log`，可被 Splunk、Elasticsearch、Datadog 等工具直接消費。

---

## 報表引擎

報表可從 Web GUI、CLI 選單，或自動依排程產生。

### Traffic Report — 15 個分析模組

| 模組 | 說明 |
|:---|:---|
| Executive Summary | KPI 卡片：總流量、覆蓋率 %、top 安全發現 |
| 1 · Traffic Overview | 總流量、policy decision 分佈、top ports |
| 2 · Policy Decisions | 每個 decision 的 inbound/outbound 分流 + 各 port 覆蓋率 % |
| 3 · Uncovered Flows | 沒有 allow rule 的流量；port 缺口排名；未覆蓋服務 |
| 4 · Ransomware Exposure | **調查標的**（允許流量於 critical/high-risk ports） |
| ... | 完整清單請見 [使用手冊](docs/User_Manual_zh.md) |

---

## 文件

- [安裝指南](docs/Installation_zh.md) ([English](docs/Installation.md)) — RHEL/Ubuntu/Windows/開發環境安裝、離線 bundle 建置/安裝/升級/移除、systemd
- [使用手冊](docs/User_Manual_zh.md) ([English](docs/User_Manual.md)) — CLI 子命令、GUI 導覽、daemon 模式、警示、隔離、多 PCE、設定、疑難排解
- [報表模組](docs/Report_Modules_zh.md) ([English](docs/Report_Modules.md)) — 全部 22+ 分析模組（mod01-mod15、R3 智慧分析、Policy Usage）、輸出格式、排程、draft_pd 行為
- [安全規則參考](docs/Security_Rules_Reference_zh.md) ([English](docs/Security_Rules_Reference.md)) — B 系列、L 系列、R 系列規則目錄；嚴重性模型；compute_draft 自動啟用
- [SIEM 整合](docs/SIEM_Integration_zh.md) ([English](docs/SIEM_Integration.md)) — CEF/JSON 格式、UDP/TCP/TLS/HEC 傳輸、forwarder 設定、欄位對應
- [架構文件](docs/Architecture_zh.md) ([English](docs/Architecture.md)) — Illumio 平台背景；系統概觀；模組地圖；資料流
- [PCE 快取](docs/PCE_Cache_zh.md) ([English](docs/PCE_Cache.md)) — SQLite WAL 快取層；更新策略；操作員命令
- [API Cookbook](docs/API_Cookbook_zh.md) ([English](docs/API_Cookbook.md)) — PCE REST API 整合模式；認證/分頁/非同步任務；常用端點

---

## 專案結構

```text
illumio_ops/
├── illumio_ops.py          # 進入點
├── src/
│   ├── main.py                 # CLI argparse、daemon/GUI 編排
│   ├── api_client.py           # PCE REST API（async job、native filter、O(1) streaming）
│   ├── analyzer.py             # 規則引擎（flow matching、事件分析、狀態管理）
│   ├── gui.py                  # Flask Web GUI（~40 個 JSON API endpoint、auth、CSRF）
│   ├── config.py               # ConfigManager（明文設定、atomic write）
│   ├── reporter.py             # 多通道警示派送（SMTP、LINE、Webhook）
│   ├── i18n.py                 # i18n 引擎（EN/ZH_TW，~1400+ string keys）
│   ├── events/                 # 事件 pipeline（catalog、normalize、dedup、throttle）
│   ├── report/                 # 報表引擎（15 個 traffic 模組 + audit + policy usage）
│   └── alerts/                 # 警示 plugin（mail、LINE、webhook）
├── config/                     # config.json、report_config.yaml
├── docs/                       # EN + ZH_TW 文件
├── tests/                      # 19 個測試檔（116 個 test）
├── deploy/                     # systemd（Ubuntu/RHEL）+ NSSM（Windows）服務設定
└── scripts/                    # 工具腳本
```
