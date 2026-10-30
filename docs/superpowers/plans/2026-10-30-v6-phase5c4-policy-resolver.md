# v6 P5c-4 policy_resolver（生效規則展開成 IP 層級）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** policy_resolver：把生效中的規則展開成「來源 IP × 目的 IP × port／協定」的平面列，輸出 JSON＋CSV 給其他工具用（例如與傳統防火牆規則比對）；不做 HTML。

**Architecture:** 報表平台先能輸出 JSON／CSV：`ReportFormat` 加兩種、`ReportSpec.formats` 宣告型別可用的格式、`ReportDocument.export` 帶平面列（不經 pydantic 驗證的容器）、寫檔／寄信／目錄／產生表單／排程表單依型別的格式。展開核心移植 5.x `src/report/analysis/policy_resolver.py`（純函式）與 `src/report/policy_resolver_report.py` 的查表建構；即時讀 PCE（active Ruleset、全部 workload 含非受管、IP list、Label Group、服務），三種收集模式一樣。

**Tech Stack:** Python 3.12、pydantic 2、React/TS。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md` §6.5（policy_resolver：維持 JSON＋CSV、不做 HTML；列數上限與截斷揭露照舊【使用者】）、§8 回收清單。

## Global Constraints

- 沿用 P5 Global Constraints。
- 列數上限沿用 5.x：每條規則 src×dst 最多 100,000 對（超過把較大一側收斂成摘要 token、該列標 truncated）；全報表最多 500,000 列，超過的 Ruleset 尾端加一列明寫被省略幾列（刻意不是合法 IP／port）。JSON 另帶 `truncated`、`row_cap`。
- 任何 PCE 讀取失敗 → 報表失敗並寫原因，不產出不完整的展開。
- 信件：附件合計超過 20 MB 時不附，正文說明請到 GUI 下載。
- 不接受篩選；期間不影響內容（產生當下的生效政策），lookback 只是表單必填，固定上限 1 天以免誤解（報表寫明「產生當下」）。

## Review Focus

1. 截斷一定看得到：CSV 有提示列、JSON 有旗標（`test_total_cap_disclosed_in_both`）。
2. 讀取失敗不得輸出空展開（`test_fetch_failure_fails_report`）。
3. 不支援的格式組合被拒絕：policy_resolver 要 HTML，或其他型別要 CSV（`test_format_refused_for_type`）；排程同理。
4. 非受管 workload 帶 label 時也要展開（5.x 註解）（`test_unmanaged_workload_included`）。
5. Ruleset scope 收斂目的端（`test_scope_narrows_destinations`）。

---

### Task 1: 平台支援 JSON／CSV

**Files:** Modify `domain/values.py`（`ReportFormat.JSON`、`CSV`）、`domain/report.py`（`RowsExport`：columns、rows、meta；`ReportDocument.export: RowsExport | None`）、`services/reports/registry.py`（`ReportSpec.formats`，預設 HTML＋XLSX）、`services/reports/generate.py`（`refusal` 拒絕型別不支援的格式→`rpt_err_format_unsupported`；`_write` 寫 JSON／CSV：CSV 為 UTF-8 BOM、JSON 為 `{meta..., rows by group}`）、`services/reports/deliver.py`（MIME、超過上限的通知改通用）、`services/reports/views.py`（`CatalogEntry.formats`）、`web/src/pages/reports/{Reports,Schedules}.tsx`（格式勾選依 entry.formats）、i18n、contracts；Test `tests_v6/services/reports/test_formats.py`

- [ ] 測試：`test_format_refused_for_type`、`test_json_and_csv_written`、`test_csv_utf8_bom`、`test_mail_large_files_not_attached`、`test_catalog_lists_formats`、schedule 存檔拒絕不支援格式。
- [ ] 實作、閘門、Commit `feat(v6): reports can be JSON and CSV, per type`

### Task 2: 展開核心與服務

**Files:** Create `illumio_ops/domain/policy_resolver.py`（移植 `resolve_ruleset` 與上限邏輯）、`illumio_ops/services/analysis/policy_resolver.py`（抓取＋查表＋總量上限）；Test `tests_v6/domain/test_policy_resolver.py`（移植 5.x `tests/test_policy_resolver_core.py`、`test_policy_resolver_facade.py` 案例）、`tests_v6/services/analysis/test_policy_resolver.py`

**Interfaces — Produces:** `resolve(ctx) -> Resolved(rows: list[dict[str, str]], per_ruleset: dict[str, int], rule_count: int, truncated_rulesets: list[str], rows_omitted: int, computed_at)`；列欄位沿用 5.x：`ruleset_name, rule_href, action, src_ip, dst_ip, port, protocol, src_kind, dst_kind, service_name, truncated`。

- [ ] 測試先行（含 Review Focus 4、5 與上限）→ 實作 → Commit `feat(v6): policy resolver — active rules expanded to IP-level rows`

### Task 3: 報表、驗收

**Files:** Create `services/reports/policy_resolver.py`（ReportDocument：KPI 規則數、Ruleset 數、列數、被收斂的規則、被省略的列；一節摘要說明＋各 Ruleset 列數表；`export` 帶全部列）；Modify `values.py`（`ReportType.POLICY_RESOLVER`）、registry（群組 policy、formats JSON＋CSV、needs_traffic False、max_lookback 1）、i18n、`common.ts`、contracts。

- [ ] 測試：`test_rows_exported`、`test_total_cap_disclosed_in_both`、`test_fetch_failure_fails_report`、`test_zh_tw_builds`、i18n 守門樣本。
- [ ] lab：產生 JSON＋CSV 兩語系，檢查列數、截斷揭露、CSV 用 Excel 相容編碼可開。
- [ ] 閘門；spec／roadmap；Codex 最終審查（prompt 開頭寫明只做審查），Important 以上修。
