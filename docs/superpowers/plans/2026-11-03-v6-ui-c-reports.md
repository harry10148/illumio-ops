# v6 介面重做 C：報表統一版式與報表畫面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每份報表第一頁一句算得出來的結論＋重點數字＋發現與行動表；報表 HTML 改成統一的明亮版式與列印樣式；「報表與寄送」畫面改成範本／排程寄送／已產出三個分頁（樣本 07、08、12–16）。

**Architecture:** 結論在 `services/reports/generate.py` 的 `_build` 之後統一產生（`domain/conclusion.py` 定義每型引用哪些 KPI 鍵，模板在 i18n），builder 不改；`ReportDocument` 加 `conclusion: str = ""`。HTML 版式只改 `render_html.py` 與 `assets/report_shell.css`；XLSX、JSON、CSV 不動，信件主旨帶結論。畫面用計畫 A 的外殼與元件。

**Tech Stack:** 同計畫 A。

**Spec:** `docs/superpowers/specs/2026-11-03-v6-ui-redesign-design.md` §4.7、§5、§6、§8、§9；樣本 `Reports`、`Delivery`、`TplLateral`、`TplReadiness`、`TplRansom`、`TplVen`、`TplDiff`。專案規則：報表不得無聲截斷，交付前用實際樣本資料逐頁檢查（`CLAUDE.md`）。

**前置：** 計畫 A 已合入。

## Global Constraints

- 結論句只能引用該報表 `kpis` 裡的值與 `findings` 依嚴重度的筆數；任何引用的 KPI 值為 None → 改用「無法完整計算」句（列出算不出的 KPI 標籤與其 `note`），不得用 0 代替。
- 不新增 PDF；「列印」用瀏覽器列印 HTML；列印樣式處理分頁與重複表頭（`thead { display: table-header-group }`）；單格過長換行，不截斷（`render_html` 既有 `CELL_SOFT_MAX` 規則保留並寫明）。
- 模式標記不比實際嚴格：流量型報表在基本模式標「按需查詢，較慢、受 PCE 保留期限制」，不標 ◆（UI 規格 §5）。
- 其餘（契約、i18n、閘門 `.superpowers/sdd/2026-11-03-v6-ui-c-reports/gates.sh`、git）同計畫 A。

## 結論模板（16 型；zh_TW 定稿，en 照意思翻；`{x}` 為 KPI 鍵，`{findings_high}` 為嚴重＋高的發現數）

| 型別 | 鍵 `rpt_conclusion_<type>` 的 zh_TW |
|---|---|
| lateral_posture | 可被觸及的重要資產 {assets_reachable} 項、樞紐主機 {pivots} 台、跨環境管理連線 {cross_env} 條；本期新偵測 {new_detections} 則 |
| new_connections | 本期新出現的連線 {new} 條，其中管理 port {admin} 條、連入重要資產 {critical} 條、來自非受管來源 {unmanaged_source} 條 |
| unmanaged_endpoints | 非受管位址 {total} 個（私有 {private}、公網 {public}），其中 {admin_sources} 個對受管主機使用管理 port |
| traffic | 流量 {flows} 筆、連線 {connections} 條，來源 {sources} 個、目的 {destinations} 個 |
| security_risk | 分段成熟度 {maturity}／100；已強制的受管主機 {enforced_hosts_pct}%；嚴重與高風險發現 {critical_high_findings} 項 |
| network_inventory | 受管主機 {managed_hosts} 台，其中 {hosts_missing_labels} 台缺 Label；有流量進入的 app {apps} 個；跨環境連線 {cross_env_connections} 條 |
| app_summary | 連入 {inbound_connections}、連出 {outbound_connections}、App 內 {intra_connections} 條連線；有規則允許的連線 {allowed_pct}% |
| ven_status | 受管主機 {managed} 台：在線 {online}、失聯超過 48 小時 {long_offline}、狀態未收集 {status_unknown}；在線但政策同步有問題 {sync_problems} 台 |
| audit | 事件 {total} 筆，嚴重與高風險 {high_risk} 筆；登入失敗 {auth_failed}、權限拒絕 {authz_denied}、政策 Provision {policy_provisions} 次 |
| ransomware | 有勒索評等的主機 {rated_hosts} 台；優先修補的服務 {priority} 項、可直接封鎖的服務 {safe_to_block} 項 |
| readiness | 評估 {apps} 個 app：可切換 {ready}、受阻 {held_back}；Draft 政策會擋下的連線 {predicted_blocked} 條 |
| policy_usage | 規則 {rules} 條：有流量命中 {used}、沒有流量命中 {unused}、停用 {disabled}；沒有規則允許的連線 {no_rule} 條 |
| rule_hit_count | 已 Provision 的啟用規則 {rules} 條：期間內有命中 {hit}、有紀錄但 0 次 {zero}、沒有紀錄 {no_record} |
| policy_diff | Draft 有 {total} 項變更尚未佈署：Ruleset {rule_sets}、規則 {rules}、政策物件 {objects}；其中 {high} 項為高風險 |
| policy_resolver | 生效中的規則 {rules} 條（{rulesets} 個 Ruleset）展開為 {rows} 列；無法展開 {not_expanded} 條 |
| custom | 自訂報表 {sections} 個章節，期間 {period}（`sections`、`period` 由文件本身算，不是 KPI） |

