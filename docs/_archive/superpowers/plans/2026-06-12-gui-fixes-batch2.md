# GUI 小修與調查批次 #2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清掉 2026-06-11 UI 實測檢視遺留的 9 個項目：Posture 空狀態 CTA、管線健康 ERROR 原因、Policy Resolver GUI 入口、規則排程頁兩個顯示 bug、VEN 版本分布、表頭截字、臨時產生報表 async 化、稽核報表無資料調查、dead code 清理。

**Architecture:** 全部是既有模式的延伸：Resolver 入口照抄 Policy Diff 路由模式；async 產生複用 report_scheduler 的 daemon-thread + state.json 模式；其餘為單點修正。兩個調查任務（T5 規則排程、T8 稽核資料源）內建探查指令與決策準則。

**Tech Stack:** Flask / vanilla JS（無建置步驟，JS 驗證用 `node --check`）/ pytest。i18n 雙檔同步 + glossary（zh_TW 保留 Policy/Port/Label/Workload 等英文，含複數形一致）。

**執行環境：** worktree（superpowers:using-git-worktrees 建立），worktree 內 `ln -sfn /home/harry/rd/illumio-ops/venv venv`。基線：`./venv/bin/python -m pytest tests/ -q` → 1740 passed, 5 skipped。

---

## 已驗證事實（plan 撰寫時 grounding）

| 事實 | 出處 |
|------|------|
| Posture 空狀態由 `_renderRiskFeed` 渲染，key `gui_ov_posture_unavailable` | dashboard.js:1406-1413 |
| `openReportGenModal('traffic')` 是全域函式，可從總覽頁呼叫 | dashboard.js:638 |
| `/api/dashboard/overview` 的 `pipeline` 已含 `cache_lag[]{source,lag_s,level}` / `siem_success_1h` / `dlq` / `verdict`；verdict 規則在 pce_cache/health.py:5-12（lag error 或 SIEM<95% 或 DLQ≥80% cap） | dashboard.py:314、health.py |
| `PolicyResolverReport(cm, api_client, config_dir, cache_reader)`，`run(output_dir, lang, fmt="all") -> list[str]`（注意：回傳 **list**，與 PolicyDiff 的單一 str 不同） | policy_resolver_report.py:117-158 |
| 鏡像對象 `/api/policy_diff_report/generate` | gui/routes/reports.py:325-369 |
| `/api/rule_scheduler/status` 只回 `check_interval_seconds` + `schedule_count`，無 timeline、無 next-trigger | rule_scheduler.py:37-46 |
| `/api/rule_scheduler/schedules` 回 type/days/start/end/timezone/expire_at | rule_scheduler.py:196-229 |
| VEN 報表已抽出 `ven_version`（`st.get('agent_version','')`）；by_family/by_mode 分布建構在 `_analyze()` | ven_status_generator.py:243、117-118、257-401 |
| 「POLICY 判」截字：index.html:913 `<th data-i18n="gui_policy_dec" style="width:80px">` | index.html:913 |
| 排程「立即執行」async 模式：daemon thread + `_save_state` 寫 state.json + 前端 3 秒輪詢 `/api/report-schedules` | report_scheduler.py:200-360、reports.py:565-574、dashboard.js |
| 稽核報表 `_fetch_events` 無事件類型過濾；實測 CLI log 顯示「events from cache」後回「沒有 Audit 事件記錄」，而 cache 延遲 1004h —— **主要嫌疑：cache 啟用時 audit 走過期 cache，事件頁走 live PCE** | audit_generator.py:434-472、2026-06-11 實測 log |
| `render_plotly_html`/`FirstChartTracker` 已無 production caller；orphaned i18n keys：rpt_tr_sec_allowed、rpt_tr_sec_allowed_intro、rpt_tr_nav_allowed、rpt_tr_allowed_flows_subnote | 2026-06-12 最終審查 |

## 檔案結構

