# v6 P5b-2 清冊／事件型報表 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 5.x 的 readiness（含預計阻擋）、勒索防護、audit、ven_status 四型改寫到 v6 報表平台，資料取自 v6 已收集的清冊、勒索判定、事件與流量；ven_status 需要的 VEN 狀態欄位由清冊收集器補收。

**Architecture:** 沿用 P5a 平台與 P5b-1 慣例：每型一個 builder 產 `ReportDocument`，流量／事件的排名經 `run_segment`，其餘經各自的讀取函式（流量只在 flowsource、事件只在 eventsource，單一讀取閘門）。ven_status 讀清冊表＋竄改分析結果；audit 讀 events；勒索讀 `ransomware_*` 表與 `analysis_results['ransomware']`；readiness 讀 flows 主列＋清冊＋PCE 預計阻擋（async＋update_rules）。

**Tech Stack:** Python 3.12、SQLite、pydantic 2、openpyxl、React/TS。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md`（§6.5 報表表格、§6.5.5 分組「評估：readiness（含預計阻擋）、勒索防護」「營運：ven_status（加入竄改與已知原因）、audit」、§6.5.6 勒索防護、§6.6 F1 預計阻擋）。5.x 盤點：`tmp/v6-p5b-verification/survey/`（readiness-app-summary.md、audit-ven.md，複本在 P5b-1 worktree）。

## Global Constraints

- 沿用 P5a／P5b-1 全部 Global Constraints：不引入 pandas、截斷必揭露、i18n 兩語系同鍵無死鍵無動態鍵、單一讀取／單一寫入閘門、`reset.py` 分類每張表、commit 英文 conventional commits。
- 新增 flowdb 欄位要遷移（0008）並把 `tests_v6/store/test_flowdb.py` 的 `user_version` 斷言改為 8；新增必填設定欄位要升 schema 並寫 upgrade（P5b-1 教訓）。本計畫不新增設定欄位。
- 需要流量的型別只有 readiness（`needs_traffic=True`、`accepts_filter=True`、`max_lookback=flow_days`、`retention=flow_retention`）；ven_status、audit、勒索在「僅事件」模式也可產生（`needs_traffic=False`），不接受篩選。
- **不移植（Ruling）**：5.x VEN 健康分數（權重無依據，讀者無法據以行動）、fleet pipeline 8 桶（v6 用強制模式分布與清冊表取代）、audit 的「非上班時間」關聯（需營業時間設定，5.x 寫死 UTC 8–18）、audit 的「agent 安全事件→政策變更」純時間關聯（無因果，誤導）、5.x 勒索 port 清單（spec §6.5.6）。
- 5.x 已知缺陷不得重現，各有守門測試：audit KPI 被截（只顯示 8 個）、HTML 趨勢永遠空、「System」actor 被當同一人關聯、ven 版本／OS／模式兩種來源、勒索錯誤被快取成「乾淨」、清冊 500 上限截斷只寫 log。

## Review Focus

1. 清冊從未收集或 VEN 狀態欄位是舊資料（遷移後尚未跑過一輪清冊）：ven_status 寫「尚未收集 VEN 狀態」，不得把空值當「離線」或「同步正常」（Task 1 `test_old_rows_have_unknown_status`、Task 2 `test_unknown_status_not_offline`）。
2. PCE 不支援 draft 重算（update_rules 404）或查詢失敗：readiness 照常產生，預計阻擋一節寫原因（Task 5 `test_predicted_unsupported_says_so`、`test_predicted_error_report_still_built`）。
3. 勒索資料不存在、PCE 不支援、或原廠分數與明細矛盾：各自說明；矛盾的主機標出、不拿來排序（Task 4 `test_contradiction_flagged_not_ranked`）。
4. 期間內完全沒有事件（新安裝、events_only 剛啟用）：audit 每節說明沒有事件，KPI 不顯示 0 當成量到（Task 3 `test_no_events_says_so`）。
5. 1,000 台：ven_status／勒索在 1,000 台清冊、audit 在一週 10 萬筆事件、readiness 在 600 萬主列上每份 ≤ 5 分鐘、增量 ≤ 0.5 GB（Task 7 量測）。

---

### Task 1: 清冊收集 VEN 狀態欄位

**Files:** Create `illumio_ops/store/flowdb/migrations/0008_workload_agent_status.sql`；Modify `illumio_ops/store/flowdb/workloads.py`、`illumio_ops/services/collect/inventory.py`、`tests_v6/store/test_flowdb.py`；Test `tests_v6/services/collect/test_inventory_agent_status.py`

**Interfaces — Produces:** `WorkloadRow` 加欄（全部可為 None）：`agent_status: str | None`、`last_heartbeat_at: str | None`（UTC 字串，`db_time`）、`policy_sync_state: str | None`、`policy_received_at: str | None`、`policy_applied_at: str | None`、`managed_since: str | None`、`fw_config_current: int | None`、`agent_health_json: str | None`（`agent.status.agent_health` 原樣 JSON；錯誤／警告數由讀取端算）。

- [ ] Step 1：測試 `test_agent_status_fields_stored`（`agent.status` 的 status、last_heartbeat_on、security_policy_sync_state、security_policy_received_at（缺時用 security_policy_refresh_at）、security_policy_applied_at、managed_since、fw_config_current、agent_health 各自寫入）、`test_old_rows_have_unknown_status`（0007 時寫入的列遷移後新欄為 NULL）、`test_unmanaged_has_no_agent_status`。
- [ ] Step 2–4：0008 以 `ALTER TABLE workloads ADD COLUMN` 加 8 欄；`_row()` 從 `w.agent.status` 取值；`test_flowdb.py` user_version 改 8。
- [ ] Step 5：Commit `feat(v6): inventory keeps each VEN's heartbeat, policy sync and health`

