# VEN 報表:Ransomware Exposure & 高風險開放埠（取代 mod16）

- **日期**: 2026-06-03
- **狀態**: 設計（待 spec review → 實作計畫）
- **目標報表**: VEN Status Report
- **PCE 需求**: Core 23.5+（`risk_summary` 隨 workload 清單回傳）；lab 已驗證於 25.2.40

## 1. 背景與動機

現有兩個相關功能各有侷限：

- **mod04（Traffic report）**：從**真實流量**比對靜態 `ransomware_risk_ports` 表推估勒索曝險。屬「流量視角」，保留不動。
- **mod16（Traffic report, Open-Ports Attack Surface）**：逐 workload 盤點**所有** `open_service_ports`，中性、無風險分級、雜訊多，且成本高（最多 1+500 次 API）。

PCE 自 23.x 起提供**原生 Ransomware Protection Dashboard 資料**，直接給出每台 workload 的曝險等級、保護覆蓋率，以及每個風險服務埠的 severity / 保護狀態。本設計**移除 mod16**，在 VEN 報表新增一個以原生資料為基礎、聚焦「高風險開放埠 + process 對應」的 section。

> 結論：原生 API 取代的是 mod16（全埠盤點），不是 mod04（流量）。兩者視角不同。

## 2. 需求（已與使用者定案）

1. 移除 mod16，寫全新模組，放 **VEN Status Report**。
2. 全部用**原生 PCE 資料**，不再維護靜態風險埠表。
3. 一張 **per-VEN 表**：看出哪些 VEN 風險較高、各開了幾個高風險埠。
4. 每個高風險開放埠要 **mapping 到 process**（哪個程序在聽）。
5. 預設常開，PCE 不支援 / 無資料時優雅略過。

## 3. 資料來源（已對 lab PCE 實測驗證）

### 3.1 端點與欄位

- **`GET /api/v2/orgs/{org}/workloads?managed=true`**（VEN 報表已呼叫）
  - 23.5+ 起每筆帶 `risk_summary.ransomware = {workload_exposure_severity, ransomware_protection_percent, last_updated_at}`。
  - 未計算的 workload 此物件為 `null`。
  - 支援過濾參數 `risk_summary.ransomware.workload_exposure_severity`（low/medium/high/critical/fully_protected）。
- **`GET {workload_href}`**（明細）→ `services.open_service_ports[]`
  - 每筆：`port`, `protocol`(int), `process_name`(完整路徑), `win_service_name`, `package`, `user`, `address`。
- **`GET {workload_href}/risk_details`** → `risk_details.ransomware`
  - `details[]`，每筆：`port`, `proto`(int), `name`(服務名), `severity`(critical/high/medium/low), `category`(admin/legacy), `port_status`(**listening**/inactive), `protection_state`(unprotected/protected_open/protected_closed), `active_policy`, `draft_policy`, `recommendation`。
  - 未計算時 `risk_details.ransomware = null`。

### 3.2 欄位語意（經 Illumio NotebookLM 筆記確認）

- `port_status`：`listening`=有程序在聽（埠真的開著）；`inactive`=無程序在跑。
- `protection_state`：`unprotected`=無政策保護；`protected_closed`=被 Deny/預設拒擋（勒索無法橫移）；`protected_open`=有 Allow 規則僅放信任來源（需 selective/full enforcement）。
- **risk_details 不含 process** → process 必須從 `open_service_ports` 取得，用 **(port, proto) JOIN**。

### 3.3 實測結果（lab PCE 25.2.40, org 1）

- 21 台 managed，14 台已計算（全 critical，lab 未 enforce），7 台待計算。
- `risk_summary` 確實隨**單次清單呼叫**回傳 → per-VEN 嚴重度/覆蓋率「零額外成本」。
- 端到端 pipeline 跑通：**(port,proto) JOIN 命中率 100%（31/31）**，每個 listening 風險埠都對到 process（Windows `svchost.exe`+服務名、Linux 完整路徑）。

## 4. 設計

### 4.1 Section 內容（三塊）

**① 全站 KPI**（來自清單，免費）
- 曝險分布計數：critical / high / medium / low / fully_protected。
- 平均保護覆蓋%（已 enforce 環境才有意義；註明）。
- 「N 台尚未計算」提示。

**② per-VEN 主表**（來自清單 + Tier-2 的埠計數）— *哪些 VEN 風險高*

| Hostname | 曝險等級 | 保護覆蓋% | 高風險開放埠數 |
|---|---|---|---|

- 依曝險等級（critical→low）再依開放埠數降序。
- 「高風險開放埠數」= 該台 `details` 中 `port_status=="listening"` 的筆數。

**③ per-VEN 高風險開放埠明細**（Tier-2 JOIN）— *process 對應*

| Hostname | Port/Proto | 服務 | Severity | Protection | Process | User |
|---|---|---|---|---|---|---|

