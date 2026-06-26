---
title: Report Engine Architecture
audience: [developer]
last_verified: 2026-05-15
verified_against:
  - src/report/
  - src/report/analysis/
  - src/report/parsers/
  - src/report/exporters/
  - src/report/rules/
  - commit 92143a6 (ReportLab removal plan)
  - commit 268d055
related_docs:
  - overview.md
  - ../user-guide/reports.md
  - ../reference/cli.md
  - i18n-contract.md
---

> [English](report-engine.md) | **[繁體中文](report-engine_zh.md)**
> 📍 [INDEX](../INDEX.md) › 架構 › 報告引擎
> 🔍 最後驗證日期 **2026-05-15**，對應 commit `268d055` — 詳見 frontmatter

# 報告引擎架構

本文件說明 `src/report/`（72 個檔案）的開發者內部實作。
操作層面的使用說明（執行報告、輸出位置、電子郵件寄送）請參閱
[Reports User Guide](../user-guide/reports.md)。

---

## 管線階段

無論資料來源為 API 或 CSV，引擎皆執行相同的五階段管線。
各 generator class（`ReportGenerator`、`AuditGenerator`、
`PolicyUsageGenerator`、`VenStatusGenerator`）各自驅動對應的變體。

```
┌──────────┐     ┌─────────┐     ┌──────────┐     ┌────────┐     ┌──────────┐
│  Fetch   │────▶│  Parse  │────▶│ Analyze  │────▶│ Render │────▶│  Export  │
└──────────┘     └─────────┘     └──────────┘     └────────┘     └──────────┘
```

| 階段 | 輸入 | 輸出 | 關鍵程式碼 |
|------|------|------|-----------|
| **Fetch** | 日期範圍 + 可選篩選條件 | 原始 JSON flow 清單或 CSV 路徑 | `ReportGenerator._fetch_traffic()` |
| **Parse** | 原始 JSON 清單 / CSV 檔案 | Unified DataFrame（共用 schema）| `src/report/parsers/` |
| **Analyze** | Unified DataFrame | `module_results` dict + `findings` 清單 | `_run_pipeline()` → `_run_modules()` + `RulesEngine.evaluate()` |
| **Render** | `module_results` + `findings` | 含嵌入圖表/CSS 的 HTML 字串 | `HtmlExporter.export()` |
| **Export** | 渲染後的 HTML / module_results | 磁碟上的 `.html`、`.xlsx`、`.csv` | `ReportGenerator.export(fmt=...)` |

**Fetch** 自動選擇三種模式之一：

- `"api"` — 透過 `api_client.fetch_traffic_for_report()` 呼叫 PCE API
- `"cache"` — 完全由 `cache_reader`（snapshot store）提供
- `"mixed"` — API 填補未涵蓋的缺口，再與快取尾端合併

**Analyze** 分為兩個子階段：

