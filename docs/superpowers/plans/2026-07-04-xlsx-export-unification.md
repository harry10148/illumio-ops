# XLSX 匯出統一 Implementation Plan（backlog 提前執行版）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> 本計劃取代 `2026-07-02-backlog-xlsx-export-unification.md` 的骨架（該檔保留為歷史記錄）。提前於 Phase 4/5 之前執行（2026-07-03 final review 裁決：它是 Phase 2/3「下放 XLSX」故事成立的前提）。順序調整的吸收：spec K1（VEN 判定統一）併入 Task 4；Phase 2/3 下放表由 module_results 直供正式路徑（Task 5）。

**Goal:** 正式 `--format xlsx` 匯出（audit / policy-usage / ven / traffic 四報表）改為輸出真實資料且與 HTML 同源（同一份 `module_results`/`_analyze` 產物），消除「production 空殼 + 測試專用富內容函式」平行路徑。

**Architecture:** 在 `xlsx_exporter.py` 新增共用 DataFrame 寫入層（沿用既有公式注入防護與告警底色）；三個 `generate_*_xlsx` 改簽名吃 `export()` 已算好的產物並由 `export()` 呼叫；traffic 的 `export()` xlsx 分支改為從 `module_results` 建 curated workbook（含 Phase 2/3 全部下放表），刪除重算式的 `generate_traffic_xlsx`。**不得重新查詢或重新分桶**。

**Tech Stack:** Python 3 / pandas / openpyxl / pytest。

**Spec:** backlog 計劃問題事實（已 refresh @925ef50）+ spec K1。

## Global Constraints

- 註解繁中、無 emoji；commit 英文 conventional-commits；每 task 一個 commit；surgical；TDD（每個行為變更先 RED）。
- **環境硬規則**：subagent shell 初始目錄可能是主 checkout `/home/harry/rd/illumio-ops`（另一 session 工作區）——每次工具呼叫先 cd 到 worktree；禁止在主 checkout 做任何寫操作；誤操作停止回報不得自行修復；commit 後 `git branch --contains` 驗證。
- **HTML 輸出零改變**（回歸鎖定；Task 6 的 note 文案除外——那是本計劃的交付物）。
- **XLSX 與 HTML 同源**：資料一律取自 `result.module_results` / `_analyze()` 產物；`generate_*_xlsx` 內不得 import 任何 `src/report/analysis/` builder、不得對 raw df 重算。
- 新 sheet 名走 i18n `rpt_xlsx_sheet_*` key（en/zh 兩 json 同步、檔尾單一 newline）；en 值沿用現行硬編英文（既有測試斷言不破）。
- 所有 DataFrame 寫入必須經過 Task 1 的共用 helper（公式注入防護 `_neutralize` 全覆蓋——現行 `generate_traffic_xlsx` 的 `str(v)` 直寫是無防護的，統一後修正）。
- 定位以程式碼內容為準（行號會漂移）。

## 現況地圖（refresh @925ef50，實作者速查）

