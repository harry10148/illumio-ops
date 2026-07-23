# Report Content Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修復 2026-07-23 報表視覺實檢的全部發現：unknown 敘事斷層、判定色語意、圓餅標籤重疊、寬表溢出（RHC 欄序／列印 CSS／KPI RWD）、readiness 建議動作樣板化、unmanaged 內外網不分、字型 404、delta 浮點、RHC KPI 卡直排。

**Architecture:** 修改集中在報表層：`chart_renderer.py`（語意色＋標籤策略）、`_exec_summary.py`＋`mod12`（KPI 桶）、i18n 導讀文字、`trend_store` meta（換基準警語）、`readiness_report._build_queue`（action 依 blocking factor）、`mod08`＋html_exporter（公網分桶）、`rule_hit_count_html_exporter`（欄序＋KPI 版面）、`report_css.py`（字型內嵌＋KPI RWD＋列印規則）、`html_exporter._trend_deltas_section`（整數格式）。

**Tech Stack:** Python（matplotlib、pandas、pytest）、報表 CSS。驗收依專案規則：實際樣本產出後逐頁視覺檢查並附截圖。

## Global Constraints

- Commit 英文 conventional commits、無 emoji；i18n en/zh_TW 同 commit 同步；測試只用 tmp_path；四 CI 硬閘綠；全套 pytest 親跑；驗證命令不接 pipe 判斷成敗。
- worktree 分支（EnterWorktree `report-polish`）。
- 交付前在測試機重產 traffic/security/readiness/rule-hit-count 四種報表，Playwright 逐段視覺驗證並附截圖（CLAUDE.md 報表規則）。

---

### Task 1: 判定/嚴重度語意色＋圓餅小切片標籤策略

**Files:** Modify `src/report/exporters/chart_renderer.py`（pie 分支 165-175）；Test `tests/test_chart_renderer*.py`（先 grep 既有檔）。

- [ ] 模組層加語意色表（label 正規化小寫去空白比對）：
```python
_SEMANTIC_COLORS = {
    "allowed": "#16a34a", "blocked": "#dc2626",
    "potentially blocked": "#f59e0b", "potentially_blocked": "#f59e0b",
    "unknown": "#6b7280",
    "critical": "#dc2626", "high": "#f97316", "medium": "#f59e0b",
    "low": "#16a34a", "info": "#64748b", "warning": "#f59e0b", "error": "#dc2626",
}
```
pie 分支：`colors=[_SEMANTIC_COLORS.get(str(l).strip().lower()) for l in labels]`——任一 label 不在表中則整組 colors=None（維持預設循環，避免混色）。
- [ ] 小切片標籤：占比 <3% 的切片 label 傳空字串（`autopct` 既有 `_pie_autopct` 門檻同步 3%），並一律加 `ax.legend(labels 全名+件數, loc="center left", bbox_to_anchor=(1, 0.5), fontsize=8)`——小切片資訊移到圖例，消除重疊。
- [ ] 測試：語意 label 組回正確色序；含未知 label 組回 None；<3% 切片 label 為空但 legend 含全名。斷言用 figure 物件的 wedge/text 屬性（matplotlib Agg backend）。
- [ ] Commit `fix(report): semantic colors and small-slice legend for pie charts`

### Task 2: unknown 敘事補課（導讀＋執行摘要 KPI＋換基準警語）

**Files:** `src/i18n_en.json`/`src/i18n_zh_TW.json`（`rpt_tr_mod02_intro` 改寫＋新增 unknown 解讀鍵）、`src/report/analysis/mod12_executive_summary.py`（KPI 清單）、`src/report/exporters/_exec_summary.py`（`kpis[:6]`→`[:8]`）、`src/report/report_generator.py`（`_snapshot_meta` 加 `policy_decisions`）、`src/report/trend_store.py`（`snapshot_mismatch` 對 `policy_decisions` 特別處理：current 有值而 previous 缺 → mismatch，previous 顯示 `legacy (pre-unknown)`）。