```
src/static/js/dashboard.js            # T1 CTA、T7 async 輪詢
src/static/js/integrations.js         # T2 ERROR 原因
src/gui/routes/reports.py             # T3 resolver 路由、T7 async 端點
src/gui/routes/rule_scheduler.py      # T5 next_trigger / timeline 資料
src/static/js/rule-scheduler.js       # T5 顯示
src/report/ven_status_generator.py    # T4 by_version
src/report/exporters/ven_html_exporter.py  # T4 區段
src/templates/index.html              # T1 按鈕、T3 卡片、T6 表頭
src/report/audit_generator.py         # T8 cache fallback
src/report/exporters/chart_renderer.py # T9 清理
src/i18n_en.json, src/i18n_zh_TW.json # T1/T2/T3/T4 新 key、T9 移除 orphan
tests/test_gui_policy_resolver_generate.py / test_ven_version_distribution.py /
tests/test_reports_async_generate.py / test_audit_cache_fallback.py  # 新測試
```

---

### Task 1: Posture 空狀態 CTA

**Files:** Modify `src/static/js/dashboard.js:1406-1413`、`src/i18n_en.json`、`src/i18n_zh_TW.json`

- [ ] **Step 1:** `_renderRiskFeed` 的 unavailable 分支（dashboard.js:1406-1413）在提示文字後加按鈕：

```javascript
      + '<button class="btn btn-primary btn-sm" data-action="openReportGenModal" data-args=\'["traffic"]\'>'
      + T('gui_ov_posture_run_now', 'Generate now') + '</button>'
```

（確認該檔空狀態 HTML 的組裝方式 — 若用 DOM API 而非字串模板，改用同檔既有的按鈕建構 idiom；`data-action` 經 `_event_dispatcher.js` 派發，與報表卡產生按鈕同機制 — 先 grep `data-action="openReportGenModal"` 確認 dispatcher 對動態插入節點有效（事件委派在 document 層則有效），否則改 `onclick`。）

- [ ] **Step 2:** i18n 兩檔加 `"gui_ov_posture_run_now": "Generate now"` / `"gui_ov_posture_run_now": "立即產生"`（字母序）。
- [ ] **Step 3:** `node --check src/static/js/dashboard.js`；`./venv/bin/python scripts/audit_i18n_usage.py` → 0 findings。
- [ ] **Step 4:** Commit `feat(gui): posture empty-state CTA opens the traffic report modal`

### Task 2: 管線健康 ERROR 顯示原因

整合頁總覽的「管線健康 ERROR」大字 banner 無原因說明。`/api/dashboard/overview` 的 `pipeline` payload 已含全部所需資料（cache_lag 含 per-source level、siem_success_1h、dlq）。

**Files:** Modify `src/static/js/integrations.js`、i18n 兩檔

- [ ] **Step 1:** 定位 banner：`grep -n "管線健康\|pipeline" src/static/js/integrations.js src/templates/index.html | head`，找出渲染 ERROR 字樣的函式與它取用的資料來源（若它目前只拿 verdict 字串，改為同時取 pipeline 物件 — 該物件已由 `/api/dashboard/overview` 提供；若整合頁用不同端點，沿用該端點並確認含同欄位，否則改呼叫 overview）。
- [ ] **Step 2:** banner 下加原因行，規則對齊 health.py 的 verdict 邏輯：

```javascript
function pipelineReasons(p, T) {
  const out = [];
  (p.cache_lag || []).forEach(l => {
    if (l.level === 'error' || l.level === 'warn') {
      out.push(T('gui_pl_reason_lag', 'Cache lag ({source}): {hours}h')
        .replace('{source}', l.source).replace('{hours}', Math.round(l.lag_s / 3600)));
    }
  });
  if (p.siem_success_1h != null && p.siem_success_1h < 95) {
    out.push(T('gui_pl_reason_siem', 'SIEM 1h success {pct}%').replace('{pct}', p.siem_success_1h));
  }
  if (p.dlq > 0) out.push(T('gui_pl_reason_dlq', 'DLQ backlog {n}').replace('{n}', p.dlq));
  return out;
}
```

渲染為 banner 下的小字列表（沿用整合頁既有的 muted-text class）。
- [ ] **Step 3:** i18n 兩檔（en/zh）：`gui_pl_reason_lag`: "Cache lag ({source}): {hours}h" / "快取延遲（{source}）：{hours} 小時"；`gui_pl_reason_siem`: "SIEM 1h success {pct}%" / "SIEM 近 1 小時成功率 {pct}%"；`gui_pl_reason_dlq`: "DLQ backlog {n}" / "DLQ 積壓 {n} 筆"。
- [ ] **Step 4:** `node --check` + i18n audit + 手動驗證（啟動 GUI 看整合頁 banner 下出現「快取延遲（traffic）：1004 小時」類訊息）。
- [ ] **Step 5:** Commit `feat(gui): pipeline-health banner shows the failing signals, not just ERROR`