### Task 2: ven_status 報表（VEN 健康、版本、竄改）

**Files:** Create `illumio_ops/services/reports/ven_status.py`；Modify registry、values（`ReportType.VEN_STATUS="ven_status"`）、i18n、`web/src/pages/reports/common.ts`；Test `tests_v6/services/reports/test_ven_status.py`

**定義（Ruling，一次定義）：** 上線＝`online=1` 且最後心跳 ≤ 1 小時；離線分「24 小時內失聯」「24–48 小時」「超過 48 小時」，依 `last_heartbeat_at`；心跳未知（NULL）另列「狀態未收集」，不算離線。同步問題（只看上線者）：`policy_sync_state` 非 `applied`／`synced`、`fw_config_current=0`、`policy_received_at > policy_applied_at`、從未 applied、agent_health 有 error／warning。版本只用 `ven_version`、OS 只用 `os_id`、模式只用 `enforcement_mode`（NULL 顯示「未知」，不歸入 selective）。

**節：** KPI（受管、上線、24h 失聯、48h 失聯、長期離線、同步問題、未解釋竄改主機）；①離線清單（三段）②同步問題表（主機、問題、sync state、received、applied）③版本分布④OS 分布⑤強制模式分布（依 app（env））⑥竄改（`analysis_results['tamper']` hosts：60 天次數、7 天未解釋數、型態、最後時間；已知原因由 `tamper_annotations` 說明；指向主機側寫）。

- [ ] Step 1：測試 `test_online_offline_buckets`、`test_unknown_status_not_offline`、`test_sync_problems_online_only`、`test_mode_unknown_not_selective`、`test_tamper_section_from_analysis`、`test_all_kpis_rendered`。
- [ ] Step 2–4／Step 5：Commit `feat(v6): VEN status report`

### Task 3: audit 報表（PCE 事件稽核）

**Files:** Create `illumio_ops/domain/audit.py`（`AUDIT_RISK: Mapping[str, Severity]`，5.x `audit_risk.AUDIT_RISK_MAP` 的值；INFO 改為不列入，v6 嚴重度從 low 起）、`illumio_ops/services/reports/audit.py`；Modify eventsource（`audit_counts(ctx, start, end) -> AuditCounts`：一次讀取的分組計數）、registry、values（`ReportType.AUDIT="audit"`）、i18n、common.ts；Test `tests_v6/domain/test_audit.py`、`tests_v6/services/reports/test_audit.py`

