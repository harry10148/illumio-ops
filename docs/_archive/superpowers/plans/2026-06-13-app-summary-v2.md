# App Summary v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the App Summary report to API-driven app selection, two new content sections (Security Policy Impact + Enforcement State) aligned to Illumio's App Group Summary methodology, and async GUI generation.

**Architecture:** No new analysis engine. The `AppSummaryReport` facade gains one new data fetch (managed workloads, for enforcement state) and two derived result blocks (`policy_impact` from the existing mod02 result, `enforcement` from the workloads). A new `GET /api/labels` endpoint feeds an app/env dropdown in the GUI modal. The GUI generate path is refactored to the existing traffic async job pattern (job_id + polling). CLI and scheduler stay synchronous.

**Tech Stack:** Python / pandas / Flask / vanilla JS / pytest. i18n dual-file + glossary. Shared report styling (`build_css` + `cover_page`) already in place.

**Spec:** `docs/superpowers/specs/2026-06-13-app-summary-v2-design.md` (scope B + async; out-of-scope: V-E, ransomware ports, events, owner/auditor split, per-app drift, dedicated rule_coverage API).

**執行環境：** worktree (superpowers:using-git-worktrees) + `ln -sfn /home/harry/rd/illumio-ops/venv venv`. 基線 `./venv/bin/python -m pytest tests/ -q`（以執行當下 main 為準；注意已知 `TestOverviewPostureHelper` snapshot 污染 quirk，隔離下通過）。

---

## 已驗證事實（grounding）

| 事實 | 出處 |
|------|------|
| `policy_decision_analysis(scoped, top_n=10)` 回 dict：每個 decision `results[d] = {'count': N, 'pct_of_total', 'inbound_count', 'outbound_count', ...}`，d ∈ allowed/blocked/potentially_blocked/unknown；另有 `results['summary']`、`results['port_coverage']`、`results['chart_spec']`。**無 lang 參數** | mod02_policy_decisions.py:6,17-20,55,85-92 |
| `api.fetch_managed_workloads(max_results=10000) -> list[dict]`；每個 workload 含 `enforcement_mode` 與 `labels`（list of `{key,value,href}`） | api_client.py `fetch_managed_workloads` |
| `api.get_labels(key: str) -> list[dict]`（每筆 `{key,value,href}`）；`get_labels("app")` 在 lab PCE 回 18 筆 | api_client.py:550；實測 |
| 非同步 job 工具：`_load_adhoc_jobs()`、`_save_adhoc_job(job_id, record)`、`_run_adhoc(job_id, payload)`（traffic 用）、job 狀態端點 `GET /api/reports/jobs/<job_id>`（`api_report_job_status`） | gui/routes/reports.py:28,32,37,178,365 |
| facade `build(app, env, lang, start_date, end_date)`：`_fetch_estate_df` → `filter_app_flows` → mod01/02/03 + `app_baseline(scoped, app, env)` + `RulesEngine(...).evaluate(scoped)`；空 scope 回 `{empty:True}` | app_summary_report.py `build` |
| `AppSummaryReport.__init__(cm, api_client, config_dir, cache_reader)`；`self.api` 是 ApiClient | app_summary_report.py:117 |
| exporter 已用共用外殼：`build_css("app_summary")` + `_build_cover_page` + `.report-shell`/`.card`/`.report-table`/`.kpi-card`；節用 `_section(id, title, content)`；空狀態走 `rpt_app_empty` | app_summary_html_exporter.py |
| GUI 報表 modal app/env 欄位 id：`m-gen-app`、`m-gen-env`（目前是 text input）；`_doGenerateAppSummary` 已存在並 POST `/api/app_report/generate` | index.html:2876-2879；dashboard.js:1120 |
| 既有 labels 抓取慣例：`api.get_labels(key)`；GUI 路由建構 ApiClient 模式見 policy_resolver 路由（`ApiClient(cm)`、`_resolve_*`） | api_client.py:550；gui/routes/reports.py |

## 檔案結構

