# Illumio PCE Monitor

![Version](https://img.shields.io/badge/Version-v1.0.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

專為 **Illumio Core (PCE)** 設計的進階 **無 Agent (Agentless)** 監控暨自動化工具。透過 REST API 實現智慧型流量分析、安全事件偵測、工作負載隔離與多通道自動告警。**CLI/Daemon 模式無需安裝外部套件**（僅使用 Python 標準函式庫）。

---

## ✨ 核心特色

| 功能 | 說明 |
|:---|:---|
| **三種執行模式** | 背景守護程序 (`--monitor`)、互動式 CLI 精靈、或 Flask 驅動的 **Web GUI** (`--gui`) |
| **安全事件監控** | 追蹤 PCE 稽核事件，採用時間戳記錨點，保證零重複告警 |
| **高效能流量引擎** | 將所有規則整合為單次 API 查詢，O(1) 記憶體串流處理 |
| **工作負載隔離** | 透過 Quarantine Label（Mild/Moderate/Severe）隔離遭入侵主機 |
| **多通道即時告警** | 同步支援 Email (SMTP)、LINE 通知、Webhooks |
| **多語系介面** | Web GUI 即時切換英文↔繁體中文，無須重新載入 |

---

## 🚀 快速開始

### 1. 系統需求
- **Python 3.8+**
- （若需 Web GUI）：`pip install flask`

### 2. 安裝與啟動

```bash
git clone <repo-url>
cd illumio_monitor
cp config.json.example config.json    # 編輯並填入 PCE 憑證

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

> 完整設定參考請見 [完整使用手冊](docs/User_Manual_zh.md)。

---

## 📖 文件目錄

| 文件 | 說明 |
|:---|:---|
| **[完整使用手冊](docs/User_Manual_zh.md)** | 安裝、執行模式、規則建立、告警通道、Web GUI 使用教學 |
| **[專案架構與修改指南](docs/Project_Architecture_zh.md)** | 程式碼設計、模組職責、資料流、如何修改程式 |
| **[API 教學與 SIEM/SOAR 整合指南](docs/API_Cookbook_zh.md)** | 按場景分類的 API 教學（隔離、流量查詢等），可供 Playbook 直接參考 |

---

## 📁 專案結構

```text
illumio_monitor/
├── illumio_monitor.py     # 程式進入點
├── config.json            # 執行時設定（憑證、規則、告警）
├── state.json             # 持久化狀態（上次檢查時間、告警歷史）
├── requirements.txt       # Python 相依套件
├── src/
│   ├── main.py            # CLI 參數解析、Daemon 迴圈、互動選單
│   ├── api_client.py      # Illumio REST API 客戶端（重試、串流、認證）
│   ├── analyzer.py        # 規則引擎：流量/事件比對、指標計算
│   ├── reporter.py        # 告警發送器（Email、LINE、Webhook）
│   ├── config.py          # 設定管理器（原子寫入）
│   ├── gui.py             # Flask Web GUI 後端（路由 + API 端點）
│   ├── settings.py        # CLI 互動選單（規則 CRUD）
│   ├── i18n.py            # 國際化（EN/ZH 翻譯字典）
│   ├── utils.py           # 工具函式（日誌、色碼、單位格式化）
│   ├── templates/         # Jinja2 HTML 模板
│   └── static/            # CSS/JS 前端資源
├── docs/                  # 文件檔案
├── tests/                 # 單元測試 (pytest)
├── logs/                  # 執行時日誌
└── deploy/                # 部署腳本 (NSSM, systemd)
```