- [ ] `rpt_tr_mod02_intro` 改寫（zh）：「先看整體決策分佈。unknown 代表 PCE 未回報判定的流量（idle/快照模式 VEN、Flowlink 未管理來源），不是錯誤——占比高代表大量資產尚未進入可判定的 enforcement 視野，優先把對應 VEN 提升到 visibility 以上或納管來源。再看有多少流量仍停留在 Potentially Blocked（有政策視野但未被 allow 規則覆蓋）。」en 對應翻譯。
- [ ] mod12 KPI：確認 allowed/blocked/pb 之外補 `mod12_kpi_unknown_flows`（en「Unknown Flows」/zh「Unknown 流量」）；`_exec_summary` 截斷 `[:6]`→`[:8]`。檢查各報表 mod00 KPI 數量不超過 8。
- [ ] `_snapshot_meta` 加 `"policy_decisions": "abpu"`（穩定字串代碼）；`snapshot_mismatch` 加：`cur = current_meta.get("policy_decisions"); prev = previous_meta.get("policy_decisions")`，cur 非 None 且 prev != cur（含 prev None）→ mismatch（prev None 顯示 "legacy"）。既有 `rpt_trend_mismatch_warning` 模板自動帶出。
- [ ] 測試：`tests/test_trend_meta.py` 擴充——prev 無 policy_decisions、cur 有 → mismatch 含 field=policy_decisions；兩邊同值 → 無。mod12/exec 測試同步（grep 既有）。
- [ ] Commit `fix(report): unknown-decision narrative, exec KPI buckets, baseline-change warning`

### Task 3: 寬表——RHC 欄序前移＋KPI 卡橫排

**Files:** `src/report/exporters/rule_hit_count_html_exporter.py`。

- [ ] 三張表（有命中/未命中/清理候選）欄序改為：Ruleset、編號、**命中次數、距上次命中、上次命中時間**（有命中表）、類型、說明、Consumers、Providers、Services（未命中/清理表無命中欄則維持既有但 Services 移到 Consumers 前？——不，未命中表欄序不動）。核心：**有命中表的 hit_count/days_since/last_hit 移到第 3-5 欄**。
- [ ] KPI 卡：找 KPI 卡容器 CSS/HTML，由直排改橫排 strip（比照 exec-summary kpi-strip grid）。
- [ ] 測試：exporter 既有測試斷言欄序（更新）；新增斷言 hit_count 欄 index < consumers 欄 index。
- [ ] Commit `fix(report): rule hit count key columns first; horizontal KPI strip`

### Task 4: 列印與窄幅 CSS（全報表）

**Files:** `src/report/exporters/report_css.py`。

- [ ] `.exec-summary .kpi-strip` → `minmax(150px, 1fr)`；`.kpi { min-width: 0; }`；`.kpi-value { font-size: clamp(1.1rem, 2.4vw, 1.6rem); }`。
- [ ] 新增列印規則：`@media print { .report-table-wrap { overflow: visible !important; } .report-table-wrap table { font-size: 9px; table-layout: auto; } .report-table-wrap td, .report-table-wrap th { word-break: break-word; white-space: normal; } }`——長文字欄可換行、避免捲動內容整段消失。
- [ ] 驗證：node 無涉；靠 Task 8 視覺驗證（含 780px 寬截圖）。
- [ ] Commit `fix(report): print-safe wide tables and responsive exec KPI strip`

### Task 5: readiness 建議動作依 blocking factor 分化

**Files:** `src/report/readiness_report.py` `_build_queue`（148-171）；i18n 新鍵；Test `tests/test_readiness_*` 擴充。