```
src/report/analysis/mod_app_baseline.py       # T1: policy_impact() + enforcement_summary() 純函式
src/report/app_summary_report.py              # T2: build() 加 workloads 抓取 + policy_impact + enforcement
src/report/exporters/app_summary_html_exporter.py  # T3: 兩個新節
src/gui/routes/reports.py                      # T4: GET /api/labels；T5: app_report async
src/templates/index.html                       # T4: m-gen-app/m-gen-env 改 <select>
src/static/js/dashboard.js                     # T4: 下拉載入；T5: 輪詢
src/cli/report.py                              # T6: --app 軟驗證
src/i18n_en.json, src/i18n_zh_TW.json          # T3 新節 key
tests/test_mod_app_baseline.py                 # T1
tests/test_app_summary_report.py               # T2/T3
tests/test_gui_app_report_generate.py          # T4/T5
tests/test_cli_app_summary_validate.py         # T6（新）
```

---

### Task 1: policy_impact + enforcement_summary 純函式

**Files:**
- Modify: `src/report/analysis/mod_app_baseline.py`
- Test: `tests/test_mod_app_baseline.py`

- [ ] **Step 1: 寫失敗測試** — 加到 `tests/test_mod_app_baseline.py`：

```python
def test_policy_impact_from_mod02():
    from src.report.analysis.mod_app_baseline import policy_impact
    mod02 = {
        "allowed": {"count": 8},
        "potentially_blocked": {"count": 3},
        "blocked": {"count": 1},
        "unknown": {"count": 0},
    }
    res = policy_impact(mod02)
    assert res["allowed"] == 8 and res["potentially_blocked"] == 3
    assert res["blocked"] == 1 and res["unknown"] == 0
    assert res["total"] == 12
    assert res["coverage_pct"] == round(8 / 12 * 100, 1)   # allowed / total
    assert res["would_be_blocked"] == 3                     # potentially_blocked
    assert res["available"] is True


def test_policy_impact_handles_error_or_empty():
    from src.report.analysis.mod_app_baseline import policy_impact
    assert policy_impact({"error": "No data"})["available"] is False
    assert policy_impact({})["available"] is False           # no decisions → unavailable


def test_enforcement_summary_filters_by_app():
    from src.report.analysis.mod_app_baseline import enforcement_summary
    wls = [
        {"hostname": "web1", "enforcement_mode": "full",
         "labels": [{"key": "app", "value": "DB"}, {"key": "env", "value": "Prod"}]},
        {"hostname": "web2", "enforcement_mode": "visibility_only",
         "labels": [{"key": "app", "value": "DB"}, {"key": "env", "value": "Prod"}]},
        {"hostname": "other", "enforcement_mode": "full",
         "labels": [{"key": "app", "value": "Web"}]},          # different app → excluded
    ]
    res = enforcement_summary(wls, app="DB")
    assert res["available"] is True
    assert res["total"] == 2
    assert res["by_mode"] == {"full": 1, "visibility_only": 1}
    assert res["enforced"] == 1                                # full + selective
    assert list(res["table"]["Workload"]) == ["web1", "web2"]


def test_enforcement_summary_env_refines_and_unavailable():
    from src.report.analysis.mod_app_baseline import enforcement_summary
    wls = [{"hostname": "web1", "enforcement_mode": "full",
            "labels": [{"key": "app", "value": "DB"}, {"key": "env", "value": "Prod"}]}]
    assert enforcement_summary(wls, app="DB", env="Dev")["total"] == 0
    assert enforcement_summary(None, app="DB")["available"] is False
    assert enforcement_summary([], app="DB")["available"] is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_mod_app_baseline.py -k "policy_impact or enforcement" -q`
Expected: FAIL（ImportError：函式不存在）

- [ ] **Step 3: 實作** — 加到 `src/report/analysis/mod_app_baseline.py`：