| 對象 | 事實 |
|---|---|
| 通用寫入器 | `xlsx_exporter.py`：`export_xlsx` :91-110（Summary sheet + 每 module 一張）；`_write_module_sheet` :36-89 只認 `{summary:str, table:list[dict], chart_spec}`——**不認 DataFrame**；`_neutralize` :27-33、`_ALERT_TOKENS`/`_ALERT_FILL` :23、欄寬/凍結/31字元清洗 |
| Audit | `export()` xlsx 分支 audit_generator.py:741-760（空殼）；`generate_audit_xlsx(events_df,...)` :818（重算、僅測試呼叫）；module_results：mod00.kpis、mod01.summary、mod02.per_user、mod03.summary、mod04 三 DataFrame（correlated_sequences/brute_force_detections/off_hours_operations，**無純量**——舊 Correlations sheet 恆空的原因） |
| Policy Usage | `export()` xlsx 分支 policy_usage_generator.py:264-283（空殼）；`generate_policy_usage_xlsx(rules_df,...)` :566（重算、cap 500 < mod03 builder 的 1000）；module_results：mod01（純量+summary_df）、mod02.hit_df(cap500)+top_ports_df、mod03.unused_df(cap1000)、mod04.deny_detail_df+deny_summary_df+純量 |
| VEN | `_analyze()` :263-408 回傳 online/offline/lost_today/lost_yesterday（DataFrame，_clean 後欄名 Hostname/IP/...）+ kpis + by_version + 兩 chart_spec；1 小時心跳門檻 :36；`export()` xlsx 分支 :168-188（空殼）；`generate_ven_xlsx(workloads_df,...)` :411-458 自行分桶（active&<24h——**K1 分歧仍在**，且 Lost sheet 名與內容錯位：\"Lost <24h\" 裝 24-48h、\"Lost 24-48h\" 裝 >=48h） |
| Traffic | `export()` xlsx 分支 report_generator.py:553-582（空殼+chart）；`generate_traffic_xlsx` :946-1094（全部從 raw flows 重算、僅 tests/test_xlsx_content_traffic.py 14 處呼叫）；下放表在 module_results 的可達性：mod08 系列三 profile 皆有；mod15/mod07 僅 security_risk/network_inventory（traffic profile 不跑該二模組，registry :59-75） |
| 進入點 | CLI report.py（_REPORT_FORMATS 含 xlsx :18）、GUI reports.py（_ALLOWED_REPORT_FORMATS 含 xlsx，_helpers.py:276）、report_scheduler.py:255-258（多格式→all）；main.py 互動選單不含 xlsx（但 'all' 可達） |
| i18n | `rpt_xlsx_sheet_*` 現有 6 個（全 traffic）:4150-4162；audit/pu/ven sheet 名全硬編英文；`rpt_tr_lateral_xlsx_note`/`rpt_tr_matrix_xlsx_note` 為「待統一上線」措辭（Task 6 改現在式） |
| 既有測試 | test_xlsx_content_{audit,policy_usage,ven}.py 各 2 測試綁舊簽名；test_xlsx_content_traffic.py 7 測試綁 generate_traffic_xlsx |

---

### Task 1: xlsx_exporter 共用 DataFrame 寫入層

**Files:**
- Modify: `src/report/exporters/xlsx_exporter.py`
- Test: `tests/test_xlsx_df_writer.py`（新檔）

**Interfaces (Produces，Task 2-5 全部依賴):**
```python
def append_df_rows(ws, df, *, header=True) -> None
    # DataFrame 逐列寫入現有 sheet：header 列 + 資料列；每格經 _neutralize；
    # 列文字含 _ALERT_TOKENS 者套 _ALERT_FILL；NaN 寫空字串。

def add_df_sheet(wb, title, df, *, empty_note=None, chart_spec=None, lang="en") -> None
    # 建新 sheet（title 經現行 31 字元/非法字元清洗）：
    # df 非空 → append_df_rows + freeze_panes("A2") + 欄寬自估（沿用 _write_module_sheet 的 74-79 邏輯，上限 60）
    # df 空/None → 寫一列 [t("rpt_xlsx_col_note",lang), empty_note or t("rpt_xlsx_no_data",lang)]
    # chart_spec 非 None → 沿用現行 render_matplotlib_png + XLImage 嵌入邏輯

def add_stacked_tables_sheet(wb, title, tables, *, empty_note=None, lang="en") -> None
    # tables: list[(subtitle:str, df)]；一張 sheet 內逐表堆疊：空列 + [subtitle] 標題列 +
    # append_df_rows；全部為空 → empty_note 一列。沿用 Phase 2 lateral 下放的堆疊視覺慣例。
```
新 i18n key：`rpt_xlsx_no_data`（en "No data" / zh "無資料"）。內部抽取自 `_write_module_sheet` 的既有邏輯（清洗/防護/欄寬/告警共用同一份 code——`_write_module_sheet` 改為呼叫新 helper，行為不變）。

- [ ] **Step 1: RED 測試**

