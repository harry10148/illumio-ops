# v6 P5b-1 流量型報表 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 5.x 的 traffic、security_risk、network_inventory、app_summary 四型改寫到 v6：流量從 `flows` 表以分析段落（`run_segment`）計算、發現由一個以 SQL 實作的規則引擎（5.x B001–B009、L001–L010）產生，沿用 P5a 的報表平台（文件模型、兩個 renderer、信件、排程、報表頁）。

**Architecture:** 排名類的節一律是 `FlowSegment` 經 `run_segment`（與 P6 工作台同一個數字）；規則引擎與成熟度分數是專用分析模組，對同一期間的 `flows` 主列做一次分組讀取；security_risk 與 network_inventory 共用一次規則執行。報表參數加上選填的 `FlowCondition` 篩選（app／env 等標籤），app_summary 就是帶 app 篩選的報表，不是另一條管線。

**Tech Stack:** Python 3.12、SQLite、pydantic 2、openpyxl、React/TS。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md`（§6.3 第 4 點、§6.5 報表表格、§6.5.5、§6.5.6、§6.5.7、§4.3）。5.x 盤點：`tmp/v6-p5b-verification/survey/`（traffic-family.md、readiness-app-summary.md）。

## 分段（Ruling，寫入帳本）

5b 再拆兩段：**5b-1（本計畫）** 流量型四型；**5b-2** readiness（含預計阻擋）、勒索防護、audit、ven_status（需擴充清冊收集）。理由：資料來源不同、5b-2 要改收集器，各自可獨立合併。

## Global Constraints

- 沿用 P5a 全部 Global Constraints（不引入 pandas、截斷規則、反目標、單一 SMTP、i18n、閘門、commit 格式）。
- **資料來源（Ruling）**：四型都讀 `flows` 主列（`is_primary=1`，一條連線一列，兩端屬性已合併），不讀 `flow_rollup_daily`——標籤是流量發生當時的、IP 與位元組都在、和工作台算出同一個數字。代價是期間受流量保留天數限制（`collection.retention.flow_days`，預設 35；告警模式 3）：`ReportParams.lookback_days` 對這四型上限為 `flow_days`，超過時拒絕排入並說明；資料品質行沿用 `coverage_note`。
- **計數定義（Ruling，一次定義）**：「流量」＝連線紀錄數（`COUNT(*)` of 主列），「連線數」＝`SUM(num_connections)`，表頭寫明是哪一個，不混用。**inbound／outbound 只有一個定義**：以受管端為準，`dst_managed=1` 的連線算「連入受管主機」（5.x 有三種定義）。
- **標籤比對只有一個定義**：PCE 標籤值完全相同（區分大小寫，與 PCE 一致）；沒有該 key 的端點顯示「（無標籤）」（5.x readiness 小寫化、app_summary 區分大小寫，不一致）。
- **不移植（Ruling，各一句理由）**：vuln CSV（spec 拿掉 CSV 輸入）；5.x 勒索 port 清單（spec §6.5.6 改用 PCE 判定）；R01–R05（5.x 從未取得 draft 判定，實際從未觸發；預計阻擋在 5b-2 readiness）；drift／change_impact 的快照檔（P5a 已有上期比較）；mod14 基礎設施分數（provider／betweenness 分數讀者無法據以行動）；ringfence 出現次數（以空字串當 app 計數，無意義）；KPI 只顯示 8 個的上限；B001 的 `/24` 比較（改比 env 標籤，IPv6 也成立）；mod_draft_*、mod12.analyze 等死碼。
- 規則門檻成為設定 `reports.rule_thresholds`（5.x `config/report_config.yaml` 的值為預設），每個欄位由規則引擎讀取（閘門 5）。
- 5.x 已知缺陷不得重現，各有守門測試：inbound 三種定義、app 比對兩種定義、KPI 被截、規則丟例外時整份報表靜默少一節。

## Review Focus

1. 篩選後沒有任何流量（例如 app 名稱打錯）：每節寫明「此篩選條件下沒有流量」並在封面列出篩選條件，不得出現全 0 的指標或 100% 覆蓋（Task 4 `test_filter_with_no_flows_says_so`）。
2. 期間超過流量保留天數：排入時拒絕並說明；排程設定時同樣驗證（Task 1 `test_lookback_beyond_flow_retention_refused`）。
3. 規則引擎某條規則出錯：該規則列為「無法評估」並寫原因，其他規則照常、報表照常產出（Task 2 `test_rule_error_is_reported_not_fatal`）。
4. process／使用者／位元組覆蓋很低：相關節寫出覆蓋率，覆蓋為 0 時不顯示空排名而是說明（Task 5 `test_zero_user_coverage_says_so`）。
5. 1,000 台規模：一份 security_risk（7 天、約 700 萬主列）在 5 分鐘內完成，規則引擎不對每條規則各掃一次全期間（Task 9 量測；Task 2 `test_rules_share_one_period_read`）。

---

### Task 1: 報表篩選與流量型報表的共用元件

**Files:** Modify `illumio_ops/services/reports/registry.py`（`ReportParams.filter: FlowCondition | None = None`）、`illumio_ops/settings/schema.py`（`ReportScheduleFields.filter: FlowCondition | None`）、`illumio_ops/services/reports/generate.py`（`enqueue` 依型別驗證 `lookback_days ≤ flow_days`，超過寫 `rpt_err_lookback_beyond_retention` 並不排入）；Create `illumio_ops/services/reports/flowsections.py`；Test `tests_v6/services/reports/test_flowsections.py`、`tests_v6/services/reports/test_generate.py`（加測試）

**Interfaces（Produces）：**
- `ReportSpec.max_lookback: Callable[[Settings], int] | None`（流量型回傳 `flow_days`）。
- `flowsections.window(inp) -> FilterSpec`：期間＋篩選條件。
- `flowsections.ranking(inp, *, title, group_by: Sequence[GroupBy], metric: SegmentMetric, extra: FlowCondition | None = None, limit: int = 20, columns: Sequence[Column]) -> TableBlock`：以 `FlowSegment(view=RANKING)` 經 `run_segment` 計算；主機鍵顯示名稱（`AggRow.display`，否則 `common.host_name`）；`limit_hit` 時寫 `rpt_limit_top`；沒有列時寫「此期間（與篩選）沒有流量」。
- `flowsections.filter_text(cond, lang) -> str | None`：封面與資料品質用的篩選描述。
- `flowsections.coverage_lines(inp, fc: FieldCoverage) -> tuple[str, ...]`：process／使用者／位元組覆蓋率句。

- [ ] Step 1：測試 `test_filter_carried_into_segments`、`test_lookback_beyond_flow_retention_refused`（`flow_days=3`、lookback 7 → failed，原因鍵）、`test_schedule_lookback_validated`、`test_ranking_limit_disclosed`、`test_ranking_empty_says_why`、`test_filter_text_lists_labels`。
- [ ] Step 2–4：FAIL → 實作 → PASS；閘門。
- [ ] Step 5：Commit `feat(v6): report filters and flow-ranking sections through run_segment`

### Task 2: 規則引擎（B001–B009、L001–L010）

**Files:** Create `illumio_ops/domain/findings_rules.py`（規則定義：id、類別、嚴重度判定、文案鍵、證據欄位，純函式，輸入是彙總後的數字）、`illumio_ops/services/reports/findings.py`（在同一個唯讀連線上，把期間 `flows` 主列**一次**彙總進 SQLite 暫存表：依 (src_key, dst_key, port, proto, decision, 兩端 app 與 env 標籤值〔env key 取 `lateral.environment_label_key`〕, 兩端 managed, initiator_user) 加總流量數、連線數、位元組與有位元組的列數；各規則對暫存表下 SQL。彙總不進 Python 記憶體——1,000 台一週可達數百萬組）；Modify `schema.py`（`ReportRuleThresholds`，預設值照 5.x：unmanaged_connection 50、min_policy_coverage_pct 30、lateral_movement_outbound_dst 10、user_destination 20、high_bytes_percentile 95、cross_env_connection 100、discovery_protocol 10、db_unique_src_app 5、identity_unique_src 3、blast_radius 5、unmanaged_critical 5、pb_lateral 10、exfil_bytes_mb 100、cross_env_lateral 5；`ReportSettings.rule_thresholds`）、`upgrade.py`（未發佈的 v6，`default_reports()` 補齊）；Test `tests_v6/domain/test_findings_rules.py`、`tests_v6/services/reports/test_findings.py`

**Interfaces（Produces）：** `RuleResult(rule_id, severity: Severity | None, category, title, description, recommendation, evidence: dict[str, Any], error: str | None)`；`run_rules(ctx, spec: FilterSpec, thresholds, lang) -> list[RuleResult]`（只回傳有觸發或出錯的規則；依嚴重度、rule_id 排序）。

**規則語意（5.x 定義，v6 改動處標出）：** 端口集合：關鍵 {135,445,3389,5985,5986}、高 {5938,5900,137,138,139}、中風險（5.x CFG:17-25 清單照抄）、管理 port＝v6 `lateral.admin_ports` 遠端執行類、DB {1433,3306,5432,1521,27017,6379}（照 5.x RE:615）、身分 {88,389,636,3268,3269,464}、明文 {20,21,23}、探索 {137,138,5353,5355,1900,3702}、Windows 管理 {135,445,5985,5986,47001}。
- B001：關鍵 port 非 blocked；嚴重度：有跨 env 列 CRITICAL；否則有 allowed HIGH；否則 MEDIUM（**移除 /24 比較**）。
- B002 HIGH、B003 MEDIUM、B004（非受管來源連線數 > 門檻）、B005（allowed 連線比例 < 門檻）、B006（管理 port 非 blocked，單一來源不重複目的主機 > 門檻；只看 allowed 也成立則 HIGH）、B007（單一使用者不重複目的 > 門檻，依 `initiator_user`）、B008（單筆位元組 > max(p95, 10×中位數, 1 MiB)，只看有位元組的列，寫明覆蓋）、B009（跨 env 連線數 > 門檻）。
- L001–L005、L007–L010 照 5.x 條件，計數依上方定義（流量＝主列數）。**L006 改讀暴露面結果**（`analysis_results['exposure']` 可觸及 ≥ 門檻的主機），不另建圖。
- 規則出錯：該規則回傳 `error`，報表列「無法評估」並寫原因（取代 5.x ENG01 只顯示一張卡）。

- [ ] Step 1：每條規則一個觸發與一個不觸發的測試（`tests_v6/domain/test_findings_rules.py`，合成彙總輸入），加 `test_b001_cross_env_without_ip_heuristic`、`test_l006_reads_exposure`、`test_rule_error_is_reported_not_fatal`、`test_rules_share_one_period_read`（以 SQLite trace 計數：期間內 `flows` 表只被掃一次）、`test_thresholds_from_settings`。
- [ ] Step 2–4：FAIL → 實作 → PASS；閘門。
- [ ] Step 5：Commit `feat(v6): findings engine over the flow store (5.x B and L rules)`

### Task 3: traffic 報表（流量大戶與排名）

**Files:** Create `illumio_ops/services/reports/traffic.py`；Modify registry、i18n；Test `tests_v6/services/reports/test_traffic.py`

**內容：** KPI（流量、連線數、不重複來源、不重複目的；上期以 `traffic_covered` 判定）；節：①判定（四判定的流量與連線數、連入受管主機比例）②依來源／目的 app、env 的連線數前 20（`SRC_LABEL`/`DST_LABEL`）③port／協定前 20（`SERVICE`）④位元組前 20 主機對（`BYTES`，寫位元組覆蓋）⑤非受管端點連線摘要（指向非受管端點報表）⑥發現（規則引擎前 5 條作為 findings；完整清單一節）。

- [ ] Step 1：測試 `test_decision_table_flows_and_connections`、`test_inbound_single_definition`、`test_bytes_section_states_coverage`、`test_findings_from_rules`、`test_previous_none_without_collection`。
- [ ] Step 2–4／Step 5：Commit `feat(v6): traffic report`

### Task 4: security_risk 報表（風險流量）

**Files:** Create `illumio_ops/services/reports/security_risk.py`、`illumio_ops/domain/maturity.py`；Modify registry、i18n；Test `tests_v6/services/reports/test_security_risk.py`、`tests_v6/domain/test_maturity.py`

**內容：**
- 成熟度（v6 定義，Ruling）：enforcement 40＝清冊受管主機 (full＋0.5·selective)/總數（5.x 實際走 fallback 把 selective 當全強制——不重現）；policy 25＝allowed 連線比例；lateral 15＝1−min(管理 port 非 blocked 連線比例,30%)/30%；managed 10＝1−min(非受管來源連線比例,50%)/50%；ransomware 10＝PCE 判定的 critical／high 服務中已防護比例（取代 5.x 自訂 port 清單；沒有勒索資料時此維度不計並縮放）。等級 A≥85 B≥70 C≥55 D≥40。
- 節：①覆蓋（enforced／staged＝PB／缺口比例；連入與連出覆蓋）②未覆蓋流量前 20（依 src app → dst app、port，判定，建議：非受管來源／同 app／跨 app）③port 缺口前 20 ④強制模式推進（依 app(env)，清冊）⑤可能被擋（PB）前 20（依標籤 × port，附建議 allow 規則文字）⑥勒索防護摘要（`analysis_results['ransomware']` 最優先清單前 10，指向勒索防護報表）⑦使用者與程式（發起端使用者、程式依不重複目的與連線數前 20，寫覆蓋率）⑧橫向移動摘要（暴露面 KPI 與本期偵測數，指向橫向移動態勢報表）⑨發現（規則全部，依類別）。
- findings：規則引擎 CRITICAL／HIGH 前 5。

- [ ] Step 1：測試 `test_maturity_weights_and_rescale`、`test_selective_counts_half`、`test_maturity_without_ransomware_rescales`、`test_uncovered_recommendation_kinds`、`test_zero_user_coverage_says_so`、`test_filter_with_no_flows_says_so`、`test_all_kpis_rendered`（9 個以上 KPI 都出現在 HTML，5.x 只顯示 8 個）。
- [ ] Step 2–4／Step 5：Commit `feat(v6): security risk report`

### Task 5: network_inventory 報表（應用相依）

**Files:** Create `illumio_ops/services/reports/network_inventory.py`；Modify registry、i18n；Test `tests_v6/services/reports/test_network_inventory.py`

**內容：** ①標籤衛生（清冊：缺 app／env／loc／role 的受管主機數與清單；流量中受管端沒有 app 標籤的連線數）②app × app 相依（連線數前 20 對；同 env 與跨 env 的連線數）③每個目的 app 對外提供的服務（port 前 3、來源 app 數）④非受管來源連入哪些 app（依目的 app 前 20）⑤發現（與 security_risk 共用規則執行的結果摘要）。

- [ ] Step 1：測試 `test_label_hygiene_from_inventory`、`test_app_pairs_same_and_cross_env`、`test_services_per_app`、`test_unmanaged_into_apps`。
- [ ] Step 2–4／Step 5：Commit `feat(v6): network inventory report`

### Task 6: app_summary 報表（單一應用側寫）

**Files:** Create `illumio_ops/services/reports/app_summary.py`；Modify registry（`needs_filter=True`：沒有 app 標籤條件時拒絕排入，`rpt_err_app_required`）、i18n；Test `tests_v6/services/reports/test_app_summary.py`

**內容：** 依篩選中的 app（＋env）：①連入相依（對方 app × port × 判定，連線數前 30）②連出相依 ③政策影響（四判定、覆蓋率、會被擋的 PB 數）④此 app 的主機與強制模式（清冊，標籤完全相符）⑤未覆蓋流量前 10 ⑥發現（規則引擎只跑此 app 的流量；門檻相同，標題寫明範圍）。

- [ ] Step 1：測試 `test_app_required`、`test_app_match_is_exact_everywhere`（同一份資料在 app_summary 與 network_inventory 中，`Finance` 與 `finance` 視為不同 app）、`test_inbound_outbound_split`、`test_intra_app_counted_once`（5.x 同 app 流量兩邊都列）。
- [ ] Step 2–4／Step 5：Commit `feat(v6): app summary report`

### Task 7: GUI：篩選選擇與排程

**Files:** Modify `web/src/pages/reports/Reports.tsx`、`Schedules.tsx`（標籤篩選選擇器：key／value 下拉，值取自 `/api/system/lateral` 已有的 label_choices 或新 `reports.labels` 端點；app_summary 必選 app）、`views.py`（catalog 帶 `needs_filter`、`max_lookback`）、i18n；Test `tests_v6/web/test_reports_routes.py`、`tests_v6/e2e/test_reports_e2e.py`

- [ ] Step 1：路由測試 catalog 帶新欄位、app_summary 沒有 app 時 400 指名欄位；e2e：選 app 產生 app_summary、排程帶篩選。
- [ ] Step 2–4／Step 5：Commit `feat(v6): report filters on the reports page and schedules`

### Task 8: 兩語系完整性

擴充 `tests_v6/services/reports/test_report_i18n.py` 到七型；注入缺鍵確認會紅。Commit `test(v6): every report type in both languages`。

### Task 9: 驗收（.106 lab 與規模）、審查、交付紀錄

- [ ] Step 1：部署 .106（沿用 `tmp/v6-p5-verification/deploy106.sh` 改路徑）。
- [ ] Step 2：四型 × 兩語系以 lab 資料產出（app_summary 選 lab 上流量最多的 app），`page_check.py` 三種寬度＋列印，逐頁親看，結果寫入 `tmp/v6-p5b-verification/report.md`。
- [ ] Step 3：規模：在 .106 用 P4.5 合成流量產生器（`/root/v6-ab` 的腳本）建 1,000 台 × 8 天 × 每天 100 萬筆的 `flows`，量四型產生時間與峰值記憶體（目標每份 ≤ 5 分鐘、增量 ≤ 0.5 GB）；不達標先 profile。
- [ ] Step 4：Codex reviewer 全分支審查；每項先寫會紅的測試再修；修正 diff 再做一次範圍限定的再審。
- [ ] Step 5：更新 spec（§5 報表規模、§6.5 報表實作語意）與路線圖；閘門；commit。
