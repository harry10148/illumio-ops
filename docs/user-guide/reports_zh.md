---
title: Reports
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - src/report/
  - src/report/rules/
  - src/report/exporters/
  - src/report/analysis/
  - src/report/rules_engine.py
  - python illumio-ops.py report --help
  - python illumio-ops.py report traffic --help
  - python illumio-ops.py report audit --help
  - python illumio-ops.py report ven-status --help
  - python illumio-ops.py report policy-usage --help
  - commit e7722ba
related_docs:
  - ../architecture/report-engine.md
  - ../reference/cli.md
  - alerts-and-quarantine.md
  - siem-integration.md
---

> 🌐 **[English](reports.md)** | **[繁體中文](reports_zh.md)**
> 📍 [INDEX](../INDEX.md) › 使用者指引 › 報告
> 🔍 最後驗證 **2026-05-15** 對 commit `e7722ba` — 詳見 frontmatter

# 報告

Illumio PCE Ops 可從即時 PCE 資料或快取資料集產生四種報告類型。
報告儲存於 `reports/` 目錄，輸出為 `.html`，並可選擇同時輸出 `.csv` / `.xlsx` 原始資料封存檔。

---

## 報告類型總覽

| 報告類型 | CLI 子命令 | 主要資料來源 | 用途 |
|:---|:---|:---|:---|
| **流量** | `report traffic` | PCE 非同步查詢或 CSV | 完整流量安全分析 — 政策決定、勒索軟體暴露、橫向移動風險、強制執行就緒度 |
| **稽核** | `report audit` | PCE 事件 API | 系統健康、使用者活動與政策變更稽核日誌 |
| **VEN 狀態** | `report ven-status` | PCE 工作負載 API | VEN 清單含上線/離線/未受管分類 |
| **政策使用量** | `report policy-usage` | PCE ruleset + 流量查詢或 Workloader CSV | 逐規則流量命中分析；識別未使用規則 |

---

## 執行報告

### 流量報告

```bash
python3 illumio-ops.py report traffic [OPTIONS]
```