**定義：** actor＝`created_by_name`；`created_by_kind='system'` 或名稱空白者顯示「系統」，**不參與任何以 actor 為鍵的計數或關聯**。登入失敗＝`request.authentication_failed`；權限拒絕＝`request.authorization_failed`；政策佈署＝`sec_policy.create`（workloads_affected 自 raw_json）；草稿變更＝`rule_set.*`、`sec_rule.*`。暴力破解＝同一來源 IP 30 分鐘內 ≥ 5 次登入失敗（來源 IP 自 raw_json `action.src_ip`）。

**節：** KPI 全數顯示（總事件、高風險事件、登入失敗、權限拒絕、政策佈署、草稿變更、agent 安全事件、不重複 actor、不重複來源 IP）；①注意事項（`AUDIT_RISK` ≤ medium 且期間內出現的類型，附次數、前 3 個 actor）②事件類型前 20 與每日趨勢（BarBlock，HTML 一定有值）③使用者（actor 排名經 `run_segment` EventSegment ACTOR；登入失敗明細前 30）④政策佈署清單（時間、actor、影響 workload 數、commit message）⑤agent 安全事件（tampering、clone_detected、suspend、unpair；指向 ven_status 竄改節）⑥暴力破解。

- [ ] Step 1：測試 `test_risk_map_levels`（agent.tampering→critical、request.authorization_failed→high、sec_policy.create→medium、lost_agent.found→low）、`test_system_actor_not_correlated`、`test_brute_force_same_ip_30min`、`test_trend_has_values`、`test_all_kpis_rendered`、`test_no_events_says_so`。
- [ ] Step 2–4／Step 5：Commit `feat(v6): audit report`

### Task 4: 勒索防護報表

**Files:** Create `illumio_ops/services/reports/ransomware_report.py`；Modify registry、values（`ReportType.RANSOMWARE="ransomware"`）、i18n、common.ts；Test `tests_v6/services/reports/test_ransomware_report.py`

**內容（spec §6.5.6）：** KPI（有勒索評等的主機、PCE 組織分數（`org_risk_snapshot_daily` 最新）、最優先服務數、可直接封服務數、可疑服務數、原廠矛盾主機數）；①最優先（未防護＋listening＋近 30 天有流量）②可直接封（零影響）③可疑（未防護＋inactive 卻有連線嘗試）④逐主機拆解（服務、嚴重度權重、覆蓋率、貢獻；`computed_percent` 標「近似」）⑤allow 規則造成的扣分：**只對最優先清單前 20 台主機**呼叫 `host_ransomware(explain_allows=True)`（每服務一次 Rule Search，寫明範圍；`allow_status` 為 error 時寫「PCE 查詢失敗」，不寫「沒有 allow 規則」）⑥趨勢（`ransomware_snapshot_daily` 依日計已防護比例；`org_risk_snapshot_daily`）。原廠數字與明細矛盾者標出、不參與排序。

- [ ] Step 1：測試 `test_three_lists_from_analysis`、`test_contradiction_flagged_not_ranked`、`test_allow_rules_top_hosts_only`、`test_allow_lookup_error_not_clean`、`test_trend_from_snapshots`、`test_not_computed_and_unsupported_say_so`。
- [ ] Step 2–4／Step 5：Commit `feat(v6): ransomware protection report`

### Task 5: readiness 報表（能否切強制＋預計阻擋）

**Files:** Create `illumio_ops/domain/readiness.py`、`illumio_ops/services/reports/readiness.py`；Modify flowsource（`readiness_rows(ctx, spec, *, app_key, env_key, remote_ports) -> list[ReadinessRow]`：依目的端 app（env）一次分組）、`illumio_ops/services/analysis/predicted_block.py`（`predicted_summary(ctx, spec, *, max_results) -> PredictedSummary`：依目的端 app、deny rule 計數，不保留逐列）、registry、values（`ReportType.READINESS="readiness"`）、i18n、common.ts；Test `tests_v6/domain/test_readiness.py`、`tests_v6/services/reports/test_readiness.py`、`tests_v6/services/analysis/test_predicted_summary.py`

