# Backlog: Policy Diff 擴充至 IP List / Service / Label Group 層 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Backlog 狀態：** 獨立功能，與報表拆分 Phase 1-6 無程式碼衝突，可隨時排入；
> 建議在 Phase 4（顯示層批次）之後，讓新章節直接沿用修好的表格版面規範（spec N）。
> 執行前以當時程式碼 refresh 行號。

**Goal:** Policy Diff 報表（DRAFT vs ACTIVE）從現有 Ruleset/Rule 層擴充到 IP List、Service、Label Group 三種 policy 物件，維持「diff → attribution → risk 分級」三步管線。

**Architecture:** 沿用 `src/report/analysis/policy_diff/` 的純函式管線：`diff_engine.py`（比對）→ `attribution.py`（audit 事件歸屬）→ `risk.py`（風險分級）。新增一個泛用的物件層 diff（named-object 比對器），三種物件共用；exporter 加三個章節。API 取數用既有 `api.get_ip_lists()` / `get_services()` / `get_label_groups()`，各需 draft 與 active 兩版（active 版走 `/sec_policy/active/` 端點——`ApiClient` 若缺 active 版取數方法，本計畫 Task 1 補齊）。

**Tech Stack:** Python 3.12、pandas、pytest。

## 現況事實（2026-07-02 盤點）

- `diff_engine.diff_rulesets()` 為純函式，輸出 `ruleset_changes` / `rule_changes`
  DataFrame（change_type / name / id / field / draft_value / active_value / last_actor /
  last_changed / last_event）與 `summary` 計數；v1 明確排除 IP list、service、
  label group、firewall settings。
- `attribution.attribute_changes()` 以物件名稱配對近 N 天 audit `draft_events`。
- `risk.grade_changes()`：HIGH（停用已生效防護）、MEDIUM（removed / re-enable）、其餘空。
- Exporter `policy_diff_html_exporter.py` 目前兩章（Ruleset 變更 / Rule 變更），
  47KB、密度良好，是本次擴充的版型基準。

## Global Constraints

- Commit：英文 conventional commits。無 emoji。i18n en/zh_TW 同步。
- 純函式優先：diff 邏輯不做 I/O，API 取數留在 `policy_diff_report.py`。
- 新章節必須符合 spec N（表格 print-fit、無水平捲動）。
- 風險分級語義：造成「防護面縮小」的變更 = HIGH（例：IP list 範圍擴大被 allow
  規則引用、service 加 port、label group 加成員都屬擴大暴露）。

---

### Task 1: ApiClient active 版物件取數

**Files:**
- Modify: `src/api_client.py`（或 `src/api/labels.py` 對應委派層）
- Test: `tests/test_api_active_policy_objects.py`（新檔）

**Interfaces:**
- Produces: `api.get_active_ip_lists()`、`api.get_active_services()`、
  `api.get_active_label_groups()` —— 與 draft 版同回傳形狀（list[dict]，含 href/name）。
  若既有方法已支援 `pversion` 參數則改用參數化，不新增方法（執行時確認）。

**Test strategy:** mock HTTP 層，斷言呼叫端點含 `/sec_policy/active/`、回傳形狀與 draft 版一致。

- [ ] Step 1-4: TDD 循環 + commit `feat(api): active-version policy object fetchers`

---

### Task 2: 泛用 named-object diff

**Files:**
- Create: `src/report/analysis/policy_diff/object_diff.py`
- Test: `tests/test_policy_diff_object_diff.py`（新檔）

**Interfaces:**
- Produces:
  `diff_objects(draft: list[dict], active: list[dict], *, kind: str, fields: list[str]) -> pd.DataFrame`
  —— 輸出欄位對齊 `diff_rulesets` 的 changes DataFrame（change_type / object_kind /
  name / id / field / draft_value / active_value + attribution 空欄），
  href 以 `/active/`→`/draft/` 正規化後配對（沿用 `_build_name_map` 的既有慣例）。
- 各物件的比對欄位：
  - ip_list：`ip_ranges`（排序後字串摘要）、`fqdns`、`description`
  - service：`service_ports`（port/proto/範圍摘要）、`windows_services`、`description`
  - label_group：`labels`（成員 href→name 排序清單）、`sub_groups`、`description`

**Test strategy:** 每種物件 added / removed / modified 三態 + 值摘要穩定性
（同內容不同順序 → 無 diff）。

- [ ] Step 1-4: TDD 循環 + commit `feat(policy-diff): generic named-object diff engine`

---

### Task 3: attribution 與 risk 擴充

**Files:**
- Modify: `src/report/analysis/policy_diff/attribution.py`（接受 object_kind 欄）
- Modify: `src/report/analysis/policy_diff/risk.py`
- Test: 既有測試檔擴充

**Interfaces:**
- attribution：以名稱配對邏輯不變，audit 事件型別集合擴充
  （`ip_list.update/create/delete`、`service.*`、`label_group.*`）。
- risk 新規則：
  - HIGH：modified 且欄位值為「範圍擴大」（ip_ranges 增加、service_ports 增加、
    label_group 成員增加）且該物件被任一 ACTIVE allow 規則引用。
  - MEDIUM：removed（active 有、draft 無 —— provision 後會消失）。
  - 其餘空字串（資訊性）。
- 「被 allow 規則引用」判定：以 Task 2 呼叫端傳入的 href→引用計數 map
  （由 `policy_diff_report.py` 掃 active rulesets 一次建立）。

- [ ] Step 1-4: TDD 循環 + commit `feat(policy-diff): attribution and risk grading for policy objects`

---

### Task 4: 報表組裝與 exporter 章節

**Files:**
- Modify: `src/report/policy_diff_report.py`（取數、呼叫 object_diff、組 module_results）
- Modify: `src/report/exporters/policy_diff_html_exporter.py`（新三章：IP List 變更 /
  Service 變更 / Label Group 變更；沿用既有變更表版型）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（章節標題與欄位）
- Test: `tests/test_policy_diff_html_exporter.py` 擴充 + CSV 匯出欄位測試

**Interfaces:**
- module_results 新增 `ip_list_changes` / `service_changes` / `label_group_changes`
  DataFrames 與 summary 計數（併入現有 summary dict）。
- 空 diff 時章節顯示「無變更」一行，不出空表。

**Test strategy:** 端對端 mock API（draft/active 物件集合含三態變更）→ HTML 含
三章節與正確列數；risk 欄顏色標記與 Ruleset 章一致。

- [ ] Step 1-5: TDD 循環 + 煙霧測試（lab PCE）+ commit `feat(policy-diff): ip-list/service/label-group diff sections`

---

## 完成定義

- `report policy-diff` 產出的 HTML 含五章（Ruleset / Rule / IP List / Service / Label Group）。
- 三種物件的 added/removed/modified 都有 attribution 與 risk 分級。
- 表格符合 print-fit（spec N），pytest 全綠。