### Task 3: Policy Resolver GUI 入口

完整鏡像 Policy Diff 的 T12 模式（路由 + 卡片 + modal meta + dispatch + i18n），差異：`run()` 回傳 **list[str]**、fmt 白名單 `('json','csv','all')`。

**Files:** Modify `src/gui/routes/reports.py`（插在 policy_diff 路由後）、`src/templates/index.html`（第 6 張卡）、`src/static/js/dashboard.js`、i18n 兩檔；Test `tests/test_gui_policy_resolver_generate.py`

- [ ] **Step 1（失敗測試）:** 複製 `tests/test_gui_policy_diff_generate.py` 為 `tests/test_gui_policy_resolver_generate.py`，改為 POST `/api/policy_resolver_report/generate`、patch `src.report.policy_resolver_report.PolicyResolverReport`、`run.return_value = ["/tmp/x/a.json", "/tmp/x/b.csv"]`、斷言 `files == ["a.json", "b.csv"]`；保留 bad-lang fallback 測試。跑 → 404 FAIL。
- [ ] **Step 2（路由）:**

```python
    # ── API: Policy Resolver Report ──────────────────────────────────────────
    @bp.route('/api/policy_resolver_report/generate', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_generate_policy_resolver_report():
        d = request.json or {}
        lang = d.get('lang', 'en')
        if lang not in ('en', 'zh_TW'):
            lang = 'en'
        try:
            from src.report.policy_resolver_report import PolicyResolverReport
            from src.api_client import ApiClient
            cm.load()
            config_dir = _resolve_config_dir()
            from src.main import _make_cache_reader
            rep = PolicyResolverReport(cm, api_client=ApiClient(cm), config_dir=config_dir,
                                       cache_reader=_make_cache_reader(cm))
            fmt = d.get('format', 'all')
            fmt = fmt if fmt in ('json', 'csv', 'all') else 'all'
            output_dir = _resolve_reports_dir(cm)
            paths = rep.run(output_dir=output_dir, lang=lang, fmt=fmt)
            return jsonify({"ok": True, "files": [os.path.basename(p) for p in paths]})
        except Exception as e:
            return _err_with_log("report_policy_resolver_generate", e, lang=lang)
```

- [ ] **Step 3（前端）:** index.html 複製 Policy Diff 卡改 `data-args='["policy_resolver"]'`；dashboard.js：modal meta 加 `policy_resolver: { titleKey: 'gui_gen_policy_resolver_title', icon: '#icon-shield', dates: false }`、新增 `_doGeneratePolicyResolver()`（仿 `_doGeneratePolicyDiff`，body `{format:'all', lang:...}`）、dispatch 分支、`loadRcardMeta` 檔名前綴 fallback `Illumio_Policy_Resolver_`（先以 `grep -n "Illumio_Policy" src/report/exporters/policy_resolver_exporter.py` 確認實際前綴，依實際值填）。
- [ ] **Step 4（i18n 兩檔）:** en：`gui_gen_policy_resolver_title`: "Generate Policy Resolver Report"、`gui_rcard_policy_resolver_title`: "Policy Resolver Report"、`gui_rcard_policy_resolver_desc`: "Expand ACTIVE label-based Policy into IP-level rows (JSON + CSV)"、`gui_toast_policy_resolver_done`: "Policy Resolver report generated."、`gui_toast_policy_resolver_fail`: "Policy Resolver report failed."；zh：「產生 Policy Resolver 報表」「Policy Resolver 報表」「將 ACTIVE 的 Label 式 Policy 展開為 IP 層級列（JSON + CSV）」「Policy Resolver 報表已產生。」「Policy Resolver 報表產生失敗。」
- [ ] **Step 5:** 測試 2 passed；`pytest -k "gui or reports" | tail -1` 無新失敗；i18n audit 0；node --check。
- [ ] **Step 6:** Commit `feat(gui): Policy Resolver report card + generate endpoint`

### Task 4: VEN 版本分布

**Files:** Modify `src/report/ven_status_generator.py`（`_analyze()`）、`src/report/exporters/ven_html_exporter.py`、i18n 兩檔；Test `tests/test_ven_version_distribution.py`