1. `RulesEngine.evaluate(df)` — 安全規則 findings（詳見[規則引擎](#規則引擎)）
2. `_run_modules(df, findings)` — 15+ 個分析模組依序執行；`mod12`（執行摘要）
   永遠最後執行，依賴所有其他模組的結果。

---

## Parsers (解析器)

位置：`src/report/parsers/`

| 檔案 | 用途 |
|------|------|
| `api_parser.py` | 將 PCE API JSON flow records 轉換為 Unified DataFrame；重用 `src.analyzer` 的 `calculate_mbps()` / `calculate_volume_mb()`，確保頻寬邏輯與監控引擎一致。 |
| `csv_parser.py` | 讀取從 Illumio PCE UI 匯出的 CSV，將欄位名稱正規化為 Unified DataFrame schema。 |
| `validators.py` | Schema 驗證與強制轉換：檢查必要欄位與相容資料型別，確保兩種 parser 輸出相同的結構給分析模組。 |

兩種 parser 產出相同的 **Unified DataFrame schema** — 每個分析模組消費此
schema，無需知道原始資料來源。

---

## Analysis 模組

位置：`src/report/analysis/`

模組在 `src/report/analysis/__init__.py` 的 `TRAFFIC_MODULES` 中註冊，
透過 `importlib` 於執行時延遲載入。`get_traffic_modules()` 回傳啟用清單；
`get_summary_module()` 回傳 `mod12`。

### 流量分析模組（mod01–mod15）

| 模組 | Entry function | 計算內容 |
|------|---------------|---------|
| `mod01_traffic_overview.py` | `traffic_overview` | 流量總覽、Top Talkers、協定分佈 |
| `mod02_policy_decisions.py` | `policy_decision_analysis` | Allow/Deny/potentially-blocked 分佈 |
| `mod03_uncovered_flows.py` | `uncovered_flows` | 無對應規則的流量 |
| `mod04_ransomware_exposure.py` | `ransomware_exposure` | 依 port 的勒索病毒風險評分 |
| `mod05_remote_access.py` | _(已整併至 mod15)_ | 遠端存取路徑 — 檔案保留供參考 |
| `mod06_user_process.py` | `user_process_analysis` | 使用者空間程序層級流量分析 |
| `mod07_cross_label_matrix.py` | `cross_label_flow_matrix` | 跨環境 label 對 label 流量矩陣 |
| `mod08_unmanaged_hosts.py` | `unmanaged_traffic` | 涉及未管理（無 VEN）主機的流量 |
| `mod09_traffic_distribution.py` | `traffic_distribution` | 依 app/env/location 的流量分佈 |
| `mod10_allowed_traffic.py` | `allowed_traffic` | 明確允許流量模式分析 |
| `mod11_bandwidth.py` | `bandwidth_analysis` | 頻寬與資料量聚合 |
| `mod12_executive_summary.py` | `executive_summary` | 彙整所有模組結果為 KPI + 評級 |
| `mod13_readiness.py` | `enforcement_readiness` | 依 app/env 的執行模式就緒度評分 |
| `mod14_infrastructure.py` | `infrastructure_scoring` | 基礎設施資產類型評分 |
| `mod15_lateral_movement.py` | `lateral_movement_risk` | 橫向移動可達性圖分析 |
| `mod_change_impact.py` | — | 兩次報告快照的變更影響 diff |
| `mod_draft_actions.py` | — | Draft 政策動作建議 |
| `mod_draft_summary.py` | `analyze` | Draft policy decision 流量摘要 |
| `mod_ringfence.py` | `analyze` | Ring-fence 分段缺口偵測 |
| `attack_posture.py` | — | mod12 使用的共用攻擊態勢輔助函式 |

### Policy usage 子模組（`analysis/policy_usage/`）

| 檔案 | 計算內容 |
|------|---------|
| `pu_mod00_executive.py` | Policy usage 報告的執行摘要 KPI |
| `pu_mod01_overview.py` | 規則命中總覽 |
| `pu_mod02_hit_detail.py` | 每條規則命中明細 |
| `pu_mod03_unused_detail.py` | 未使用規則明細清單 |
| `pu_mod04_deny_effectiveness.py` | Deny 規則有效性指標 |
| `pu_mod05_draft_pd.py` | Draft policy-decision 涵蓋率 |

### Audit 子模組（`analysis/audit/`）

| 檔案 | 計算內容 |
|------|---------|
| `audit_mod00_executive.py` | 稽核日誌報告的執行摘要 KPI |
| `audit_mod01_health.py` | PCE 健康事件摘要 |
| `audit_mod02_users.py` | 使用者操作分佈 |
| `audit_mod03_policy.py` | 政策變更事件分析 |
| `audit_mod04_correlation.py` | 跨事件相關性分析 |
| `audit_risk.py` | 風險評分輔助函式 |

---

## 規則引擎

位置：`src/report/rules/` + `src/report/rules_engine.py`

### 規則檔案結構

`src/report/rules/` 中每個規則檔案定義一個規則 class，繼承自
`_base.Finding`（dataclass），並可選擇性繼承 `_DraftPdRuleMixin`：

```
_base.py                         — Finding dataclass + _DraftPdRuleMixin base
r01_draft_deny_detected.py
r02_override_deny_detected.py
r03_visibility_boundary_breach.py
r04_allowed_across_boundary.py
r05_draft_reported_mismatch.py
```

`_DraftPdRuleMixin.needs_draft_pd() → bool` 用來標記該規則需要 DataFrame 中
存在 `draft_policy_decision` 欄位。

### 評估流程

`rules_engine.py` 中的 `RulesEngine.evaluate(df) → list[Finding]` 執行兩類
內建規則：

**行為規則（`_b001`–`_b009`）** — 評級為 CRITICAL / HIGH / MEDIUM：

| 規則 | 發現內容 |
|------|---------|
| `_b001_ransomware_critical` | /24 子網路內的勒索病毒 port 流量 |
| `_b002_ransomware_high` | 跨子網路的勒索病毒 port 流量 |
| `_b003_ransomware_medium_uncovered` | 無規則的勒索病毒 port 流量 |
| `_b004_unmanaged_high_activity` | 高流量的未管理主機 |
| `_b005_low_policy_coverage` | 政策涵蓋率低於設定閾值 |
| `_b006_lateral_movement` | 橫向移動可達性圖 |
| `_b007_user_high_destinations` | 使用者程序連線至大量目標 |
| `_b008_bandwidth_anomaly` | 統計上的頻寬異常值 |
| `_b009_cross_env_volume` | 高資料量跨越環境邊界 |

**協定/拓撲規則（`_l001`–`_l008`）**：

| 規則 | 發現內容 |
|------|---------|
| `_l001_cleartext_protocols` | 明文傳輸憑證的協定（Telnet、FTP 等） |
| `_l002_legacy_discovery_protocols` | 舊式廣播/探索協定 |
| `_l003_database_port_wide_exposure` | 資料庫 port 開放範圍過廣 |
| `_l004_cross_env_database_access` | 資料庫存取跨越環境邊界 |
| `_l005_identity_infrastructure_exposure` | AD/LDAP/Kerberos 大範圍曝露 |
| `_l006_high_reachability_lateral_path` | BFS 橫向可達路徑偵測 |
| `_l007_unmanaged_targeting_critical_services` | 未管理主機存取關鍵 port |
| `_l008_enforcement_mode_gap` | 關鍵服務附近執行模式薄弱 |

每個規則方法回傳 `Optional[Finding]`。引擎收集非 None 的結果，並將完整的
`findings` 清單傳給所有分析模組。

---

## Exporters (匯出器)

位置：`src/report/exporters/`

| 檔案 | 用途 |
|------|------|
| `html_exporter.py` | 主要 HTML 報告渲染器；嵌入圖表、表格、CSS、導覽側欄、封面頁 |
| `audit_html_exporter.py` | 稽核日誌報告的 HTML 渲染器 |
| `policy_usage_html_exporter.py` | Policy usage 報告的 HTML 渲染器 |
| `ven_html_exporter.py` | VEN 狀態報告的 HTML 渲染器 |
| `csv_exporter.py` | 將 `module_results` 展平為每個模組的 CSV 檔，打包為 ZIP |
| `xlsx_exporter.py` | 透過 `openpyxl` 寫入每個模組的 Excel 工作表 |
| `table_renderer.py` | 共用 HTML 表格渲染器；處理寬表拆分 |
| `chart_renderer.py` | 將 Plotly 圖表渲染為互動式 HTML div |
| `cover_page.py` | 生成封面頁 HTML（標題、評級、日期、成熟度分數） |
| `report_css.py` | 所有報告 CSS，含 `@media print` 與 `@page` 規則 |
| `report_i18n.py` | 報告層級的 i18n 輔助函式（標籤查詢、語言路由） |
| `_exec_summary.py` | 執行摘要區塊建構器 |
| `code_highlighter.py` | 報告輸出中的程式碼區塊語法高亮 |
| `grade_colors.py` | 共用語義評級顏色調色盤（A/B 綠色、C 橘色、D/F 紅色） |

### 匯出格式

`ReportGenerator.export(result, fmt=...)` 接受以下格式字串：

| `fmt` | 輸出 |
|-------|------|
| `'html'` | 單一 `.html` 檔案 |
| `'pdf'` | `'html'` 的別名 — 透過瀏覽器列印產生 PDF（詳見下方） |
| `'xlsx'` | 透過 `openpyxl` 產生的 `.xlsx` |
| `'csv'` | 打包為 `.zip` 的每模組 CSV |
| `'all'` | HTML + XLSX + CSV |

### PDF 產生 — 目前路徑

**ReportLab 已移除**（計畫記錄於 commit `92143a6`）。PDF 輸出透過 HTML 導覽列
中的「Print / PDF」按鈕觸發瀏覽器原生的 `window.print()`（`html_exporter.py:593`）。
`.html` 檔案內含完整的 `@media print` 樣式表（位於 `report_css.py`），控制
A4 輸出的分頁、邊距與表格版面。

目前程式碼中**不使用**任何伺服器端 PDF 函式庫（WeasyPrint、pdfkit、wkhtmltopdf）。

> [!NOTE] **2026-05-15 已稽核**：尚未新增無頭瀏覽器 PDF 路徑。`src/report/exporters/`
> 並未匯入 playwright、chromium、weasyprint 或 pdfkit。PDF 輸出仍是「以 HTML 渲染
> 再透過 `window.print()` 列印」；`'pdf'` 格式選項實質上是 `'html'` 的別名。

每次 HTML 和 XLSX 輸出旁都會由 `_write_report_metadata()` 寫入
`.metadata.json` 附帶檔案。

---

## 列印版面與寬表處理

所有列印版面設定位於 `src/report/exporters/report_css.py` 的 `@media print`
與 `@page` 規則下。

### 分頁規則

```css
@page { /* A4 橫向 */ }
@page { /* A4 直向 */ }
@media print {
  section              { page-break-before: always; }
  section#summary      { page-break-before: avoid; }
  section.report-cover { page-break-before: avoid !important; page-break-after: always; }
  tr                   { page-break-inside: avoid; }
  .chart-container     { page-break-inside: avoid; overflow: hidden; }
  .finding-card        { page-break-inside: avoid; }
}
```

### 寬表拆分（commit `f935717`）

欄位過多的表格（mod04 的 `part_b_per_port`、mod13 的 `app_env_scores`、
mod14 的 `top_apps`）會拆分為 2–3 個垂直堆疊的子表格，共享錨定欄位，
消除列印時的水平捲動。每個子表格有 `.subtable-label` 標題。
同時新增 8 個子表格標籤的 i18n 鍵值。

### CSS 選擇器特異性修正（commit `9db21d5`）

JavaScript 的 `autoFitColumns()` 在表格上設定 `data-auto-fitted="true"`，
使規則 `.report-table[data-auto-fitted=true]` 具有特異性 `(0,2,0)`。
列印覆寫使用 `table-layout: auto !important` 以優先於 JS 套用的
`table-layout: fixed`。

### 列印強化歷程

| Commit | 修正內容 |
|--------|---------|
| `0eabc30` | 列印表格使用 `overflow-wrap: break-word` 取代 `anywhere` |
| `ac0ae02` | 全域移除寬表的 `table-layout: fixed` |
| `36f46d8` | 僅對寬表套用 `table-layout: fixed` |
| `caa1349` | 列印時隱藏頁腳（封面頁已提供標題/日期） |
| `959ca91` | 以 `!important` 覆寫 JS 內嵌表格寬度 |

---

## 中間結果快取

### 1. 流量擷取快取（`cache_reader`）

`ReportGenerator` 接受可選的 `cache_reader` 建構子參數。
`_fetch_traffic()` 呼叫 `cache_reader.cover_state("traffic", start, end)` 並
選擇以下三種路徑之一：

| `cover_state` 結果 | 行為 |
|-------------------|------|
| `"full"` | 從快取直接回傳 raw + agg flows；不呼叫 API |
| `"partial"` | 混合模式：API 填補 `[start, cache_start)` 缺口，與快取尾端合併；source 標記為 `"mixed"` 或 `"cache"` |
| 其他值 | 完整的即時 API 擷取 |

### 2. KPI 快照儲存

兩個輕量 JSON 儲存在執行之間持久化 KPI：

- **`snapshot_store.py`** — 供 Change Impact 分析使用的僅 KPI JSON 快照。
  主要函式：`write_snapshot`、`list_snapshots`、`read_latest`、`cleanup_old`。
- **`trend_store.py`** — 每種報告類型的 KPI 趨勢歷史。
  主要函式：`save_snapshot`、`load_previous`、`compute_deltas`、
  `build_kpi_dict_from_metadata`。

### 3. 執行中快取

- `mod15_lateral_movement.py` 在 BFS 可達性遍歷期間使用
  `reach_cache: dict[str, dict]`，避免單次執行中重複的圖遍歷。
- `policy_usage` 執行上下文追蹤 `cached_rules`（從前次執行重用的已完成
  非同步摘要）。

**無跨執行的記憶體快取** — 除非提供 `cache_reader`，每次 `generate_from_*()`
呼叫都會從頭重新擷取與分析。

---

## 新增報告模組的步驟

此流程適用於新增**流量分析模組**（mod01–mod15 系列）。
稽核或 policy-usage 子模組請在對應的子套件中遵循相同模式。

1. **找一個相似的模組** — 選擇現有模組中與你的新模組 signature 和輸出結構最
   相近的（例如，主機導向模組選 `mod08_unmanaged_hosts.py`；數值聚合選
   `mod11_bandwidth.py`）。

2. **建立模組檔案** — 新增
   `src/report/analysis/mod{NN}_{name}.py`。實作 entry function，signature 為
   `(df: pd.DataFrame, top_n: int, *, lang: str = "en") -> dict`。
   回傳的 dict 至少需含 `"title"`、`"chart_spec"`（或 `None`）、`"table"` 鍵，
   `HtmlExporter` 才能正確渲染。

3. **在 `TRAFFIC_MODULES` 中註冊** — 在
   `src/report/analysis/__init__.py` 的清單中新增一個 tuple：
   ```python
   ('modNN', 'src.report.analysis.modNN_name', 'entry_function', _call_df_n),
   ```
   依據 function signature 選擇適當的 `_call_*` adapter：`_call_df`、
   `_call_df_n`、`_call_df_cfg_n` 或 `_call_readiness`。

4. **撰寫測試** — 新增 `tests/report/analysis/test_modNN_name.py`。
   使用現有測試的 fixtures 建構最小化 Unified DataFrame，對輸出 dict 的鍵值
   和資料型別進行斷言。

5. **新增 i18n 鍵值** — 將所有使用者可見字串以鍵值形式加入
   `src/i18n_en.json` 和 `src/i18n_zh_TW.json`。在模組內使用
   `from src.i18n import t, get_language`，每次 `t()` 呼叫都傳入 `lang=lang`。
   參見 [i18n Contract](i18n-contract.md)。

6. **處理寬表** — 若模組產生超過約 8 欄的表格，請在 `table_renderer.py` 中
   為其註冊群組子表格拆分（參見 commit `f935717`）。在兩個語系檔中新增
   子表格標籤 i18n 鍵值。

7. **驗證輸出** — 在本機執行報告，確認新區塊出現在 TOC 側欄中，
   畫面顯示正確，且從瀏覽器列印為 PDF 時分頁乾淨。

---

## 相關文件
- [架構總覽](overview.md) — 整體架構
- [Reports User Guide](../user-guide/reports.md) — 操作層面使用說明
- [CLI Reference](../reference/cli.md) — `report` 子指令
- [i18n Contract](i18n-contract.md) — 報告標籤如何與語系保持同步