`tests/test_xlsx_df_writer.py`：
```python
"""xlsx_exporter 共用 DataFrame 寫入層。"""
import pandas as pd
from openpyxl import Workbook, load_workbook
from src.report.exporters.xlsx_exporter import add_df_sheet, add_stacked_tables_sheet


def _read_rows(path, sheet):
    wb = load_workbook(path)
    return [[c.value for c in r] for r in wb[sheet].iter_rows()]


def test_add_df_sheet_writes_header_and_rows(tmp_path):
    wb = Workbook()
    df = pd.DataFrame([{"Name": "web", "Count": 3}, {"Name": "db", "Count": 1}])
    add_df_sheet(wb, "MySheet", df)
    p = str(tmp_path / "t.xlsx")
    wb.save(p)
    rows = _read_rows(p, "MySheet")
    assert rows[0] == ["Name", "Count"]
    assert rows[1] == ["web", 3]
    assert len(rows) == 3


def test_formula_injection_neutralized(tmp_path):
    wb = Workbook()
    df = pd.DataFrame([{"Name": "=HYPERLINK(evil)", "Count": 1}])
    add_df_sheet(wb, "Inj", df)
    p = str(tmp_path / "t.xlsx")
    wb.save(p)
    rows = _read_rows(p, "Inj")
    assert rows[1][0].startswith("'=")  # 前綴單引號中和


def test_empty_df_writes_note(tmp_path):
    wb = Workbook()
    add_df_sheet(wb, "Empty", pd.DataFrame(), empty_note="nothing here")
    p = str(tmp_path / "t.xlsx")
    wb.save(p)
    rows = _read_rows(p, "Empty")
    assert "nothing here" in [v for r in rows for v in r]


def test_stacked_tables_have_subtitles(tmp_path):
    wb = Workbook()
    t1 = pd.DataFrame([{"A": 1}])
    t2 = pd.DataFrame([{"B": 2}])
    add_stacked_tables_sheet(wb, "Stack", [("First", t1), ("Second", t2)])
    p = str(tmp_path / "t.xlsx")
    wb.save(p)
    flat = [v for r in _read_rows(p, "Stack") for v in r]
    assert "First" in flat and "Second" in flat and 1 in flat and 2 in flat
```

- [ ] **Step 2: 跑測試確認 FAIL**（ImportError）
- [ ] **Step 3: 實作（GREEN）**——自 `_write_module_sheet` 抽取共用邏輯，`_write_module_sheet` 改為委派（行為不變：`python -m pytest tests/ -k xlsx -q` 全綠證明）。i18n `rpt_xlsx_no_data` 兩 json。
- [ ] **Step 4: 全套一次 `python -m pytest -q`**
- [ ] **Step 5: Commit** `feat(xlsx): shared dataframe sheet writers with injection guard`

---

### Task 2: Audit XLSX 接線

**Files:**
- Modify: `src/report/audit_generator.py`（`generate_audit_xlsx` 改造 + `export()` xlsx 分支接線）
- Modify: `tests/test_xlsx_content_audit.py`
- Modify: 兩 json（5 個 sheet 名 key）

**Interfaces:**
- Produces: `generate_audit_xlsx(module_results: dict, out_path: str, *, lang: str = "en") -> str`——只讀 module_results，不 import 任何 analysis builder。
- Sheet 對應（en 值 = 現行硬編字串，測試不破）：

| sheet（i18n key） | 資料來源 |
|---|---|
| Attention Required（rpt_xlsx_sheet_audit_attention） | mod00.kpis → 兩欄表（`t("rpt_xlsx_col_kpi")`/`t("rpt_xlsx_col_value")`，逐 kpi label/value） |
| Health（rpt_xlsx_sheet_audit_health） | mod01.summary（DataFrame） |
| Users（rpt_xlsx_sheet_audit_users） | mod02.per_user |
| Policy Changes（rpt_xlsx_sheet_audit_policy） | mod03.summary |
| Correlations（rpt_xlsx_sheet_audit_correlations） | mod04 三 DataFrame 以 `add_stacked_tables_sheet` 堆疊（correlated_sequences/brute_force_detections/off_hours_operations）——修復舊路徑「寫純量恆空」缺陷 |

- `export()` xlsx 分支（現行 :741-760）改為呼叫上述函式（保留 try/except、檔名、`rpt_xlsx_saved` 訊息與 outputs append 慣例），刪除空殼組裝。

- [ ] **Step 1: RED 測試**——`tests/test_xlsx_content_audit.py` 重寫：fixture 改為手組 module_results dict（mod00 kpis 兩項、mod01 summary 2 列、mod02 per_user 1 列、mod03 summary 1 列、mod04 三 DataFrame 各 1 列），斷言：5 sheet 存在、Policy Changes 有資料列、**Correlations 含 correlated_sequences 的欄位值（舊路徑做不到——RED 的關鍵斷言）**、Attention Required 含 kpi label。新增 export-path 整合測試：以最小 AuditReportResult（手組 module_results + record_count）呼叫 `export(fmt='xlsx')`，openpyxl 讀回斷言 sheet 非空。
- [ ] **Step 2: 確認 FAIL**（舊簽名吃 DataFrame 會 TypeError / Correlations 空）
- [ ] **Step 3: 改造 `generate_audit_xlsx`（GREEN 前半）**——用 Task 1 helpers；kpis 兩欄表以 `pd.DataFrame([{kpi_col: k["label"], val_col: k["value"]} for k in kpis])` 組。缺 key/空 df 一律 `empty_note=t("rpt_xlsx_no_data")` 不炸。
- [ ] **Step 4: `export()` 接線（GREEN 後半）**——傳 `lang`（export 已有 lang 參數）。
- [ ] **Step 5: 聚焦 + 全套**：`python -m pytest tests/test_xlsx_content_audit.py tests/test_xlsx_df_writer.py -v && python -m pytest -q`
- [ ] **Step 6: Commit** `refactor(audit): wire rich xlsx builder into export()`