- [ ] **Step 1（失敗測試）:**

```python
# tests/test_ven_version_distribution.py
"""VEN report: distribution by agent version (upgrade planning)."""
import pandas as pd


def test_by_version_distribution_built():
    from src.report.ven_status_generator import VenStatusGenerator
    df = pd.DataFrame([
        {"ven_version": "23.2.10"}, {"ven_version": "23.2.10"},
        {"ven_version": "22.5.1"}, {"ven_version": ""},
    ])
    dist = VenStatusGenerator._by_version(df)
    assert dist == {"23.2.10": 2, "22.5.1": 1, "(unknown)": 1}
```

（若 `_analyze` 不易抽測，將分布建構抽成 `@staticmethod _by_version(df) -> dict` 再被 `_analyze` 呼叫 — 此即實作形狀。）跑 → FAIL（AttributeError）。
- [ ] **Step 2（實作）:** ven_status_generator.py 加：

```python
    @staticmethod
    def _by_version(df) -> dict:
        """Distribution of VEN agent versions; blank → (unknown)."""
        s = df["ven_version"].fillna("").astype(str).replace("", "(unknown)")
        return s.value_counts().to_dict()
```

在 `_analyze()` 建 by_family/by_mode 的同一處（:117-118 模式）加 `results["by_version"] = self._by_version(df)`（確認 `_analyze` 內 df 變數名）。
- [ ] **Step 3（exporter）:** ven_html_exporter.py 的 Estate Inventory 區段（OS Distribution 旁，grep `by_family` 定位）加同型表格：標題 key `rpt_ven_by_version`（en "VEN Version Distribution" / zh "VEN 版本分布"），以該檔既有的 distribution 表渲染 idiom 輸出 by_version。
- [ ] **Step 4:** 測試 + `pytest -k "ven" | tail -1` + i18n audit。
- [ ] **Step 5:** Commit `feat(report): VEN version distribution for upgrade planning`

### Task 5: 規則排程頁 — timeline 卡 Loading、「下次觸發 —」（調查→修復）

**Files:** Modify `src/gui/routes/rule_scheduler.py:37-46`、`src/static/js/rule-scheduler.js`、可能 i18n

- [ ] **Step 1（調查，15 分鐘上限）:**
  - `grep -n "timeline\|Loading\|status" src/static/js/rule-scheduler.js | head -20` — 找 timeline 渲染函式與其資料來源呼叫。
  - 判定：timeline JS 期待的欄位是否存在於任何端點回應？「下次觸發」JS 是否有計算邏輯但資料不足？
  - 記錄結論後依下列既定方向修（若調查發現與假設不符的更簡單根因，採更簡單修法並在報告說明）。
- [ ] **Step 2（後端）:** 擴充 `rs_status()`（rule_scheduler.py:37-46）回傳 `next_trigger_at`（ISO 字串或 null）與 `timeline_24h`：

```python
        from src.rule_scheduler import compute_next_trigger  # 若無此 util，於 src/rule_scheduler.py 新增
        schedules = db.get_all()
        next_at = compute_next_trigger(schedules)  # 掃 recurring days/start 與 one-time expire_at，回最近未來時刻
        # timeline：取最近 24h 的 check log（GUI 已有 in-memory rs log deque — grep '_rs_log' src/gui/__init__.py）
```

`compute_next_trigger(schedules) -> str | None`：對每個 enabled recurring 排程，用其 timezone 計算今天/未來 7 天內最近的 `days`+`start` 時刻；one-time 取未來的 `expire_at`；全部取 min。寫成 `src/rule_scheduler.py` 的純函式 + 單元測試（3 cases：recurring 今天稍後、recurring 下週、one-time 過期回 None）。
- [ ] **Step 3（前端）:** rule-scheduler.js：KPI 卡「下次觸發」改讀 `status.next_trigger_at`（本地時區格式化）；timeline 渲染改用 `status.timeline_24h`（若 Step 1 判定 timeline 資料源是 log deque，後端把 deque 內 24h 的 enable/disable 事件映射為 `[{hour, count}]`；無資料時顯示「無紀錄」而非永遠 Loading — 空狀態文字 key `gui_rs_timeline_empty` en "No rule switches in the last 24h" / zh "過去 24 小時無規則切換紀錄"）。
- [ ] **Step 4:** 單元測試 compute_next_trigger 3 passed；node --check；手動驗證頁面兩處不再卡住。
- [ ] **Step 5:** Commit `fix(gui): rule-scheduler next-trigger + 24h timeline render real data (was stuck Loading / em-dash)`

