# v6 P5c-1 policy_usage（規則使用）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** policy_usage 報表：期間內哪些規則真的被流量用到、哪些沒被用到、哪些 Deny Rule 擋過東西、哪些流量沒有任何規則允許——數字來自 PCE 的 Draft 重算（PCE 自己比對），並寫明 Draft 與生效版本是否相同。

**Architecture:** 新服務 `services/analysis/rule_usage.py`：期間依天切窗，每窗做一次 async 查詢＋`update_rules`（沿用 `predicted_block` 的解析：`parse_draft`、`group_pairs`），逐窗把每條規則的命中累加後丟棄原始列；規則清單取自 Draft Ruleset（`fetch_rule_sets(draft)`＋`index_rules`），待 Provision 的變更取自 `GET /sec_policy/pending`。報表 builder `services/reports/policy_usage.py` 照 P5b 慣例，含「怎麼讀這份報表」。不讀本機流量庫，所以三種收集模式都一樣（輕量預設不需特別處理）。

**Tech Stack:** Python 3.12、pydantic 2、openpyxl、React/TS。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md` §6.5 報表表格（policy_usage）、§6.5.5、§6.2.1 用語；使用者 2026-10-29 決定方案 A（Draft 重算；生效規則的實際命中看 Rule Hit Count；lab 實測：一般流量查詢不帶規則欄位，見記憶 pce-flow-rule-fields）。

## Global Constraints

- 沿用 P5a／P5b Global Constraints：截斷必揭露、i18n 兩語系同鍵無死鍵無動態鍵、單一讀取／寫入閘門、用語守門（§6.2.1）、commit 英文 conventional commits、不引入 pandas。
- 每窗 `max_results = 50_000`（Draft 重算持有整份答案，約 200 MB）；窗在上限時對半切，最多 3 層；仍滿即該窗截斷並揭露。截斷判斷用 `AsyncQueryResult.capped`（已含 matches_count）。
- 「沒被用到」只在讀到的範圍內成立：任何窗截斷時，沒被用到的清單標題與說明要寫「在讀到的流量中」並揭露截斷；不得把它寫成可安全刪除。
- 報表不接受篩選（第一版）；lookback 上限 30 天（每天一次重算，lab 一窗約 1–4 分鐘）。
- PCE 不支援重算（update_rules 404）或查詢失敗：報表照常產生，各節寫原因，不顯示成 0。

## Review Focus

1. Draft 有待 Provision 的變更：報表開頭明說「這份報表依 Draft 計算，與目前生效政策不同」並列出待 Provision 的 Ruleset；沒有時明說「等同目前生效政策」（Task 2 `test_pending_changes_said`、`test_no_pending_equals_active`）。
2. 截斷時「沒被用到的規則」不得聲稱確定（Task 2 `test_unused_hedged_when_capped`）。
3. 停用的規則（enabled=false）不列入「沒被用到」（它本來就不會命中）；另列（Task 2 `test_disabled_rules_listed_apart`）。
4. 同一連線兩端都回報時只算一次，兩端的規則取聯集（沿用 group_pairs）（Task 1 `test_pair_counted_once`）。
5. 30 天 × 1,000 台規模：量時間與記憶體（Task 3）。

---

### Task 1: 規則命中服務

**Files:** Create `illumio_ops/services/analysis/rule_usage.py`；Modify `illumio_ops/pce/policy.py`（`fetch_pending(client, *, deadline) -> list[PendingItem]`）、`illumio_ops/services/analysis/predicted_block.py`（抽出「原始列 → (records, views)」共用函式，行為不變）；Test `tests_v6/services/analysis/test_rule_usage.py`、`tests_v6/pce/test_policy.py`

**Interfaces — Produces:** `rule_usage(ctx, *, start, end) -> RuleUsage`；`RuleUsage(rules: dict[str, RuleRef], hits: dict[str, RuleHits], no_rule: list[NoRuleGroup], windows: int, truncated: list[tuple[datetime, datetime]], unsupported: bool, pending: list[PendingItem], computed_at: datetime)`；`RuleHits(flows: int, connections: int, top_pairs: list[tuple[str | None, str | None, int]])`（來源 app、目的 app、連線數，前 3）；`NoRuleGroup(src_app, dst_app, port, proto, connections)`（Draft 判定非 allowed 且沒有任何允許規則的連線，依連線數前 50）。

- [ ] Step 1：測試（假 PCE，沿用 predicted_block 測試的寫法）：`test_hits_counted_per_rule`、`test_pair_counted_once`、`test_deny_rule_hits`、`test_no_rule_groups`、`test_windows_are_days`、`test_capped_window_halved_then_truncated`、`test_unsupported_when_update_rules_404`、`test_pending_parsed`（`{"rule_sets": [{"href", "name", "update_type", "updated_at"}]}`）。
- [ ] Step 2–4：實作至全綠。
- [ ] Step 5：Commit `feat(v6): rule usage from the PCE's draft recompute, a day at a time`

### Task 2: policy_usage 報表

**Files:** Create `illumio_ops/services/reports/policy_usage.py`；Modify `domain/values.py`（`ReportType.POLICY_USAGE`）、`services/reports/registry.py`（group 新增 `"policy"`、`needs_traffic=False`、`max_lookback` 30）、i18n、`web/src/pages/reports/common.ts`（分組名稱）、contracts；Test `tests_v6/services/reports/test_policy_usage.py`

**節：** 怎麼讀這份報表（這份報表回答什麼、Draft 與生效版本、Rule Hit Count 的差別、名詞）；摘要 KPI（規則數、有命中、沒命中、停用、Deny Rule 有擋下、沒有規則允許的連線）；發現（沒命中的規則數＋建議檢視、待 Provision 的變更）；①待 Provision 的變更（沒有時一句話）②有命中的規則（Ruleset、規則說明、流量、連線、主要來源→目的 app）③沒命中的規則（Ruleset、規則說明、範圍摘要）④停用的規則 ⑤ Deny Rule 擋下的連線 ⑥沒有規則允許的連線（來源 app → 目的 app × 服務）。

- [ ] Step 1：測試：`test_sections_and_kpis`、`test_pending_changes_said`、`test_no_pending_equals_active`、`test_unused_hedged_when_capped`、`test_disabled_rules_listed_apart`、`test_unsupported_says_so`、`test_failure_report_still_built`、`test_zh_tw_builds`、`test_how_to_read_first`。
- [ ] Step 2–4：實作至全綠；`tests_v6/services/reports` 與 i18n 守門全綠。
- [ ] Step 5：Commit `feat(v6): policy usage report — which rules traffic used, which it did not`

### Task 3: 驗收、文件

- [ ] lab：.106 輕量根目錄產生 policy_usage × 兩語系，`page_check.py` 0 問題；對照 lab 的 3 個待 Provision Ruleset 有列出。
- [ ] 規模：假 PCE 30 天 × 每天 5 萬列（1,000 台），量時間與記憶體。
- [ ] 閘門全綠；spec §6.5.5 補 policy_usage 語意、roadmap 5c-1 完成；最終審查（Codex reviewer），Critical／Important 一輪修正。
