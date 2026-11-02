# v6 介面重做 A：主控台外殼與畫面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 v6 GUI 換成明亮的資安主控台：新的左側導覽與外殼、告警首頁、偵測、調查、主機、告警規則與通知、SIEM、系統（含模式與資料來源），以及規格 §5.1 要補的資料。

**Architecture:** 前端沿用 React／TS／Vite 與 `shell/nav.ts` 自行註冊的頁面；新增一組共用元件（數字列、狀態標籤、嚴重度、表格、右側詳情、模式標記、「需要進階模式」說明框），每張畫面只組合這些元件。後端只加規格 §5.1 列出的讀取與計算，每個新 API 都走 `web/contract.py` 的 `operation()`，重產 `contracts.json`／`generated.ts`。

**Tech Stack:** Python 3.12、Flask、pydantic 2、SQLite；React 19、react-router 7、Vite 8、TypeScript 7；Playwright（`tests/e2e`）。

**Spec:** `docs/superpowers/specs/2026-11-03-v6-ui-redesign-design.md`（以下稱 UI 規格）；樣本原始檔 `docs/superpowers/specs/2026-11-03-v6-ui-samples/`（`Main`=01、`Detect`=02、`Investigate`=03、`Host`=04、`Schedule`=05、`Basic`=06、`Reports`=07、`Delivery`=08、`Siem`=09、`Rules`=10、`Modes`=11）。主規格 `2026-10-24-illumio-ops-v6-rebuild-design.md` 管資料與偵測語意。

**範圍：** 本計畫不含規則排程（計畫 B `2026-11-03-v6-ui-b-rule-scheduling.md`）與報表／排程寄送畫面、一句結論、報表版式（計畫 C `2026-11-03-v6-ui-c-reports.md`）。報表頁在本計畫只換上新色票與外殼，不改版面。

## Global Constraints

- 只有明亮模式，不提供切換（UI 規格 §2 非目標）。顏色（§7）：底 `#F4F6F8`、面板 `#FFFFFF`、文字 `#111827`、邊框 `#E5E7EB`；嚴重 `#B91C1C`、高 `#C2410C`、中 `#A16207`、低 `#4B5563`；正常 `#15803D`；累積中 `#1D4ED8`；進階模式 `#6D28D9`；主要動作 `#2563EB`。顏色不單獨表意，一律同時有文字。
- 字型：JetBrains Mono 隨前端打包（`@fontsource-variable/jetbrains-mono` 5.3.0，固定版本，Vite 打包進 dist，不連外），用於時間、數字、主機名稱、程式名；中文用系統字型 `"Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif`（UI 規格 §7 修訂）。
- 文字規則（UI 規格 §6）：每句由模板＋算出的值產生；不得推論對象語意、猜測意圖、沒有對應計算的建議；缺資料寫原因（累積中、欄位覆蓋、缺口、需要進階模式、群組太小），不顯示 0、不拿掉欄位。
- 隔離按鈕只對清冊中的受管 workload（`QuarantineTarget.reason` 為 None）；`no_enforcement` 顯示「不會生效」。
- 模式標記不得比主規格 §6.4 實際更嚴格（UI 規格 §5）：介面只有「基本模式」（`CollectionMode.LIGHTWEIGHT`）與「進階模式」（`ALERT`、`FULL`）。
- 每個新增或改動的 API：`operation()` 宣告，然後 `bash scripts/gen_contracts.sh` 重產 `web/src/api/contracts.json` 與 `generated.ts` 並一起提交（CI 以 `git diff --exit-code` 檢查）。
- i18n：新鍵同時加 `illumio_ops/i18n/zh_TW.json` 與 `en.json`；中文用語依主規格 §6.2.1；每個 task 跑 `tests/i18n`。
- 每個 task 結束跑完整閘門 `.superpowers/sdd/2026-11-03-v6-ui-a-console/gates.sh`（Task 1 建立，內容照 `.github/workflows/ci.yml`：pip-audit、契約、typecheck、build、ruff、mypy、pytest）。
- Git：只 `git add <明確路徑>`；commit 用英文 conventional commits，結尾兩行 trailer（Co-Authored-By、Claude-Session）。

## Review Focus