```python
import pandas as pd

_ENFORCED_MODES = ("full", "selective")


def policy_impact(mod02: dict) -> dict:
    """Derive the app's Security Policy Impact from the mod02 policy-decision result.

    coverage_pct = allowed / total; would_be_blocked = potentially_blocked count
    (flows allowed today only because the workload is in visibility/test mode —
    they have no rule and would drop under Full Enforcement).
    """
    if not mod02 or mod02.get("error"):
        return {"available": False}
    counts = {d: int(mod02.get(d, {}).get("count", 0))
              for d in ("allowed", "blocked", "potentially_blocked", "unknown")}
    total = sum(counts.values())
    if total == 0:
        return {"available": False}
    return {
        "available": True,
        "allowed": counts["allowed"],
        "blocked": counts["blocked"],
        "potentially_blocked": counts["potentially_blocked"],
        "unknown": counts["unknown"],
        "total": total,
        "coverage_pct": round(counts["allowed"] / total * 100, 1),
        "would_be_blocked": counts["potentially_blocked"],
    }


def _workload_has_label(wl: dict, key: str, value: str) -> bool:
    return any(l.get("key") == key and l.get("value") == value
              for l in (wl.get("labels") or []))


def enforcement_summary(workloads, app: str, env: str | None = None) -> dict:
    """Per-workload enforcement-mode summary for one app (optional env refine)."""
    if not workloads:
        return {"available": False}
    scoped = [w for w in workloads if _workload_has_label(w, "app", app)
              and (not env or _workload_has_label(w, "env", env))]
    by_mode: dict[str, int] = {}
    rows = []
    for w in scoped:
        mode = w.get("enforcement_mode", "") or "(unknown)"
        by_mode[mode] = by_mode.get(mode, 0) + 1
        rows.append({"Workload": w.get("hostname", w.get("href", "")), "Enforcement": mode})
    enforced = sum(by_mode.get(m, 0) for m in _ENFORCED_MODES)
    return {
        "available": True,
        "total": len(scoped),
        "by_mode": by_mode,
        "enforced": enforced,
        "table": pd.DataFrame(rows, columns=["Workload", "Enforcement"]),
    }
```

（注意：`pd` 在該檔可能已 import — 確認後勿重複。`policy_impact` 取 mod02 已算好的 count，不重算流量。）

- [ ] **Step 4: 跑測試確認通過**

Run: `./venv/bin/python -m pytest tests/test_mod_app_baseline.py -q`
Expected: PASS（含原有 baseline 測試）

- [ ] **Step 5: Commit**

```bash
git add src/report/analysis/mod_app_baseline.py tests/test_mod_app_baseline.py
git commit -m "feat(report): policy-impact + enforcement-summary pure functions for App Summary"
```

---

### Task 2: facade — 抓 workloads + 注入 policy_impact / enforcement

**Files:**
- Modify: `src/report/app_summary_report.py`（`build`）
- Test: `tests/test_app_summary_report.py`

- [ ] **Step 1: 寫失敗測試** — 加到 `tests/test_app_summary_report.py`（沿用既有 `_row`/mock fetch fixture）：

```python
def test_build_adds_policy_impact_and_enforcement(monkeypatch):
    import pandas as pd
    from unittest.mock import MagicMock, patch
    from src.report.app_summary_report import AppSummaryReport
    df = pd.DataFrame([
        _row("Web", "P", "DB", "P", 3306, "allowed", 5),
        _row("Batch", "P", "DB", "P", 3306, "potentially_blocked", 2),
    ])
    api = MagicMock()
    api.fetch_managed_workloads.return_value = [
        {"hostname": "db1", "enforcement_mode": "full",
         "labels": [{"key": "app", "value": "DB"}]},
    ]
    rep = AppSummaryReport(cm=MagicMock(), api_client=api)
    with patch.object(rep, "_fetch_estate_df", return_value=df):
        res = rep.build(app="DB", lang="en")
    assert res["policy_impact"]["available"] is True
    assert res["policy_impact"]["would_be_blocked"] == 1   # 1 pb flow to DB
    assert res["enforcement"]["available"] is True
    assert res["enforcement"]["total"] == 1
    api.fetch_managed_workloads.assert_called_once()


def test_build_enforcement_unavailable_when_workloads_fetch_fails(monkeypatch):
    import pandas as pd
    from unittest.mock import MagicMock, patch
    from src.report.app_summary_report import AppSummaryReport
    df = pd.DataFrame([_row("Web", "P", "DB", "P", 3306, "allowed", 5)])
    api = MagicMock()
    api.fetch_managed_workloads.side_effect = Exception("boom")
    rep = AppSummaryReport(cm=MagicMock(), api_client=api)
    with patch.object(rep, "_fetch_estate_df", return_value=df):
        res = rep.build(app="DB", lang="en")
    assert res["enforcement"]["available"] is False         # report still builds
    assert res["empty"] is False
```

