# Illumio PCE Ops

![Version](https://img.shields.io/badge/Version-v3.1.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

專為 **Illumio Core (PCE)** 設計的進階**無 Agent** 監控暨自動化平台。透過 REST API 實現即時安全事件偵測、智慧型流量分析、進階報表產生（含自動化資安發現）、排程報表寄送，以及多通道即時告警。

---

## ✨ 核心特色

| 功能 | 說明 |
|:---|:---|
| **多樣化執行模式** | 背景守護程序 (`--monitor`)、互動式 CLI、獨立 Web GUI (`--gui`)，或**常駐監控 + UI 模式** (`--monitor-gui`) |
| **安全防護強化** | **所有 Web 模式強制登入驗證**；支援 **IP 白名單控制** (CIDR/子網段)，嚴格限制來源存取 |
| **安全事件監控** | 追蹤 PCE 稽核事件，採用時間戳記錨點，保證零重複告警 |
| **高效能流量引擎** | 將所有規則整合為單次 API 查詢，O(1) 記憶體串流處理大型資料集 |
| **進階報表引擎** | 15 模組流量報表（支援**批次刪除**管理）、4 模組稽核報表、VEN 狀態盤點報表 — HTML + CSV |
| **自動化資安發現** | 19 項預設規則：B 系列（勒索軟體、覆蓋率）+ L 系列（橫向移動、資料外洩）。 |
| **排程報表** | 類 Cron 週期性報表（每日/每週/每月），可自動 Email 附件寄送 |
| **規則排程器** | 依時間區間自動啟用/停用 PCE 規則；**三層 Draft 安全防護**防止意外派送 |
| **工作負載隔離** | 透過 Quarantine Label 隔離遭入侵主機；支援 IP/CIDR/子網段搜尋 |

---

## 🚀 快速開始

### 1. 系統需求

- **Python 3.8+**
- **核心功能 (CLI/Daemon)**：無需安裝外部套件
- **選用 — Web GUI**：`flask`
- **選用 — 報表**：`pandas`、`pyyaml`

### 2. 安裝與啟動

```bash
git clone <repo-url>
cd illumio_ops
cp config/config.json.example config/config.json    # 編輯、填入 PCE 憑證

# 互動式 CLI：
python illumio_ops.py

# Web 視覺化介面 (需登入: illumio / illumio)：
python illumio_ops.py --gui

# 常駐模式 (監控守護程序 + Web GUI)：
python illumio_ops.py --monitor-gui --interval 5 --port 5001

# 純背景 Daemon 模式：
python illumio_ops.py --monitor --interval 5
```

### 3. 預設登入資訊

所有 Web 介面均受到保護：
- **帳號**：`illumio`
- **密碼**：`illumio`

> [!WARNING]
> 第一次登入後，請務必立即至 **Settings** 頁面修改密碼，並建議設定 **IP 白名單** 以強化安全性。

---

## 📊 報表引擎

報表可從 Web GUI、CLI 選單手動產生，或設定排程自動執行。詳細模組介紹請參考[使用手冊](docs/User_Manual_zh.md)。

---

## 📚 文件索引

| 文件 | 說明 |
|:---|:---|
| **[完整使用手冊](docs/User_Manual_zh.md)** | 安裝、執行模式、安全設定、報表排程 |
| **[資安規則說明文件](docs/Security_Rules_Reference_zh.md)** | 19 條資安發現規則的完整說明、觸發條件與指引 |
| **[專案架構文件](docs/Project_Architecture_zh.md)** | 模組設計、執行緒模型與安全性實作說明 |
| **[API 整合教學](docs/API_Cookbook_zh.md)** | 按場景分類的 API 教學（SIEM/SOAR 整合） |

---

## 📁 專案結構

```text
illumio_ops/
├── illumio_ops.py          # 程式進入點
├── src/
│   ├── main.py                 # CLI 參數、Daemon/GUI 執行序協調
│   ├── gui.py                  # Flask Web GUI (含登入驗證與 IP 過濾)
│   ├── config.py               # ConfigManager (執行緒安全、原子寫入)
│   ├── templates/login.html    # 明亮主題登入頁面
│   └── ...
├── docs/                       # 完整的中文/英文文件
└── ...
```