`rpt_conclusion_incomplete`：「{title}：{missing} 無法計算（{reasons}）」；`missing` 為算不出的 KPI 標籤以「、」連接。Task 1 的守門測試保證每個 `{x}` 都是該型 builder 實際輸出的 KPI 鍵；若某鍵不存在，**改模板不改 builder**，並在帳本記 Ruling。

## Review Focus

1. **KPI 為 None**：累積中、輕量模式、PCE 不支援時，結論不得出現「0」或「None」，要走 incomplete 句。
2. **百分比格式**：`unit="percent"` 的值依 `fmt_number` 顯示，不出現 `0.4523`。
3. **超長表格列印**：200 列以上的表在列印時每頁重複表頭、不切半列；單格 2,000 字以上寫明原長度。
4. **英文版**：en 結論句的單複數與數字格式（千分位）正確。
5. **信件主旨長度**：結論很長時主旨截到 200 字並以「…」結尾（主旨是唯一允許截短的地方，正文完整），在 `render_email` 寫明。

---

### Task 1: 一句結論

**Files:**
- Create: `illumio_ops/domain/conclusion.py`
- Modify: `illumio_ops/domain/report.py`（`ReportDocument.conclusion: str = ""`）、`illumio_ops/services/reports/generate.py`（`_build` 後補上）、`render_email.py`（主旨＝`rpt_mail_subject` 加結論；正文第一段為結論）、i18n 兩檔
- Test: `tests/domain/test_conclusion.py`、`tests/services/reports/test_conclusion_keys.py`

**Interfaces:**
- Produces：`CONCLUSION_KPIS: dict[ReportType, tuple[str, ...]]`（上表每型引用的鍵；custom 為空）；`conclusion(doc: ReportDocument, tr: Callable[..., str]) -> str`。

- [ ] **Step 1: 失敗測試**：`test_every_type_has_template`（每個 `ReportType` 在 zh_TW 與 en 都有 `rpt_conclusion_<type>`）；`test_placeholders_match_declared_kpis`（模板佔位符＝`CONCLUSION_KPIS[type]`，custom 例外為 `sections`、`period`）；`test_declared_kpis_exist_in_builder_output`（用 `tests/services/reports` 既有的各型建置 fixture 產一份文件，`CONCLUSION_KPIS[type] ⊆ {k.key for k in doc.kpis}`）；`test_none_kpi_gives_incomplete_sentence`；`test_percent_formatted`；`test_findings_high_counts_critical_and_high`；`test_mail_subject_carries_conclusion_and_caps_200`。
- [ ] **Step 2: 跑** `timeout 900 python -m pytest tests/domain/test_conclusion.py tests/services/reports/test_conclusion_keys.py -q` → FAIL。
- [ ] **Step 3: 實作。**
- [ ] **Step 4: 跑同一指令** → PASS；`timeout 1200 python -m pytest tests/services/reports tests/i18n -q` → PASS。
- [ ] **Step 5: Commit** `feat(v6): every report opens with one computed sentence`。

### Task 2: 統一 HTML 版式與列印樣式（樣本 12–16）

**Files:**
- Modify: `illumio_ops/services/reports/render_html.py`、`illumio_ops/services/reports/assets/report_shell.css`
- Test: `tests/services/reports/test_render_html.py`（加）、`tests/e2e/test_report_table_fit.py`（加列印寬度）

- 第 1 頁：眉標「illumio-ops・<報表名>」、結論（大字）、期間與來源、重點數字列（含與前次差異，沿用 `kpi_trend`）、S01 發現與行動表（嚴重度標籤、發現、行動、證據＝`why`）、資料涵蓋（`data_quality`）。頂線顏色＝整份最高嚴重度（findings 最高者；沒有 findings 為灰）。
- 之後：章節列（00 摘要、01…依 `sections` 順序編號）、每章編號標題；規則檢查卡片不新增資料（只有 builder 已給的 `TextBlock`／`TableBlock`）。
- 「列印」按鈕（`window.print()`），隱藏於列印。
- 明亮色票與計畫 A 相同；字型同計畫 A（中文系統字型，數字 JetBrains Mono 退回系統等寬，報表單檔不內嵌字型）。

