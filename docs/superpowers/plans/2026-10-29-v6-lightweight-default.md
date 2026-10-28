# v6 輕量模式（預設）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新安裝預設「輕量」：不收流量；流量型報表、工作台與試算在使用時向 PCE 按需查詢；需要持續流量的偵測與告警寫明「需要告警或完整模式」。告警／完整模式的報表在期間超出本機保留時也改走按需查詢。

**Architecture:** 模式閘門仍集中在 `services/collect/mode.py`（`EVENTS_ONLY` 改名 `LIGHTWEIGHT`）。新增 `services/ondemand.py`：把一段期間依天切窗向 PCE 拉取、逐窗寫進一次性的暫存流量庫（同 schema），以 `dataclasses.replace(ctx, flowdb=...)` 交給既有報表 builder，做完即刪。報表產生時先看本機覆蓋：完整覆蓋讀本機，否則走按需。

**Tech Stack:** Python 3.12、SQLite、pydantic 2、APScheduler、React/TS。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md` §6.4〈收集模式〉〈報表取流量的方式〉〈各功能在輕量模式的做法〉、§5〈輕量模式（按需查詢）〉、§7。

## Global Constraints

- 沿用 P5a／P5b 全部 Global Constraints：截斷必揭露、i18n 兩語系同鍵無死鍵無動態鍵、單一讀取／單一寫入閘門、`reset.py` 分類每張表、commit 英文 conventional commits、不引入 pandas。
- 設定 schema 升到 8：`CollectionMode.EVENTS_ONLY` → `LIGHTWEIGHT = "lightweight"`；`_v7_to_v8` 只把 `events_only` 改成 `lightweight`，其他模式不動；**新安裝** `default_collection()` 為 `mode=lightweight`。
- 告警模式在 UI 選擇時保留 8 天（`flow_days=8, rollup_days=8`，原 3 天）。
- 5.x 遷移器把「快取關閉」對應到 `lightweight`（訊息鍵改名）。
- 不可行的功能一律寫「需要告警或完整模式」並連到資料收集頁，**不得顯示成 0 或無資料**（反目標 1）。
- 按需查詢：每窗 `max_results = 50_000`（lab 15 萬列一次下載峰值 1.4 GB），以天為起始窗，`harvest` 遇上限再對半切；單窗切到 1 小時仍滿則該窗截斷並記錄；一份報表總列數上限 `ONDEMAND_MAX_ROWS = 1_000_000`，到達即停並揭露。
- 暫存庫放 `paths.data_dir / "ondemand"`（不放 /tmp），任何結束方式都刪檔；服務啟動時清掉殘檔。

## Review Focus

1. 已安裝的 v6（.106 為 full）升版後模式不變；舊 `events_only` 檔升版後是 lightweight（Task 1 `test_upgrade_keeps_mode`、`test_events_only_becomes_lightweight`）。
2. 告警模式保留 8 天、報表期間 30 天：不得只讀本機那 8 天就當成整段（Task 3 `test_partial_store_coverage_goes_ondemand`）。
3. PCE 查詢失敗或逾時：報表失敗並寫原因，不產空報表；部分窗截斷：照常產生並揭露（Task 2 `test_window_failure_fails_pull`、Task 3 `test_ondemand_capped_disclosed`）。
4. 輕量模式下的偵測、流量告警、異常偵測與首頁：狀態是「需要告警或完整模式」，不是「累積中」或「無資料」（Task 4 `test_detectors_say_alert_mode_needed`、`test_focus_lateral_needs_alert_mode`）。
5. 暫存檔在成功、失敗、例外、服務重啟四種情況都不殘留（Task 2 `test_tmp_removed_*`、`test_startup_sweeps_leftovers`）。

---

### Task 1: 模式與設定（schema 8）

**Files:** Modify `illumio_ops/domain/values.py`、`settings/schema.py`、`settings/upgrade.py`、`services/collect/mode.py`、`migrate/v5.py`、所有 `EVENTS_ONLY`／`events_only` 引用（含 i18n 鍵與 web）、`web/src/pages/system/Collection.tsx`、contracts；Test `tests_v6/settings/test_upgrade.py`、`tests_v6/services/collect/test_mode.py`、`tests_v6/migrate/test_v5.py`、web 測試

- [ ] Step 1：測試 `test_new_install_is_lightweight`、`test_upgrade_keeps_mode`（v7 full／alert → v8 不變）、`test_events_only_becomes_lightweight`、5.x `test_cache_off_maps_to_lightweight`、web `alert mode sets 8 days`。
- [ ] Step 2：跑測試確認失敗。
- [ ] Step 3：實作。頁面三個模式依序「輕量（預設）／告警／完整」，每個一句說明能做什麼、要多少資源；輕量寫明「橫向移動偵測與流量告警需要告警模式」。
- [ ] Step 4：`tests_v6/settings tests_v6/migrate tests_v6/services/collect` 與 web 測試全綠。
- [ ] Step 5：Commit `feat(v6): lightweight collection mode replaces events-only and is the new-install default (settings schema 8)`

### Task 2: 按需暫存流量庫

**Files:** Create `illumio_ops/services/ondemand.py`；Modify `services/collect/traffic.py`（`fetch_traffic` 接受 `max_results` 與條件 payload）、`collect/harvest`（若需要：起始窗）、啟動流程（清殘檔）、`store/flowdb/reset.py` 分類；Test `tests_v6/services/test_ondemand.py`

**Interfaces — Produces:** `pull_period(ctx, spec: FilterSpec, *, start, end, now) -> ContextManager[OnDemandResult]`；`OnDemandResult(ctx: AppContext, rows: int, windows: int, truncated: list[tuple[datetime, datetime, int]], earliest: datetime | None, capped_total: bool)`，`ctx` 的 flowdb 是填好的暫存庫（已綁同一 PCE、覆蓋記為整段已收集，截斷窗記為 gap）。

- [ ] Step 1：測試（假 PCE）：`test_pull_writes_rows_into_temp_db`、`test_windows_start_daily`、`test_capped_window_split_then_truncated`、`test_total_cap_stops_and_says_so`、`test_condition_sent_to_pce`（報表的 app／label 條件交給 PCE）、`test_window_failure_fails_pull`、`test_tmp_removed_on_success`、`test_tmp_removed_on_error`、`test_startup_sweeps_leftovers`、`test_earliest_reported`。
- [ ] Step 2–4：實作至全綠。
- [ ] Step 5：Commit `feat(v6): on-demand pulls fill a throwaway flow store a window at a time`

### Task 3: 報表依本機覆蓋選擇來源

**Files:** Modify `services/reports/generate.py`（`needs_traffic` 型別：本機完整覆蓋 → 本機，否則 `pull_period` 後以其 ctx 建置；`availability`：輕量模式不再反灰流量型報表；`max_lookback` 輕量時 90 天、其餘照舊但超出保留改按需；資料品質行）、`services/reports/lateral*.py`／新連線／非受管端點（輕量時的行為：態勢無趨勢、新連線用兩次查詢差集）、`services/reports/history.py`（上期先取歷史）、i18n；Test `tests_v6/services/reports/test_ondemand_reports.py`

- [ ] Step 1：測試：`test_full_coverage_reads_store`、`test_partial_store_coverage_goes_ondemand`、`test_lightweight_report_uses_ondemand`、`test_ondemand_builds_same_report_as_store`（同一批列：按需與本機產出相同章節與數字）、`test_ondemand_capped_disclosed`、`test_ondemand_failure_fails_report`、`test_quality_says_ondemand_and_current_labels`、`test_quality_states_pce_earliest`、`test_lateral_posture_lightweight_no_trend`、`test_new_connections_lightweight_two_queries`、`test_lightweight_availability_not_greyed`。
- [ ] Step 2–4：實作至全綠；`tests_v6/services/reports` 全綠。
- [ ] Step 5：Commit `feat(v6): flow reports pull from the PCE when the local store does not cover the period`

### Task 4: 偵測、告警、首頁、工作台在輕量模式

**Files:** Modify `services/alerts/evaluate.py`（`collection_off` 狀態在輕量模式改為 `needs_alert_mode`）、`services/analysis/*` 狀態、`domain/focus.py`（輕量模式一項「橫向移動偵測未啟用：需要告警模式」）、`services/flowsource.py` `query_flows`（輕量模式整段走 PCE、預算揭露；確認既有補洞路徑）、deny rule 試算／隔離試算的流量來源、對應頁面文字、i18n；Test `tests_v6/services/alerts/test_lightweight.py`、`tests_v6/services/analysis/test_lightweight.py`、`tests_v6/domain/test_focus.py`、`tests_v6/services/test_flowsource_lightweight.py`

- [ ] Step 1：測試：`test_traffic_rules_need_alert_mode`、`test_detectors_say_alert_mode_needed`、`test_anomaly_says_alert_mode_needed`、`test_focus_lateral_needs_alert_mode`、`test_workbench_lightweight_reads_pce`、`test_workbench_budget_disclosed`、`test_deny_sim_lightweight_queries_pce`。
- [ ] Step 2–4：實作至全綠。
- [ ] Step 5：Commit `feat(v6): lightweight mode says which features need alert mode; workbench and estimates query the PCE`

### Task 5: 驗收、文件與交付紀錄

- [ ] lab：.106 另開一個輕量安裝根目錄（不動既有 full 安裝），流量型四型＋橫向移動態勢＋新連線＋非受管端點 × 兩語系按需產生，`page_check.py` 1280／768／390／列印 0 問題；工作台查一次；首頁與告警規則頁的說明截圖。
- [ ] 規模：假 PCE 餵 100 萬列（每窗 5 萬），量按需拉取＋traffic 報表的時間與記憶體；目標記憶體增量 ≤ 1 GB。
- [ ] 閘門全綠（gates.sh）；spec §5 寫入量測；roadmap 加這一段，5c 改為輕量優先設計。
- [ ] 最終審查（Codex reviewer），Critical／Important 一輪修正。
