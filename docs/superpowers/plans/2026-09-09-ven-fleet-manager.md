# VEN Fleet Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 VEN 車隊分析（版本／compat／進程管線／coverage gaps／health score）接進既有 ven_summary 排程、新 GUI 頁 `#/investigate/fleet` 與 VEN 狀態報表，並提供兩段式（preview→apply）批次推進 enforcement_mode。

**Architecture:** 一個純函式模組 `src/report/analysis/fleet.py` 產出 fleet dict；`run_ven_summary` 在既有那一次 `fetch_managed_workloads` 後呼叫它寫進 `dashboard_summary.json["fleet"]`；GUI 與報表都只讀這個 dict。寫入 PCE 只在 `POST /api/fleet/progress/apply`，走 `PUT /workloads/bulk_update`，逐筆結果落 `config/fleet_progressions.json`（含 previous_mode，可還原）。

**Tech Stack:** Python 3.12／Flask／APScheduler／pandas／openpyxl；前端 ES modules（`src/static/js/v2`）；Playwright e2e；pytest。

**Spec:** `docs/superpowers/specs/2026-09-09-ven-fleet-manager-design.md`

## Global Constraints

- 工作目錄是 worktree `.worktrees/ven-fleet-manager`、分支 `feat/ven-fleet-manager`；每個 task 開工先 `pwd` 與 `git branch --show-current` 驗證，錯了就停。
- 每個新 i18n 鍵同時進 `src/i18n_en.json` 與 `src/i18n_zh_TW.json`；GUI 鍵（`gui_` 前綴）另釘 `src/i18n/data/zh_explicit.json`。PCE 字面 `idle`／`visibility_only`／`selective`／`full`／`managed`／`unmanaged`／`VEN`／`PCE`／`enforcement` 依 glossary 保留英文。
- 禁止在 `.mjs` 行尾寫 CJK 註解。
- PCE 寫入只允許 `enforcement_mode` 一個欄位，只允許 idle→{visibility_only,selective,full}、visibility_only→{selective,full}、selective→{full}。
- 不新增第二次全量 workload 抓取；不引入 `/vens`；不做 time_in_mode。
- 每個 task 結束跑該 task 的測試檔（前景、`timeout 600`），提交只 `git add <明確路徑>`。
- 全套閘門（orchestrator 在 task 之間跑）：
  `timeout 900 python3 -m pytest -m "not slow" -x -q`、
  `python3 scripts/audit_i18n_usage.py`、
  `timeout 600 python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py tests/test_i18n_zh_explicit_sync.py -q`。

---

### Task 1: 分析模組 `analyze_fleet`

**Files:**
- Create: `src/report/analysis/fleet.py`
- Test: `tests/test_fleet_analysis.py`

**Interfaces:**
- Produces:
  ```python
  def parse_ven_version(s: str) -> tuple[int, ...] | None   # "26.2.20-2063" -> (26,2,20,2063); 無法解析 -> None
  def compat_state(agent_health: list[dict]) -> str          # "pass"|"warn"|"fail"|"unknown"
  def analyze_fleet(workloads: list[dict], now: datetime, target_version: str | None,
                    *, top_n: int = 50, index_cap: int = 20000) -> dict
  VALID_PROGRESSIONS = {"idle": {"visibility_only","selective","full"},
                        "visibility_only": {"selective","full"}, "selective": {"full"}}
  PIPELINE_BUCKETS = ("idle_compat_pass","idle_compat_warn","idle_compat_fail","idle_compat_unknown",
                      "visibility_ready","visibility_not_ready","selective","full")
  ```
- 回傳 dict 結構照 spec §2.2；每個 pipeline／agent_health／unlabeled bucket 為 `{"count": int, "sample": [...]}`，sample 最多 `top_n`；`workloads_index` 每筆 `{href, hostname, mode, online, version, compat, hslh, app, env, os}`，超過 `index_cap` 則 `workloads_index=[]`、`index_truncated=True`。
- online 判定：`agent.status.status` 小寫 ∈ {active, online} 且 `hours_since_last_heartbeat`（缺則由 `last_heartbeat_on` 算）≤ 1.0。heartbeat 分桶：fresh ≤24h、stale_24h (24,48]、stale_48h >48、no_heartbeat。
- health_score：權重 online .30／enforcement .25／version .20／heartbeat .15／compat .10；分量「不存在」的定義：version→target 為 None；heartbeat→fresh+stale 皆 0；compat→pass+warn+fail 皆 0；enforcement 與 online 在 total=0 時不存在。缺者剔除、其餘權重除以權重和；`partial` = 有任一分量缺；total=0 時 `score=None`。
- 版本：`versions.ordered` 依 `parse_ven_version` 降冪，None 者集中到 `unparsable` 且排最後；`target` 為 `target_version` 去空白後的字串或 None；`on_target` 為 `agent_version == target` 的數；`needs_upgrade` 在 target None 時為 None。
- agent_version 來源優先序：`agent.status.agent_version` → `ven.version` → `agent.config.agent_version` → ""。

