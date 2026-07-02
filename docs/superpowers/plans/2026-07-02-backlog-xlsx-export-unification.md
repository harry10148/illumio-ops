# Backlog: XLSX 匯出統一（接線內容建構器、消除平行路徑）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Backlog 狀態：** 本計畫排在報表拆分 Phase 5（Audit/Policy Usage/VEN 精簡）之後執行。
> 屆時 audit/policy-usage/ven 的模組與 exporter 已變動，**執行前必須以當時程式碼
> refresh 每個 task 的行號與程式片段**；本文件鎖定的是問題事實、目標架構、task
> 邊界與測試策略。

**Goal:** 正式 `--format xlsx` 匯出改用既有的富內容 XLSX 建構器，消除「production 空殼 XLSX + 測試專用富內容函式」的平行路徑，並保證 HTML 與 XLSX 的資料語義一致。

**Architecture:** 三個報表（audit、policy-usage、ven）各自的 `export()` 目前在 `fmt in ('xlsx','all')` 時呼叫共用 `export_xlsx()` 並塞入空 sheet；而 `generate_audit_xlsx()` / `generate_policy_usage_xlsx()` / `generate_ven_xlsx()` 是有完整 sheet 內容的建構器，但只有 `tests/test_xlsx_content_*.py` 在呼叫。統一方向：把富內容建構器改為吃 `export()` 已算好的 `module_results` / `_analyze` 產物（單一資料語義來源），由 `export()` 呼叫，刪除其獨立重算邏輯。

**Tech Stack:** Python 3.12、pandas、openpyxl（經 `src/report/exporters/xlsx_exporter.py`）、pytest。

## 問題事實（2026-07-02 盤點）

1. `src/report/audit_generator.py:799` `generate_audit_xlsx(events_df, out_path, top_n=100)`、
   `src/report/policy_usage_generator.py:566` `generate_policy_usage_xlsx(rules_df, ...)`、
   `src/report/ven_status_generator.py:411` `generate_ven_xlsx(workloads_df, ...)`
   —— 在 `src/` 內**零呼叫者**，僅 `tests/test_xlsx_content_{audit,policy_usage,ven}.py` 使用。
2. 正式路徑（各 generator 的 `export()`，如 `audit_generator.py:722-737`）呼叫
   `export_xlsx()` 時，每個 module 塞的是 `{'summary': '', 'table': []}` 空殼
   （traffic 亦同，見 `report_generator.py:524-530`）—— 使用者拿到的 XLSX 沒有內容。
3. 平行路徑已造成語義分歧：`generate_ven_xlsx` 的 online/offline 判定
   （`ven_status=="active" & age<24h`）與 `VenStatusGenerator._analyze`
   （1 小時心跳閾值）不一致。此分歧的 VEN 部分由拆分案 Phase 5（K1）先修；
   本計畫消除結構成因。

## Global Constraints

- Commit：英文 conventional commits。無 emoji。i18n 字串 en/zh_TW 兩檔同步。
- 測試命令 `venv/bin/python -m pytest`。
- HTML 輸出不得因本重構改變（回歸鎖定）。
- XLSX sheet 的資料必須與 HTML 同源（同一份 `module_results` / `_analyze` 結果），
  不得重新查詢或重新分桶。

---

### Task 1: Audit XLSX 接線

**Files:**
- Modify: `src/report/audit_generator.py`（`export()` 的 xlsx 分支 + `generate_audit_xlsx` 改造）
- Modify: `tests/test_xlsx_content_audit.py`
- Test: 新增 export-path 整合測試（`export(fmt='xlsx')` 產出的 sheet 非空、sheet 名與 HTML 章節對應）

**Interfaces:**
- Produces: `generate_audit_xlsx(module_results: dict, out_path: str) -> str` —— 簽名改吃
  `export()` 已算好的 `module_results`（原為 raw `events_df` 自行重算）。
- `export()` 的 `fmt in ('xlsx','all')` 分支改呼叫上述函式，刪除空殼 `xlsx_result` 組裝。