1. **基本模式下的進階功能**：橫向移動偵測、允許流量異常、主機基準、同群先例在 `lightweight` 下必須顯示「需要進階模式」與連結，不得是空表或 0。每個 task 的 e2e 要在 lightweight 設定下走一次。
2. **非受管與不在清冊的主機**：告警詳情、調查、主機頁都不能出現隔離按鈕；e2e 用 unmanaged key 與不在清冊的 href 各驗一次。
3. **760 寬度**：左側導覽收合、右側詳情改為下方，無水平溢出（每張畫面 e2e 量 `document.documentElement.scrollWidth <= clientWidth`）。
4. **未翻譯鍵與殘留 `{}`**：所有新畫面 zh_TW 與 en 各掃一次 DOM 文字，不得出現 `{`、`}` 或鍵名樣式（`[a-z]+_[a-z_]+`）。
5. **舊網址**：`/alerts`、`/lateral`、`/system/channels`、`/alerts/rules` 書籤要轉到新位置，不能 404 或空白。

---

### Task 1: 外殼、色票、共用元件與狀態 API

**Files:**
- Modify: `web/src/styles/tokens.css`（整份改寫為 UI 規格 §7 的明亮色票；刪除深色與 density 分支）、`web/src/styles/base.css`
- Modify: `web/package.json`、`web/package-lock.json`（加 `@fontsource-variable/jetbrains-mono@5.3.0`）、`web/src/main.tsx`（import 字型 CSS）
- Modify: `web/src/shell/nav.ts`、`web/src/shell/Shell.tsx`
- Create: `web/src/components/ui.tsx`（共用元件）
- Create: `illumio_ops/services/shell.py`、`illumio_ops/web/routes/shell.py`；Modify: `illumio_ops/web/app.py`（註冊 blueprint）
- Test: `tests/web/test_shell_status.py`、`tests/e2e/test_shell_e2e.py`；Modify: `tests/e2e/conftest.py`（加寬度參數）
- Create: `.superpowers/sdd/2026-11-03-v6-ui-a-console/gates.sh`

**Interfaces:**
- Produces（後端）：`services.shell.status(ctx, *, now: datetime | None = None) -> ShellStatus`；`ShellStatus(mode: Literal["basic","advanced"], collection_mode: CollectionMode, collection: Literal["ok","degraded","failing","not_started"], unprocessed_alerts: int, write_key: bool)`；operation `shell.status` `GET /api/shell/status`。
- Produces（前端 `nav.ts`）：`NavSection = "main" | "output" | "bottom" | "system"`；`NavItem` 加 `needs?: "advanced"`、`badge?: "unprocessed"`；`navItems(section)` 不變。
- Produces（`components/ui.tsx`）：`KpiStrip({items: {label, value: string|number|null, note?, delta?}[]})`、`Tag({tone: "crit"|"high"|"med"|"low"|"ok"|"accum"|"adv"|"muted", children})`、`SeverityTag({severity})`、`ModeMark({needs})`（◆ 進階／● 基本）、`NeedsAdvanced({what: string})`（虛線框＋連到 `/system/collection`）、`DataTable({columns, rows, empty})`（表頭固定、數字欄靠右、等寬欄）、`DetailPane({open, onClose, children})`（≥1100px 右側、窄螢幕在下方）、`Reason({text})`（取代 0 的原因字）、`PageHead({title, sub, actions})`。
- Produces（e2e）：`conftest.py` 的 `context` fixture 接受 `request.param` 寬度，新增 `narrow_context`（760×900）。

- [ ] **Step 1: 寫失敗的狀態 API 測試** `tests/web/test_shell_status.py`：
  - `test_status_basic_mode`：settings `collection.mode=lightweight` → `mode == "basic"`、`collection_mode == "lightweight"`。
  - `test_status_advanced_for_alert_and_full`：`alert`、`full` 都回 `"advanced"`。
  - `test_unprocessed_counts_ungrouped_last_7_days`：插入 3 則 7 天內告警（1 則 `grouped_annotation` 有值）與 1 則 8 天前 → `unprocessed_alerts == 2`；別的 PCE（不同 `pce_url`）的告警不計。
  - `test_collection_state_from_job_health`：`collect_traffic`／`collect_events`／`collect_inventory` 都沒跑過 → `not_started`；任一最後一次失敗 → `degraded`；全部最後一次失敗 → `failing`；全部成功 → `ok`。lightweight 模式只看 `collect_events` 與 `collect_inventory`。
  - `test_write_key_flag`：`write_api_key`／`write_api_secret` 都有值才 True。