### Task 6: 「POLICY 判」表頭截字

**Files:** Modify `src/templates/index.html:913`

- [ ] **Step 1:** `style="width:80px"` 改 `style="min-width:110px;white-space:nowrap"`（zh「Policy 判定」與 en「Policy Decision」都需 ~110px；先 grep 同表格其他 th 是否用 class 而非 inline style，若有 class 慣例改用 class）。
- [ ] **Step 2:** 啟動 GUI 目視驗證 zh/en 兩語言表頭完整。Commit `fix(gui): flow-table policy-decision header no longer truncates`

### Task 7: 臨時產生報表 async 化

同步 POST 在慢 PCE 下逾時（實測 408）。改為：POST 立即回 `job_id`，daemon thread 執行，前端輪詢。複用 report_scheduler 的 thread+state 模式，但 ad-hoc job 狀態存 state.json 新 key `adhoc_report_jobs`（保留最近 20 筆）。

**Files:** Modify `src/gui/routes/reports.py`（traffic generate 改 async + 新 job-status 端點）、`src/static/js/dashboard.js`（輪詢）、i18n；Test `tests/test_reports_async_generate.py`

- [ ] **Step 1（失敗測試）:** 仿 `tests/test_gui_policy_diff_generate.py` fixture：

```python
def test_traffic_generate_returns_job_id_and_completes(client_logged_in, monkeypatch):
    # patch ReportGenerator 整體流程為快速假實作（generate_from_api 回最小 result、export 回 ["x.html"]）
    r = client_logged_in.post("/api/reports/generate", json={"source": "api", "format": "html",
                                                              "start_date": "...", "end_date": "..."})
    body = r.get_json()
    assert body["ok"] is True and "job_id" in body
    # 輪詢 job 端點直到 done（測試內 join thread 或輪詢上限 5 秒）
    for _ in range(50):
        s = client_logged_in.get(f"/api/reports/jobs/{body['job_id']}").get_json()
        if s["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert s["status"] == "done"
    assert s["files"] == ["x.html"]


def test_job_endpoint_unknown_id_404(client_logged_in):
    assert client_logged_in.get("/api/reports/jobs/nonexistent").status_code == 404
```

- [ ] **Step 2（後端）:** reports.py 的 `api_generate_report`（:146 起）重構：參數驗證照舊（同步回 400 給壞輸入）；通過後建 `job_id = uuid4().hex[:12]`，把現有產生邏輯移入 `def _run_adhoc(job_id, payload):`，以 `threading.Thread(target=_run_adhoc, daemon=True).start()` 執行；job 紀錄（status: running/done/error、files、error、started_at、finished_at）寫入 state.json `adhoc_report_jobs[job_id]`（用既有 state 讀寫 util — grep `_save_state\|state.json` reports.py/report_scheduler.py 沿用同把鎖/原子寫法；保留最近 20 筆，超出修剪最舊）。新端點：

```python
    @bp.route('/api/reports/jobs/<job_id>', methods=['GET'])
    def api_report_job_status(job_id):
        jobs = _load_adhoc_jobs()
        if job_id not in jobs:
            return jsonify({"ok": False, "error": "unknown job"}), 404
        return jsonify({"ok": True, **jobs[job_id]})
```

rate limit 維持產生端點 30/hr；job 查詢不限流。audit/ven/policy_usage/policy_diff/policy_resolver 的產生端點**本任務不動**（它們執行快；traffic 是唯一實測逾時者 — YAGNI）。
- [ ] **Step 3（前端）:** dashboard.js `_doGenerateTraffic` 兩個變體（API/CSV）：POST 後拿 job_id，進入輪詢（每 2 秒 GET job 端點，沿用 `_updateGenStep` 顯示進度文字；done → 現有成功路徑（toast + loadReports + loadRcardMeta）；error → 現有失敗路徑；輪詢上限 15 分鐘）。i18n：`gui_gen_step_running_bg` en "Generating in background…" / zh "背景產生中…"。
- [ ] **Step 4:** 測試 2 passed；`pytest -k "reports or gui" | tail -1` 無新失敗（既有同步測試若斷言立即回 files，改斷 job 流程 — 預期需更新 1-2 個既有測試，報告列明）。
- [ ] **Step 5:** Commit `feat(gui): ad-hoc traffic report generation is async (job_id + polling) — no more 408 on slow PCE`