（若 test 檔尚無 `_row` helper，先讀檔確認其簽名；本plan T2 測試的 `_row(src_app, src_env, dst_app, dst_env, port, decision, conns)` 需與既有 helper 一致 — 不一致就用既有 helper 的參數順序並更新此測試。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_app_summary_report.py -k "policy_impact or enforcement" -q`
Expected: FAIL（KeyError：`policy_impact`/`enforcement` 不存在）

- [ ] **Step 3: 實作** — 在 `build()` 的 `results["findings"] = ...` 之後、`return results` 之前加：

```python
        from src.report.analysis.mod_app_baseline import policy_impact, enforcement_summary
        results["policy_impact"] = policy_impact(results["mod02"])
        try:
            workloads = self.api.fetch_managed_workloads() if self.api else None
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[AppSummary] workloads fetch failed: {exc}")
            workloads = None
        results["enforcement"] = enforcement_summary(workloads, app, env)
        return results
```

（`logger` 取該檔既有 logger；確認 import。`policy_impact` 取 `results["mod02"]`（已算）。workloads 抓取失敗時 `enforcement_summary(None, ...)` 回 `{available:False}`，報表照常產生。）

- [ ] **Step 4: 跑測試確認通過**

Run: `./venv/bin/python -m pytest tests/test_app_summary_report.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/app_summary_report.py tests/test_app_summary_report.py
git commit -m "feat(report): App Summary facade adds policy-impact + enforcement-state blocks"
```

---

### Task 3: exporter — Security Policy Impact + Enforcement State 兩節

**Files:**
- Modify: `src/report/exporters/app_summary_html_exporter.py`、`src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_app_summary_report.py`

- [ ] **Step 1: 寫失敗測試** — 加到 `tests/test_app_summary_report.py`（沿用 build→export e2e 形狀，mock fetch + workloads）：

```python
def test_export_renders_policy_impact_and_enforcement_sections(tmp_path):
    import pandas as pd
    from unittest.mock import MagicMock, patch
    from src.report.app_summary_report import AppSummaryReport
    from src.report.exporters.app_summary_html_exporter import AppSummaryHtmlExporter
    df = pd.DataFrame([
        _row("Web", "P", "DB", "P", 3306, "allowed", 5),
        _row("Batch", "P", "DB", "P", 3306, "potentially_blocked", 2),
    ])
    api = MagicMock()
    api.fetch_managed_workloads.return_value = [
        {"hostname": "db1", "enforcement_mode": "full", "labels": [{"key": "app", "value": "DB"}]},
    ]
    rep = AppSummaryReport(cm=MagicMock(), api_client=api)
    with patch.object(rep, "_fetch_estate_df", return_value=df):
        res = rep.build(app="DB", lang="en")
    html = AppSummaryHtmlExporter(res, lang="en")._render_html()
    assert 'id="policy-impact"' in html and 'id="enforcement"' in html
    assert "db1" in html                       # enforcement table renders the workload
    assert "report-shell" in html              # still the shared shell
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_app_summary_report.py -k "policy_impact_and_enforcement" -q`
Expected: FAIL（`id="policy-impact"` 不在 html）

- [ ] **Step 3: 實作（exporter）** — 在 `_render_html()` 非空分支的 sections 串接中，於 `coverage` 之後、`findings` 之前插入兩節，並新增兩個 render 方法：

```python
    def _policy_impact_section(self) -> str:
        pi = self._r.get("policy_impact") or {}
        if not pi.get("available"):
            return f'<p class="note">{_esc(t("rpt_app_no_policy_impact", lang=self._lang))}</p>'
        cards = (
            self._kpi_card(t("rpt_app_pi_coverage", lang=self._lang), f'{pi["coverage_pct"]}%')
            + self._kpi_card(t("rpt_app_pi_would_block", lang=self._lang), str(pi["would_be_blocked"]))
            + self._kpi_card(t("rpt_app_pi_allowed", lang=self._lang), str(pi["allowed"]))
            + self._kpi_card(t("rpt_app_pi_blocked", lang=self._lang), str(pi["blocked"]))
        )
        note = _esc(t("rpt_app_pi_note", lang=self._lang)).replace("{n}", str(pi["would_be_blocked"]))
        return f'<div class="kpi-grid">{cards}</div><p class="note">{note}</p>'

    def _enforcement_section(self) -> str:
        en = self._r.get("enforcement") or {}
        if not en.get("available"):
            return f'<p class="note">{_esc(t("rpt_app_enf_unavailable", lang=self._lang))}</p>'
        summary = _esc(t("rpt_app_enf_summary", lang=self._lang)) \
            .replace("{enforced}", str(en["enforced"])).replace("{total}", str(en["total"]))
        table = render_df_table(en.get("table"), col_i18n={}, lang=self._lang)
        return f'<p class="note">{summary}</p>{table}'