**Constraints:** 純函式、不 import Flask／ApiClient；lab 實測 `agent_health` 為 `[]`、`agent_health_errors` 為 `{"errors":[],"warnings":[]}`，兩者都要能吃。

**Acceptance / Tests（TDD，先紅後綠）:**
- compat 四態各一例（含 type 大小寫混寫 `"Compatibility"`、severity `"err"`）。
- `parse_ven_version("26.2.20-2063")==(26,2,20,2063)`、`"23.4.11-8"`、`""`→None、`"dev"`→None；ordered 為 26.2.20 > 25.2.40 > 23.4.11、unparsable 在最後。
- target None → `needs_upgrade is None` 且 score `partial=True` 且 components.version.present False；權重重正規化後三分量全滿為 100。
- 21 台 fixture（1 idle、1 visibility_only、18 selective online、1 selective offline）：pipeline 計數與 `workloads_index` 長度一致；`top_n=2` 時 sample 長度 2 而 count 不變。
- `index_cap=5` 時 `index_truncated=True`、`workloads_index==[]`。
- unlabeled 判定：labels 為空。

Run: `timeout 600 python3 -m pytest tests/test_fleet_analysis.py -q`

Commit: `feat(fleet): pure fleet analysis (compat four-state, numeric versions, renormalised score)`

---

### Task 2: 排程寫入、設定鍵、唯讀 API

**Files:**
- Modify: `src/scheduler/jobs.py`（`run_ven_summary`，寫 summary 的同一個 `write_dashboard_summary` 呼叫）
- Modify: `src/gui/_helpers.py:177-179`（`_SETTINGS_ALLOWLISTS["settings"]` 加三鍵）
- Create: `src/gui/routes/fleet.py`（`make_fleet_blueprint(cm, csrf, limiter, login_required)`）
- Modify: `src/gui/__init__.py:503-504` 之後註冊 blueprint
- Test: `tests/test_ven_summary_job.py`（擴充）、`tests/test_gui_fleet_api.py`

**Interfaces:**
- Consumes: Task 1 `analyze_fleet`。
- 設定鍵（皆在 `config.json["settings"]`）：`fleet_target_ven_version: str`（預設 ""）、`fleet_max_batch: int`（預設 200，上限 1000）、`fleet_index_cap: int`（預設 20000）。讀法 `cm.config.get("settings", {}).get(...)`。
- `run_ven_summary`：成功時 `write_dashboard_summary(lambda d: {**d, "ven_summary": summary, "fleet": fleet})`，`fleet = analyze_fleet(workloads, now, target or None, top_n=50, index_cap=...)` 加 `"updated_at"`；失敗時比照 ven_summary 保留舊 `fleet` 並寫 `fleet.last_error`／`fleet.updated_at`，不得寫 0。
- Produces（GET，皆 `login_required`）：
  - `GET /api/fleet` → `{"ok": True, "available": bool, "fleet": <fleet 去掉 workloads_index>, "next_run_at": str|None}`；`available=False` 時 `fleet={}`。`next_run_at` 從 `logs/job_health.json` 的 `ven_summary` 條目取（`src/job_health` 讀法照 `#/system/jobs` 用的函式），拿不到給 None。
  - `GET /api/fleet/list?bucket=<PIPELINE_BUCKETS|agent_errors|agent_warnings|unlabeled|stale_24h|stale_48h|no_heartbeat>&offset=&limit=` → `{"ok", "bucket", "total", "rows": [...index 列...], "index_truncated"}`；limit 預設 100 上限 500；bucket 不合法 400。bucket 對 index 列的過濾規則寫成模組級 `BUCKET_PREDICATES: dict[str, Callable[[dict], bool]]`，Task 3 重用。