- [ ] **Step 2: 跑** `timeout 600 python -m pytest tests/web/test_shell_status.py -q` → FAIL（模組不存在）。
- [ ] **Step 3: 實作** `services/shell.py` 與 `web/routes/shell.py`。未處理數只讀 `store/alerts.py`（加一個 `count_ungrouped(conn, *, pce_url, org_id, since) -> int`，不另開寫入者）。job 健康讀 `jobs/health.py` 既有 `list_health`。
- [ ] **Step 4: 跑同一指令** → PASS；重產契約（Global Constraints）。
- [ ] **Step 5: 外殼與元件。** 導覽結構照 UI 規格 §3：頂部品牌＋第二行「◆ 進階模式・收集正常」（由 `shell.status`，每 60 秒重抓）；`main`：告警（`badge: "unprocessed"`，order 10）、偵測（`needs: "advanced"`）、調查、主機、（規則排程由計畫 B 註冊）；`output` 標題「產出」：報表與寄送、SIEM 轉送；`bottom`：告警規則與通知、系統。基本模式下 `needs: "advanced"` 的項目淡化並加 ◆，仍可點。`Shell.tsx` 不再硬寫 `Home`；`/` 由告警頁註冊（Task 2）。760 寬度以下導覽收成頂部選單按鈕。色票與元件照樣本 `Main.dc.html` 的密度：表格列高 36px、數字等寬。
- [ ] **Step 6: e2e** `tests/e2e/test_shell_e2e.py`：
  - `test_nav_order_and_sections`：導覽文字順序＝告警、偵測、調查、主機、（產出）報表與寄送、SIEM 轉送、告警規則與通知、系統。
  - `test_basic_mode_marks_advanced_items`：lightweight 設定下「偵測」帶 ◆ 且 `aria-disabled` 不存在（可點）。
  - `test_no_horizontal_overflow_760`：760 寬度首頁 `scrollWidth <= clientWidth`。
  - `test_fonts_offline`：頁面載入期間沒有對外（非 127.0.0.1）的請求；`getComputedStyle` 的 `.mono` 字型含 `JetBrains Mono`。
- [ ] **Step 7: 跑** `npm --prefix web run build` 後 `timeout 900 python -m pytest tests/e2e/test_shell_e2e.py tests/web/test_shell_status.py -q` → PASS；再跑 gates.sh → ALL GREEN。既有 e2e 若因外殼改變而失敗，只修選擇器，不改它們驗的行為；每一處列入帳本。
- [ ] **Step 8: Commit** `feat(v6-ui): light console shell, shared components, shell status`。

### Task 2: 告警首頁（樣本 01）

**Files:**
- Create: `web/src/pages/alerts/AlertsHome.tsx`（清單＋右側詳情）；Modify: `AlertDetail.tsx`（抽出 `AlertDetailBody` 供兩處用）、`AlertList.tsx`（刪除，改為轉址）、`web/src/pages/Home.tsx`（刪除；關注清單移到 Task 3）
- Modify: `illumio_ops/services/alerts/views.py`、`illumio_ops/web/routes/alerts.py`
- Create: `illumio_ops/domain/alertcategory.py`
- Test: `tests/domain/test_alertcategory.py`、`tests/web/test_alerts_routes.py`（加）、`tests/e2e/test_alerts_e2e.py`（改）、`tests/e2e/test_home_e2e.py`（刪除，內容移到 Task 3 的 e2e）

**Interfaces:**
- Consumes：Task 1 的 `ui.tsx` 元件、`shell.status`。
- Produces：`AlertCategory = Literal["lateral","anomaly","traffic","event","system"]`；`domain.alertcategory.category(rule_type: AlertRuleType, detector: str | None) -> AlertCategory`；`ANOMALY_DETECTORS: frozenset[DetectorKind]` ＝ peer_deviation、volume_surge、account_new_source、suspicious_tool、new_process、auth_to_non_dc、new_dc_client、directory_surge、direction_reversal、new_pair_port、quiet_host_wakes、data_staging、off_hours。
- Produces：`AlertItem.category: AlertCategory`；`AlertQuery.category: AlertCategory | None`、`AlertQuery.unprocessed: bool = False`；`AlertList.counts: AlertCounts(critical, high, medium, low, grouped: int)`（同一期間、同一篩選前的總數）；`AlertDetail.timeline: list[TimelineEntry(at, kind: Literal["event","detection","alert"], text_key, params)]`、`AlertDetail.beyond_vendor: list[BeyondVendor(text_key, params)]`、`AlertDetail.quarantine: QuarantineEligibility(eligible: bool, reason: Literal["unmanaged","not_in_inventory","no_subject"] | None, no_enforcement: bool)`。