```

並在 sections 串接加：

```python
                + self._section("policy-impact", _esc(t("rpt_app_policy_impact", lang=lang)), self._policy_impact_section())
                + self._section("enforcement", _esc(t("rpt_app_enforcement", lang=lang)), self._enforcement_section())
```

（`_kpi_card` 若該檔已有就用既有的；若目前 KPI 是用 `_kpi_row()` 一次組好，改為新增一個 `_kpi_card(label, value)` helper 回單張 `.kpi-card`，並讓 `_kpi_row` 也用它 — 先讀該檔確認既有 KPI 卡的 class/結構，沿用之。`_esc`、`render_df_table`、`t`、`_section` 皆該檔既有。）

- [ ] **Step 4: i18n（兩檔，字母序，glossary：Policy/App/enforcement 在 zh 保留英文）：**

en：
```
"rpt_app_policy_impact": "Security Policy Impact",
"rpt_app_pi_coverage": "Rule coverage",
"rpt_app_pi_would_block": "Would block (if enforced)",
"rpt_app_pi_allowed": "Allowed",
"rpt_app_pi_blocked": "Blocked",
"rpt_app_pi_note": "If this app moves to Full Enforcement, {n} flow(s) currently allowed by visibility mode would be blocked.",
"rpt_app_no_policy_impact": "No policy-decision data for this app in the selected window.",
"rpt_app_enforcement": "Enforcement State",
"rpt_app_enf_summary": "{enforced} of {total} workloads are in enforced mode (selective or full).",
"rpt_app_enf_unavailable": "Workload enforcement data is unavailable.",
```
zh_TW：
```
"rpt_app_policy_impact": "Security Policy 影響",
"rpt_app_pi_coverage": "規則覆蓋率",
"rpt_app_pi_would_block": "將被阻擋（若強制）",
"rpt_app_pi_allowed": "Allowed",
"rpt_app_pi_blocked": "Blocked",
"rpt_app_pi_note": "若此 App 進入 Full Enforcement，目前因 visibility 模式而被允許的 {n} 條流量將被阻擋。",
"rpt_app_no_policy_impact": "選定期間內此 App 無 policy decision 資料。",
"rpt_app_enforcement": "Enforcement 狀態",
"rpt_app_enf_summary": "{total} 個 workload 中有 {enforced} 個處於 enforced 模式（selective 或 full）。",
"rpt_app_enf_unavailable": "無法取得 workload enforcement 資料。",
```

- [ ] **Step 5: 跑測試 + i18n 稽核**

Run: `./venv/bin/python -m pytest tests/test_app_summary_report.py -q && ./venv/bin/python scripts/audit_i18n_usage.py && ./venv/bin/python -m pytest tests/test_i18n_glossary.py -q`
Expected: 測試 PASS；audit 0 findings；glossary PASS

- [ ] **Step 6: Commit**

```bash
git add src/report/exporters/app_summary_html_exporter.py src/i18n_en.json src/i18n_zh_TW.json tests/test_app_summary_report.py
git commit -m "feat(report): App Summary renders Security Policy Impact + Enforcement State sections"
```

---

### Task 4: GET /api/labels 端點 + app/env 下拉

**Files:**
- Modify: `src/gui/routes/reports.py`、`src/templates/index.html`、`src/static/js/dashboard.js`
- Test: `tests/test_gui_app_report_generate.py`

- [ ] **Step 1: 寫失敗測試**（路由）— 加到 `tests/test_gui_app_report_generate.py`：

```python
def test_labels_endpoint_returns_app_labels(client_logged_in, monkeypatch):
    from unittest.mock import patch
    with patch("src.api_client.ApiClient.get_labels", return_value=[
        {"key": "app", "value": "DB"}, {"key": "app", "value": "Web"}]):
        r = client_logged_in.get("/api/labels?key=app")
    body = r.get_json()
    assert body["ok"] is True
    assert body["labels"] == ["DB", "Web"]          # sorted values