**Acceptance / Tests:**
- 擴充 `tests/test_ven_summary_job.py`：既有兩測不變；新增 fleet 鍵存在、`target` 取自 settings、PCE 例外時舊 `fleet` 保留且 `last_error` 出現。
- `tests/test_gui_fleet_api.py`（用 `tests/v2_e2e_utils.build_v2_app` 或既有 Flask test client fixture，登入後）：無快照回 `available=False`；有快照時 `workloads_index` 不在回應；list 分頁與非法 bucket 400。

Run: `timeout 600 python3 -m pytest tests/test_ven_summary_job.py tests/test_gui_fleet_api.py -q`

Commit: `feat(fleet): ven_summary job emits the fleet snapshot; read-only fleet API`

---

### Task 3: 批次推進（preview／apply／records）

**Files:**
- Modify: `src/api_client.py`（在 `set_flow_reporting_frequency` 附近新增方法）
- Create: `src/fleet_progress_store.py`
- Modify: `src/gui/routes/fleet.py`（Task 2 的 blueprint 加三個路由）
- Test: `tests/test_fleet_progress.py`

**Interfaces:**
- `ApiClient.bulk_update_workloads(items: list[dict], *, timeout: int = 30) -> list[dict]`
  - `PUT /api/v2/orgs/{org}/workloads/bulk_update`，body 為陣列 `[{"href":..., "enforcement_mode":...}]`，每 1000 筆一批，經 `self._request(..., method="PUT", rate_limit=True)`。
  - 回傳逐筆 `{"href", "status": "updated"|"error", "http": int, "errors": list}`；PCE 200 時解析 body 陣列（每項有 `href`、`status`、可選 `errors`），非 2xx 整批標 error 並帶 `http` 與 body 前 500 字；傳輸例外同上 `http=0`。
- `src/fleet_progress_store.py`：`class FleetProgressStore(db_path)`，複製 `src/rule_scheduler.py:168-265 ScheduleDB` 的鎖內重讀單筆寫入（`file_lock`＋mkstemp＋os.replace＋corrupt 隔離），介面 `put(record_id, record)`、`get(record_id)`、`recent(limit) -> list`（依 `at` 降冪）。預設路徑 `config/fleet_progressions.json`。record：
  `{"at", "user", "to_mode", "items": [{"href","hostname","previous_mode","new_mode","deferred","status","http","errors"}]}`。
- 路由（皆 `login_required`、CSRF 生效、`@limiter.limit("10 per minute")`）：
  - `POST /api/fleet/progress/preview` in `{to_mode, hrefs?: [...], bucket?: str}`（二擇一，皆缺或皆有→400）→ `{ok, to_mode, eligible:[{href,hostname,from,to}], deferred:[同], skipped:[{href,hostname,reason}], cap, truncated}`。
    eligibility 純函式 `classify_targets(index_rows, to_mode, cap) -> (eligible, deferred, skipped)`：reason ∈ `unknown_href`（不在 index）、`not_managed`（index 列 mode 缺或 workload 無 agent）、`already_target`、`invalid_transition`、`over_cap`；online False 且合法→deferred。eligible+deferred 依 hostname 排序後合計截到 cap，多的進 skipped(over_cap)。`href` 必須通過 `src/gui/_helpers._is_workload_href`。
  - `POST /api/fleet/progress/apply` in `{to_mode, hrefs: [...]}` → 伺服端重跑 `classify_targets`；任一 href 落 skipped→400 `{ok:False, skipped:[...]}`；否則呼叫 `bulk_update_workloads`，寫 store，`_audit_action("fleet_progress", to_mode=..., applied=n, failed=n, record_id=...)`（從 `src/gui/routes/actions.py:54-67` 抽成 `_helpers` 共用或直接 import），回 `{ok, applied:[{href,hostname,from,to,deferred}], failed:[{href,hostname,http,error}], record_id}`。
  - `GET /api/fleet/progress/records?limit=` → `{ok, records:[...]}`，limit 預設 20 上限 100。
- to_mode 不在 {visibility_only, selective, full} → 400。

**Acceptance / Tests（TDD）:**
- `classify_targets`：五種 reason 各一、offline→deferred、cap 截斷後 skipped(over_cap) 含被截者、hostname 排序。
- `bulk_update_workloads`：以 `patch.object(ApiClient, "_request")` 驗 1000 分批、body 只有 href+enforcement_mode、逐筆解析、非 2xx 整批 error。
- 路由：preview 二擇一驗證；apply 收到含 skipped 的 href 整批 400 且 `_request` 未被呼叫；成功時 store 檔出現 record 含 previous_mode；records 依時間降冪。
- 速率限制：第 11 次 preview 回 429（照 `tests/test_actions_rate_limit.py` 寫法）。