- [ ] **Step 1: 失敗測試** `tests/domain/test_alertcategory.py`：每個 `ANOMALY_DETECTORS` 成員 → `"anomaly"`；fanout、pivot_chain 等其他偵測器 → `"lateral"`；traffic／bandwidth／volume → `"traffic"`；event → `"event"`；system → `"system"`；lateral 但 detector 為 None → `"lateral"`。另 `test_every_detector_is_classified`：`set(DetectorKind) - ANOMALY_DETECTORS` 與 `ANOMALY_DETECTORS` 的聯集等於全部（新增偵測器時強迫分類）。
- [ ] **Step 2: 跑** `timeout 300 python -m pytest tests/domain/test_alertcategory.py -q` → FAIL。
- [ ] **Step 3: 實作** `domain/alertcategory.py`；`views.py` 從告警 `params["detector"]`（`domain/alerting.py` lateral trigger 寫入的鍵）取偵測器。
- [ ] **Step 4: 路由測試**（加到 `tests/web/test_alerts_routes.py`）：`test_filter_by_category`、`test_unprocessed_filter_excludes_grouped`、`test_counts_ignore_category_filter`、`test_detail_timeline_orders_by_time`（同主體的事件、偵測、告警各一，依時間排序）、`test_detail_beyond_vendor_from_detection_summary`（只來自偵測 summary 裡實際存在的欄位：同群先例數、首次出現的程式、首次出現的帳號；summary 沒有的就不列）、`test_detail_quarantine_eligibility`（受管且在清冊 → eligible；unmanaged key → `reason="unmanaged"`；清冊沒有的 href → `not_in_inventory`；system 告警 → `no_subject`）。資格判定呼叫 `services/quarantine.py` 既有的目標判定（`_targets` 的同一邏輯；抽成公開函式 `eligibility(ctx, key) -> QuarantineTarget`，不複製判斷）。
- [ ] **Step 5: 跑** `timeout 600 python -m pytest tests/web/test_alerts_routes.py tests/domain/test_alertcategory.py -q` → FAIL 後實作 → PASS；重產契約。
- [ ] **Step 6: 前端。** `AlertsHome` 註冊 `path: "/"`、`labelKey: "nav_alerts"`、`badge: "unprocessed"`；`/alerts` 轉址 `/`（保留 query）；`/alerts/:id` 保留為單獨頁並用同一個 `AlertDetailBody`。版面照樣本 01：數字列（嚴重／高／中／低／已歸組＝`counts`）、類型篩選（全部、橫向移動、允許流量異常、流量、事件、系統）、「只看未處理」切換（預設開）、清單欄（時間、等級、標題、偵測器類型、來源 → 目的、通知結果「已送 N／失敗 M」）、右側詳情（時間軸、原廠查不到的、通知紀錄、動作：開始調查＝主要按鈕連 `/investigate?from_alert=<id>`、隔離只在 `quarantine.eligible`、標為已知）。`eligible=false` 時顯示原因字，不顯示按鈕。
- [ ] **Step 7: e2e**（改寫 `tests/e2e/test_alerts_e2e.py`）：`test_home_is_alerts`、`test_old_alerts_url_redirects`、`test_category_filter`、`test_no_quarantine_button_for_unmanaged`、`test_detail_below_list_at_760`。
- [ ] **Step 8: 跑** build ＋ `timeout 900 python -m pytest tests/e2e/test_alerts_e2e.py -q` → PASS；gates.sh → ALL GREEN。
- [ ] **Step 9: Commit** `feat(v6-ui): alerts are the home page — categories, unprocessed, timeline, managed-only quarantine`。

### Task 3: 偵測（樣本 02）

**Files:**
- Create: `web/src/pages/detect/Detect.tsx`；Modify: `web/src/pages/lateral/LateralMovement.tsx`（拆成可重用區塊或併入 Detect 後刪除）、`Simulation.tsx`（保留路由）
- Modify: `illumio_ops/services/lateral_view.py`（攻擊面數字與上次差異、本週新偵測數）
- Test: `tests/web/test_lateral_routes.py`（加）、`tests/e2e/test_lateral_e2e.py`（改為偵測頁）、`tests/e2e/test_detect_attention_e2e.py`（原 home e2e 的關注清單斷言搬來）

**Interfaces:**
- Consumes：`lateral.view`（既有）、`home.focus`（既有 `FocusView`）。
- Produces：`LateralPage.surface: SurfaceNumbers(reachable_critical: int|None, reachable_critical_prev: int|None, hubs: int|None, residual_after_enforce: int|None, cross_env: int|None, new_this_week: int)`；`None` 時帶 `reason_key`（累積中、未設重要資產標籤等，沿用 `lateral_view` 既有原因）。