---

### Task 3: Policy Usage XLSX 接線

**Files:**
- Modify: `src/report/policy_usage_generator.py`
- Modify: `tests/test_xlsx_content_policy_usage.py`
- Modify: 兩 json（4 個 sheet 名 key）

**Interfaces:**
- Produces: `generate_policy_usage_xlsx(module_results: dict, out_path: str, *, lang: str = "en") -> str`。
- Sheet 對應：

| sheet（i18n key，en=現行硬編值） | 資料來源 |
|---|---|
| Hit Rules（rpt_xlsx_sheet_pu_hit） | mod02.hit_df（builder cap 500） |
| Unused Rules（rpt_xlsx_sheet_pu_unused） | mod03.unused_df（builder cap 1000——**取代舊重算 cap 500，完整清單語意**；決策記入 commit body） |
| Deny Effectiveness（rpt_xlsx_sheet_pu_deny） | mod04：deny_summary_df + deny_detail_df 以 `add_stacked_tables_sheet` 堆疊 |
| Execution Stats（rpt_xlsx_sheet_pu_stats） | mod01 純量（total_rules/hit_count/unused_count/hit_rate_pct）+ mod04 純量（total_deny/deny_hit_rate_pct 等）組 Metric/Value 兩欄表 |

- `export()` xlsx 分支（:264-283）接線，刪空殼。

- [ ] **Step 1: RED 測試**——重寫測試檔：手組 module_results fixture；斷言 4 sheet、Unused sheet 列數 == fixture unused_df 列數（同源驗證）、Deny sheet 含 summary 與 detail 兩段、Execution Stats 含 Total Rules 值。export-path 整合測試（最小 PolicyUsageResult → `export(fmt='xlsx')` → sheet 非空）。
- [ ] **Step 2: 確認 FAIL**
- [ ] **Step 3-4: 改造 + 接線（GREEN）**
- [ ] **Step 5: 聚焦 + 全套**
- [ ] **Step 6: Commit** `refactor(policy-usage): wire rich xlsx builder into export()`

---

### Task 4: VEN XLSX 接線 + K1 語意統一

**Files:**
- Modify: `src/report/ven_status_generator.py`
- Modify: `tests/test_xlsx_content_ven.py`
- Modify: 兩 json（5 個 sheet 名 key）

**Interfaces:**
- Produces: `generate_ven_xlsx(analysis: dict, out_path: str, *, lang: str = "en") -> str`——吃 `_analyze()` 回傳 dict，**不得自行分桶**（spec K1 在此吸收：online/offline 判定唯一來源是 `_analyze` 的 1 小時心跳門檻）。
- Sheet 對應（**修復舊 sheet 名/內容錯位**）：

| sheet（i18n key） | 資料來源 |
|---|---|
| Online（rpt_xlsx_sheet_ven_online） | analysis["online"] |
| Offline（rpt_xlsx_sheet_ven_offline） | analysis["offline"] |
| Lost Today（rpt_xlsx_sheet_ven_lost_today） | analysis["lost_today"]（offline 且 24h 內有心跳） |
| Lost Yesterday（rpt_xlsx_sheet_ven_lost_yesterday） | analysis["lost_yesterday"]（24-48h） |
| Versions（rpt_xlsx_sheet_ven_versions） | analysis["by_version"] dict → Version/Count 兩欄表 |

- 舊 sheet 名 "Lost <24h"/"Lost 24-48h"（名稱與內容錯位）廢棄——測試同步改新名，commit body 記錄語意修正。
- `export()` xlsx 分支（:168-188）接線：`result` 持有 `_analyze` 產物（以現行 export 的 result 屬性為準——實作時確認 result.module_results 或等價屬性中 `_analyze` dict 的位置，報告記錄）。