def test_labels_endpoint_bad_key_400(client_logged_in):
    assert client_logged_in.get("/api/labels?key=evil").status_code == 400
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_gui_app_report_generate.py -k labels -q`
Expected: FAIL（404）

- [ ] **Step 3: 實作（路由）** — 在 `src/gui/routes/reports.py` 加（鏡像 policy_resolver 路由建構 ApiClient 的方式）：

```python
    @bp.route('/api/labels', methods=['GET'])
    @limiter.limit("60 per hour")
    def api_list_labels():
        key = request.args.get('key', 'app')
        if key not in ('app', 'env', 'role', 'loc'):
            return jsonify({"ok": False, "error": "invalid key"}), 400
        try:
            from src.api_client import ApiClient
            cm.load()
            labels = ApiClient(cm).get_labels(key)
            values = sorted({l.get('value', '') for l in labels if l.get('value')})
            return jsonify({"ok": True, "labels": values})
        except Exception as e:
            return _err_with_log("list_labels", e)
```

（`_err_with_log` 既有；`limiter`/`bp`/`cm` 為該模組 blueprint 既有變數。短快取可選做，不強制。）

- [ ] **Step 4: 前端（index.html）** — 把 `m-gen-app`/`m-gen-env` 從 text input 改為 select（保留 id）：

```html
        <label for="m-gen-app" data-i18n="gui_app_label_field">App Label</label>
        <select id="m-gen-app" style="width:100%; padding:8px; ...（沿用原 input 的 style）"></select>
        ...
        <label for="m-gen-env" data-i18n="gui_env_label_field">Env Label (optional)</label>
        <select id="m-gen-env" style="..."></select>
```

- [ ] **Step 5: 前端（dashboard.js）** — 在 `openReportGenModal` 的 `m.appField` 分支載入下拉（取代清空 value）：

```javascript
  if (appRow) {
    appRow.style.display = m.appField ? '' : 'none';
    if (m.appField) _populateAppLabelSelects();
  }
```
新增：
```javascript
async function _populateAppLabelSelects() {
  const appSel = document.getElementById('m-gen-app');
  const envSel = document.getElementById('m-gen-env');
  if (!appSel) return;
  appSel.innerHTML = `<option value="">${_t('gui_app_loading') || 'Loading…'}</option>`;
  try {
    const [apps, envs] = await Promise.all([api('/api/labels?key=app'), api('/api/labels?key=env')]);
    appSel.innerHTML = ((apps && apps.labels) || []).map(v => `<option value="${v}">${v}</option>`).join('');
    if (envSel) envSel.innerHTML = `<option value="">${_t('gui_env_any') || '(any)'}</option>`
      + ((envs && envs.labels) || []).map(v => `<option value="${v}">${v}</option>`).join('');
  } catch (_) {
    // graceful fallback: leave a single blank option so generation still posts a typed value
    appSel.innerHTML = '<option value=""></option>';
  }
}
```

（i18n：加 `gui_app_loading`("Loading…"/"載入中…")、`gui_env_any`("(any)"/"（全部）")兩 key 兩檔。`_doGenerateAppSummary` 已用 `appEl.value` — select 的 value 行為一致，無需改讀法。option 值用既有的 select 已內建跳脫；label 來自 PCE，若要更嚴謹可 escapeHtml — 用該檔既有 escapeHtml 包 v。）

- [ ] **Step 6: 驗證 + commit**

Run: `./venv/bin/python -m pytest tests/test_gui_app_report_generate.py -q && node --check src/static/js/dashboard.js && ./venv/bin/python scripts/audit_i18n_usage.py`
Expected: PASS；node OK；audit 0
```bash
git add src/gui/routes/reports.py src/templates/index.html src/static/js/dashboard.js src/i18n_en.json src/i18n_zh_TW.json tests/test_gui_app_report_generate.py
git commit -m "feat(gui): App Summary app/env dropdowns populated from /api/labels"
```

---

### Task 5: app_report 非同步產生（job + 輪詢）

**Files:**
- Modify: `src/gui/routes/reports.py`（`api_generate_app_report`）、`src/static/js/dashboard.js`（`_doGenerateAppSummary`）
- Test: `tests/test_gui_app_report_generate.py`

- [ ] **Step 1: 寫失敗測試** — 加：

```python
def test_app_report_generate_returns_job_id_and_completes(client_logged_in):
    import time
    from unittest.mock import patch
    with patch("src.report.app_summary_report.AppSummaryReport") as M:
        M.return_value.run.return_value = "/tmp/x/Illumio_App_Summary_DB.html"
        r = client_logged_in.post("/api/app_report/generate", json={"app": "DB", "lang": "en"})
        body = r.get_json()
        assert body["ok"] is True and "job_id" in body
        for _ in range(50):
            s = client_logged_in.get(f"/api/reports/jobs/{body['job_id']}").get_json()
            if s.get("status") in ("done", "error"):
                break
            time.sleep(0.1)
    assert s["status"] == "done"
    assert s["files"] == ["Illumio_App_Summary_DB.html"]


