# v6 P6c 橫向移動頁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `/lateral` 橫向移動頁：暴露面（現在／全部強制後、重要資產的路徑與切斷點、可觸及排名、樞紐、app／env 彙總、跨環境、落腳點）、正在發生（偵測器狀態與近 7 天偵測）、deny rule 試算；輕量模式按需向 PCE 只拉管理 port 算一次；首頁關注清單的 lateral 項目改連到這頁。

**Architecture:** 完整／告警模式讀每小時算好的 `analysis_results`（kind `exposure`），請求時不重算，只補名稱。輕量模式由頁面按鈕觸發：`ondemand.pull_period` 只拉圖用的管理 port（推給 PCE 的 filter），在暫存庫上用同一套 `exposure` 計算，結果與圖的邊在記憶體保留 30 分鐘（同工作台）。彙總檢視在每小時計算時用 `domain.exposure.collapse` 算好存進結果（不存逐條邊）。試算沿用 `services/analysis/deny_sim.simulate_deny`，補路由與畫面；輕量模式另拉「符合提案」的流量計數，圖的變化用保留的邊。

**Tech Stack:** Python 3.12、Flask、pydantic 2、SQLite、React/TS/Vite、Playwright。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md` §6.5.1（橫向移動）、§6.4 輕量模式表（暴露面：按需查詢後在記憶體算一次，只取管理 port；試算：按需）、§6.5.4（關注清單）、§6.5.6（落腳點）。畫面草稿 `focus-lateral.html`（§12）。

## Global Constraints

- 每個 operation 要有前端呼叫者，API 與 GUI 同一個 commit。
- 流量表只能經 `services/flowsource.py` 讀（`test_single_reader`）。
- 新讀取者先 `require_same_pce`；`BindingMismatch`／`StaleGeneration` → 409 `pce_switched`。
- 中文用字照 PCE 主控台（Label、Allowed／Potentially Blocked／Blocked、Full／Selective）；zh 不可出現小寫 label／service／workloads／allow／full／selective（`tests_v6/i18n/test_terminology.py`）。新鍵 en／zh_TW 都要有；不用動態鍵，用字面對照表。
- 畫面不顯示 href：主機一律以清冊 hostname／name、或流量裡的位址命名（P6b lab 教訓）。
- 失敗、未算過、過期、截斷、能力不支援都要寫明，不得顯示成空或 0（反目標 1）。
- 不寫 PCE：試算只輸出清單與建議。隔離（P6d）不放任何按鈕或反灰入口。
- 規模：1,000 台；長清單先列前 N 再展開。

## Review Focus

1. 未設定重要資產——資產、路徑、切斷點段落寫「尚未設定重要資產」並連 `/system/lateral`，不是空表；可觸及排名照常。
2. 輕量模式——偵測段寫「需要告警或完整模式」連 `/system/collection`；暴露面未計算時給「從 PCE 計算」按鈕，算完寫明讀了哪段、幾列、是否截斷，且說明期間與完整模式的觀察期間不同。
3. 存的暴露面結果是 P6c 之前算的（沒有 `groups`）——彙總檢視寫「下次計算後才有」，頁面其餘照常，不可 500。
4. 試算提案來源、目的、服務都空（等於「擋全部」）→ 400；node 型切斷點只算「進入該主機」的流量，畫面要說明。
5. 勒索能力 `UNSUPPORTED` → 落腳點段寫「此 PCE 版本不提供」；暴露面 `limits_hit`（assets／cross_env／groups）與 `unknown_edges` 都要揭露。

---

### Task 1: 暴露面讀取模型、輕量計算、試算路由

**Files:**
- Modify: `illumio_ops/domain/exposure.py`（`ExposureResult.groups: dict[str, GroupGraph] = {}`；`compute_exposure(..., group_of: Mapping[str, Mapping[str, str | None]] = {}, max_group_edges: int = 2000)`，每個 label key 一張 `collapse`，超過上限截斷並加 `limits_hit` 項 `groups:<key>`）
- Modify: `illumio_ops/services/analysis/exposure.py`（拆出 `graph_edges(ctx, lc, since) -> list[EdgeIn]` 與 `exposure_from(ctx, lc, edges, *, since, now) -> ExposureResult`；`run_exposure` 改用兩者，行為不變；`group_of` 用 `app` 與 `lat.environment_label_key` 兩個 key）
- Modify: `illumio_ops/services/analysis/deny_sim.py`（`simulate_deny(ctx, proposal, *, now=None, sample=200, window: tuple[datetime, datetime] | None = None, edges: Sequence[EdgeIn] | None = None)`：給了 `edges` 就不讀 `baseline_edges`；給了 `window` 就用它）
- Modify: `illumio_ops/domain/deny.py`（`DenyProposal` 驗證：src、dst 皆空且 ports 空 → ValueError）
- Create: `illumio_ops/services/lateral_view.py`
- Modify: `illumio_ops/services/hosts.py`（抽出 `display_names(ctx, keys) -> dict[str, str]`：清冊 hostname/name → 流量位址 → `ip:` 去前綴；`home._named` 與本頁共用）
- Create: `illumio_ops/web/routes/lateral.py`（在 `web/app.py` 註冊）
- Test: `tests_v6/domain/test_exposure.py`（補）、`tests_v6/services/test_lateral_view.py`、`tests_v6/services/test_deny_sim.py`（補）、`tests_v6/web/test_lateral_routes.py`

**Interfaces:**
- Produces（`services/lateral_view.py`）：
  - `LateralView{state: Literal["ok","not_computed","collection_off","lightweight"], source: Literal["stored","pulled"] | None, computed_at: datetime | None, stale: bool, exposure: ExposureResult | None, names: dict[str,str], pull: PullInfo | None, critical_set: bool, admin_set: bool, ransomware_unsupported: bool, detections_available: bool, detectors: list[DetectorStatusView], detections: list[DetectionEntry], detections_total: int, observation_days_setting: int, lightweight_days: list[int]}`
  - `DetectionEntry{detector: DetectorKind, severity: str, subject: str, subject_name: str, critical_asset: bool, first_seen: datetime, last_seen: datetime, title_key: str, params: dict[str, Any], link_q: str | None}`（`title_key` 取 `domain.focus.DETECTION_TITLE_KEYS`；`link_q` 是 `workbench.request_for("flow", segment)` 的 JSON，超過 30 天或格式不符為 None）
  - `view(ctx, *, now=None) -> LateralView`；`compute(ctx, days: int, *, now=None) -> LateralView`（只在輕量模式；其他模式 ValueError）；`simulate(ctx, proposal: DenyProposal, *, now=None) -> DenySimulation`
  - `KEEP = timedelta(minutes=30)`；`LIGHTWEIGHT_DAYS = (1, 7, 30)`（大於 `observation_days` 的不列）
  - `class NotComputed(Exception)`（輕量模式沒有保留的結果時試算用）
- Operations：`lateral.view` GET `/api/lateral` → LateralView；`lateral.compute` POST `/api/lateral/compute` `{days}` → LateralView；`lateral.simulate` POST `/api/lateral/simulate` `{proposal: DenyProposal}` → DenySimulation。
- 錯誤對應：ValueError／ValidationError → 400（不回顯輸入）；StaleGeneration／BindingMismatch → 409 `pce_switched`（`lat_pce_switched`）；NotComputed → 409 `not_computed`；OnDemandFailed → 502 `pull_failed`（訊息截 300 字，同工作台）。

規則（實作與測試照此）：
- `view`：先 `require_same_pce`。非輕量：讀存的 exposure；`analysis.get_run(conn,"exposure")` 狀態為 `collection_off` → state `collection_off`；無結果 → `not_computed`；`computed_at` 早於 now − `focus.STALE_AFTER` → `stale=True`。輕量：有保留且 key 相符 → `source="pulled"`，否則 state `lightweight`、exposure None。
- 保留結果的 key：（PCE url＋org、days、settings revision）；任一不同視為沒有（設定改了要重算）。一次只保留一份；拉取用一把鎖序列化，簿記鎖不在 PCE 回應期間持有（同 `workbench_store`）。
- 輕量拉取的 filter：`FilterSpec(start, end, ports=…)`，ports 取 `lc.admin_ports.entries` 中類別屬 `GRAPH_CLASSES` 者，`PortProto(port=e.port, proto=e.proto)`；期間 `[now − days, now]` 取整點（同工作台）；`pull_period` 內呼叫 `graph_edges`＋`exposure_from`，保留結果、邊、`PullInfo`。
- `names`：exposure 裡出現的每個主機 key（hosts、assets、paths、cuts、cross_env、footholds）＋偵測主體，經 `display_names`。
- 偵測：只在 `lc.collected` 時讀 `analysis.detections_ranked(conn, now − 7d, limit=50)`；否則 `detections_available=False`、清單空。
- `simulate`：先驗證提案；非輕量 → `simulate_deny(ctx, proposal, now=now)`；輕量 → 沒有保留結果時 `NotComputed`，否則 `pull_period(ctx, start, end, spec=proposal_filter(proposal, start, end))` 後 `simulate_deny(res.ctx, proposal, now=now, window=保留的期間, edges=保留的邊)`。

- [ ] **測試先寫（應全部紅）**：
  - `test_exposure.py`：`test_groups_collapsed_by_label`（兩個 app、一條跨 app 邊 → `groups["app"].edges` 有該組計數與最強狀態）、`test_group_edges_capped`（`max_group_edges=1` → `limits_hit` 含 `groups:app`）、`test_result_without_groups_loads`（舊 JSON 沒有 `groups` 仍可 `model_validate`）。
  - `test_deny_sim.py`：`test_all_empty_proposal_refused`、`test_given_edges_used`（給 `edges` 時 `baseline_edges` 不被呼叫，reach_change 依給的邊）。
  - `test_lateral_view.py`：`test_not_computed`、`test_collection_off`、`test_stale_after_two_hours`、`test_names_never_hrefs`（結果裡的 href 都換成 hostname；沒清冊名稱的用流量位址）、`test_detections_only_when_collected`、`test_ransomware_unsupported_flag`、`test_previous_pce_refused`（`BindingMismatch`）、`test_lightweight_compute_pulls_admin_ports_only`（fake `pull_period` 收到的 spec 只有 GRAPH_CLASSES 的 port）、`test_lightweight_held_then_expired`（KEEP 後 state 回 `lightweight`）、`test_lightweight_settings_change_drops_held`、`test_simulate_lightweight_needs_compute`（NotComputed）、`test_simulate_lightweight_uses_held_edges`、`test_compute_refused_outside_lightweight`。
  - `test_lateral_routes.py`：三個 operation 的 200、400（全空提案、days 不在選項）、409（BindingMismatch、NotComputed）、502（OnDemandFailed）。
- [ ] 執行：`timeout 900 python3 -m pytest tests_v6/domain/test_exposure.py tests_v6/services/test_lateral_view.py tests_v6/services/test_deny_sim.py tests_v6/web/test_lateral_routes.py -q` → Expected: 新測試 FAIL（名稱不存在／斷言失敗）。
- [ ] 實作上述檔案；`home._named` 改用 `display_names`（`tests_v6/services/test_home.py` 照過）。
- [ ] 同一指令再跑 → Expected: 全 PASS；`timeout 900 python3 -m pytest tests_v6/services/test_home.py tests_v6/services/test_hosts.py tests_v6/services/analysis -q` → PASS。
- [ ] 前端呼叫者在 Task 2，本 task 不單獨 commit。

### Task 2: `/lateral` 頁、試算面板、關注清單改接

**Files:**
- Create: `web/src/pages/lateral/LateralMovement.tsx`（`registerNav({section:"main", path:"/lateral", labelKey:"nav_lateral", order: 14})`，在 `main.tsx` import）
- Create: `web/src/pages/lateral/Simulation.tsx`（試算面板）
- Modify: `illumio_ops/services/home.py`（`_link`）、`web/src/pages/hosts/HostProfile.tsx`（暴露段加「在橫向移動頁看」連結）、`web/src/styles/base.css`、i18n en／zh_TW（前綴 `lat_`，避開既有 `nav_system_lateral`／設定頁鍵）
- Test: `tests_v6/services/test_home.py`（改 `test_focus_links`）、`tests_v6/e2e/test_lateral_e2e.py`

**Interfaces:**
- Consumes: Task 1 的三個 operation 與 `LateralView`／`DenySimulation`。
- 關注清單連結（`_link`）：`exposure_asset` → `/lateral?asset=<key>`；`pivot_host` → `/lateral?host=<key>`；`cross_env` → `/lateral?section=cross_env`；`vendor_contradiction` → `/lateral?section=footholds`；其他 `target="lateral"` 無 host_key → `/lateral`。

頁面段落（由上而下）：
1. 狀態列：計算時間、觀察期間、跳數；`stale`／`not_computed`（連 `/system/jobs`）／`collection_off`（連 `/system/collection`）／輕量（期間選單 1／7／30 天中不超過設定的，預設 7，按鈕「從 PCE 計算」，算完以工作台的 `Pulled` 顯示讀取資訊，並寫「期間是本次選的 N 天，不是設定的觀察期間 M 天」）；`unknown_edges`、`limits_hit` 逐項說明。
2. 現在 vs 全部強制後：連線數、可被觸及的重要資產數、樞紐數，兩欄並排（草稿 `.cmp`）。
3. 重要資產：未設定 → 引導連 `/system/lateral`；否則資產選單（`?asset=` 預選，預設第一個），顯示現在／強制後來源數、最短路徑圖（SVG，依跳數分層、路徑上的邊標 port 名稱）與文字路徑、切斷點（「只切 A → B 的 RDP，可觸及 X 的主機從 41 降到 9」；node 型寫「隔開主機 A」）每項一顆「試算」。
4. 可觸及排名：前 20、`lat-more` 展開；欄位名稱（連 `/hosts?key=`）、現在、強制後、樞紐標記；`?host=` 時該列醒目並捲到。
5. 樞紐主機：`pivot_now` 者，標示強制後是否仍是樞紐。
6. 彙總檢視：app／env 切換，矩陣（列＝來源組、欄＝目的組、格＝主機連線數，顏色依最強狀態；組數超過 30 先列連線最多的 30 組並寫明）；結果沒有 `groups` → 「下次計算後才有」。
7. 跨環境：表格（來源、目的、兩端 env、port、狀態），每列「試算」（該主機對、該 port 的 edge 提案）；`cross_env_total` 大於列數時寫明。
8. 落腳點：主機、服務 port、嚴重度；`ransomware_unsupported` → 版本說明。
9. 正在發生：偵測器狀態（停用原因、基準期累積中）＋近 7 天偵測（嚴重度、標題、主體、首末見、「在工作台開啟」）；`detections_total` 大於列數時寫明；輕量 → 「需要告警或完整模式」連 `/system/collection`。

試算面板：提案用文字寫出（來源、目的、服務；以名稱而非 href）、會擋下的連線數與 flow 數、來源／目的前 50、每個重要資產可觸及來源數的前後變化、明細樣本（200 筆）＋「匯出 CSV」（前端產生，欄位：來源、目的、port、協定、決策、連線數、首末見）；`limit_hit`、`coverage` 缺口照工作台的 `Caveats` 揭露；node 型提案註明「只算進入該主機的流量」；輕量模式時另顯示這次拉取的 `Pulled`。

- [ ] **測試先寫**：`test_home.py::test_focus_links` 改為上述 lateral 對應（先紅）；`test_lateral_e2e.py`：`test_exposure_sections`（種存的 exposure＋清冊名稱：狀態列、現在／強制後、路徑、切斷點、排名前 20 與展開、頁面文字不含 `/orgs/`）、`test_critical_not_set_guides`、`test_lightweight_detections_need_mode`、`test_old_result_without_groups`、`test_simulate_from_cut`（點切斷點的試算，面板出現數字與 CSV 按鈕）、`test_focus_asset_link_preselects`（`/lateral?asset=` 預選該資產）。
- [ ] 執行：`timeout 900 python3 -m pytest tests_v6/services/test_home.py tests_v6/e2e/test_lateral_e2e.py -q` → Expected: FAIL。
- [ ] 實作頁面、面板、`_link`、HostProfile 連結、i18n、CSS。
- [ ] 同指令 → PASS；跑閘門 `.superpowers/sdd/2026-10-30-v6-phase6c-lateral/gates.sh`（複製 P6b 的）→ 全綠（contracts 有變就 `git add web/src/api/contracts.json web/src/api/generated.ts` 再跑）。
- [ ] 與 Task 1 一起 commit：`feat(v6): lateral movement page — exposure, paths, cuts, deny rule simulation`。

### Task 3: lab 驗收、最終審查、合併

- [ ] .106 lab（經 SSH 通道、另開 web-only 行程，不動正在跑的服務；腳本放 `tmp/v6-p6c-verification/`，`PYTHONPATH=$PWD`）：完整安裝根目錄的 `/lateral` 各段有資料且無 href；首頁 lateral 項目點進來預選資產／主機；對一個切斷點試算，數字與工作台同條件（Potentially Blocked＋Allowed、該主機對與 port）對得上；輕量根目錄按「從 PCE 計算」7 天，記錄耗時與列數，再試算一次。
- [ ] lab 抓到的問題逐項先寫會紅的測試再修。
- [ ] Codex 最終審查（prompt 開頭「TASK: code review only…」，附 plan、Review Focus 與 ledger 的 Ruling），Important 以上一次修完，每項 RED→GREEN＋閘門全綠。
- [ ] 合併 main（`--no-ff`）、閘門全綠、`git push origin main` 單獨一行、盯 CI。

**不在本計畫**：隔離（P6d，入口在主機頁、工作台主機列、本頁樞紐）；手寫任意 deny 提案的編輯器（本頁只試算產品給的切斷點與跨環境連線）；暴露面趨勢（輕量模式沒有每日快照；完整模式的趨勢在橫向移動態勢報表）。
