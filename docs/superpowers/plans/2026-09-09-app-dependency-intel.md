# App Dependency Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 由既有流量 DataFrame 建 `app|env` 依賴圖，提供 blast radius／SPOF／cycles／cross-env／change impact，接進 Security & Risk 報表新段落與 GUI 查詢頁 `#/investigate/dependencies`。

**Architecture:** 純函式圖層 `src/report/analysis/dependency_graph.py` 產 `DepGraph`；報表模組 `mod16_dependency_intel` 走 TRAFFIC_MODULES 註冊；GUI 後端 `POST /api/dependencies/query` 讀 pce_cache（`_make_cache_reader`→`read_flows_df`）不打 PCE。

**Tech Stack:** Python／pandas／Flask；ES modules；Playwright；pytest。

**Spec:** `docs/superpowers/specs/2026-09-09-app-dependency-intel-design.md`

## Global Constraints

- 從 main 開分支 `feat/app-dependency-intel`（fleet 合併後；spec 隨 fleet 分支進 main）；每 task 先驗 `pwd`／分支。
- 節點鍵正規化只用 `mod14_infrastructure._normalize_key_series` 的規則（lower/strip/空→"unlabeled"）。
- i18n 雙檔＋zh_explicit（gui_ 鍵）；報表欄名走 `src/report/exporters/report_i18n.py:409-423` STRINGS overlay 的 `rpt_col_*`。
- `.mjs` 不寫行尾 CJK 註解。
- 提交只 `git add <路徑>`；每 task 跑自己的測試檔（前景、`timeout 600`）。
- 全套閘門：`timeout 900 python3 -m pytest -m "not slow" -x -q`、`python3 scripts/audit_i18n_usage.py`、`timeout 600 python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py tests/test_i18n_zh_explicit_sync.py -q`。

---

### Task 1: 圖層 `dependency_graph.py`

**Files:**
- Create: `src/report/analysis/dependency_graph.py`
- Modify: `src/report/analysis/mod14_infrastructure.py:156`（改 import `is_prod_env`）
- Test: `tests/test_dependency_graph.py`、`tests/test_mod14_prod_pin.py`

**Interfaces（Produces）:**
```python
def is_prod_env(env: str) -> bool                       # {"prod","production","prd"}，其餘 False
def build_graph(df, *, workloads=None, include_unlabeled=False,
                exclude_decisions=("blocked",)) -> DepGraph
def blast_radius(g, key, max_depth=10) -> dict           # spec §2 形狀，含 truncated
def spof(g, *, min_consumers=2, max_workloads=1) -> list[dict]   # 每筆 {key, consumers:int, workload_count, approximate, services[:10], risk}
def cycles(g, *, limit=50) -> dict                       # {"cycles":[{"path":[keys], "length":int}], "truncated": bool}
def cross_env(g) -> list[dict]                           # {consumer, provider, direction:"nonprod_to_prod"|"prod_to_nonprod", severity:"critical"|"warning", connections, services[:5]}
def change_impact(g, targets: list[str]) -> dict         # {matched:[{target, key}], unmatched_targets:[...], affected: blast_radius 聯集, maintenance_window_risk}
STRENGTH_STRONG = 1000; STRENGTH_MODERATE = 100
```
- `DepGraph.nodes[key] = Node{app, env, workload_count|None, hostnames:set, ips:set, roles:set}`；`workloads` 給了才填 `workload_count`（用 `readiness_report._workload_app_env_key` 分組），否則 `None` 且 spof `approximate=True`（用 distinct managed provider hostname 數）。
- cycles 用迭代版 Johnson（或 Tarjan SCC＋每個 SCC 內 DFS 列簡單環），禁止遞迴。
- `risk`：consumers≥5 critical、≥3 high、else medium。
- change_impact 比對欄：`src_hostname`／`dst_hostname`／`src_ip`／`dst_ip`（大小寫不分）；`maintenance_window_risk` 依受影響 app 數 ≥10 critical／≥5 high／≥2 medium／low。

