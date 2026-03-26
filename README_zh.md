# Illumio PCE Monitor

![Version](https://img.shields.io/badge/Version-v1.0.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

專為 **Illumio Core (PCE)** 設計的進階**無 Agent** 監控暨自動化平台。透過 REST API 實現即時安全事件偵測、智慧型流量分析、進階報表產生（含自動化資安發現）、排程報表寄送，以及多通道即時告警。**CLI/Daemon 模式無需安裝外部套件**（僅使用 Python 標準函式庫）。

---

## ✨ 核心特色

| 功能 | 說明 |
|:---|:---|
| **三種執行模式** | 背景守護程序 (`--monitor`)、互動式 CLI 精靈、或 Flask 驅動的 **Web GUI** (`--gui`) |
| **安全事件監控** | 追蹤 PCE 稽核事件，採用時間戳記錨點，保證零重複告警 |
| **高效能流量引擎** | 將所有規則整合為單次 API 查詢，O(1) 記憶體串流處理大型資料集 |
| **進階報表引擎** | 15 模組流量報表、4 模組稽核報表、VEN 狀態盤點報表 — HTML + Excel 雙格式 |
| **19 項自動化資安發現** | B 系列（勒索軟體、覆蓋率、異常行為）+ L 系列（橫向移動、資料外洩、爆炸半徑） |
| **排程報表** | 類 Cron 週期性報表（每日/每週/每月），可自動 Email 附件寄送 |
| **工作負載隔離** | 透過 Quarantine Label（Mild/Moderate/Severe）隔離遭入侵主機 |
| **多通道即時告警** | 同步支援 Email (SMTP)、LINE 通知、Webhooks |
| **多語系介面** | Web GUI 及 HTML 報表均支援即時切換英文 ↔ 繁體中文，無須重新載入 |

---

## 🚀 快速開始

### 1. 系統需求

- **Python 3.8+**
- **核心功能（免安裝）**：CLI 及 Daemon 模式僅使用 Python 標準函式庫，無需任何外部套件
- **選用 — Web GUI**：`flask`
- **選用 — 報表**：`pandas`、`openpyxl`、`pyyaml`

### 2. 安裝與啟動

```bash
git clone <repo-url>
cd illumio_monitor
cp config/config.json.example config/config.json    # 編輯並填入 PCE 憑證

# 互動式 CLI：
python illumio_monitor.py

# Web 視覺化介面（開啟 http://127.0.0.1:5001）：
python illumio_monitor.py --gui

# 背景 Daemon 模式（每 5 分鐘自動檢查）：
python illumio_monitor.py --monitor --interval 5
```

### 3. 基本設定 (`config.json`)

```json
{
    "api": {
        "url": "https://pce.example.com:8443",
        "org_id": "1",
        "key": "api_xxxxxxxxxxxxxx",
        "secret": "your-api-secret-here",
        "verify_ssl": true
    }
}
```

> 完整設定參考請見[完整使用手冊](docs/User_Manual_zh.md)。

---

## 📊 報表引擎

報表可從 Web GUI、CLI 選單手動產生，或設定排程自動執行。

### 流量報表 — 15 個分析模組

| 模組 | 說明 |
|:---|:---|
| 執行摘要 | KPI 指標卡：總流量、覆蓋率%、主要資安發現 |
| 1 · 流量總覽 | 總流量、策略決策分佈、Top 通訊埠 |
| 2 · 策略判定 | 各決策分佈，含進出向拆分與各 Port 覆蓋率 |
| 3 · 未覆蓋流量 | 無允許規則的流量；Port 缺口排名；未覆蓋服務 |
| 4 · 勒索軟體風險 | **需調查目標**（高風險 Port 上的允許流量）、各 Port 明細、主機暴露排名 |
| 5 · 遠端存取 | SSH/RDP/VNC/TeamViewer 流量分析 |
| 6 · 使用者與程序 | 流量紀錄中出現的使用者帳號與程序 |
| 7 · 跨標籤矩陣 | 環境/應用/角色標籤組合間的流量矩陣 |
| 8 · 非受管主機 | 非 PCE 管理主機的流量；按應用及 Port 細分 |
| 9 · 流量分佈 | 通訊埠與協定分佈 |
| 10 · 允許流量 | Top 允許流量；稽核標記 |
| 11 · 頻寬與傳輸量 | Top 傳輸量流量 + 頻寬統計（Max/Avg/P95）；異常偵測 |
| 13 · 執行就緒評分 | 0–100 分評估，含各因子細項與修補建議 |
| 14 · 基礎架構評分 | 節點中心性評分，識別關鍵基礎架構 |
| 15 · 橫向移動風險 | 橫向移動模式分析與高風險路徑 |
| **資安發現項目** | 19 條自動化規則 — CRITICAL/HIGH/MEDIUM/LOW/INFO |

### 其他報表

| 報表 | 說明 |
|:---|:---|
| **稽核報表** | 系統健康事件、使用者認證活動、策略變更 |
| **VEN 狀態盤點** | 線上/離線 VEN，含最後心跳時間分桶（24h / 24–48h / 長期離線） |

---

## 🔍 資安發現（19 條規則）

對每份流量資料集自動執行偵測，結果依嚴重性分組呈現。

| 系列 | 偵測重點 | 規則 |
|:---|:---|:---|
| **B 系列** | 勒索軟體暴露、策略覆蓋率缺口、行為異常 | B001–B009 |
| **L 系列** | 橫向移動、憑證竊取、爆炸半徑路徑、資料外洩 | L001–L010 |

主要偵測項目包含：跨環境未阻斷的勒索軟體 Port（CRITICAL）、單一來源對橫向移動 Port 的扇出攻擊、基於圖形遍歷的爆炸半徑分析、受管理主機向非受管主機的大量資料傳輸。詳見 [資安規則說明文件](docs/Security_Rules_Reference_zh.md)。

---

## 🏢 企業環境 / 離線安裝

### 方案 A — Red Hat / CentOS（dnf / yum）

```bash
sudo dnf install python3-flask python3-pyyaml python3-pandas
# openpyxl 不在官方 RHEL Repo，請使用方案 B
```

### 方案 B — 預先下載 Wheel（pip 離線安裝）

```bash
# 在有網路的機器上：
pip download flask pandas openpyxl pyyaml -d ./offline_packages/

# 在離線主機上：
pip install --no-index --find-links=./offline_packages/ flask pandas openpyxl pyyaml
```

### 方案 C — 內部 PyPI Mirror（Nexus / Artifactory）

```bash
pip install pandas openpyxl pyyaml flask \
    --index-url https://nexus.internal/repository/pypi-proxy/simple/
```

| 套件 | RHEL AppStream | Ubuntu `apt` | Wheel 離線 |
|------|:--------------:|:------------:|:----------:|
| `flask` | ✅ `python3-flask` | ✅ `python3-flask` | ✅ |
| `pyyaml` | ✅ `python3-pyyaml` | ✅ `python3-yaml` | ✅ |
| `pandas` | ✅ `python3-pandas`（RHEL 8+）| ✅ `python3-pandas` | ✅ |
| `openpyxl` | ❌ 不在官方 Repo | ✅ `python3-openpyxl` | ✅ |

---

## 📚 文件索引

| 文件 | 說明 |
|:---|:---|
| **[完整使用手冊](docs/User_Manual_zh.md)** | 安裝、執行模式、規則建立、告警通道、報表、排程 |
| **[資安規則說明文件](docs/Security_Rules_Reference_zh.md)** | 19 條資安發現規則的完整說明、觸發條件與調校指引 |
| **[API 整合教學](docs/API_Cookbook_zh.md)** | 按場景分類的 API 教學（SIEM/SOAR 整合） |

---

## 📁 專案結構

```text
illumio_monitor/
├── illumio_monitor.py          # 程式進入點
├── config/
│   ├── config.json             # 執行時設定（已加入 gitignore）
├── state.json                  # 持久化狀態（已加入 gitignore）
├── requirements.txt
│
├── src/
│   ├── main.py                 # CLI 參數解析、Daemon 迴圈、互動選單
│   ├── api_client.py           # Illumio REST API 客戶端（重試、串流、認證）
│   ├── analyzer.py             # 規則引擎：事件/流量/頻寬比對
│   ├── reporter.py             # 告警發送器（Email、LINE、Webhook）+ 報表 Email
│   ├── config.py               # ConfigManager（原子寫入、規則 CRUD）
│   ├── gui.py                  # Flask Web GUI（~25 個 JSON API 端點）
│   ├── settings.py             # CLI 互動式精靈（規則、排程管理）
│   ├── report_scheduler.py     # 週期性報表排程引擎
│   ├── i18n.py                 # EN / ZH_TW 翻譯字典（200+ 鍵）
│   ├── utils.py                # 日誌、ANSI 色碼、單位格式化、CJK 寬度
│   ├── templates/index.html    # Web GUI SPA（vanilla JS，Illumio 品牌主題）
│   │
│   └── report/                 # 報表引擎
│       ├── report_generator.py     # 統一入口：解析 → 分析 → 匯出
│       ├── audit_generator.py      # 稽核報表協調器
│       ├── ven_status_generator.py # VEN 狀態報表協調器
│       ├── rules_engine.py         # 19 條資安發現規則（B+L 系列）
│       ├── parsers/                # API 解析器、CSV 解析器、驗證器
│       ├── exporters/              # HTML + Excel 匯出器、報表 i18n
│       └── analysis/               # 15 個流量模組 + 4 個稽核模組
│
├── config/
│   ├── report_config.yaml      # 勒索軟體 Port 清單、偵測閾值
│   ├── semantic_config.yaml    # 自訂語意規則（選用）
│   └── csv_column_mapping.yaml # CSV 欄位對映設定
│
├── docs/                       # 文件
├── deploy/                     # systemd 服務 + Windows 安裝腳本
├── tests/                      # 單元測試 (pytest)
└── logs/                       # 應用程式日誌（循環寫入）
```

---

## 🧪 測試

```bash
# 單元測試
pytest tests/test_analyzer.py

# 稽核報表整合測試（使用 DummyApiClient）
python test_audit.py

# 真實 API 整合測試（需要 config.json 有效憑證）
python test_real_events.py
```