| 旗標 | 值 | 預設 | 說明 |
|:---|:---|:---|:---|
| `--source` | `api` \| `csv` | `api` | 從 PCE 取得即時資料或從 CSV 檔案讀取 |
| `--file PATH` | 路徑 | — | `--source csv` 時必填 |
| `--format` | `html` \| `csv` \| `pdf` \| `xlsx` \| `all` | `html` | 輸出格式；`pdf` 產生列印就緒 HTML（見[列印版面](#列印版面與-html-匯出)） |
| `--output-dir PATH` | 路徑 | `reports/` | 目的目錄 |
| `--email` | 旗標 | 關閉 | 產生後寄送報告 Email |
| `--profile` | `security_risk` \| `network_inventory` | `security_risk` | 報告焦點設定檔 |

### 稽核報告

```bash
python3 illumio-ops.py report audit [OPTIONS]
```

| 旗標 | 值 | 說明 |
|:---|:---|:---|
| `--format` | `html` \| `csv` \| `pdf` \| `xlsx` \| `all` | 輸出格式 |
| `--output-dir PATH` | 路徑 | 目的目錄 |

### VEN 狀態報告

```bash
python3 illumio-ops.py report ven-status [OPTIONS]
```

| 旗標 | 值 | 說明 |
|:---|:---|:---|
| `--format` | `html` \| `csv` \| `pdf` \| `xlsx` \| `all` | 輸出格式 |
| `--output-dir PATH` | 路徑 | 目的目錄 |

### 政策使用量報告

```bash
python3 illumio-ops.py report policy-usage [OPTIONS]
```

| 旗標 | 值 | 說明 |
|:---|:---|:---|
| `--source` | `api` \| `csv` | 資料來源 |
| `--file PATH` | 路徑 | `--source csv` 時必填 |
| `--format` | `html` \| `csv` \| `pdf` \| `xlsx` \| `all` | 輸出格式 |
| `--output-dir PATH` | 路徑 | 目的目錄 |

### 命令別名

四個子命令均有 `generate-*` 別名以維持向後相容：

| 建議用法 | 別名 |
|:---|:---|
| `report traffic` | `report generate-traffic` |
| `report audit` | `report generate-audit` |
| `report ven-status` | `report generate-ven-status` |
| `report policy-usage` | `report generate-policy-usage` |

> 完整旗標矩陣（含日期範圍與 PCE 設定檔旗標）請見 [CLI Reference](../reference/cli.md)。

---

## 報告模組

**流量報告** 由 15 個分析模組加上安全發現掃描組成。
其他報告類型各自使用專屬產生器。

### 流量報告模組（src/report/analysis/）

- **mod01 — Traffic Overview**：流量總數、允許/封鎖/潛在封鎖分類、最高流量埠號
- **mod02 — Policy Decisions**：逐決定分類含入站/出站拆分與逐埠覆蓋率 %
- **mod03 — Uncovered Flows**：未匹配允許規則的流量；埠號缺口排名；未覆蓋服務（app + port）
- **mod04 — Ransomware Exposure**：目標主機在關鍵/高風險埠號上有 ALLOWED 流量；逐埠詳情；主機暴露排名
- **mod05 — Remote Access**：SSH、RDP、VNC 與 TeamViewer 流量分析
- **mod06 — User & Process**：流量記錄中出現的使用者帳號與處理程序名稱
- **mod07 — Cross-Label Matrix**：environment / app / role 標籤組合間流量矩陣
- **mod08 — Unmanaged Hosts**：來自/前往非 PCE 受管主機的流量；逐 app 與逐埠詳情
- **mod09 — Traffic Distribution**：埠號與協定分佈圖表
- **mod10 — Allowed Traffic**：最高允許流量含稽核旗標
- **mod11 — Bandwidth & Volume**：依位元組排名的最高流量；max/avg/P95 統計卡；多連線流量異常偵測
- **mod12 — Executive Summary**：KPI 卡片（總流量、政策覆蓋率 %、最高發現）；同時用作 Email 內容
- **mod13 — Enforcement Readiness**：0–100 分評分含因子分解與修復建議
- **mod14 — Infrastructure Scoring**：節點中心性評分以識別關鍵服務（入度、出度、介數中心性）
- **mod15 — Lateral Movement Risk**：橫向移動模式分析與高風險樞紐路徑

### 附加分析模組（src/report/）

- **attack_posture**：跨模組結果彙整的攻擊態勢評分
- **mod_change_impact**：變更影響報告的差異分析
- **mod_draft_actions**：從草稿政策決定衍生的建議行動
- **mod_draft_summary**：草稿政策狀態摘要指標
- **mod_ringfence**：Ring-fence 邊界驗證

### 解析器（src/report/parsers/）

- **api_parser**：將 PCE API 流量查詢回應正規化為內部流量綱要
- **csv_parser**：解析 CSV 匯出（來自 PCE 或 Workloader）為相同流量綱要
- **validators**：分析前對流量記錄進行輸入驗證

> 完整報告引擎內部架構：[Architecture › Report Engine](../architecture/report-engine.md)（B2 deliverable）。

---

## 安全規則 — 速查

安全發現在每次流量報告時自動執行。24 條規則分為三個系列。

### 系列總覽

| 系列 | 規則 ID | 焦點 |
|:---|:---|:---|
| **B 系列**（基準） | B001–B009 | 勒索軟體暴露、政策覆蓋缺口、行為異常 |
| **L 系列**（橫向移動） | L001–L010 | 攻擊者樞紐、憑證竊取、爆炸半徑路徑、資料外洩 |
| **R 系列**（草稿政策決定） | R01–R05 | 即時政策狀態與草稿（未佈建）規則之間的衝突 |

### B 系列 — 基準規則

| 規則 ID | 名稱 | 嚴重度 | 觸發條件 |
|:---|:---|:---|:---|
| B001 | Ransomware Risk Port — Contextual Analysis | CRITICAL / HIGH / MEDIUM / INFO | 關鍵勒索軟體埠號上有允許流量（SMB 445、RDP 3389、RPC 135、WinRM 5985/5986）；嚴重度依跨環境/跨子網路情境而定 |
| B002 | Ransomware Risk Port (High) | HIGH | 高階埠號上有允許流量（TeamViewer 5938、VNC 5900、NetBIOS 137–139） |
| B003 | Ransomware Risk Port (Medium) — Uncovered | MEDIUM | 中階埠號上的未覆蓋流量（SSH 22、FTP 20/21、Telnet 23、NFS 2049、mDNS 5353 等） |
| B004 | Unmanaged Source High Activity | MEDIUM | 未受管來源主機超過流量計數閾值（預設：50 筆流量） |
| B005 | Low Policy Coverage | MEDIUM | 政策覆蓋率 % 低於閾值（預設：30%） |
| B006 | High Lateral Movement (Fan-Out) | HIGH | 單一來源聯繫超過 N 個唯一目的地（預設：10） |
| B007 | Single User High Destinations | HIGH | 單一使用者帳號抵達超過 N 個唯一目的地（預設：20） |
| B008 | High Bandwidth Anomaly | MEDIUM | 流量位元組超過觀測流量的第 N 百分位數（預設：P95） |
| B009 | Cross-Env Flow Volume | INFO | 跨環境流量計數超過閾值（預設：100） |

### L 系列 — 橫向移動規則

| 規則 ID | 名稱 | 主要焦點 |
|:---|:---|:---|
| L001 | Cleartext Protocol in Use | 內部流量使用 Telnet、FTP、HTTP |
| L002 | Network Discovery Protocol Exposure | 未封鎖的探索協定流量（mDNS、LLMNR、SSDP、WSD） |
| L003 | Database Port Wide Exposure | 資料庫埠號（MySQL、MSSQL、PostgreSQL 等）可被多個來源存取 |
| L004 | Cross-Environment Database Access | 資料庫流量跨越環境邊界 |
| L005 | Identity Infrastructure Wide Exposure | LDAP/Kerberos/AD 埠號廣泛可存取 |
| L006 | High Blast-Radius Lateral Movement Path | 來源透過橫向埠號可抵達大量目的地 |
| L007 | Unmanaged Host Accessing Critical Services | 未受管主機存取身份識別/資料庫/管理服務 |
| L008 | Lateral Ports in Test Mode (PB) | 橫向風險埠號處於潛在封鎖（測試模式）狀態 |
| L009 | Data Exfiltration Pattern (Outbound to Unmanaged) | 受管工作負載向未受管外部主機傳送大量資料 |
| L010 | Cross-Environment Lateral Port Access | SSH/Telnet/RDP 跨越環境標籤 |

### R 系列 — 草稿政策決定規則

| 規則 ID | 名稱 | 啟用時機 |
|:---|:---|:---|
| R01 | Draft Deny Detected | 活躍 ruleset 使用 `draft_pd`；草稿規則下流量將被拒絕 |
| R02 | Override Deny Detected | 草稿拒絕覆蓋即時允許規則 |
| R03 | Visibility Boundary Breach | 草稿規則將使流量暴露於可見性邊界外 |
| R04 | Allowed Across Boundary | 草稿允許跨越已設定邊界 |
| R05 | Draft/Reported Mismatch | `draft_policy_decision` 與 `policy_decision` 不同 |

> 完整規則細節與可調閾值：[CLI Reference](../reference/cli.md) 及 `src/report/rules_engine.py`。

---

## 列印版面與 HTML 匯出

**透過 ReportLab 產生 PDF 的功能已移除**（commit `9acedda`）。`--format pdf` 旗標與 GUI 的「PDF」選項
現在產生以 `@media print` CSS 樣式化的**列印就緒 HTML 檔案**。

主要行為：

- 選擇 `--format pdf` 輸出含 `@media print` 規則的 `.html` 檔案，針對 A4 紙張最佳化。
- 報告導覽列中的**列印**按鈕觸發 `window.print()`，供瀏覽器原生儲存為 PDF。
- 列印 CSS 功能：A4 封面頁（螢幕模式隱藏）、防溢出資料表版面、圖表裁切修正、
  高對比度徽章、以及列印時隱藏頁尾（封面頁已含標題/日期）。
- 寬資料表在列印寬度下分割為群組子表（commit `f935717`）。
- `mod13` 就緒度表格在列印模式切換為緊縮 5 欄版面，螢幕保留完整 10 欄（commit `93f5efc`）。

匯出格式摘要：

| 格式值 | 輸出 | 說明 |
|:---|:---|:---|
| `html` | `report_<date>.html` | 含圖表與導覽側欄的互動式報告 |
| `csv` | `report_<date>_raw.zip` | CSV 原始流量資料；適合 SIEM 擷取 |
| `xlsx` | `report_<date>.xlsx` | 含逐模組工作表的 Excel 活頁簿 |
| `pdf` | `report_<date>_print.html` | 列印就緒 HTML；在瀏覽器開啟後列印為 PDF |
| `all` | 以上全部 | 同時產生 html、csv、xlsx 與 pdf |

---

## Email 派送

流量報告支援透過 CLI 的 `--email` 旗標或 Web GUI 排程器的 **Email** 開關進行 Email 派送。

啟用時：
1. 報告 HTML 檔案作為附件附上。
2. 從執行摘要模組（mod12）建構精簡 HTML 摘要 Email — 包含關鍵指標、最高發現與行動矩陣表格。
3. Email 透過 `reporter.send_report_email()` 寄出，該函式從操作員設定讀取 SMTP 設定。

**常駐程式 / 排程模式**：排程器產生的報告可設定為自動寄送 Email。
請見 Web GUI › Settings › Report Schedule，或 CLI **2. Report Generation → 5. Report Schedule Management** 選單。

> SMTP 設定與事件轉發：[SIEM Integration](siem-integration.md)。

---

## 相關文件

- [Report engine internals](../architecture/report-engine.md) — 報告建構方式（B2 deliverable）
- [CLI Reference](../reference/cli.md) — `report` 子命令與旗標
- [Alerts & Quarantine](alerts-and-quarantine.md) — 當報告驅動警報時
- [SIEM Integration](siem-integration.md) — 轉發報告相關事件
