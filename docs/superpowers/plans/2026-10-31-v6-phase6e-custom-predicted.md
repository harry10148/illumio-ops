# v6 P6e 自訂報表＋預計阻擋視角 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 工作台加「預計阻擋」視角（依 Draft 政策向 PCE 重算，明確按鈕觸發，顯示每筆連線會被哪條 Deny Rule 擋）；工作台的分析段落可「存成報表的一節」，多節組成自訂報表，可立即產生與排程。

**Architecture:** 預計阻擋沿用 `services/analysis/predicted_block.predict_blocks`（P5 readiness 已用），工作台新增一個操作，互動用較小的 `max_results` 與 deadline，並持 `INTERACTIVE_PULL`。自訂報表的定義存 app.sqlite（`custom_reports`），每節是「去掉絕對期間的段落」，產生時以報表期間 materialize 成 `FlowSegment`／`EventSegment` 經 `run_segment` 算——與工作台同數。報表平台加 `ReportType.CUSTOM` 與 `ReportParams.custom_id`。

**Spec:** §6.5.3（三個視角、存成排程報表）、§6.5.5（自訂＝工作台存下的分析段落）、§6.3 第 4 點（段落在畫面與報表同數）、§6.6 F1（預計阻擋的 PCE 形狀）、§6.4 輕量表。

## Global Constraints

- 每個 operation 有前端呼叫者，同一 commit；zh 用字過 `test_terminology.py`（Workload、Ruleset、Deny Rule、Override Deny、Draft、Provision）。
- 失敗／截斷／不支援不得顯示成空：預計阻擋的 `capped`、`limit_hit`、`missing_rules`、`unsupported` 各有文字；自訂報表每節的截斷照報表平台的 `limit_note`。
- 自訂報表上限明確：每份最多 20 節、每節 limit 依工作台上限（明細 ≤ 500、排名 ≤ 50）、名稱與節標題 ≤ 120 字；超過時拒絕並說明（專案 CLAUDE.md 報表截斷規則）。
- 主機以名稱顯示，不顯示 href。

## Review Focus

1. 預計阻擋重算中條件被改了——結果標「依先前條件算的」，不跟著變也不靜默清掉。
2. 自訂報表全是事件節——輕量模式不向 PCE 拉流量。
3. 自訂報表被刪而排程還引用——拒絕刪除並列出排程；排程執行時定義已不存在——報表失敗並寫原因。
4. 節的條件指向另一個 PCE 的 href——查無資料照常顯示「沒有資料」，不 500。
5. update_rules 404（PCE 不支援）——寫「此 PCE 版本不提供」。

---

### Task 1: 工作台預計阻擋視角

- 後端：`workbench.predicted` POST `{request}` → `PredictedView{predicted: PredictedBlock, names, request}`；只接受 flows；`predict_blocks(ctx, spec, limit=500, max_results=50_000, deadline_seconds=300)` 持 `INTERACTIVE_PULL`；BindingMismatch／StaleGeneration → 409、PceQueryError／PCE 失敗 → 502、ValueError → 400。
- 前端：工作台 flows 模式「依 Draft 重算」按鈕；表格：來源、目的、port、目前回報、Draft 判定、擋下它的規則（Ruleset 名、型別、consumers → providers（services））；結果保存當時請求，條件變了標示「依先前條件」。
- 測試：服務／路由（事件模式 400、unsupported、409）；e2e monkeypatch `predict_blocks`。

### Task 2: 自訂報表後端

- `store/migrations/0011_custom_reports.sql`、`store/custom_reports.py`（登記 TABLE_OWNERS、APP_DB_PCE_INDEPENDENT）。
- `domain/custom_report.py`：`SavedSegment{mode, condition, view(detail|ranking), group_by, metric, limit}`、`CustomReportDef{name, sections: list[CustomSection{title, segment}]}`，`materialize(seg, start, end)`、`to_request(seg, start, end)`。
- `services/custom_reports.py`：list／create／add_section／remove_section／rename／delete（排程引用時 `InUse(names)`）。
- 報表：`ReportType.CUSTOM`、`ReportParams.custom_id`、`refusal`（缺 id／不存在）、`services/reports/custom.py` build（ranking 用 `flowsections.ranking`、明細照 traffic／audit 的欄位、每節工作台連結）、`pulls_on_demand` 依定義有無流量節。
- 測試：store、materialize、build（ranking／detail／events）、refusal、純事件不拉流量、刪除被排程引用。

### Task 3: 入口與畫面（與 Task 2 同 commit）

- 工作台「存成報表的一節」（detail／ranking 才有）→ 選既有或新建＋節標題。
- 報表頁「自訂」分組：每份自訂報表的節清單、刪節、改名、刪除、立即產生（帶 custom_id）。
- 排程頁：型別選自訂時選哪一份。
- e2e：工作台存一節→報表頁看到並產生→排程帶 custom_id。

### Task 4: lab、審查、合併

- .106 輕量根目錄：工作台存兩節（排名＋明細）、產生自訂報表兩語系逐頁看截斷；預計阻擋：一台 Visibility Only 目的主機 7 天，量耗時與列數，確認顯示 Deny Rule。
- Codex 最終審查；合併、push、CI。
