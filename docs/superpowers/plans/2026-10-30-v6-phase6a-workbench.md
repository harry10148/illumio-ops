# v6 P6a 調查工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 調查工作台：從告警一鍵帶條件進來，左側維度欄直接列各維度前幾名、點一下加進條件，中間明細／兩層排名，可切到事件模式；輕量模式（預設）也能用。

**Architecture:** 計算全走既有的分析段落入口 `services/analysis/segments.run_segment`（明細、排名）與 `aggregate_flows`／`aggregate_events`（維度欄＝每個維度一個單層排名，前 10）；新增 `web/routes/workbench.py`（`workbench.run`、`workbench.dimension`、`workbench.from_alert`）與 `web/src/pages/workbench/*`。維度欄**展開才算**（預設展開來源主機、目的主機、服務三個），每個維度一個請求；預設期間 1 天、可選 1 小時／1 天／7 天／30 天。輕量模式：工作台先把期間向 PCE 拉進按需暫存庫（`services/ondemand.py`），以「期間＋PCE」為鍵保留 30 分鐘供後續點選共用，之後明細／排名／維度都讀它。

**Tech Stack:** Python 3.12、Flask、pydantic 2、React/TS、Playwright。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md` §6.5.3（工作台骨架、維度、三視角、事件模式、成本取捨）、§6.3 第 4 點（分析段落：畫面與報表同一個數）、§6.4（輕量模式按需）、§6.5.2（告警詳情「在工作台開啟」）；定案草稿 `.superpowers/brainstorm/3221625-1792825707/content/workbench-v2.html`（B 骨架、C 排名、預計阻擋獨立視角）；roadmap P6 列（P2 Task 14 量測：條件查詢直接掃 flows 1 天 3.5–4.7 秒／6 維度、7 天 25 秒）。

## Global Constraints

- 一個數字只有一個算法：工作台的明細與排名一律經 `run_segment`；維度欄是單層 RANKING 段落，與報表同定義。
- 不無聲截斷：每個維度寫「前 10」；排名／明細達上限時寫明；資料涵蓋（缺口、PCE 補洞、截斷）照 `Coverage` 揭露；位元組指標附覆蓋率。
- 期間上限 30 天（30 天時提示可能較慢）；輕量模式的拉取沿用按需上限（每查詢 5 萬、總 100 萬列）並揭露。
- 預計阻擋視角、存成報表、主機側寫、隔離不在本段（P6b–P6e）；畫面上不放沒有作用的按鈕。
- 沿用 P5 慣例：i18n 兩語系同鍵無死鍵無動態鍵、用語守門、contracts 重產、英文 conventional commits。

## Review Focus

1. 從告警開啟：條件與期間＝告警證據段落的條件與期間（`test_from_alert_carries_segment`）；告警條件可逐一移除。
2. 點維度值加進條件後，維度欄與主畫面同時用新條件重算；已在條件中的維度值顯示為已選、可移除。
3. 輕量模式第一次查詢觸發拉取並顯示進度與揭露；同期間第二次不重拉（`test_lightweight_reuses_pull`）；換 PCE 時暫存庫作廢。
4. 事件模式的維度改為事件類型、主機、嚴重度、操作者，不混用流量維度（`test_event_dimensions_only`）。
5. 1,000 台規模 1 天條件查詢：一個維度 ≤ 2 秒（量測，Task 5）。

---

### Task 1: 工作台 API

**Files:** Create `illumio_ops/web/routes/workbench.py`、`illumio_ops/services/workbench.py`；Modify `illumio_ops/web/app.py`、contracts；Test `tests_v6/web/test_workbench_routes.py`、`tests_v6/services/test_workbench.py`

**Interfaces — Produces:** `WorkbenchRequest(mode: "flows"|"events", condition: FlowCondition|EventCondition, start, end, view: detail|ranking, group_by, metric, limit)` → `run(ctx, req) -> SegmentResult`；`dimension(ctx, req, dimension, label_key=None) -> DimensionTop(rows, limit_hit, coverage, field_coverage)`；`from_alert(ctx, alert_id) -> WorkbenchRequest`（取告警證據段落）。路由：`workbench.run` POST `/api/workbench/run`、`workbench.dimension` POST `/api/workbench/dimension`、`workbench.from_alert` GET `/api/workbench/from-alert/<id>`。

- [ ] 測試：`test_run_detail_and_ranking_match_run_segment`、`test_dimension_top_ten`、`test_event_dimensions_only`、`test_from_alert_carries_segment`、`test_period_capped_30_days`、登入與 CSRF。
- [ ] 實作、閘門、Commit `feat(v6): workbench API — segments, dimension tops, from an alert`

### Task 2: 工作台畫面

**Files:** Create `web/src/pages/workbench/{Workbench,ConditionBar,DimensionPanel,ResultView}.tsx`；Modify 導覽（調查）、i18n；Test `tests_v6/e2e/test_workbench_e2e.py`

- [ ] 條件列（期間、條件膠囊可移除、部分比對搜尋）、左側維度欄（預設展開三個、其餘點開才算、點值加條件、已選標示）、明細／排名視角（兩層分組、指標切換、位元組覆蓋率）、事件模式切換、涵蓋與截斷揭露；條件存在網址（可分享、可重新整理）。
- [ ] e2e：條件加減、排名兩層、事件模式、網址還原。
- [ ] Commit `feat(v6): investigation workbench page`

### Task 3: 告警詳情「在工作台開啟」

**Files:** Modify `web/src/pages/alerts/AlertDetail.tsx`；Test e2e

- [ ] 告警詳情主要動作「在工作台開啟」→ `/investigate?alert=<id>`，工作台以 `workbench.from_alert` 帶入條件（標示「來自告警 #id」可移除）。
- [ ] Commit `feat(v6): open an alert in the workbench`

### Task 4: 輕量模式

**Files:** Create `illumio_ops/services/workbench_store.py`（按需暫存庫的保留：期間＋PCE 鍵、30 分鐘、一次一份、換 PCE 作廢、離開時清除）；Modify `services/workbench.py`、`services/ondemand.py`（拆出可在 context manager 之外持有的建立／關閉）；Test `tests_v6/services/test_workbench_store.py`

- [ ] 測試：`test_lightweight_pulls_then_reuses`、`test_expired_store_removed`、`test_pce_switch_drops_store`、`test_pull_failure_disclosed`；完整／告警模式期間落在保留內時不拉。
- [ ] 畫面：拉取中顯示進度，完成後揭露（期間、列數、上限）。
- [ ] Commit `feat(v6): workbench in lightweight mode — the period pulled once, reused`

### Task 5: 規模與驗收

- [ ] 量測：P2 合成資料（1,000 台、1 天／7 天），每個維度的回應時間；1 天 > 2 秒時加入每日維度預先加總表（`(day, dimension, value, count)`，P2 Task 14 已驗證 0.6–0.7 秒）並只供無條件的維度欄使用。
- [ ] .106 實機：Playwright 從告警點進工作台、加減條件、兩層排名、事件模式、輕量根目錄拉取；兩語系、四寬度。
- [ ] 閘門；spec／roadmap；Codex 最終審查（prompt 開頭寫明只做審查）。