- [ ] **Step 1: 失敗測試**（`tests/web/test_lateral_routes.py`）：`test_surface_numbers_with_previous`（兩次計算之間重要資產可觸及數 5→7，回 `reachable_critical=7, reachable_critical_prev=5`）；`test_surface_unknown_says_why`（沒有重要資產標籤 → `None` 與原因鍵，不是 0）；`test_new_this_week_counts_detections_first_seen_7d`。
- [ ] **Step 2–4:** 跑 `timeout 600 python -m pytest tests/web/test_lateral_routes.py -q` → FAIL → 實作（上次的值取自已存的前一次暴露圖計算；沒有前一次 → `prev=None`）→ PASS；重產契約。
- [ ] **Step 5: 前端。** 註冊 `path: "/detect"`、`labelKey: "nav_detect"`、`needs: "advanced"`；`/lateral` 轉址 `/detect`。版面照樣本 02：數字列（surface）、偵測器狀態清單（每列：偵測器名、狀態標籤 正常 N／累積中 x/y 天／缺標籤／欄位覆蓋 n%／停用、原因、「調整門檻」連 `/system/lateral#<detector>`）、可觸及路徑與建議切點（既有暴露圖與切點，按鈕「模擬強制後」「產生 deny 規則草稿」連既有試算）、最近偵測表、**需要注意**區（`home.focus` 裡非告警的項目：暴露、樞紐、覆蓋率、就緒度，排序與連結沿用 `FocusEntry.link`）。基本模式：整頁只顯示 `NeedsAdvanced`（說明三類功能與資源需求），**「需要注意」裡不依賴本機流量的項目照常顯示**（以 `FocusView.sources_status` 判斷）。
- [ ] **Step 6: e2e**：`test_detect_sections_present`、`test_old_lateral_url_redirects`、`test_attention_items_link`（原 `test_home_e2e.py` 的斷言）、`test_basic_mode_explains_not_empty`、`test_no_overflow_760`。
- [ ] **Step 7:** build ＋ `timeout 900 python -m pytest tests/e2e/test_lateral_e2e.py tests/e2e/test_detect_attention_e2e.py tests/e2e/test_lateral_settings.py -q` → PASS；gates.sh → ALL GREEN。
- [ ] **Step 8: Commit** `feat(v6-ui): detection page — attack surface, detector states, paths, attention list`。

### Task 4: 調查（樣本 03）與同群先例

**Files:**
- Modify: `web/src/pages/workbench/Workbench.tsx`（版面）、`conditions.ts`
- Modify: `illumio_ops/services/workbench.py`、`illumio_ops/services/flowsource_anomaly.py`（新讀取）
- Test: `tests/services/test_workbench_peer_precedent.py`、`tests/e2e/test_workbench_e2e.py`（改）

**Interfaces:**
- Produces：`flowsource_anomaly.peer_precedent(ctx, *, group_members: Collection[str], exclude_src: str, dst_keys: Collection[str], port: int, proto: int, before: datetime) -> int`（`connection_baseline` 中 `src_key IN group_members − {exclude_src}`、`dst_key IN dst_keys`、`first_seen <= before` 的 `COUNT(DISTINCT src_key)`；走 `ix_baseline_port_src`）。
- Produces：`WorkbenchResult` 的每列加 `peer_precedent: int | None` 與結果層 `peer_precedent_state: Literal["ok","no_source_dimension","basic_mode","group_too_small"]`；列層 `group_too_small` 時該列為 None。
- 「同一目的簽章」＝ 偵測 A（同群偏離）用的目的簽章函式（`services/analysis/anomaly_inputs.py` 計算 `sig` 的那一個），不得另寫一份；dst_keys ＝ 基準中簽章相同的目的。群組 ＝ `peer_group_keys`；成員數 < `LateralSettings.detectors.peer_min_group` → `group_too_small`。

