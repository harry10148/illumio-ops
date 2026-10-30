# v6 P5c-3 policy_diff（Draft 與生效政策差在哪）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** policy_diff 報表：Provision 之前，一眼看出 Draft 相對生效政策改了什麼（Ruleset、規則、IP list、service、label group，以及其他待 Provision 的物件）、哪些改動有風險、最後是誰改的。

**Architecture:** 純差異引擎 `domain/policy_diff.py`（移植 5.x `src/report/analysis/policy_diff/` 的 diff_engine、object_diff、risk，不用 pandas）；服務 `services/analysis/policy_diff.py` 抓 Draft／active 的 Ruleset 與三種物件、名稱、待 Provision 清單，並從本機事件庫對每個變動找最近一次事件（依 `resource_changes[].href` 比對，比 5.x 的名稱比對準）；報表 builder 照 P5 慣例，含「怎麼讀這份報表」。即時讀 PCE，三種收集模式一樣。

**Tech Stack:** Python 3.12、pydantic 2、React/TS。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md` §6.5（policy_diff：草稿與已佈署政策差在哪，保留）、§6.5.5（評估分組）、§6.2.1 用語；§8 回收清單（policy_diff 四核心）。

## Global Constraints

- 沿用 P5 Global Constraints（截斷揭露、i18n 兩語系同鍵無死鍵無動態鍵、單一讀寫閘門、用語守門 §6.2.1、英文 conventional commits、不引入 pandas）。
- 任何 PCE 讀取失敗 → 報表失敗並寫原因（`ReportFailed`），**絕不**把讀取失敗當成「規則全被移除」（5.x 註解的教訓）。
- 差異語意「Draft 相對 active」：新增＝只在 Draft、刪除＝只在 active、修改＝兩邊都有但白名單欄位不同。規則以「集合/id」為鍵（`sec_rules/3` 與 `deny_rules/3` 不同）；allow、Deny Rule、Override Deny 都要比。
- 風險：停用中（Draft 停用、active 啟用）＝高；重新啟用或刪除＝中；物件刪除＝中；物件範圍擴大且被啟用中的 allow 規則引用＝高。
- 歸因只來自本機事件庫（期間內，含輕量模式收的事件）；找不到時寫「事件庫中沒有紀錄」，不猜。
- 報表不接受篩選；lookback 上限沿用事件保留（90 天）；期間只影響歸因找事件的範圍，差異本身是產生當下的狀態（報表寫明）。

## Review Focus

1. 讀取失敗不得產出「全部被刪除」的報表（`test_fetch_failure_fails_report`）。
2. Deny／Override Deny 規則的新增、刪除、修改不能消失（`test_deny_rules_diffed`）；同號 `sec_rules/3` 與 `deny_rules/3` 不對齊（`test_rule_keys_namespaced`）。
3. 停用 Quarantine 類 Ruleset 判為高風險（`test_disabling_is_high_risk`）。
4. 物件成員順序不同不算修改；範圍擴大才可能高風險（`test_member_order_ignored`、`test_expanded_referenced_object_high`）。
5. 新增的 Ruleset 內含的規則數要看得到（不展開成逐條也要寫出條數）（`test_added_ruleset_rule_count`）。

---

### Task 1: 差異引擎

**Files:** Create `illumio_ops/domain/policy_diff.py`；Test `tests_v6/domain/test_policy_diff.py`

**Interfaces — Produces:** `Change(kind: Literal["rule_set","rule","ip_list","service","label_group"], change: Literal["added","removed","modified"], ruleset: str, name: str, ref: str, href: str, field: str, draft: str, active: str, risk: Literal["high","medium",""], scope_expanded: bool)`；`diff_rule_sets(draft, active, names) -> list[Change]`；`diff_objects(draft, active, *, kind, fields, names) -> list[Change]`；`object_refs(active_rule_sets) -> dict[str, int]`；`grade(changes, refs) -> list[Change]`。`names` 為 href→顯示名（label 以 `key:value`）。物件欄位白名單沿用 5.x：ip_list `ip_ranges, fqdns, description`；service `service_ports, windows_services, description`；label_group `labels, sub_groups, description`。

- [ ] 測試先行（移植 5.x `tests/test_policy_diff_engine.py`、`test_policy_diff_object_diff.py`、`test_policy_diff_risk.py` 的案例，含 Review Focus 1–5 的引擎面）→ 實作 → Commit `feat(v6): policy diff engine — rule sets, rules and policy objects, Draft against active`

### Task 2: 抓取與歸因服務

**Files:** Create `illumio_ops/services/analysis/policy_diff.py`；Modify `illumio_ops/pce/policy.py`（`fetch_objects(client, pversion, kind, *, deadline) -> list[dict]`）；Test `tests_v6/services/analysis/test_policy_diff.py`

**Interfaces — Produces:** `policy_diff(ctx, *, start, end) -> PolicyDiff(changes: list[Change], pending: list[PendingItem], other_pending: list[PendingItem], attribution: dict[str, Attribution], computed_at)`；`Attribution(actor, at, event_type)`。`other_pending`＝待 Provision 清單中不屬於上述五類的（firewall_settings、virtual_services…），只列不比。歸因：期間內 `rule_set.* / sec_rule.* / deny_rule.* / ip_list.* / service.* / label_group.*` 事件，依 `resource_changes[].href`（Draft 路徑）對應到變動的 Draft href，取最新一筆。

- [ ] 測試（假 PCE、事件寫進本機事件庫）：`test_attribution_by_href`、`test_attribution_latest_wins`、`test_no_event_left_blank`、`test_other_pending_listed`、`test_fetch_failure_raises` → 實作 → Commit `feat(v6): policy diff from the PCE, attributed from the event store`

### Task 3: 報表、驗收

**Files:** Create `illumio_ops/services/reports/policy_diff.py`；Modify `domain/values.py`（`ReportType.POLICY_DIFF`）、`registry.py`（群組 policy、needs_traffic False、max_lookback 90）、i18n、`web/src/pages/reports/common.ts`、contracts；Test `tests_v6/services/reports/test_policy_diff.py`、`test_report_i18n.py` 樣本

**節：** 怎麼讀（Draft vs active、產生當下的狀態、歸因從哪來）；KPI（變動總數、高風險、Ruleset 變動、規則變動、物件變動、其他待 Provision）；發現（高風險逐條、待 Provision 項目數）；①高風險變動 ②Ruleset 變動 ③規則變動（Ruleset、規則、類型、欄位、Draft、生效中、最後修改者／時間）④物件變動 ⑤其他待 Provision。

- [ ] 測試：`test_how_to_read_first`、`test_sections_and_kpis`、`test_fetch_failure_fails_report`、`test_no_changes_says_same`、`test_zh_tw_builds`。
- [ ] lab：產生兩語系、page_check 0 問題；對照 lab 待 Provision 的 3 個 Ruleset。
- [ ] 閘門全綠；spec 補 policy_diff 實作語意、roadmap；Codex 最終審查（prompt 開頭寫明只做審查），Important 以上一輪修。