- [ ] **Step 1: 失敗測試**：`test_first_page_order`（結論在數字列之前、發現表在數字列之後）；`test_top_rule_color_is_highest_severity`；`test_sections_numbered`；`test_print_css_repeats_header`（CSS 含 `thead{display:table-header-group}` 與 `tr{break-inside:avoid}`）；`test_long_cell_states_length`（既有規則仍成立）；`test_no_external_requests`（HTML 內沒有 `http://`／`https://` 的資源引用，除 `gui_link`）。e2e `test_report_table_fit.py` 加 `test_print_media_no_overflow`（`page.emulate_media(media="print")` 後 A4 寬度無水平溢出）。
- [ ] **Step 2–4:** `timeout 900 python -m pytest tests/services/reports/test_render_html.py tests/e2e/test_report_table_fit.py -q` → FAIL → 實作 → PASS。
- [ ] **Step 5:** gates.sh → ALL GREEN。
- [ ] **Step 6: Commit** `feat(v6): unified light report layout and print styles`。

### Task 3: 報表與寄送畫面（樣本 07、08）

**Files:**
- Modify: `web/src/pages/reports/Reports.tsx`（分頁容器：範本／排程寄送／已產出）、`Schedules.tsx`、`CustomReports.tsx`、`ReportFilter.tsx`；Move: `web/src/pages/system/ReportSettings.tsx` 的內容成為「排程寄送」分頁下方的「保留與輸出設定」區（系統次層選單移除「報表設定」，`/system/reports` 轉址）
- Modify: `illumio_ops/web/routes/reports.py`（清單項目加 `conclusion`、`delivery`；範本清單加 `mode_note`）
- Test: `tests/web/test_reports_routes.py`（加）、`tests/e2e/test_reports_e2e.py`（改）

**Interfaces:**
- Produces：`ReportItem.conclusion: str`（存在報表 sidecar／DB 列；舊報表沒有時為空字串，畫面顯示報表標題）；`ReportItem.delivery: DeliverySummary | None`（寄送結果：通道、成功／失敗、錯誤）；範本 `ReportTypeInfo.group: Literal["assessment","traffic","policy","operations"]`（由 `ReportSpec` 既有分類對應：lateral／assessment → assessment；analysis／inventory → traffic；policy → policy；operations → operations；custom → traffic）、`ReportTypeInfo.mode: Literal["basic","on_demand","advanced"]`（依主規格 §6.4：流量型＝`on_demand`，需要本機基準的＝`advanced`，其他＝`basic`）、`schedule_summary: str | None`、`copies: int`。
- 結論存放：報表列多一欄 `conclusion`（app 遷移下一號，計畫 B 用了 0013 則此為 0014；以實際最大號＋1 為準）。

- [ ] **Step 1: 失敗測試**：`test_report_items_carry_conclusion`、`test_old_reports_without_conclusion_ok`、`test_type_groups_and_modes`（traffic 為 `on_demand`、lateral_posture 為 `advanced`、policy_diff 為 `basic`）、`test_report_settings_moved_redirect`。
- [ ] **Step 2–4:** `timeout 600 python -m pytest tests/web/test_reports_routes.py tests/web/test_report_schedules_routes.py -q` → FAIL → 實作 → PASS；重產契約。
- [ ] **Step 5: 畫面** 照樣本 07：範本分頁四欄分組卡片（名稱、模式標記、排程摘要或份數、產生／排程）、下方產生列（報表、期間、範圍、格式與語言、立即產生／排程寄送）、最近產出（結論、類型、時間、寄送結果、開啟／下載／列印）。樣本 08：排程清單、寄送紀錄、編輯側欄（頻率、期間與範圍、收件人、信件內容、保留份數＝顯示全域 `reports.retention_days`、立即寄一次）、保留與輸出設定區。
- [ ] **Step 6: e2e**：`test_template_groups`、`test_traffic_card_not_marked_advanced`、`test_recent_shows_conclusion`、`test_schedule_editor_side_panel`、`test_no_overflow_760`。
- [ ] **Step 7:** build ＋ `timeout 900 python -m pytest tests/e2e/test_reports_e2e.py tests/e2e/test_custom_reports_e2e.py tests/e2e/test_rhc_e2e.py -q` → PASS；gates.sh → ALL GREEN。
- [ ] **Step 8: Commit** `feat(v6-ui): reports and delivery — template groups, conclusions, schedule editor`。

### Task 4: 真資料逐頁驗收

- [ ] **Step 1:** 合併、push、CI、部署 .106 與 .135（同計畫 A Task 8，先備份）。
- [ ] **Step 2:** 兩台各以真資料重產全部 16 型 × zh_TW／en（.135 只有 NFR 唯讀可產生的型別；RHC 依實際權限，產不了的寫原因）。
- [ ] **Step 3:** Playwright 以 1280 與 A4 列印兩種寬度逐頁截圖，親看：結論句每個數字對得到第 1 頁的數字列；無截斷、無溢出；長表列印重複表頭。寫入 `tmp/v6-ui-c-verification/report.md`，逐型列出檢查結果（專案規則要附在回報）。
- [ ] **Step 4:** 文字規則審查：把 16 句結論模板、`rpt_conclusion_incomplete`、計畫 A 新增的所有模板句列成清單，逐句對照資料來源，結果寫進同一份報告。