- 只列 `port_status=="listening"` 的風險埠。
- 一張表，Hostname 重複（依 host、severity 排序）。
- `User`：來自 `open_service_ports.user`（執行該程序的帳號，如 `root`/`NETWORK SERVICE`，≤15 字）；對不到或空值顯示「—」。
- 刻意**不列** `recommendation`/`active_policy`/`draft_policy`/`category`/`port_status`：recommendation 與 active/draft 屬政策佈署 drill-down（且機器碼需額外對應），port_status 已篩成定值，category 與 severity 重疊 — 一律省去以維持表寬精簡。

### 4.2 Process 顯示規則（方案 A，已定案）

```
process_label = win_service_name or basename(process_name)   # ≤ ~12 字，永不截斷
title (hover) = process_name 完整路徑                         # HTML tooltip
user 為獨立欄位（見 ③ 表）                                    # ≤15 字
```

- 理由（實測）：`process_name` 最長 33 字且 Windows 多為通用 `svchost.exe`；`win_service_name` 短（≤11）又能區分 RpcSs/TermService/Dnscache；Linux 端 basename（sshd/nginx/rpcbind）已足夠。
- `User` 獨立成欄（實測 31/31 填充、≤15 字），提供權限三角判讀（如 RDP 以 SYSTEM 執行）。
- PDF 列印無 hover → 短標籤本身已可辨識，完整路徑於 PDF 省略可接受。

### 4.3 元件

| 層 | 檔案 | 職責 |
|---|---|---|
| 純分析 | **新增** `src/report/analysis/ransomware_posture.py` | 純函式：吃 `(workloads, per_workload_enrichment)`，輸出 `{kpi, per_ven_rows, port_detail_rows}`。負責 JOIN、`port_status` 篩選、severity 排序、process_label 計算。無 I/O、可單元測試。 |
| API | `src/api_client.py` | **新增** `get_workload_risk_details(href) -> dict`（GET `{href}/risk_details`，失敗回 `{}`）。severity/覆蓋率已在清單，不需新方法。 |
| 抓取 | **新增** `src/report/ransomware_posture_enrichment.py` | 沿用 `open_ports_enrichment` 模式（`GlobalRateLimiter` + `data/ransomware_posture_cache.json` 24h TTL）。逐台抓 `get_workload`（open_service_ports）+ `get_workload_risk_details`，per-workload 例外 → 該台略過。只處理「已計算且非 fully_protected」的台，硬上限 500（超過則 `log` 告知，不靜默截斷）。 |
| 串接 | `src/report/ven_status_generator.py` | 呼叫 enrichment + 分析，寫入 `results["ransomware_posture"]`。 |
| 渲染 | `src/report/exporters/ven_html_exporter.py` | 新增 KPI + 兩張表的渲染（`risk_summary=None`/空資料時整段略過）。 |
| i18n | `src/i18n_en.json` / `src/i18n_zh_TW.json` | 新增 `rpt_ven_rwp_*` 鍵。 |

### 4.4 移除 mod16

- 刪除 `src/report/analysis/open_ports_surface.py`、`src/report/open_ports_enrichment.py`。
- 移除 `src/report/report_generator.py` 的 `_compute_open_ports_surface()` 與 `results['mod16']` 接線。
- 移除 `src/report/exporters/html_exporter.py` 的 mod16 nav（:573-574）、section（:684-687）、`_mod16_html()`（:996-1034）。
- 移除 `src/config_models.py` 的 `AttackSurfaceSettings`（及 `ReportSettings.attack_surface`）。
- 移除 `src/i18n_*.json` 的 `rpt_ops_*` 鍵。
- 刪除 `tests/test_open_ports_surface.py`、`tests/test_mod16_report.py`。

### 4.5 邊界處理

- **未計算**（`risk_summary.ransomware` 為 null）：排除於風險表；KPI 標示「N 台待計算」。
- **PCE < 23.5**（清單無 `risk_summary`）：偵測全為 null → 整段優雅略過（不報錯）。
- **port_status=inactive 的風險服務**：不計入「開放」數（聚焦真正在聽的埠）。
- **process_name 為空**：Process 欄顯示「—」。
- **risk_details 抓取失敗**：該台從明細表略過，但仍可出現在主表（覆蓋率來自清單）。

### 4.6 成本

- KPI + 主表的嚴重度/覆蓋率：**1 次**清單呼叫（VEN 報表本就會跑）。
- 埠明細：每台 2 次（`get_workload` + `risk_details`），限流 + 24h 快取，上限 500 台。
- 相較舊 mod16（最多 1+500）更省、更聚焦。

## 5. 測試策略

- `ransomware_posture.py` 純函式單元測試（fixtures，不打網路）：
  - JOIN 命中 / 未命中（process 顯示 — / 短標籤）。
  - `port_status` 篩選（listening 計入、inactive 排除）。
  - process_label 規則（Windows 用 win_service_name、Linux 用 basename）。
  - KPI 計數含「待計算」。
  - 空資料 / 全 null → 回可被渲染端判定為「略過」的結構。
- 渲染端測試（仿 `test_ven_report_estate.py`）：section 有/無資料、i18n 無洩漏。

## 6. 附錄：驗證腳本

探測腳本暫存於 `/tmp/probe_*.py`（list bulk、per-workload risk_details、端到端 pipeline、process 欄位分析）。實作完成後可刪。