def test_app_report_generate_missing_app_still_400(client_logged_in):
    r = client_logged_in.post("/api/app_report/generate", json={"app": ""})
    assert r.status_code == 400
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_gui_app_report_generate.py -k "job_id" -q`
Expected: FAIL（回應無 `job_id`）

- [ ] **Step 3: 實作（路由）** — 重構 `api_generate_app_report`：同步驗證（缺 app → 400）後，建 job 並丟背景線程，鏡像 traffic 的 `_run_adhoc` 形狀：

```python
        app = (d.get('app') or '').strip()
        if not app:
            return jsonify({"ok": False, "error": t("gui_app_required", lang=lang)}), 400
        import uuid, threading
        job_id = uuid.uuid4().hex[:12]
        payload = {"app": app, "env": d.get('env') or None, "lang": lang,
                   "start_date": d.get('start_date'), "end_date": d.get('end_date')}
        _save_adhoc_job(job_id, {"status": "running", "files": [], "started_at": _now_iso()})

        def _run_app_summary(jid, p):
            try:
                from src.report.app_summary_report import AppSummaryReport
                from src.api_client import ApiClient
                cm.load()
                rep = AppSummaryReport(cm, api_client=ApiClient(cm),
                                       config_dir=_resolve_config_dir(),
                                       cache_reader=_make_cache_reader(cm))
                path = rep.run(app=p["app"], env=p["env"], output_dir=_resolve_reports_dir(cm),
                               lang=p["lang"], start_date=p["start_date"], end_date=p["end_date"])
                _save_adhoc_job(jid, {"status": "done", "files": [os.path.basename(path)],
                                      "finished_at": _now_iso()})
            except Exception as e:  # noqa: BLE001
                logger.error(f"App summary job {jid} failed: {e}", exc_info=True)
                _save_adhoc_job(jid, {"status": "error", "error": str(e), "finished_at": _now_iso()})

        threading.Thread(target=_run_app_summary, args=(job_id, payload), daemon=True).start()
        return jsonify({"ok": True, "job_id": job_id})
```

（`_now_iso`/`_save_adhoc_job`/`_resolve_*`/`_make_cache_reader` 沿用 traffic `_run_adhoc` 裡用的同一批 helper — 先讀 `_run_adhoc`(reports.py:178) 確認確切名稱與 state 寫法並沿用；job 狀態端點 `/api/reports/jobs/<id>` 已存在，不需新增。）

- [ ] **Step 4: 前端（dashboard.js）** — `_doGenerateAppSummary`：POST 後拿 `job_id`，改走輪詢（沿用 `_pollTrafficJob` 的機制）：

```javascript
    const r = await post('/api/app_report/generate', { app, env: ..., lang: ..., start_date: start, end_date: end });
    if (r.ok && r.job_id) {
      await _pollReportJob(r.job_id, {
        doneToast: 'gui_toast_app_summary_done', failToast: 'gui_toast_app_summary_fail',
      });
    } else { /* 既有錯誤路徑 + r.error */ }
```

（若 `_pollTrafficJob` 是 traffic 專用，將其輪詢核心抽成可重用的 `_pollReportJob(jobId, opts)`（done→toast+loadReports+loadRcardMeta；error→fail toast；上限 15 分鐘），traffic 與 app_summary 共用 — 先讀 `_pollTrafficJob` 再決定抽取或複用。）

- [ ] **Step 5: 驗證 + commit**

Run: `./venv/bin/python -m pytest tests/test_gui_app_report_generate.py -q && ./venv/bin/python -m pytest -k "reports or gui" -q | tail -3 && node --check src/static/js/dashboard.js`
Expected: PASS；無新失敗
```bash
git add src/gui/routes/reports.py src/static/js/dashboard.js tests/test_gui_app_report_generate.py
git commit -m "feat(gui): App Summary generation is async (job_id + polling) — no more timeout"
```

---

### Task 6: CLI --app 軟驗證

**Files:**
- Modify: `src/cli/report.py`（`app-summary` 命令）
- Test: `tests/test_cli_app_summary_validate.py`（新）

- [ ] **Step 1: 寫失敗測試**：

```python
# tests/test_cli_app_summary_validate.py
"""CLI app-summary soft-validates --app against the PCE app labels (warn, not fail)."""
from unittest.mock import patch, MagicMock
from click.testing import CliRunner