**Acceptance / Tests（TDD）:**
- `tests/test_mod14_prod_pin.py`：先在改 mod14 前用 fixture df 釘住 `infrastructure_scoring` 的 `top_apps[["app_env_key","infrastructure_score"]]` 輸出（存 JSON 到 `tests/fixtures/dependency/mod14_pin.json`），改 import 後相等。
- 六節點 fixture（含一個 prod←nonprod 邊、兩個環、一個單機 provider）：BFS 深度與 chain、SPOF 兩模式、cycles 兩個且 `limit=1` truncated、cross_env 方向／嚴重度、change_impact hostname 與 ip 各命中一個、`unmatched_targets`。
- `include_unlabeled` 兩態節點數差異；`exclude_decisions` 預設不含 potentially_blocked。

Run: `timeout 600 python3 -m pytest tests/test_dependency_graph.py tests/test_mod14_prod_pin.py -q`

Commit: `feat(analysis): app|env dependency graph — blast radius, SPOF, cycles, cross-env, change impact`

---

### Task 2: 報表模組 `mod16_dependency_intel`

**Files:**
- Create: `src/report/analysis/mod16_dependency_intel.py`
- Modify: `src/report/analysis/__init__.py:57-72`（新 adapter `_call_df_workloads` ＋ TRAFFIC_MODULES 一列，profiles 與 mod14 同 `_SEC_INV`）
- Modify: `src/report/report_generator.py:795-803`（把 `_workloads` 存 `self._workloads_cache`，adapter 從這裡拿；CSV 來源為 None）＋ `_run_modules :876`（adapter 需要 `self` 時傳 workloads）
- Modify: `src/report/exporters/html_exporter.py:797-860`（`_sec['dependency']`）、`:1793` 附近新增 `_mod16_html`、`:1989` 順序在 `infrastructure` 後
- Modify: `src/report/section_guidance.py:26`（`mod16_dependency_intel` 條目）、`src/report/exporters/report_i18n.py:409-423`（新 `rpt_col_*`）、`src/report/report_metadata.py`（若 `blast_radius` 已在 ATTACK_SECTION_KEYS 則不動）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（`rpt_dep_*`、`rpt_guidance_mod16_*` 四鍵、`rpt_tr_sec_dependency(_intro)`）
- Test: `tests/test_mod16_dependency_intel.py`、擴充 `tests/test_chart_spec_coverage.py`

**Interfaces:**
- `dependency_intel(df, workloads=None, top_n=25, *, lang="en") -> dict` 回 `{total_apps, total_edges, spof(DF), spof_approximate, cycles(DF), cycles_truncated, cross_env(DF), top_blast(DF), attack_posture_items, chart_spec}`；空 df 回 `chart_spec=None` 與空表（不回 `error`）。
- `attack_posture_items` 用 `analysis/attack_posture.make_posture_item(finding_kind="blast_radius", ...)`，最多 5 筆。
- HTML 四表列上限 25＋`_trunc_note`；chain 欄 `white-space: normal; word-break: break-word`。

**Acceptance / Tests:**
- `_run_pipeline(df, source="csv", traffic_report_profile="security_risk")` 後 HTML 含 `id="dependency"`；`network_inventory` profile 依 `tests/test_inventory_sections_trim.py` 期望（先讀該測試決定是否保留）。
- `test_chart_spec_coverage.py` 新 class 覆蓋非空／空 df；`test_chart_spec_lang.py` 風格驗 zh。
- `tests/test_section_guidance_keys.py`、`tests/test_i18n_strings_parity.py`、`tests/test_report_generators_format_parity.py` 綠。
- 真機驗收（orchestrator）：lab 30 天 cache 產 Security & Risk en＋zh，Playwright 800／1280 看四表無截斷。

Run: `timeout 900 python3 -m pytest tests/test_mod16_dependency_intel.py tests/test_chart_spec_coverage.py tests/test_chart_spec_lang.py tests/test_section_guidance_keys.py tests/test_inventory_sections_trim.py tests/test_i18n_strings_parity.py -q`

Commit: `feat(reports): dependency intelligence chapter in the Security & Risk report`

---

### Task 3: GUI 後端 `/api/dependencies/*`

**Files:**
- Create: `src/gui/routes/dependencies.py`（`make_dependencies_blueprint(cm, csrf, limiter, login_required)`）
- Modify: `src/gui/__init__.py:503-512` 註冊
- Test: `tests/test_gui_dependencies_api.py`