- [ ] **Step 1: 失敗測試**：`test_counts_other_members_only`（3 名成員中自己與另 1 人連過 → 1）；`test_ignores_after_period_start`（`first_seen` 晚於 `before` 不計）；`test_same_signature_other_host_counts`（不同主機但同簽章 → 計入）；`test_column_absent_without_source_dimension`（分組只有目的 → `no_source_dimension`，各列 None）；`test_basic_mode_state`（lightweight → `basic_mode`）；`test_group_too_small`。
- [ ] **Step 2–4:** `timeout 600 python -m pytest tests/services/test_workbench_peer_precedent.py -q` → FAIL → 實作 → PASS；重產契約。
- [ ] **Step 5: 前端** 照樣本 03：從告警進入時上方有「← 返回告警 #id」；條件列（篩選、分組最多兩層、排名指標）；左欄事件＋流量時間軸，右欄分組結果表含「同群先例」欄（`peer_precedent_state != "ok"` 時欄位標題旁寫原因，不顯示 0）；欄位覆蓋句「有程式／帳號的連線佔 n%，分組只涵蓋有值的部分」（取既有 `Coverage`）；動作：存成報表章節（既有 SaveSection）、在 PCE 主控台開啟、隔離（只對 eligible 的來源主機，用 Task 2 的 `eligibility`）。基本模式寫明「即時向 PCE 查詢、查完即丟」。
- [ ] **Step 6: e2e**：`test_from_alert_back_link`、`test_peer_precedent_column_states`、`test_coverage_sentence`、`test_no_overflow_760`。
- [ ] **Step 7:** build ＋ `timeout 900 python -m pytest tests/e2e/test_workbench_e2e.py tests/e2e/test_predicted_e2e.py tests/e2e/test_custom_reports_e2e.py -q` → PASS；gates.sh → ALL GREEN。
- [ ] **Step 8: Commit** `feat(v6-ui): investigation layout and peer precedent column`。

### Task 5: 主機（樣本 04）與隔離資格

**Files:**
- Modify: `web/src/pages/hosts/HostProfile.tsx`、`web/src/pages/quarantine/QuarantineDialog.tsx`
- Modify: `illumio_ops/services/hosts.py`；Create: 讀取函式於 `illumio_ops/store/flowdb/`（`flow_rollup_daily` 的讀取放在既有讀取模組，不新增寫入者）
- Modify: `illumio_ops/web/routes/hosts.py`（加 `hosts.search`）
- Test: `tests/services/test_host_baseline.py`、`tests/web/test_hosts_routes.py`（加）、`tests/e2e/test_hosts_e2e.py`、`tests/e2e/test_quarantine_e2e.py`（改）

**Interfaces:**
- Produces：`HostProfile.usual: HostUsual | None`（`top_destinations`、`top_processes`、`top_accounts`: 各 `list[RankedValue(value: str, connections: int)]` 最多 5 筆，近 30 天 `flow_rollup_daily`，依連線數排序；`days_covered: int`）與 `usual_state: Literal["ok","basic_mode","accumulating"]`；`HostProfile.different: list[HostDifference(detection_id, detector, first_seen, text_key, params)]`（這台主機近 7 天的偵測 summary，原樣）；`HostProfile.quarantine: QuarantineEligibility`（Task 2 型別）。
- Produces：operation `hosts.search` `GET /api/hosts/search?q=` → `HostSearch(items: list[HostHit(key, name, address, managed: bool)])`，清冊 workload 名稱或 IP 前綴比對，最多 50 筆；`q` 是 IP 且清冊沒有 → 回一筆 unmanaged key。

- [ ] **Step 1: 失敗測試**：`test_usual_top5_by_connections_30d`（31 天前的不計）；`test_usual_basic_mode`（lightweight → `usual=None, usual_state="basic_mode"`）；`test_usual_accumulating_when_fewer_than_7_days`（`days_covered < 7` → `accumulating`，仍回已有的排名）；`test_different_lists_detection_summaries_7d`；`test_search_by_name_and_ip`、`test_search_unknown_ip_gives_unmanaged_key`。
- [ ] **Step 2–4:** `timeout 600 python -m pytest tests/services/test_host_baseline.py tests/web/test_hosts_routes.py -q` → FAIL → 實作 → PASS；重產契約。
- [ ] **Step 5: 前端** 照樣本 04：主機標頭（名稱、標籤、IP、OS、VEN 版本、enforcement 模式、是否已隔離）、重點數字、「平常的樣子」三欄、「這次不一樣的地方」、隔離區（非受管或不在清冊：不顯示按鈕，顯示原因；`no_enforcement`：可套用但標「不會生效」；文字只寫套哪個標籤、原標籤、enforcement 模式；說明「實際擋掉什麼取決於 PCE 的 Quarantine 規則集」）。導覽「主機」顯示（不再 hidden）：沒有 `key` 時是搜尋框＋結果清單。解除隔離為紅框按鈕。
- [ ] **Step 6: e2e**：`test_host_search_then_open`、`test_unmanaged_host_has_no_quarantine_button`、`test_not_in_inventory_no_button`、`test_idle_host_marked_no_effect`、`test_usual_basic_mode_explained`、`test_no_overflow_760`。
- [ ] **Step 7:** build ＋ `timeout 900 python -m pytest tests/e2e/test_hosts_e2e.py tests/e2e/test_quarantine_e2e.py -q` → PASS；gates.sh → ALL GREEN。
- [ ] **Step 8: Commit** `feat(v6-ui): host page — usual behaviour, what differs, managed-only quarantine, host search`。