Run: `timeout 600 python3 -m pytest tests/test_fleet_progress.py tests/test_gui_fleet_api.py -q`

Commit: `feat(fleet): two-phase enforcement progression with a restorable record`

---

### Task 4: GUI 頁 `#/investigate/fleet`

**Files:**
- Create: `src/static/js/v2/areas/fleet.mjs`（`export async function mountFleet(el, ctx)`）
- Modify: `src/static/js/v2/app.mjs:142-148`（比照 workloads 註冊 `#/investigate/fleet`）
- Modify: `src/static/js/v2/shell.mjs:43-44`（investigate 子項加 `["#/investigate/fleet", "gui_nav_fleet"]`）
- Modify: `src/static/js/v2/core/store-map.mjs`（GET_MAP 加 `fleet: "/api/fleet"`、`fleet_list(params)`、`fleet_records: "/api/fleet/progress/records"`）
- Modify: `design/v2/tools/endpoints.yaml`（同三筆 GET，與 store-map 逐行對應，這是 `tests/test_v2_coverage_live.py` 的守門）
- Modify: `design/v3/coverage.yaml`（IV-16..IV-20，route `#/investigate/fleet`，anchor 為 `data-cov` 值）
- Modify: `src/static/js/v2/components/page.mjs:160-199`（`crumbsFor`／`labelForRoute` 認得新路由）
- Modify: `src/static/js/v2/areas/system.mjs`（`#/system/pce` 設定表單加 `settings.fleet_target_ven_version` 文字欄與 `fleet_max_batch` 數字欄，經既有 `POST /api/settings` 的 `settings` 區段送出）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`、`src/i18n/data/zh_explicit.json`
- Test: `tests/test_v2_fleet_e2e.py`

**Interfaces:**
- Consumes: `GET /api/fleet`、`/api/fleet/list`、`POST /api/fleet/progress/preview|apply`、`GET /api/fleet/progress/records`（Task 2／3 形狀）。
- 頁面結構（`pageHead` 一顆主按鈕「推進」）：
  - IV-16 `data-cov="IV-16"` 摘要卡列：health score（partial 時附「部分資料」chip 與缺分量名）、版本（target／on_target／needs_upgrade，target None 顯示「未設定目標版本」並連到 `#/system/pce`）、管線八格計數。
  - IV-17 `IV-17` bucket 清單：bucket 切換（chip 列）、`table.mjs` 表格（hostname／mode／online／version／compat／hslh／app／env）、分頁走 `fleet_list`、勾選列。
  - IV-18 `IV-18` 版本分布表（含 os_breakdown 展開）。
  - IV-19 `IV-19` coverage gaps（by_app／by_env 兩表＋unlabeled 計數）。
  - IV-20 `IV-20` 推進抽屜（`drawer.mjs`）：to_mode 選單、來源＝目前 bucket 或勾選名單、「預覽」→列 eligible／deferred（預設不勾）／skipped（reason 文案 i18n）、「套用 N 台」→結果與 record_id；底部「最近推進」讀 `fleet_records`。所有可變欄位用 `data-field`。
- 無快照（`available=False`）：`errorcard.mjs` 風格提示＋`next_run_at`；`fleet.last_error` 存在→頁首 `data-tone="warn"` 條。
- 新 i18n 鍵前綴 `gui_fleet_`（至少：nav、title、subtitle、score、partial、target_unset、buckets×8、cols×8、progress_btn、preview、apply、reason×5、deferred_note、no_snapshot、last_error）。

**Acceptance / Tests（Playwright，`pytest_plugins=["tests.v2_e2e_utils"]`，路由以 `page.route` stub 三個 GET 與兩個 POST）:**
- 冷載入 `#/investigate/fleet`：`[data-route="#/investigate/fleet"]` 出現、左導覽 investigate 展開且新項高亮、五個 `data-cov` anchor 都在 DOM。
- 無快照 stub：無數字「0」渲染，提示文案為 `gui_fleet_no_snapshot` 的真值（用 `_labels` 讀 catalogue）。
- 抽屜：預覽 stub 回 1 eligible／1 deferred／1 skipped，畫面三段各一列且 deferred 未勾；按套用送出的 body `hrefs` 只含 eligible。
- 注入測試：把 IV-20 anchor 拿掉跑一次 `tools/gate_coverage_live.py` 對應測試應紅，再放回。
- 全套：`timeout 900 python3 -m pytest tests/test_v2_fleet_e2e.py tests/test_v2_shell_e2e.py tests/test_i18n_js_key_refs.py -q`。

