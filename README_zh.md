# Illumio PCE Ops

![Version](https://img.shields.io/badge/Version-v3.2.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

專為 **Illumio Core (PCE)** 設計的進階**無 Agent** 監控暨自動化平台。透過 REST API 實現即時安全事件偵測、智慧型流量分析、進階報表產生（含自動化資安發現）、排程報表寄送，以及多通道即時告警。CLI/Daemon 模式 **無需安裝任何外部套件**（僅使用 Python 標準函式庫）。

---

## 核心特色

| 功能 | 說明 |
|:---|:---|
| **多樣化執行模式** | 背景守護程序 (`--monitor`)、互動式 CLI、獨立 Web GUI (`--gui`)，或**常駐監控 + UI 模式** (`--monitor-gui`) |
| **企業級安全防護** | **PBKDF2 密碼雜湊**（260k 輪迭代）、**登入速率限制**（5 次/分鐘）、**CSRF Synchronizer Token** 防護、**IP 白名單** (CIDR/子網段) |
| **安全事件監控** | 追蹤 PCE 稽核事件，採用時間戳記錨點，保證零重複告警 |
| **高效能流量引擎** | 將所有規則整合為單次 API 查詢，O(1) 記憶體串流處理大型資料集 |
| **進階報表引擎** | 15 模組流量報表（支援**批次刪除**管理）、4 模組稽核報表、政策使用報表、VEN 狀態盤點報表 — HTML + CSV |
| **自動化資安發現** | 19 項預設規則：B 系列（勒索軟體、覆蓋率）+ L 系列（橫向移動、資料外洩） |
| **排程報表** | 類 Cron 週期性報表（每日/每週/每月），可自動 Email 附件寄送 |
| **規則排程器** | 依時間區間自動啟用/停用 PCE 規則；**三層 Draft 安全防護**防止意外派送 |
| **工作負載隔離** | 透過 Quarantine Label 隔離遭入侵主機；支援 IP/CIDR/子網段搜尋 |
| **多通道告警** | Email (SMTP)、LINE 通知、Webhook 同時發送 |
| **國際化** | 完整英文 + 繁體中文介面覆蓋 CLI、Web GUI、報表及告警（~1400+ 翻譯鍵值） |

---

## SIEM 狀態（Preview）

> [!WARNING]
> 內建 SIEM Forwarder 目前定位為 **Preview**。
> 已在使用中的部署可先維持相容運作；新環境暫不建議直接作為正式生產轉送方案，待 runtime pipeline 缺口補齊後再升級為 GA。

## 快速開始

### 1. 系統需求

- **Python 3.8+**
- **核心功能 (CLI/Daemon)**：無需安裝外部套件
- **選用 — Web GUI**：`flask>=3.0`
- **選用 — 報表**：`pandas`、`pyyaml`
- **選用 — PDF 匯出**：`reportlab`（純 Python）。PDF 匯出使用 ReportLab，不需要 WeasyPrint、Pango、Cairo、GTK 或 GDK-PixBuf。PDF 輸出為英文靜態摘要版；完整在地化內容請使用 HTML 或 XLSX。

### 2. 安裝與啟動

```bash
git clone <repo-url>
cd illumio_ops
cp config/config.json.example config/config.json    # 編輯、填入 PCE 憑證

# 互動式 CLI：
python illumio_ops.py

# Web 視覺化介面：
python illumio_ops.py --gui

# 常駐模式 (監控守護程序 + Web GUI)：
python illumio_ops.py --monitor-gui --interval 5 --port 5001

# 純背景 Daemon 模式：
python illumio_ops.py --monitor --interval 5
```

### 3. 首次登入

預設帳號密碼：**帳號 `illumio`** / **密碼 `illumio`**。

1. 使用預設帳號密碼登入。
2. 登入後**立即至 Settings 頁面修改密碼**。
3. 建議設定 **IP 白名單**以限制存取來源。

> [!WARNING]
> 若遺失密碼，請手動刪除 `config/config.json` 中的 `password_hash` 及 `password_salt` 欄位以重設為預設值。

### 4. 安全機制

| 功能 | 說明 |
|:---|:---|
| **密碼雜湊** | PBKDF2-HMAC-SHA256，260,000 次迭代（使用標準函式庫，無需外部套件） |
| **登入速率限制** | 每個 IP 每 60 秒最多 5 次登入嘗試；超過後回傳 HTTP 429 |
| **CSRF 防護** | Synchronizer Token 模式，透過 `<meta>` 標籤注入（無可被 XSS 讀取的 Cookie） |
| **IP 白名單** | 支援單一 IP、CIDR 範圍及子網段遮罩 |
| **SMTP 憑證** | 可設定 `ILLUMIO_SMTP_PASSWORD` 環境變數，避免在設定檔中明文儲存密碼 |

---

## 報表引擎

報表可從 Web GUI、CLI 選單手動產生，或設定排程自動執行。詳細模組介紹請參考[使用手冊](docs/User_Manual_zh.md)。

---

## 文件索引

| 文件 | 說明 |
|:---|:---|
| **[完整使用手冊](docs/User_Manual_zh.md)** | 安裝、執行模式、安全設定、報表排程 |
| **[資安規則說明文件](docs/Security_Rules_Reference_zh.md)** | 19 條資安發現規則的完整說明、觸發條件與指引 |
| **[專案架構文件](docs/Project_Architecture_zh.md)** | 模組設計、執行緒模型與安全性實作說明 |
| **[API 整合教學](docs/API_Cookbook_zh.md)** | 按場景分類的 API 教學（SIEM/SOAR 整合） |

---

## 專案結構

```text
illumio_ops/
├── illumio_ops.py          # 程式進入點
├── src/
│   ├── main.py                 # CLI 參數、Daemon/GUI 執行序協調
│   ├── api_client.py           # PCE REST API (非同步作業、原生過濾器、O(1) 串流)
│   ├── analyzer.py             # 規則引擎（流量比對、事件分析、狀態管理）
│   ├── gui.py                  # Flask Web GUI (~40 JSON API 端點、驗證、CSRF)
│   ├── config.py               # ConfigManager (PBKDF2 雜湊、原子寫入)
│   ├── reporter.py             # 多通道告警發送 (SMTP, LINE, Webhook)
│   ├── i18n.py                 # 國際化引擎 (EN/ZH_TW, ~1400+ 翻譯鍵值)
│   ├── events/                 # 事件處理管線（分類、正規化、去重、節流）
│   ├── report/                 # 報表引擎（15 個流量分析模組 + 稽核 + 政策使用）
│   └── alerts/                 # 告警外掛模組 (mail, LINE, webhook)
├── config/                     # config.json、report_config.yaml
├── docs/                       # 中文/英文完整文件
├── tests/                      # 19 個測試檔案 (116 個測試)
├── deploy/                     # systemd (Ubuntu/RHEL) + NSSM (Windows) 服務設定
└── scripts/                    # 工具腳本
```