### Task 6: 告警規則與通知（樣本 10）

**Files:**
- Create: `web/src/pages/alerts/RulesAndChannels.tsx`（分頁：規則／通知通道）；Modify: `Rules.tsx`、`RuleEditor.tsx`（成為右側詳情）、`web/src/pages/system/Channels.tsx`（成為分頁內容，移除獨立 nav）
- Modify: `illumio_ops/web/routes/alert_rules.py`、`illumio_ops/store/alerts.py`（計數）、`illumio_ops/services/alerts/`（規則測試）
- Test: `tests/web/test_alert_rules_routes.py`（加）、`tests/services/alerts/test_rule_test.py`、`tests/e2e/test_alerts_e2e.py`（規則部分）、`tests/e2e/test_channels_e2e.py`（改）

**Interfaces:**
- Produces：規則清單每列加 `triggers_7d: int`（`alerts` 依 `rule_id` 計數，目前 PCE，近 7 天）、`known_count: int`（該規則下已標為已知的數量）。
- Produces：operation `alert_rules.test` `POST /api/alert-rules/test` body `RuleTestRequest(source: Literal["alert","detection","event"], id: int)` → `RuleTestResult(matches: list[RuleMatch(rule_id, rule_name, would_alert: bool, reason_key: str | None, channels: list[str])])`。用既有 `domain/alerting.py` 的 `evaluate_*_rule` 對該筆事實逐條評估；**不寫入、不送出、不更新冷卻**；冷卻中的規則 `would_alert=false, reason_key="rule_test_cooldown"`。

- [ ] **Step 1: 失敗測試**：`test_triggers_7d_counts_per_rule`；`test_rule_test_lists_matching_rules_and_channels`；`test_rule_test_writes_nothing`（前後 `alerts`、`alert_rule_state`、`deliveries` 列數不變）；`test_rule_test_cooldown_reported`；`test_rule_test_excluded_by_exclude_filter`（命中排除條件 → `would_alert=false`、`reason_key="rule_test_excluded"`）。
- [ ] **Step 2–4:** `timeout 600 python -m pytest tests/web/test_alert_rules_routes.py tests/services/alerts/test_rule_test.py -q` → FAIL → 實作 → PASS；重產契約。
- [ ] **Step 5: 前端** 照樣本 10：註冊 `path: "/alert-rules"`（section `bottom`，`labelKey: "nav_alert_rules"`）；`/alerts/rules`、`/system/channels` 轉址（帶分頁參數）；規則分頁每列：通知（送出／只記錄）、類型、名稱與狀態（冷卻中、累積中）、條件、排除、7 天觸發次數；右側詳情＝規則編輯器（偵測器、最低嚴重度、排除條件、通知與冷卻、已標為已知數）；「規則測試」：選最近 20 筆告警／偵測／事件之一 → 顯示命中結果；通知通道分頁＝原 Channels 內容。
- [ ] **Step 6: e2e**：`test_rules_tab_columns`、`test_rule_test_shows_matches`、`test_channels_tab`、`test_old_urls_redirect`、`test_no_overflow_760`。
- [ ] **Step 7:** build ＋ `timeout 900 python -m pytest tests/e2e/test_alerts_e2e.py tests/e2e/test_channels_e2e.py -q` → PASS；gates.sh → ALL GREEN。
- [ ] **Step 8: Commit** `feat(v6-ui): alert rules and channels on one page, 7-day triggers, rule test`。

### Task 7: SIEM（樣本 09）、系統次層選單與模式頁（樣本 11）、基本模式呈現（樣本 06）

**Files:**
- Modify: `web/src/pages/siem/Siem.tsx`、`Dlq.tsx`
- Create: `web/src/pages/system/SystemLayout.tsx`（次層選單）；Modify: `web/src/pages/system/Collection.tsx`（成為「模式與資料來源」）及其他 system 頁（改註冊到 `section: "system"` 次層，主導覽只留一個「系統」）
- Modify: `illumio_ops/web/routes/system_collection.py`（資料狀態與磁碟分段）
- Test: `tests/web/test_system_collection.py`（加）、`tests/e2e/test_siem_e2e.py`、`tests/e2e/test_collection_e2e.py`（改）、`tests/e2e/test_basic_mode_e2e.py`（新）