- [ ] blocking factor → 動作對照（新 helper `_action_for_blocking(blocking, lang)`）：
  - `policy_coverage` → 新鍵 `rpt_qact_policy_coverage`：zh「先為未覆蓋流量撰寫 allow policy 提升覆蓋率，再考慮推進 enforcement」
  - `ringfence_maturity` → `rpt_qact_ringfence`：zh「先建立/收斂應用程式邊界 Ringfence policy」
  - `enforcement_mode` → `rpt_qact_enforcement`：zh「將範圍內 Workload 由 visibility/testing 推進到 selective 或 full enforcement」
  - `staged_readiness` → `rpt_qact_staged`：zh「以 staged policy 驗證規則行為後再推進」
  - `remote_app_coverage` → `rpt_qact_remote`：zh「檢視遠端 App 存取路徑，補齊跨界 allow 規則或收斂邊界埠」
  （en 各自對應翻譯；`recommended_action` 改用此對照，找不到才 fallback `action_by_key`。）
- [ ] 測試：queue 兩列不同 blocking factor → 不同 action 文字；current_mode 已 selective 的列不再出現「由 visibility/testing 推進」（因其 blocking factor 非 enforcement_mode 時取別的文字——若 blocking 恰為 enforcement_mode 且 mode 已 selective，文字改用「推進到 full enforcement」變體：`rpt_qact_enforcement_full`）。
- [ ] Commit `fix(report): readiness queue action matches blocking factor`

### Task 6: unmanaged 內外網分桶

**Files:** `src/report/analysis/mod08_unmanaged_hosts.py`（來源/目的表加 `network` 欄：`ipaddress.ip_address(ip).is_private` → internal/external，解析失敗 → external 保守）；`src/report/exporters/html_exporter.py` mod08 render（新欄 i18n 標頭 `rpt_col_network`，值 `rpt_net_internal`「內網」/`rpt_net_external`「公網」；external 以既有警示樣式標紅）；KPI 補「公網來源數」。Test：mod08 既有測試擴充（公網/內網分類、非法 IP fallback）。

- [ ] TDD 循環 → Commit `feat(report): unmanaged sources flag public-internet addresses`

### Task 7: 字型內嵌＋delta 整數格式

**Files:** `src/report/exporters/report_css.py`（`build_css` 內把三個 `/static/fonts/*-VF.woff2` 讀檔轉 base64 data URI，模組級 cache；檔案不存在時保留原 URL）；`src/report/exporters/html_exporter.py` `_trend_deltas_section`（Previous/Current：`float(val).is_integer()` → `f'{int(val):,}'`，否則維持 `:,.1f`）。Test：build_css 含 `data:font/woff2;base64`；delta 表整數無 `.0`（test_trend_meta.py 擴充）。

- [ ] TDD 循環 → Commit `fix(report): embed report fonts; integer formatting in trend deltas`

### Task 8: 收尾——全套驗證＋測試機重產報表逐頁視覺驗證

- [ ] CHANGELOG（Fixed 一段彙總）；全套 pytest＋四硬閘。
- [ ] merge main（non-ff）→ push → CI 綠 → 部署測試機。
- [ ] 測試機重產 traffic/security/readiness/rule-hit-count html，抓回本地 Playwright 檢查：
  1. Policy 判定圓餅：allowed 綠/PB 橘/unknown 灰、無標籤重疊、legend 齊。
  2. 執行摘要含 PB/unknown 桶；780px 寬 KPI 不互擠。
  3. 成熟度 delta 出現 policy_decisions 換基準警語（前次快照為 legacy）。
  4. RHC 命中次數欄在 1440px 可見；KPI 卡橫排。
  5. readiness 佇列各列 action 依 blocking factor 分化。
  6. unmanaged 表公網標紅＋KPI。
  7. 列印模擬（Playwright `media: print` 或 pdf 匯出）確認寬表內容不消失。
  8. console 無 fonts 404。
  逐項截圖附回報（CLAUDE.md 報表規則）。
- [ ] 記憶更新＋worktree 清理。