**Test strategy:** 以小型合成 events 走 `generate_from_api`（mock API）→ `export(fmt='xlsx')`，
openpyxl 讀回驗證：各 sheet 存在、列數 > 0、關鍵欄位值與 `module_results` 對應。
既有 `tests/test_xlsx_content_audit.py` 改走新簽名。

**執行時 refresh：** Phase 5（Audit 精簡 I1-I3）會改「近期事件」表與 KPI —— sheet
清單須對齊精簡後的模組輸出（完整明細留在 XLSX 是 Phase 5 的設計，故本 task 的
sheet 內容以「HTML 精簡版 + XLSX 完整明細」為準）。

- [ ] Step 1: 寫 export-path 失敗測試（xlsx sheet 非空斷言）
- [ ] Step 2: `generate_audit_xlsx` 改吃 `module_results`，刪除內部重算
- [ ] Step 3: `export()` xlsx 分支接線、刪空殼組裝
- [ ] Step 4: 更新 `tests/test_xlsx_content_audit.py`；全部通過
- [ ] Step 5: Commit `refactor(audit): wire rich xlsx builder into export()`

---

### Task 2: Policy Usage XLSX 接線

**Files:**
- Modify: `src/report/policy_usage_generator.py`（同 Task 1 模式）
- Modify: `tests/test_xlsx_content_policy_usage.py`

**Interfaces:**
- Produces: `generate_policy_usage_xlsx(module_results: dict, out_path: str) -> str`。
- 注意 Phase 5（J1）後 HTML unused 明細摺疊 50 列、完整清單走 CSV/XLSX ——
  XLSX 的 unused sheet 保留完整清單（上限沿用原 top_n=500 或取消上限，執行時定案並記錄於 commit message）。

**Test strategy:** 同 Task 1 模式；額外斷言 unused sheet 列數 > HTML 摺疊上限（驗證「完整明細在 XLSX」成立）。

- [ ] Step 1-5 同 Task 1 模式，commit `refactor(policy-usage): wire rich xlsx builder into export()`

---

### Task 3: VEN XLSX 接線與語義統一

**Files:**
- Modify: `src/report/ven_status_generator.py`
- Modify: `tests/test_xlsx_content_ven.py`

**Interfaces:**
- Produces: `generate_ven_xlsx(analysis: dict, out_path: str) -> str` —— 吃 `_analyze()`
  的分桶結果（online/offline/lost_today/lost_yesterday DataFrames），**不得**自行分桶。
- Phase 5（K1）已把 XLSX 判定改走 `_analyze`；本 task 把整個函式的資料來源收斂到
  `_analyze` 產物並由 `export()` 呼叫。

**Test strategy:** 斷言 XLSX 的 online/offline 列集合與 `_analyze` 回傳完全一致
（同一 mock workloads 集合、含 59 分鐘/61 分鐘心跳邊界案例）。

- [ ] Step 1-5 同 Task 1 模式，commit `refactor(ven): xlsx export consumes _analyze buckets`

---

### Task 4: Traffic XLSX 空殼修復（順帶）

**Files:**
- Modify: `src/report/report_generator.py:507-536`（xlsx 分支）
- Test: 新增 traffic xlsx 內容測試

**Interfaces:**
- `export()` xlsx 分支把 `module_results` 中各模組的 DataFrame 直接餵給
  `export_xlsx`（sheet per module，DataFrame → rows），取代 `{'summary': '', 'table': []}` 空殼。
- 執行時 refresh：Phase 1 之後 traffic profile 只有 5+1 個模組；三種 profile 的
  sheet 集合依當時 module_results 動態決定。

- [ ] Step 1: 失敗測試（xlsx sheet 有資料列）
- [ ] Step 2: 實作 DataFrame → sheet 轉換
- [ ] Step 3: 三 profile 煙霧測試（cache-only）
- [ ] Step 4: Commit `fix(report): traffic xlsx export writes real module data`

---

## 完成定義

- `rg "generate_(audit|policy_usage|ven)_xlsx" src/` 的呼叫者只剩各自 `export()`。
- 三份報表 + traffic `--format xlsx` 的產出各 sheet 皆有資料，且與 HTML 同源。
- `venv/bin/python -m pytest tests/ -q` 全綠。
