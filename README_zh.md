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

![Version](https://img.shields.io/badge/Version-v3.20.0--report--intelligence-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow?style=flat-square&logo=python&logoColor=white)
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
| **進階報表引擎** | 15 模組的 Traffic 報表附 **Bulk-Delete** 管理；4 模組 Audit 報表、Policy Usage 報表，以及 VEN Status 庫存報表 — HTML + CSV |
| **資安發現** | 19 條自動化規則：B 系列（勒索軟體、覆蓋率）+ L 系列（橫向移動、外洩）+ R 系列（Draft Policy 對齊） |
| **報表排程** | Cron 風格的循環報表（每日/每週/每月）並自動以 Email 派送 |
| **規則排程器** | 自動啟用/停用 PCE 規則；**三層 Draft 保護**避免誤 provision |
| **Workload Quarantine** | 以 Quarantine label 隔離受感染 workload；支援 IP/CIDR/subnet 搜尋 |
| **多通道警示** | Email (SMTP)、LINE Notifications、Webhook 同時派送 |
| **多語系** | CLI、Web GUI、報表、警示完整支援英文 + 繁體中文 |

> [!WARNING]
> **SIEM 狀態（Preview）** — 內建 SIEM 轉送器目前處於 **Preview** 階段。既有部署可繼續沿用以維持相容性，但在 runtime pipeline 缺口補齊前，不建議新環境上線。

---

## 快速開始

```bash
git clone <repo-url>
cd illumio-ops
cp config/config.json.example config/config.json    # 編輯填入 PCE 認證資訊
pip install -r requirements.txt

# 最常見：常駐 daemon + Web GUI 於 https://127.0.0.1:5001
python illumio-ops.py --monitor-gui --interval 5 --port 5001
```

RHEL / Ubuntu / Windows 離線 bundle 安裝、隔離環境部署、systemd / NSSM 服務註冊、相依套件詳情，請見 **[安裝指南](docs/Installation_zh.md)**。

所有執行模式（`--gui` / `--monitor` / 互動式 CLI）、完整子命令參考、操作流程說明，請見 **[使用手冊 §1](docs/User_Manual_zh.md)**。

### 首次登入

預設帳號為 `illumio`。首次啟動時若 `web_gui.password` 為空，系統會自動產生初始密碼並存於 `config.json` 的 `web_gui._initial_password`，首次登入會強制變更。完整流程：**[使用手冊 §3](docs/User_Manual_zh.md#3-web-gui-安全性)**。

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
├── illumio-ops.py          # 進入點
├── src/
│   ├── main.py                 # CLI argparse、daemon/GUI 編排
│   ├── api_client.py           # PCE REST API（async job、native filter、O(1) streaming）
│   ├── analyzer.py             # 規則引擎（flow matching、事件分析、狀態管理）
│   ├── gui.py                  # Flask Web GUI（~40 個 JSON API endpoint、auth、CSRF）
│   ├── config.py               # ConfigManager（Argon2id GUI 密碼、atomic write）
│   ├── reporter.py             # 多通道警示派送（SMTP、LINE、Webhook）
│   ├── i18n.py                 # i18n 引擎（EN/ZH_TW，~1400+ string keys）
│   ├── events/                 # 事件 pipeline（catalog、normalize、dedup、throttle）
│   ├── report/                 # 報表引擎（15 個 traffic 模組 + audit + policy usage）
│   ├── pce_cache/              # SQLite WAL 快取 + ingestor
│   ├── siem/                   # SIEM forwarder（CEF/JSON/Syslog、UDP/TCP/TLS/HEC）
│   └── alerts/                 # 警示 plugin（mail、LINE、webhook）
├── config/                     # config.json、report_config.yaml
├── docs/                       # EN + ZH_TW 文件
├── tests/                      # 19 個測試檔（116 個 test）
├── deploy/                     # systemd（Ubuntu/RHEL）+ NSSM（Windows）服務設定
└── scripts/                    # 工具腳本
```
