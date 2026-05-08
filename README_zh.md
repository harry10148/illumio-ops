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
| Glossary | [Glossary.md](docs/Glossary.md) | [Glossary_zh.md](docs/Glossary_zh.md) |
| Troubleshooting | [Troubleshooting.md](docs/Troubleshooting.md) | [Troubleshooting_zh.md](docs/Troubleshooting_zh.md) |
<!-- END:doc-map -->

![Version](https://img.shields.io/badge/Version-v3.25.0--tracks--abcd-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

針對 **Illumio Core (PCE)** 的進階 **agentless** 監控與自動化工具，僅透過 REST API 與 PCE 互動。

---

## 這個工具解決什麼問題

Illumio PCE 負責 workload 微分段策略運算與流量遙測，但日常維運所需的功能（排程報表、多通道警示、SIEM 轉送、規則排程、多 PCE 切換）並未內建於 Web Console。**illumio-ops** 以 agentless 方式補齊這些缺口。

如果您符合下列任一情境，這個工具大概對您有用：

- 您運維一個或多個 PCE，並希望以 Email 自動派送 **流量 / 稽核 / VEN 狀態 / Policy Usage 排程報表**。
- 您需要 **持續監控 PCE 稽核事件與流量異常**，並透過 Email、LINE、Webhook（Slack/Teams）發出警示。
- 您想 **將 PCE 事件 / 流量推送到 SIEM**（Splunk HEC、Splunk syslog、ELK、Sentinel）而不想額外架設 forwarder。
- 您管理 **多座 PCE**，希望以單一工具切換。
- 您需要 **安全的規則排程器**，自動啟用 / 停用 PCE 規則並有三層 Draft 保護。

如果只是偶爾透過 PCE Web Console 做手動查詢，您不需要這個工具。

---

## 核心特色

| 功能 | 說明 |
|:---|:---|
| **執行模式** | 背景 daemon (`--monitor`)、互動式 CLI、獨立 Web GUI (`--gui`)，或 **常駐監控 + UI** (`--monitor-gui`) |
| **企業級安全** | Argon2id 密碼雜湊 + 首次登入強制變更、HTTPS 預設啟用（ECDSA P-256 自簽憑證）、CSRF synchronizer token、登入速率限制、IP 白名單（CIDR/Subnet） |
| **安全事件監控** | 透過 anchor-based timestamp 追蹤 PCE audit 事件 — 保證零重複警示 |
| **高效能流量引擎** | 將規則合併為單一 bulk API query；對大資料集採 O(1) memory streaming |
| **進階報表引擎** | 15 模組的 Traffic 報表附 **Bulk-Delete** 管理；4 模組 Audit 報表、Policy Usage 報表，以及 VEN Status 庫存報表 — HTML、CSV、PDF、XLSX 或全部格式 |
| **資安發現** | 24 條自動化規則：B 系列（B001–B009：勒索軟體、覆蓋率）+ L 系列（L001–L010：橫向移動、外洩）+ R 系列（R01–R05：Draft Policy 對齊） |
| **報表排程** | Cron 風格的循環報表（每日/每週/每月）並自動以 Email 派送 |
| **規則排程器** | 自動啟用/停用 PCE 規則；**三層 Draft 保護**避免誤 provision |
| **Workload Quarantine** | 以 Quarantine label 隔離受感染 workload；支援 IP/CIDR/subnet 搜尋 |
| **多通道警示** | Email (SMTP)、LINE Notifications、Webhook 同時派送 |
| **多語系** | CLI、Web GUI、報表、警示完整支援英文 + 繁體中文 |

> [!NOTE]
> **SIEM 轉送器** — 內建 CEF / JSON / RFC5424 syslog / Splunk HEC 轉送，支援 UDP / TCP / TLS / HTTPS，每個目的地獨立 DLQ 與指數退避重試。新 cache 列在 ingest 時即直接派送排入。詳見 **[SIEM 整合](docs/SIEM_Integration_zh.md)**。

---

## 快速開始（從原始碼開發）

> 正式部署採用自包含的離線 bundle（目標主機不需系統 Python，也不需網路）。Linux 與 Windows 的 bundle 流程請見 **[安裝指南](docs/Installation_zh.md#12-安裝)**。

### 先決條件

- **PCE 管理員權限**以建立 API Key — 進入 PCE Web Console 右上角使用者選單 → **My API Keys** → **Add**，記下產生的 `auth_username`（即 `api.key`）與 `secret`。
- **網路連通性**：本機需可透過 HTTPS（通常為 8443 port）連到 PCE。
- **Python 3.10+** 並可使用 `venv`。Ubuntu 22.04+ / Debian 12+ 因 PEP 668 強制使用 venv。
- 若 PCE 使用 **自簽 TLS 憑證**（lab 環境常見），複製 example 後請將 `api.verify_ssl` 改為 `false`，否則首次連線會以 SSL 驗證錯誤失敗。

### 執行

```bash
git clone <repo-url>
cd illumio-ops
cp config/config.json.example config/config.json    # 接著編輯 api.url / api.key / api.secret，填入「My API Keys」取得的值
python -m venv venv && source venv/bin/activate     # Ubuntu 22.04+ / Debian 12+ 必要（PEP 668）
pip install -r requirements.txt

# 最常見：常駐 daemon + Web GUI 於 https://127.0.0.1:5001
python illumio-ops.py --monitor-gui --interval 5 --port 5001
```

### 驗證啟動成功

首次執行依序應見：

1. stderr 印出 `DEFAULT ADMIN LOGIN` 橫幅，顯示 `username: illumio` / `password: illumio`（出廠預設值，首次登入會強制變更）。
2. `TLS: Using self-signed certificate (NNN days remaining)`。
3. `Open in browser: https://127.0.0.1:5001`，非 daemon 模式下瀏覽器會自動開啟。

於瀏覽器：忽略自簽憑證警告 → 以 `illumio` / `illumio` 登入 → 設定新密碼 → 進入 Dashboard，**PCE Status** widget 應顯示「connected」。若顯示「auth failed」，請覆核 `api.key` / `api.secret`。

隔離環境部署、systemd / NSSM 服務註冊、完整相依套件清單，請見 **[安裝指南](docs/Installation_zh.md)**。所有執行模式（`--gui` / `--monitor` / 互動式 CLI）、完整子命令參考、操作流程說明，請見 **[使用手冊 §1](docs/User_Manual_zh.md)**。

### 首次登入（安全性）

預設帳密 `illumio` / `illumio` 於首次啟動自動 seed；GUI session 會以 `must_change_password=true` 阻擋直到密碼變更（見 `src/config.py:200`）。明文初始密碼亦會寫入 `config.json` 的 `web_gui._initial_password`，並在首次密碼變更成功後抹除。完整流程：**[使用手冊 §3](docs/User_Manual_zh.md#3-web-gui-安全性)**。

### Logging

純文字 log 寫入 `logs/illumio_ops.log`（10 MB × 10 檔案輪替）。SIEM 用結構化 log 可在 `config.json` 加上 `logging.json_sink: true` 以額外輸出 `logs/illumio_ops.json.log`。Log 診斷見 **[疑難排解 §7](docs/Troubleshooting_zh.md)**。

---

## 文件 — 依角色

**首次安裝部署**
- [安裝指南](docs/Installation_zh.md) — RHEL/Ubuntu/Windows 安裝、離線 bundle、systemd/NSSM
- [使用手冊 §1](docs/User_Manual_zh.md) — 執行模式、CLI 子命令

**日常運維**
- [使用手冊](docs/User_Manual_zh.md) — 警示、隔離、多 PCE、設定參考
- [報表模組](docs/Report_Modules_zh.md) — 各報表章節含義
- [疑難排解](docs/Troubleshooting_zh.md) — 常見錯誤與解法

**安全分析**
- [安全規則參考](docs/Security_Rules_Reference_zh.md) — B/L/R 規則目錄、嚴重性模型
- [報表模組](docs/Report_Modules_zh.md) — 模組層級資安發現

**整合**
- [SIEM 整合](docs/SIEM_Integration_zh.md) — CEF/JSON/HEC 格式、接收端範例
- [API Cookbook](docs/API_Cookbook_zh.md) — PCE REST API 模式；本工具的 HTTP API

**儲存 / 進階**
- [PCE 快取](docs/PCE_Cache_zh.md) — 本機 SQLite 快取；backfill；retention

**背景知識**
- [架構文件](docs/Architecture_zh.md) — Illumio 平台入門 + 本工具內部結構
- [詞彙表](docs/Glossary_zh.md) — Illumio 與工具特有術語

---

## 專案結構

```text
illumio-ops/
├── illumio-ops.py          # 進入點 — dispatcher 視 argv 路由 click subcommand 或 legacy argparse
├── src/
│   ├── main.py                 # 舊版 argparse 路徑（--monitor / --gui / --report）；新 flag 已移至 src/cli
│   ├── api_client.py           # PCE REST API（async job、native filter、O(1) streaming）
│   ├── api/                    # PCE API helpers（async jobs、labels、traffic queries）
│   ├── analyzer.py             # 規則引擎（flow matching、事件分析、狀態管理）
│   ├── cli/                    # Click subcommand + 共用 output / exit-code helper（root、monitor、gui_cmd、report、rule、workload、cache、siem、status、config、menus/）
│   ├── gui/                    # Flask Web GUI 套件 — shell + Blueprint routes（auth/admin/dashboard/events/reports/rules/rule_scheduler/actions/config）— 約 70 個 route
│   ├── config.py               # ConfigManager（Argon2id GUI 密碼、atomic write）
│   ├── reporter.py             # 多通道警示派送（SMTP、LINE、Webhook）
│   ├── i18n/                   # i18n 引擎（engine.py + JSON 資料）— EN/ZH_TW，約 2,200 個 string key
│   ├── events/                 # 事件 pipeline（catalog、normalize、dedup、throttle）
│   ├── report/                 # 報表引擎（15 個 traffic 模組 + audit + policy usage + R3 intelligence 模組）
│   ├── scheduler/              # 報表排程 cron 工作
│   ├── settings/               # 互動式設定 wizard（從 legacy settings.py 拆分）
│   ├── pce_cache/              # SQLite WAL 快取 + ingestor
│   ├── siem/                   # SIEM forwarder（CEF/JSON/Syslog、UDP/TCP/TLS/HEC）
│   ├── alerts/                 # 警示 plugin（mail、LINE、webhook）
│   ├── templates/              # Flask HTML templates（login、index）
│   └── static/                 # 內嵌字型（Space Grotesk / Inter / JetBrains Mono）、JS、CSS
├── config/                     # config.json、alerts.json、report_config.yaml、rule_schedules.json
├── docs/                       # EN + ZH_TW 文件
├── tests/                      # 約 178 個測試檔（~970 個 test）
├── deploy/                     # systemd（Ubuntu/RHEL）+ NSSM（Windows）服務設定
└── scripts/                    # 工具腳本（離線 bundle 建置、安裝/解除安裝、preflight）
```