- [ ] **Step 1: RED 測試**——重寫測試檔：fixture 含心跳邊界案例（59 分鐘 → online、61 分鐘 → offline+lost_today；72h → offline 不在 lost 桶），走 `VenStatusGenerator._analyze` 真實分桶後餵 `generate_ven_xlsx`，斷言各 sheet 列集合與 analysis 桶完全一致（hostname 集合比對）。export-path 整合測試。**RED 關鍵**：舊實作對 59 分鐘案例會因 24h 門檻誤判（分桶斷言失敗）。
- [ ] **Step 2: 確認 FAIL**
- [ ] **Step 3-4: 改造 + 接線（GREEN）**——函式內禁止出現任何 `ven_status ==`/age 計算；只讀 analysis dict。
- [ ] **Step 5: 聚焦 + 全套**
- [ ] **Step 6: Commit** `refactor(ven): xlsx export consumes _analyze buckets (spec K1)`

---

### Task 5: Traffic XLSX 接線（含 Phase 2/3 下放表）+ 刪除重算路徑

**Files:**
- Modify: `src/report/report_generator.py`（`export()` xlsx 分支重寫 + 新 `build_traffic_xlsx` + 刪 `generate_traffic_xlsx`）
- Modify: `tests/test_xlsx_content_traffic.py`（7 測試遷移到新函式/export 路徑）
- Modify: 兩 json（沿用既有 6 個 sheet key + 新 unmanaged sheet key）

**Interfaces:**
- Produces: `build_traffic_xlsx(module_results: dict, out_path: str, *, profile: str, lang: str = "en", record_count: int = 0, metadata: dict | None = None) -> str`——只讀 module_results。
- Sheet 對應（key 缺（該 profile 不跑該模組）→ 整張 sheet 略過，不寫空 sheet）：

| sheet（既有/新 i18n key） | 資料來源（module_results） |
|---|---|
| Executive Summary（rpt_xlsx_sheet_exec_summary） | mod12.kpis（list[dict label/value]）→ KPI/Value 兩欄表；chart_spec=mod12.chart_spec |
| Policy Decisions（rpt_xlsx_sheet_policy_decisions） | mod02：summary + port_coverage + audit_flags 堆疊；chart_spec=mod02.chart_spec |
| Uncovered Flows（rpt_xlsx_sheet_uncovered_flows） | mod03：top_flows + uncovered_port_services + uncovered_ports + uncovered_services + by_recommendation 堆疊 |
| Lateral Movement（rpt_xlsx_sheet_lateral_movement） | mod15：service_summary + fan_out_sources + allowed_lateral_flows + attack_paths + **六下放表**（ip_top_talkers/ip_top_pairs/source_risk_scores/bridge_nodes/top_reachable_nodes/app_chains）堆疊，各子表標題沿用既有 `rpt_tr_*`/`rpt_mod15_*` key；全空 → `rpt_xlsx_no_lateral` note |
| Cross-Label Matrix（rpt_xlsx_sheet_cross_label） | mod07.matrices 四維度的 top_cross_pairs 堆疊（子表標題 `f"{t('rpt_tr_label_key')} {DIM}"`；至少 role/loc——env/app 一併給全） |
| Unmanaged Hosts（新 key rpt_xlsx_sheet_unmanaged，en "Unmanaged Hosts"/zh "Unmanaged 主機"） | mod08：top_unmanaged_src + per_dst_app + exposed_ports_merged + **三下放表**（src_port_detail/managed_hosts_targeted_by_unmanaged/top_unmanaged_dst）堆疊 |

- 舊 Top Talkers sheet（原自 raw flows groupby 重算）：改由 mod15.ip_top_talkers 涵蓋（lateral sheet 內）——獨立 sheet 廢棄，測試的 expected sheet 集合同步更新，決策記入 commit body（同源約束下無 raw-df 重算空間）。
- `export()` xlsx 分支（:553-582）改為呼叫 `build_traffic_xlsx(result.module_results, ..., profile=傳入的 traffic_report_profile, lang=..., record_count=result.record_count, metadata=既有 title/日期組裝)`，保留 try/except 與 `rpt_xlsx_saved`。
- **刪除 `generate_traffic_xlsx`（:946-1094）**——grep 確認僅測試呼叫後移除；7 個既有測試遷移：monkeypatch 型測試（fake lateral / fake cross-label）改為直接手組 module_results dict 餵 `build_traffic_xlsx`（不再需要 monkeypatch），斷言意圖逐一保留（no-lateral note 邏輯、下放表標題、role/loc fallback note）。