def _invoke(app):
    from src.cli.report import report as report_group  # adjust to real group import
    runner = CliRunner()
    with patch("src.config.ConfigManager"), \
         patch("src.api_client.ApiClient") as A, \
         patch("src.report.app_summary_report.AppSummaryReport") as R:
        A.return_value.get_labels.return_value = [{"key": "app", "value": "DB"}]
        R.return_value.run.return_value = "/tmp/x.html"
        return runner.invoke(report_group, ["app-summary", "--app", app, "--output-dir", "/tmp/x"])


def test_unknown_app_warns_but_proceeds():
    res = _invoke("Nope")
    assert res.exit_code == 0
    assert "DB" in res.output            # suggests known labels
    assert "Nope" in res.output


def test_known_app_no_warning():
    res = _invoke("DB")
    assert res.exit_code == 0
```

（`report_group` 的實際 import 路徑以 `tests/test_app_summary_report.py` 既有 CLI 測試為準 — 對齊它的 patch 目標與 group import。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_cli_app_summary_validate.py -q`
Expected: FAIL（無警告輸出）

- [ ] **Step 3: 實作** — 在 `app-summary` 命令組好 facade、呼叫 `run()` 之前加軟驗證：

```python
        try:
            known = {l.get("value") for l in api.get_labels("app") if l.get("value")}
            if app not in known:
                close = ", ".join(sorted(k for k in known if app.lower() in k.lower())[:5]) \
                    or ", ".join(sorted(known)[:8])
                click.echo(f"Warning: App Label '{app}' not found on the PCE. Known: {close}")
        except Exception:
            pass  # validation is best-effort; never block generation
```

（`api` 為命令內既有的 ApiClient 實例 — 確認變數名；若命令尚未建 ApiClient，於驗證處建一個 `ApiClient(cm)`。不 hard-fail。）

- [ ] **Step 4: 跑測試 + commit**

Run: `./venv/bin/python -m pytest tests/test_cli_app_summary_validate.py -q && ./venv/bin/python -m pytest -k "app_summary or cli" -q | tail -3`
Expected: PASS；無新失敗
```bash
git add src/cli/report.py tests/test_cli_app_summary_validate.py
git commit -m "feat(cli): report app-summary soft-validates --app against PCE labels"
```

---

## 完成後整體驗證

```bash
./venv/bin/python -m pytest tests/ -q          # 無新失敗（注意 posture snapshot 污染 quirk：隔離下通過）
./venv/bin/python scripts/audit_i18n_usage.py  # 0 findings
# lab e2e（部署後在測試機跑）：
# 1) GUI：開 App Summary modal → app 下拉列出 PCE app（18 個）→ 選一個 → 產生走背景輪詢（不逾時）→ 報表含 Policy Impact + Enforcement 節、共用樣式。
# 2) CLI：report app-summary --app <真實app> → HTML 有兩新節；--app 打錯 → 警告但仍產生。
# 3) 排程：app_summary 排程仍可建立並執行一次。
```

## Self-Review 紀錄
- Spec 覆蓋：app-select(T4) / policy-impact(T1,T2,T3) / enforcement(T1,T2,T3) / async(T5) / CLI validate(T6) 各有對應任務。
- 無 placeholder：每個 code step 給了實作；標「依實際碼確認」處皆附既有出處（grounding 表）。
- 型別一致：`policy_impact(mod02)->dict(available,coverage_pct,would_be_blocked,...)`、`enforcement_summary(workloads,app,env)->dict(available,total,by_mode,enforced,table)`，T2/T3 用法與 T1 定義一致。
- async 重用既有 traffic job store/endpoint（`_save_adhoc_job`/`/api/reports/jobs`），不另造機制。
- enforcement/labels 抓取失敗皆優雅降級（報表仍產生、前端退回文字）。
```