### Task 8: 稽核報表「7 天無資料」（調查→修復）

主要假設：`pce_cache.enabled` 時 audit 走 cache，而 cache 已過期 1004h（事件頁走 live PCE 所以有資料）。

**Files:** Modify `src/report/audit_generator.py:434-472`；Test `tests/test_audit_cache_fallback.py`

- [ ] **Step 1(調查):**
  - 讀 `_fetch_events` 的 cache 分支：cache 回傳空/過舊時的行為？
  - lab 驗證：`./venv/bin/python illumio-ops.py report audit --output-dir /tmp/x` 同時開 DEBUG，確認事件來源與筆數；對照 `/api/events/viewer` 同窗口筆數。
  - 若根因不是 cache 過期（例如時間窗計算錯誤），按實際根因修並在報告說明（決策準則：修復後同窗口 audit 報表筆數應與事件頁同數量級）。
- [ ] **Step 2(失敗測試，按假設):**

```python
# tests/test_audit_cache_fallback.py
"""Audit report must fall back to live API when the cache window doesn't cover the request."""
def test_stale_cache_falls_back_to_api(...):
    # cache_reader stub: 回 0 筆且 max(timestamp) 早於請求起點
    # api stub: 回 3 筆
    # 斷言 _fetch_events 回 3 筆且來源標記為 api
```

（fixture 依 audit_generator 建構子簽名組裝：`AuditGenerator(cm, api_client=stub, cache_reader=stub)`。）
- [ ] **Step 3(實作):** `_fetch_events` cache 分支加守門：cache 回傳 0 筆、或 cache 最新事件時間早於 `start` 時，log warning（「cache stale/empty — falling back to live API」）並改走 API 分支。
- [ ] **Step 4:** 測試 passed；lab 實跑 audit 報表有資料。Commit `fix(report): audit report falls back to live API when event cache is stale/empty`

### Task 9: dead code 清理

**Files:** Modify `src/report/exporters/chart_renderer.py`（刪 `render_plotly_html`、`FirstChartTracker`、其專屬 plotly imports）、刪除其單元測試中對應 case（grep `render_plotly_html\|FirstChartTracker` tests/）、i18n 兩檔刪 4 個 orphan key（`rpt_tr_sec_allowed`、`rpt_tr_sec_allowed_intro`、`rpt_tr_nav_allowed`、`rpt_tr_allowed_flows_subnote`）

- [ ] **Step 1:** `grep -rn "render_plotly_html\|FirstChartTracker" src/ tests/` 確認僅定義與測試引用；刪除函式/類/相關 import（若 `plotly` import 仍被其他函式用，保留 import）。
- [ ] **Step 2:** 刪 orphan i18n keys（兩檔同步刪，JSON parse 驗證）；跑 `./venv/bin/python scripts/audit_i18n_usage.py` 與 `pytest -k "i18n or chart" | tail -1` — audit Cat I（parity）必須仍為 0。
- [ ] **Step 3:** 全套件 `pytest tests/ -q | tail -1` 無新失敗。Commit `chore(report): remove dead plotly path and orphaned allowed-section i18n keys`

---

## 完成後整體驗證

```bash
./venv/bin/python -m pytest tests/ -q          # 無新失敗
./venv/bin/python scripts/audit_i18n_usage.py  # 0 findings
# lab GUI 手動：Posture CTA 直開 modal；整合頁 ERROR 下有原因；Resolver 卡可產生；
# 規則排程頁 timeline/下次觸發有值；流量表頭完整；traffic 產生走背景+輪詢；audit 報表有資料。
```

## Self-Review 紀錄
- 9 個項目（E、G、H–N）各對應 T7、T8、T1–T6、T9，無遺漏。
- 調查任務（T5、T8）都附了探查指令、主要假設與「與假設不符時」的決策準則，非開放式。
- T7 刻意只改 traffic 端點（其餘端點執行快，YAGNI）；T3 的 resolver 檔名前綴留了現場確認指令。