**定義（Ruling）：** 對象是「連入某 app（env）」的流量（目的端受管且 app 相符，P5b-1 的連入定義；切強制擋的是連入）。五因子權重沿用 5.x：policy 35＝allowed 連線比例；ringfence 20＝來源同 app 的連線比例；enforcement 20＝該 app 受管主機 (full＋0.5·selective)/總數（清冊，標籤完全相符）；staged 15＝1 − potentially_blocked 連線比例；remote 10＝遠端管理 port 連線中 allowed 比例（沒有這類連線則不計）。沒有資料的因子不計並縮放；等級沿用成熟度的 A≥85 B≥70 C≥55 D≥40（與安全風險一致，取代 5.x 的 90/75/60/45）。

**節：** KPI（評估的 app 數、可切換（A／B）數、受阻（D／F）數、全域分數＝各 app 未加權平均、預計阻擋連線數）；①各 app 分數表（分數、等級、五因子、阻礙因子＝argmax W·(1−r)、目前模式計數、建議）②預計阻擋（`predicted_summary`：依目的 app × deny rule 的會被擋連線數；`unsupported` 寫 PCE 不支援；PCE 查詢失敗寫原因、報表照常；`capped` 揭露）③推進佇列（分數降序、阻礙因子、下一步）。

- [ ] Step 1：測試 `test_factor_weights_and_rescale`、`test_enforcement_from_inventory_exact_labels`、`test_inbound_only`、`test_predicted_grouped_by_rule`、`test_predicted_unsupported_says_so`、`test_predicted_error_report_still_built`、`test_predicted_capped_disclosed`。
- [ ] Step 2–4／Step 5：Commit `feat(v6): enforcement readiness report with predicted blocks`

### Task 6: 報表頁與兩語系

**Files:** Modify `web/src/pages/reports/common.ts`（四型的 TYPE／DESC 鍵）、`tests_v6/web/test_reports_routes.py`（catalog 型別集合、events_only 下這三型可用）、`tests_v6/services/reports/test_report_i18n.py`（樣本補清冊 VEN 狀態、事件、勒索結果、PCE 假回應，使四型每節都有內容）；Test 同上、`tests_v6/e2e/test_reports_e2e.py`（events_only 下產生 audit）

- [ ] Step 1：測試 `test_events_only_types_available`、`test_report_i18n` 參數化自動涵蓋新型；e2e `test_audit_in_events_only_mode`。
- [ ] Step 2–4／Step 5：Commit `feat(v6): P5b-2 report types on the reports page in both languages`

### Task 7: 驗收（.106 lab 與規模）、審查、交付紀錄

- [ ] Step 1：部署 .106（`tmp/v6-p5b2-verification/deploy106.sh`）；確認遷移 0008 後清冊跑過一輪、VEN 欄位有值。
- [ ] Step 2：四型 × 兩語系以 lab 資料產出（readiness 對 lab PCE 真跑預計阻擋），`page_check.py` 三種寬度＋列印，逐頁親看，結果寫入 `tmp/v6-p5b2-verification/report.md`。
- [ ] Step 3：規模：1,000 台清冊（合成 VEN 狀態）＋一週 10 萬筆合成事件＋P5b-1 的 600 萬主列合成庫；量 ven_status、audit、勒索、readiness（預計阻擋以假 PCE 回應 20 萬筆量記憶體）的時間與峰值記憶體；不達標先 profile。
- [ ] Step 4：Codex reviewer 全分支審查；每項先寫會紅的測試再修；修正 diff 範圍限定再審（至多兩輪）。
- [ ] Step 5：更新 spec（§5 報表規模、§6.5.5 實作語意）與路線圖；閘門；commit。