Commit: `feat(gui): the VEN fleet page and the progression drawer`

---

### Task 5: VEN 狀態報表擴充

**Files:**
- Modify: `src/report/ven_status_generator.py:118-176`（generate 內呼叫 `analyze_fleet(workloads, now, target)` 存 `results["fleet"]`）、`:522`（xlsx 加 sheet）
- Modify: `src/report/exporters/ven_html_exporter.py:287-289`（在 `_extra` 迴圈加 `self._fleet_sections()` 回傳的四個 ShellSection）
- Modify: `src/report/section_guidance.py:197-226` 附近（新增 `ven_fleet_pipeline`、`ven_fleet_compat`、`ven_fleet_score`、`ven_fleet_gaps` 四筆 SectionGuidance，`profile_visibility` 比照 `ven_offline`）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（`rpt_ven_fleet_*` 標題／intro／欄名、`rpt_guidance_ven_fleet_*` 四×四、`rpt_xlsx_sheet_ven_fleet_*`）
- Test: `tests/test_ven_report_fleet.py`

**Interfaces:**
- Consumes: Task 1 `analyze_fleet`；target 讀 `cm.config["settings"]["fleet_target_ven_version"]`。
- 四段落 id：`fleet-pipeline`、`fleet-compat`、`fleet-score`、`fleet-gaps`，用既有 `self._section(id_, title_key, count, content, intro_key, guidance_module_id)`。表格走 `_df_to_html`；欄名經 `COL_I18N`。
- 截斷規則（專案規則）：hostname、audit_event 欄以 CSS `word-break` 換行不省略；sample 表最多 50 列並在 intro 標「前 50／共 N」。
- xlsx：新增 sheet `Fleet Pipeline`（index 全量，不截）與 `Fleet Versions`。

**Acceptance / Tests:**
- `tests/test_ven_report_fleet.py`：以 fake api 產報表（en／zh），四個 section id 存在、TOC 有四項、guidance 四模組在 REGISTRY、partial score 文案出現、xlsx 兩 sheet 存在且列數＝index 長度。
- 既有 `tests/test_report_i18n_leakage.py`、`tests/test_render_layer_i18n.py`、`tests/test_i18n_glossary.py` 綠。
- 真機驗收（orchestrator 做）：對 lab 產 VEN 報表 en＋zh 各一份，Playwright 800／1280 兩寬度逐頁截圖看四段落無截斷溢出，結果附在回報。

Run: `timeout 600 python3 -m pytest tests/test_ven_report_fleet.py tests/test_report_i18n_leakage.py tests/test_render_layer_i18n.py tests/test_i18n_glossary.py -q`

Commit: `feat(reports): VEN status report grows fleet pipeline, compat, score and gaps chapters`

---

### Task 6: 文件、changelog、全套閘門

**Files:**
- Modify: `docs/reference/rest-api.md`（fleet 六個端點與 record 格式）
- Modify: `docs/guide/reports.md`（VEN 報表四新段落）、`docs/guide/gui-tour.md`（fleet 頁）若存在
- Modify: `CHANGELOG.md`（Unreleased 下 Added 三條：fleet 頁、批次推進、報表段落；Changed：settings 三鍵）
- Modify: `docs/superpowers/specs/2026-09-09-ven-fleet-manager-design.md`（狀態改「已實作」＋實作偏離註記）

**Acceptance:**
- `python3 -m pytest tests/test_docs_check*.py -q` 若存在（docs_check verified_against 防門）綠。
- 全套：`timeout 900 python3 -m pytest -m "not slow" -x -q`、`python3 scripts/audit_i18n_usage.py`、`timeout 600 python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py tests/test_i18n_zh_explicit_sync.py -q`、`timeout 900 python3 -m pytest tests/test_v2_coverage_live.py -q`（slow）。
- 逐條對照 spec §2.1 七項決定與 §5 合約，任何偏離寫進 spec 註記。

Commit: `docs(fleet): reference, guide and changelog for the VEN fleet manager`