**Interfaces:**
- `GET /api/dependencies/nodes?days=30&include_unlabeled=0` → `{ok, coverage:"full"|"partial", covered_until, nodes:[{key, app, env, workload_count|null}]}`；cover_state `none` → `{ok:False, code:"cache_incomplete"}`；`count_flows` > `read_max_rows` → `{ok:False, code:"cache_too_large", count, cap}`。
- `POST /api/dependencies/query` `{mode:"blast"|"impact", target?:str, targets?:[str], days:7|14|30, include_unlabeled:bool}` → `{ok, coverage, result:<blast_radius|change_impact>, spof:[...], cross_env:[...]}`；`mode` 非法或 target 缺 → 400。
- 圖快取：模組級 `_GRAPH_CACHE[(days, include_unlabeled)] = (built_at, graph)`，5 分鐘；`threading.Lock` 保護。
- 讀取：`from src.main import _make_cache_reader`；`reader.read_flows_df(start, end)`；`apply_df_traffic_filters` 不套（本頁無 filter）。
- `@limiter.limit("30 per minute")` on query。

**Acceptance / Tests:**
- fake reader（monkeypatch `src.gui.routes.dependencies._make_cache_reader`）：none／partial／too_large 三路徑；blast 與 impact 形狀；快取命中不重讀（reader 呼叫次數）。

Run: `timeout 600 python3 -m pytest tests/test_gui_dependencies_api.py -q`

Commit: `feat(gui): dependency query API over the flow cache`

---

### Task 4: GUI 頁 `#/investigate/dependencies`

**Files:**
- Create: `src/static/js/v2/areas/dependencies.mjs`（`export async function mountDependencies(el, ctx)`）
- Modify: `src/static/js/v2/app.mjs:138-148`、`src/static/js/v2/shell.mjs:39-44`、`src/static/js/v2/components/page.mjs:160-199`
- Modify: `src/static/js/v2/core/store-map.mjs`（`dependency_nodes(params)`）、`design/v2/tools/endpoints.yaml`（GET 一筆＋POST 一筆）、`tests/test_v2_coverage_live.py:183`（entry 計數 +1）
- Modify: `design/v3/coverage.yaml`（IV-21 摘要卡、IV-22 目標輸入、IV-23 chain 表、IV-24 SPOF／cross-env 卡）
- Modify: `docs/guide/gui-tour.md`（新路由，`tests/test_docs_gui_tour_routes.py` 守門）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`、`src/i18n/data/zh_explicit.json`（`gui_dep_*`）
- Test: `tests/test_v2_dependencies_e2e.py`

**Interfaces:** Consumes Task 3 兩端點。`pageHead` 主按鈕「查詢」；`coverage:"partial"` 顯示 warn chip 帶 `covered_until`；`cache_incomplete` 用 errorcard；「在流量搜尋開啟」連到 `#/investigate/traffic?f=<encoded filters>`（filter 形狀照 `investigate.mjs:1369 trafficPayload` 反推，只帶 app／env）。

**Acceptance / Tests（stub 兩端點）:** route mount＋四 anchor；partial chip 文案為 catalogue 真值；blast 查詢後 chain 表列數＝stub；impact 模式 unmatched 列出；注入測試：移除 IV-23 anchor 應讓 live gate 測試紅。

Run: `timeout 900 python3 -m pytest tests/test_v2_dependencies_e2e.py tests/test_v2_shell_e2e.py tests/test_v2_coverage_live.py tests/test_docs_gui_tour_routes.py tests/test_i18n_js_key_refs.py -q`

Commit: `feat(gui): the dependency intelligence page`

---

### Task 5: 文件與全套閘門

**Files:** `docs/reference/rest-api.md`（兩端點＋總數對帳）、`docs/guide/reports.md`（新段落）、`CHANGELOG.md`、spec 狀態更新。

**Acceptance:** `python3 -m pytest tests/test_docs_check.py -q`；全套閘門；逐條對照 spec §2 表格與 §4 合約。

Commit: `docs(dependencies): reference, guide and changelog`