**Interfaces:**
- Produces：`CollectionView.data_status: DataStatus(events_latest: datetime|None, flows_latest: datetime|None, baseline_days: int|None, baseline_target_days: int, live_hours_days: int|None, gaps: list[Gap(start, end, kind)])`、`CollectionView.disk: list[DiskPart(name: Literal["flows","archive","app","reports"], bytes: int)]`（各自量測檔案大小；量不到的部分不列並寫原因）。
- 系統次層選單項目與順序（UI 規格 §3）：模式與資料來源、PCE 連線、橫向移動設定、背景工作、TLS、帳號與安全、日誌、顯示、報表設定（計畫 C 會移走）。

- [ ] **Step 1: 失敗測試**：`test_data_status_lightweight_has_no_flows`（`flows_latest=None`，`baseline_days=None`）；`test_data_status_gaps_listed`；`test_disk_parts_sum_files`。
- [ ] **Step 2–4:** `timeout 600 python -m pytest tests/web/test_system_collection.py -q` → FAIL → 實作 → PASS；重產契約。
- [ ] **Step 5: 前端。** SIEM 照樣本 09：每個目的地一張卡（狀態、端點、四種來源各送到哪個時間、24 小時送出、積壓、DLQ、最後錯誤、送測試訊息）、CEF 樣本與東西向分析指引（既有內容）。基本模式下新連線與偵測事件兩種來源寫「需要進階模式」。模式頁照樣本 11：兩種模式並列（能做什麼、資源需求、目前模式標示；進階模式內可選「告警」或「完整」）、資料狀態、磁碟分段。基本模式首頁（樣本 06）：告警頁上方一個虛線框（只出現在 lightweight），說明進階模式才有的三類功能與資源需求，連「系統 › 模式與資料來源」；告警類型篩選只留事件與系統。
- [ ] **Step 6: e2e** `test_basic_mode_e2e.py`：lightweight 設定下走過告警、偵測、調查、主機、SIEM、模式頁，每頁斷言「需要進階模式」說明出現、沒有空表格（`table tbody` 有列或有原因字）、沒有數字 0 代表未計算（抽查數字列的 `data-reason` 屬性）。另 `test_siem_cards`、`test_system_subnav_order`、`test_no_overflow_760`（SIEM、模式頁）。
- [ ] **Step 7:** build ＋ `timeout 1200 python -m pytest tests/e2e -q` → PASS（整個 e2e 目錄，因為所有 system 頁的註冊都動過）；gates.sh → ALL GREEN。
- [ ] **Step 8: Commit** `feat(v6-ui): SIEM cards, system sub-navigation, modes and data sources, basic-mode presentation`。

### Task 8: 真資料驗收（.106 lab、.135 NFR）

**Files:**
- Create: `tmp/v6-ui-a-verification/shots.py`（Playwright：登入、逐頁 1280 與 760、zh_TW 與 en 截圖、掃 DOM 文字找 `{`、`}`、鍵名樣式、量水平溢出）、`tmp/v6-ui-a-verification/report.md`
- 部署腳本沿用 `tmp/v6-anomaly2-verification/deploy106.sh`、`deploy135.sh` 的做法（離線安裝包、部署前備份到 `/root/v6-backup/<時間>-ui-a`）

- [ ] **Step 1:** 合併前在本機以 `tests/e2e` 的 fake PCE 跑 `shots.py`，修完所有溢出與未翻譯鍵。
- [ ] **Step 2:** 依「v6 push main 長期授權」：gates.sh 全綠 → 合併到 main（fast-forward）→ `git push origin main`（單獨一行）→ `gh run watch` 盯 CI。
- [ ] **Step 3:** 部署 .106 與 .135（各先備份）；兩台跑 `shots.py`（.135 為 lightweight 以外的模式時，另用設定切換在 .106 驗基本模式後切回，並寫進報告）。
- [ ] **Step 4:** 逐張截圖親看：資訊順序與樣本一致、每句文字對得到資料（抽查告警詳情的「原廠查不到的」、主機「這次不一樣的地方」、偵測器狀態原因）。結果寫進 `report.md`。
- [ ] **Step 5:** 帳本記錄驗收結果；更新記憶 `v6-rebuild-decided.md`。