- [ ] **Step 1: RED 測試**（新測試 + 遷移；`build_traffic_xlsx` ImportError + export-path sheet 非空斷言先 FAIL）
- [ ] **Step 2: 確認 FAIL**
- [ ] **Step 3: `build_traffic_xlsx` 實作（GREEN 前半）**——全部經 Task 1 helpers；沿用 `_wrote_any` 式 note 邏輯（lateral 全空才寫 no_lateral note）。
- [ ] **Step 4: `export()` 接線 + 刪 `generate_traffic_xlsx`（GREEN 後半）**
- [ ] **Step 5: 三 profile 煙霧**：手組三種 profile 的 module_results（traffic 無 mod15/mod07——驗證 sheet 略過不炸）+ 聚焦 + 全套
- [ ] **Step 6: Commit** `refactor(report): traffic xlsx builds curated workbook from module results`

---

### Task 6: 註記改現在式 + 樣本 E2E + CHANGELOG + 文件

**Files:**
- Modify: 兩 json（`rpt_tr_lateral_xlsx_note`/`rpt_tr_matrix_xlsx_note` 改現在式）、`CHANGELOG.md`、`docs/operations-manual.md`、`docs/operations-manual_zh.md`
- Create: scratchpad E2E 腳本（不入版控）

- [ ] **Step 1: 註記改現在式**——en "…is available in the XLSX export." / zh "…已於 XLSX 匯出提供。"（lateral 與 matrix 兩 key；受影響測試走 STRINGS 值查找應透明，跑 tests/test_mod07_matrix_trim.py tests/test_mod15_html_trim.py 確認）；手冊 en/zh 對應句同步改現在式。
- [ ] **Step 2: 樣本 E2E（專案 CLAUDE.md 硬性規則）**——四報表各以合成資料走真實 `export(fmt='xlsx')`：
  1. traffic（security_risk profile）：openpyxl 驗證 6 sheet、lateral sheet 含六下放表標題、Cross-Label 含 role/loc、Unmanaged 含下放表、無空殼 sheet
  2. network_inventory profile：同上（mod15/mod07 有）；traffic profile：sheet 正確略過
  3. audit：5 sheet 非空、Correlations 有資料（舊路徑恆空的修復證明）
  4. policy-usage：4 sheet、Unused 列數 == module_results 完整清單
  5. ven：5 sheet、59/61 分鐘邊界分桶正確
  6. **HTML-XLSX 同源抽查**：同一 module_results 產 HTML 與 XLSX，抽 2 個表比對列數/首列值一致
  7. 公式注入樣本（`=HYPERLINK` 值）在所有四報表 XLSX 中被中和
  逐項證據記錄報告；產物留 scratchpad。
- [ ] **Step 3: 完成定義驗證**——`grep -rn "generate_\(audit\|policy_usage\|ven\)_xlsx" src/` 呼叫者只剩各自 export()；`grep -rn "generate_traffic_xlsx" src/ tests/` 歸零；全套 `python -m pytest -q` + `python3 scripts/check_no_naive_datetime.py`。
- [ ] **Step 4: CHANGELOG + 手冊**——Unreleased 條目：xlsx export unification（四報表真實資料、同源保證、K1 判定統一、Phase 2/3 下放表兌現、公式注入防護全覆蓋、Top Talkers sheet 併入 lateral）。
- [ ] **Step 5: Commit** `docs: document xlsx export unification`

---

## Self-Review 檢核

1. **Backlog 覆蓋**：Task 1（原計劃隱含的形狀落差——新增共用層）；Task 2=原 Task 1；Task 3=原 Task 2；Task 4=原 Task 3+spec K1；Task 5=原 Task 4+Phase 2/3 下放兌現+平行路徑刪除；Task 6=完成定義+承諾兌現。完成定義三條全對應。
2. **相依**：Task 2-5 依賴 Task 1（必須先做）；Task 2-5 相互獨立可依序；Task 6 收尾。
3. **同源鐵律的可驗證性**：每個 generate_*/build_* 內禁 import analysis builder、禁 raw df 運算——reviewer 逐 task 以 grep 驗證；E2E 第 6 點做行為層驗證。
4. **行為變更點（非純重構）已明列並記 commit body**：audit Correlations 從恆空變有資料；PU unused cap 500→1000（完整清單）；VEN 分桶語意（K1）與 Lost sheet 名修正；traffic Top Talkers sheet 併入 lateral；三 profile sheet 集合依 module_results 動態。
5. **下游安全**：HTML 渲染零觸碰（Task 6 note 文案除外）；export() 的 html/csv/pdf 分支零觸碰；`export_xlsx`/`_write_module_sheet` 對外行為不變（內部委派）。
