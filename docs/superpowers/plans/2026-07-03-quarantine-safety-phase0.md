# 第 0 期：隔離安全與截斷提示 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 隔離操作可審計、可解除、有二次確認；流量查詢的 500 筆截斷從無聲變有提示（分析器 + Top 10）。

**Architecture:** 純既有結構內的增量——`Analyzer` 加查詢統計屬性（仿 `last_traffic_query_diagnostics` 樣式）、`actions.py` 藍圖加審計 helper 與 lift 端點、前端 `quarantine.js`/`dashboard.js` 加提示與按鈕。無 schema、無新依賴。

**Tech Stack:** Python 3.10+、Flask、pytest（Flask test client + monkeypatch）、vanilla JS、i18n 雙 JSON。

**Spec:** `docs/superpowers/specs/2026-07-03-pce-style-filter-object-selector-design.md` §11

## Global Constraints

- 程式內註解繁體中文、commit message 英文 conventional commits、不用 emoji。
- 只動本計畫列出的檔案；不順手重構。
- 新增 UI 字串一律進 `src/i18n_en.json` 與 `src/i18n_zh_TW.json` 兩檔（缺一 i18n 稽核測試會擋）。
- CSP：JS 不可 inline，事件用 `data-action` 綁定（`_event_dispatcher.js` 分派）。
- 端點測試沿用 `tests/test_gui_quarantine.py` 樣式：`client` fixture + `/api/login` + `_csrf` helper + `monkeypatch.setattr("src.api_client.ApiClient.<method>", ...)`。
- 每 Task 結尾跑測試 + commit；Task 6 全量 `python3 -m pytest tests/ -q`（基準 2237 passed）。

---

### Task 1: Analyzer 查詢統計 + search 端點回傳截斷欄位

**Files:**
- Modify: `src/analyzer.py`（`query_flows` 尾端 1226-1227 行 + 模組常數）
- Modify: `src/gui/routes/actions.py`（`/api/quarantine/search` 回應，111-118 行）
- Test: `tests/test_analyzer_truncation_stats.py`（新檔）+ `tests/test_gui_quarantine.py`（追加）

**Interfaces:**
- Produces: `Analyzer.last_query_stats: dict`——`{"total_matches": int, "cap": int, "truncated": bool}`，每次 `query_flows` 重設；Task 2 的 top10 route 與本 Task 的 search 端點消費。
- Produces: `/api/quarantine/search` 回應新欄位 `total_matches`（int）、`truncated`（bool）；Task 3 前端消費。
- Produces: 模組常數 `QUERY_RESULT_CAP = 500`（`src/analyzer.py`）。

- [ ] **Step 1: 寫失敗測試（Analyzer 統計）**

```python
# tests/test_analyzer_truncation_stats.py
"""query_flows 截斷統計：500 上限不再無聲（spec §11.3）。"""
from src.analyzer import Analyzer, QUERY_RESULT_CAP


def _flow(i):
    return {
        "src": {"ip": f"10.0.{i // 250}.{i % 250}", "workload": None},
        "dst": {"ip": "10.9.9.9", "workload": None},
        "service": {"port": 443, "proto": 6},
        "policy_decision": "allowed",
        "num_connections": 1,
        "timestamp_range": {"first_detected": "2026-07-01T00:00:00Z",
                            "last_detected": "2026-07-01T01:00:00Z"},
    }


def _analyzer_with_flows(monkeypatch, n):
    # 沿用 tests/test_analyzer_with_mock_api.py 的 _make_analyzer 建構方式
    # （stub api + 暫存 config）；此處只覆寫流量來源。
    from tests.test_analyzer_with_mock_api import _make_analyzer
    ana = _make_analyzer()
    monkeypatch.setattr(ana.api, "fetch_traffic_for_report",
                        lambda *a, **kw: [_flow(i) for i in range(n)], raising=False)
    return ana


def test_under_cap_not_truncated(monkeypatch):
    ana = _analyzer_with_flows(monkeypatch, 3)
    out = ana.query_flows({"mins": 60})
    assert len(out) == 3
    assert ana.last_query_stats == {"total_matches": 3, "cap": QUERY_RESULT_CAP,
                                    "truncated": False}


def test_over_cap_truncated_and_counted(monkeypatch):
    ana = _analyzer_with_flows(monkeypatch, QUERY_RESULT_CAP + 37)
    out = ana.query_flows({"mins": 60})
    assert len(out) == QUERY_RESULT_CAP
    assert ana.last_query_stats["total_matches"] == QUERY_RESULT_CAP + 37
    assert ana.last_query_stats["truncated"] is True
```

註：`_make_analyzer` 若非模組頂層可 import（讀 `tests/test_analyzer_with_mock_api.py:34-40` 確認），就把該 helper 的建構碼複製進本檔（stub api + 暫存 config dict）。`query_flows` 的 params 需要的最小鍵以 `analyzer.py` 開頭的參數處理段為準（可能需要 `pd` 或時間鍵——跑一次看錯誤補齊）。

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_analyzer_truncation_stats.py -v`
Expected: FAIL（`ImportError: QUERY_RESULT_CAP` 或 `AttributeError: last_query_stats`）。

- [ ] **Step 3: 實作 Analyzer**

`src/analyzer.py` 模組層（class 定義前）加常數；`__init__` 初始化 `self.last_query_stats = {}`；`query_flows` 尾端（1226-1227 行）：

```python
QUERY_RESULT_CAP = 500  # query_flows 單次回傳上限（截斷需回報，不可無聲）
```

```python
        matches.sort(key=lambda x: x.get('_metric_val', 0), reverse=True)
        total = len(matches)
        # 截斷統計：仿 ApiClient.last_traffic_query_diagnostics 的屬性樣式，
        # 回傳型別不變、既有呼叫者零影響（spec §11.3）
        self.last_query_stats = {
            "total_matches": total,
            "cap": QUERY_RESULT_CAP,
            "truncated": total > QUERY_RESULT_CAP,
        }
        return matches[:QUERY_RESULT_CAP]
```

- [ ] **Step 4: 跑 Analyzer 測試確認通過**

Run: `python3 -m pytest tests/test_analyzer_truncation_stats.py tests/test_analyzer_with_mock_api.py -v`
Expected: 全 PASS。

- [ ] **Step 5: search 端點失敗測試（追加 tests/test_gui_quarantine.py）**

```python
def test_quarantine_search_reports_truncation(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    from src.analyzer import Analyzer, QUERY_RESULT_CAP

    def fake_query(self, params):
        self.last_query_stats = {"total_matches": 1234, "cap": QUERY_RESULT_CAP,
                                 "truncated": True}
        return [{"policy_decision": "allowed"}]

    monkeypatch.setattr(Analyzer, "query_flows", fake_query)
    r = client.post('/api/quarantine/search', json={"mins": 60},
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                    headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    assert r.json["ok"] is True
    assert r.json["total_matches"] == 1234
    assert r.json["truncated"] is True
```

註：search 端點內 analyzer 的建構鏈（`base_ana` 怎麼來，`actions.py:41-110`）若不是直接 `Analyzer` 實例而是包裝物，monkeypatch 目標依實際類別調整。

Run: `python3 -m pytest tests/test_gui_quarantine.py -v -k truncation`
Expected: FAIL（回應無 `total_matches` 鍵）。

- [ ] **Step 6: 實作端點回傳**

`src/gui/routes/actions.py`（111-118 行，`results = base_ana.query_flows(params)` 之後、`return jsonify` 改寫）：

```python
            results = base_ana.query_flows(params)

            for r in results:
                flow_pd = r.get("policy_decision", "")
                if flow_pd == "allowed": r["pd"] = 0
                elif flow_pd == "potentially_blocked": r["pd"] = 1
                else: r["pd"] = 2

            stats = getattr(base_ana, "last_query_stats", {}) or {}
            return jsonify({
                "ok": True,
                "data": results,
                "total_matches": int(stats.get("total_matches", len(results))),
                "truncated": bool(stats.get("truncated")),
                "cap": int(stats.get("cap", 0)),
            })
```

- [ ] **Step 7: 跑測試 + Commit**

Run: `python3 -m pytest tests/test_gui_quarantine.py tests/test_analyzer_truncation_stats.py -v`
Expected: 全 PASS。

```bash
git add src/analyzer.py src/gui/routes/actions.py \
        tests/test_analyzer_truncation_stats.py tests/test_gui_quarantine.py
git commit -m "feat(analyzer): expose query result truncation stats to search API

500-cap truncation was silent; query_flows now records last_query_stats
and /api/quarantine/search returns total_matches/truncated/cap."
```

---

### Task 2: Top 10 route 回傳截斷旗標

**Files:**
- Modify: `src/gui/routes/dashboard.py`（top10 端點，508-589 行）
- Test: `tests/test_gui_dashboard.py`（追加）

**Interfaces:**
- Consumes: `Analyzer.last_query_stats`（Task 1）。
- Produces: top10 端點回應新欄位 `truncated`（bool）、`cap`（int）；Task 3 前端消費。

- [ ] **Step 1: 寫失敗測試（追加 tests/test_gui_dashboard.py，沿用該檔既有 top10 測試的登入/monkeypatch 樣式）**

```python
def test_top10_reports_truncation_flag(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    from tests._helpers import _csrf
    csrf_token = _csrf(login)

    from src.analyzer import Analyzer, QUERY_RESULT_CAP

    def fake_query(self, params):
        self.last_query_stats = {"total_matches": 2000, "cap": QUERY_RESULT_CAP,
                                 "truncated": True}
        return [{"policy_decision": "allowed", "src": {"ip": "10.0.0.1"},
                 "dst": {"ip": "10.0.0.2"}, "service": {"port": 443, "proto": 6},
                 "_metric_val": 1}]

    monkeypatch.setattr(Analyzer, "query_flows", fake_query)
    # top10 端點路徑與 method 以 dashboard.py:464 實際 route 裝飾器為準
    r = client.post('/api/dashboard/top10/run', json={"idx": 0},
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                    headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    assert r.json.get("truncated") is True
    assert r.json.get("cap") == QUERY_RESULT_CAP
```

註：端點 URL、request payload（idx 或整組 query 定義）與既有回應鍵名以 `dashboard.py:464-589` 實際程式為準；若需先建立儲存查詢，仿該檔既有測試先 POST `/api/dashboard/queries`。

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_gui_dashboard.py -v -k truncation_flag`
Expected: FAIL（回應無 `truncated` 鍵）。

- [ ] **Step 3: 實作**

`dashboard.py` top10 端點在 `query_flows` 呼叫（508 行）之後、組回應 dict（580-589 行）處加入：

```python
        stats = getattr(ana, "last_query_stats", {}) or {}
        # 既有回應 dict 增加兩鍵（變數名 ana 以該函式實際命名為準）
        resp["truncated"] = bool(stats.get("truncated"))
        resp["cap"] = int(stats.get("cap", 0))
```

- [ ] **Step 4: 跑測試 + Commit**

Run: `python3 -m pytest tests/test_gui_dashboard.py -v`
Expected: 全 PASS。

```bash
git add src/gui/routes/dashboard.py tests/test_gui_dashboard.py
git commit -m "feat(dashboard): surface query truncation flag in top10 response"
```

---

### Task 3: 前端截斷提示 + i18n

**Files:**
- Modify: `src/static/js/quarantine.js`（`runTrafficAnalyzer` 存回應 meta、`renderQtPage` 總數標籤 387 行）
- Modify: `src/static/js/dashboard.js`（top10 卡片 status badge，`_setStatusWithSourceBadge` 1871 行附近）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_gui_quarantine.py`（i18n 鍵存在斷言，仿 `test_quarantine_translation_keys_present`）

**Interfaces:**
- Consumes: `/api/quarantine/search` 的 `total_matches`/`truncated`/`cap`（Task 1）、top10 的 `truncated`/`cap`（Task 2）。
- Produces: i18n 鍵 `gui_results_truncated`、`gui_top10_truncated`。

- [ ] **Step 1: i18n 鍵（兩檔都加）**

`src/i18n_en.json`：

```json
  "gui_results_truncated": "Showing first {cap} of {total} matches — narrow your filters to see the rest",
  "gui_top10_truncated": "Ranking based on first {cap} matches only",
```

`src/i18n_zh_TW.json`：

```json
  "gui_results_truncated": "僅顯示前 {cap} 筆（共 {total} 筆符合）——請縮小條件以檢視其餘結果",
  "gui_top10_truncated": "排名僅基於前 {cap} 筆結果",
```

i18n 鍵存在測試（追加 tests/test_gui_quarantine.py）：

```python
def test_truncation_translation_keys_present():
    set_language("zh_TW")
    messages = get_messages("zh_TW")
    assert "{cap}" in messages["gui_results_truncated"]
    assert "{cap}" in messages["gui_top10_truncated"]
    en = get_messages("en")
    assert "{cap}" in en["gui_results_truncated"]
    set_language("en")
```

Run: `python3 -m pytest tests/test_gui_quarantine.py -v -k translation`
Expected: 新測試先 FAIL（KeyError）→ 加完兩 JSON 後 PASS。

- [ ] **Step 2: quarantine.js 提示**

`runTrafficAnalyzer` 收回應處（`_qt_data = r.data` 附近，299 行）追加保存 meta：

```javascript
  _qt_data = r.data;
  _qt_meta = { total: r.total_matches || r.data.length, truncated: !!r.truncated, cap: r.cap || 0 };
```

（檔頭宣告 `let _qt_meta = { total: 0, truncated: false, cap: 0 };`，與 `_qt_data` 同區。）

`renderQtPage` 總數標籤（387 行）改為：

```javascript
  if (_qt_meta.truncated) {
    totalLabel.textContent = _t('gui_results_truncated')
      .replace('{cap}', _qt_meta.cap).replace('{total}', _qt_meta.total);
    totalLabel.classList.add('warn-text');
  } else {
    totalLabel.textContent = (_t('gui_total_found')).replace('{count}', total);
    totalLabel.classList.remove('warn-text');
  }
```

`warn-text` 樣式若 `app.css` 沒有，加一條：`.warn-text { color: var(--warn); }`。

- [ ] **Step 3: dashboard.js top10 badge**

top10 結果渲染的 status 處（`_setStatusWithSourceBadge` 呼叫端）追加：回應 `truncated` 為真時在 status 列 append 一個 `span.warn-text`，內容 `_t('gui_top10_truncated').replace('{cap}', resp.cap)`。實作位置以 `_renderTop10Body`（1896-1978 行）收到回應物件的地方為準。

- [ ] **Step 4: 驗證（CSP + 靜態）**

Run: `python3 -m pytest tests/test_csp_compliance.py tests/test_no_external_resources.py tests/test_gui_quarantine.py -q`
Expected: 全 PASS（無 inline script 違規）。

手動驗證（測試機有 PCE）：GUI 模式跑一次寬鬆條件流量查詢（例如 24h 無 filter），確認超過 500 筆時提示出現且數字正確；截圖附在回報。

- [ ] **Step 5: Commit**

```bash
git add src/static/js/quarantine.js src/static/js/dashboard.js \
        src/i18n_en.json src/i18n_zh_TW.json src/static/css/app.css tests/test_gui_quarantine.py
git commit -m "feat(gui): visible truncation warnings for traffic results and top10 ranking"
```

---

### Task 4: 隔離審計 log + 前端二次確認

**Files:**
- Modify: `src/gui/routes/actions.py`（審計 helper + `apply`/`bulk_apply` 接線）
- Modify: `src/static/js/quarantine.js`（`applyQuarantine`，159 行）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（confirm 文案）
- Test: `tests/test_gui_quarantine.py`（追加）

**Interfaces:**
- Produces: 模組層函式 `_audit_action(action: str, **fields) -> None`（`actions.py`；Task 5 的 lift 重用）。

- [ ] **Step 1: 寫失敗測試（追加 tests/test_gui_quarantine.py）**

```python
def test_quarantine_apply_writes_audit_log(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    monkeypatch.setattr("src.api_client.ApiClient.check_and_create_quarantine_labels",
                        lambda self: {"Mild": "/orgs/1/labels/1"})
    monkeypatch.setattr("src.api_client.ApiClient.get_workload",
                        lambda self, href: {"href": href, "labels": []})
    monkeypatch.setattr("src.api_client.ApiClient.update_workload_labels",
                        lambda self, href, labels: True)

    records = []

    class _Rec:
        def info(self, msg):
            records.append(msg)

    from src.module_log import ModuleLog
    monkeypatch.setattr(ModuleLog, "get", classmethod(lambda cls, name: _Rec()))

    r = client.post('/api/quarantine/apply',
                    json={"href": "/orgs/1/workloads/1", "level": "Mild"},
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                    headers={'X-CSRF-Token': csrf_token})
    assert r.json["ok"] is True
    audit = [m for m in records if "quarantine_apply" in m]
    assert len(audit) == 1
    assert "/orgs/1/workloads/1" in audit[0]
    assert "Mild" in audit[0]
    assert "user=admin" in audit[0]


def test_quarantine_bulk_apply_writes_audit_log(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    monkeypatch.setattr("src.api_client.ApiClient.check_and_create_quarantine_labels",
                        lambda self: {"Mild": "/orgs/1/labels/1"})
    monkeypatch.setattr("src.api_client.ApiClient.get_workload",
                        lambda self, href: {"href": href, "labels": []})
    monkeypatch.setattr("src.api_client.ApiClient.update_workload_labels",
                        lambda self, href, labels: True)

    records = []

    class _Rec:
        def info(self, msg):
            records.append(msg)

    from src.module_log import ModuleLog
    monkeypatch.setattr(ModuleLog, "get", classmethod(lambda cls, name: _Rec()))

    client.post('/api/quarantine/bulk_apply',
                json={"hrefs": ["/orgs/1/workloads/1", "/orgs/1/workloads/2"], "level": "Mild"},
                environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                headers={'X-CSRF-Token': csrf_token})
    audit = [m for m in records if "quarantine_bulk_apply" in m]
    assert len(audit) == 1
    assert "success=2" in audit[0]
```

註：`ModuleLog.get` 若是 staticmethod/一般函式而非 classmethod（讀 `src/module_log.py` 確認），monkeypatch 寫法對應調整。

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_gui_quarantine.py -v -k audit`
Expected: 2 FAIL（無審計 log 寫入）。

- [ ] **Step 3: 實作審計 helper + 接線**

`actions.py` 藍圖工廠內（`_is_workload_href` 附近）加：

```python
    def _audit_action(action, **fields):
        """隔離/解除隔離審計 log——best-effort，絕不阻斷主操作（spec §11.1）。"""
        try:
            from src.module_log import ModuleLog as _ML
            try:
                from flask_login import current_user
                user = current_user.get_id() if getattr(current_user, "is_authenticated", False) else "?"
            except Exception:
                user = "?"
            parts = " ".join(f"{k}={v}" for k, v in fields.items())
            _ML.get("actions").info(f"{action}: user={user} {parts}")
        except Exception:
            pass
```

`api_quarantine_apply` 成功/失敗 return 前各加（成功處）：

```python
            success = api.update_workload_labels(href, new_labels)
            _audit_action("quarantine_apply", href=href, level=level,
                          result=("ok" if success else "update_failed"))
```

`api_quarantine_bulk_apply` 組完 `results` 後、return 前加：

```python
            _audit_action("quarantine_bulk_apply", level=level,
                          success=results["success"], failed=len(results["failed"]),
                          skipped_invalid=results["skipped_invalid"],
                          hrefs=",".join(hrefs))
```

- [ ] **Step 4: 前端 confirm + i18n**

i18n 兩檔加：

```json
  "gui_q_confirm_apply": "Quarantine {count} workload(s) at severity {level}?"
```

```json
  "gui_q_confirm_apply": "確定要以嚴重度 {level} 隔離 {count} 台 workload 嗎？"
```

`quarantine.js` `applyQuarantine`（159 行）函式開頭加：

```javascript
  const _n = _qTargets.length || 1;  // 目標數變數名以該函式實際實作為準
  const _lvl = document.querySelector('input[name="q-severity"]:checked')?.value || '';
  if (!confirm(_t('gui_q_confirm_apply').replace('{count}', _n).replace('{level}', _lvl))) return;
```

（目標數與 severity 的取值方式以 `openQuarantineModal`/`applyQuarantine` 現行程式為準，139-190 行。）

- [ ] **Step 5: 跑測試 + Commit**

Run: `python3 -m pytest tests/test_gui_quarantine.py tests/test_csp_compliance.py -q`
Expected: 全 PASS。

```bash
git add src/gui/routes/actions.py src/static/js/quarantine.js \
        src/i18n_en.json src/i18n_zh_TW.json tests/test_gui_quarantine.py
git commit -m "feat(quarantine): audit logging and apply confirmation for isolate actions"
```

---

### Task 5: 解除隔離端點 + UI

**Files:**
- Modify: `src/gui/routes/actions.py`（新端點 `/api/quarantine/lift`）
- Modify: `src/static/js/quarantine.js`（isolated 標籤改按鈕，607 行 + 新 handler）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_gui_quarantine.py`（追加）

**Interfaces:**
- Consumes: `_audit_action`（Task 4）、`_normalize_quarantine_hrefs`/`_is_workload_href`（既有）。
- Produces: `POST /api/quarantine/lift`，request `{"hrefs": [...]}`，response `{"ok": true, "results": {"success": n, "failed": [...], "skipped_invalid": n, "not_quarantined": n}}`。

- [ ] **Step 1: 寫失敗測試**

```python
def test_quarantine_lift_removes_only_quarantine_labels(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    q = {"Mild": "/orgs/1/labels/1", "Moderate": "/orgs/1/labels/2", "Severe": "/orgs/1/labels/3"}
    monkeypatch.setattr("src.api_client.ApiClient.check_and_create_quarantine_labels",
                        lambda self: q)
    monkeypatch.setattr("src.api_client.ApiClient.get_workload", lambda self, href: {
        "href": href,
        "labels": [{"href": "/orgs/1/labels/2"}, {"href": "/orgs/1/labels/77"}],
    })
    calls = []
    monkeypatch.setattr("src.api_client.ApiClient.update_workload_labels",
                        lambda self, href, labels: calls.append((href, labels)) or True)

    r = client.post('/api/quarantine/lift',
                    json={"hrefs": ["/orgs/1/workloads/1"]},
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                    headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    assert r.json["ok"] is True
    assert r.json["results"]["success"] == 1
    assert calls == [("/orgs/1/workloads/1", [{"href": "/orgs/1/labels/77"}])]


def test_quarantine_lift_skips_not_quarantined(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    monkeypatch.setattr("src.api_client.ApiClient.check_and_create_quarantine_labels",
                        lambda self: {"Mild": "/orgs/1/labels/1"})
    monkeypatch.setattr("src.api_client.ApiClient.get_workload", lambda self, href: {
        "href": href, "labels": [{"href": "/orgs/1/labels/77"}]})
    calls = []
    monkeypatch.setattr("src.api_client.ApiClient.update_workload_labels",
                        lambda self, href, labels: calls.append(href) or True)

    r = client.post('/api/quarantine/lift',
                    json={"hrefs": ["/orgs/1/workloads/1", "/orgs/1/labels/9"]},
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                    headers={'X-CSRF-Token': csrf_token})
    assert r.json["results"]["not_quarantined"] == 1
    assert r.json["results"]["skipped_invalid"] == 1
    assert calls == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_gui_quarantine.py -v -k lift`
Expected: 2 FAIL（404）。

- [ ] **Step 3: 實作端點（actions.py，bulk_apply 之後）**

```python
    @bp.route('/api/quarantine/lift', methods=['POST'])
    def api_quarantine_lift():
        """解除隔離：移除 Quarantine 標籤、保留其餘標籤（spec §11.2）。

        隔離是「附加」標籤（見 api_quarantine_apply 第 3 步），原標籤
        未被動過，故解除＝過濾掉 q_hrefs 即可，無需還原機制。
        """
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        raw_hrefs = d.get('hrefs', [])
        hrefs = _normalize_quarantine_hrefs(raw_hrefs)
        try:
            if not hrefs:
                return jsonify({"ok": False, "error": t("gui_q_no_targets", lang=lang)})
            from src.api_client import ApiClient
            api = ApiClient(cm)
            q_hrefs = set(api.check_and_create_quarantine_labels().values())

            invalid_count = sum(1 for h in (raw_hrefs or [])
                                if str(h or "").strip() and not _is_workload_href(h))
            results = {"success": 0, "failed": [], "skipped_invalid": invalid_count,
                       "not_quarantined": 0}
            import concurrent.futures

            def process_wl(href):
                if not _is_workload_href(href):
                    return href, "invalid"
                wl = api.get_workload(href)
                if not wl:
                    return href, "failed"
                current = wl.get("labels", [])
                kept = [{"href": l.get("href")} for l in current
                        if l.get("href") not in q_hrefs]
                if len(kept) == len(current):
                    return href, "not_quarantined"
                return href, ("ok" if api.update_workload_labels(href, kept) else "failed")

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                futures = {ex.submit(process_wl, h): h for h in hrefs}
                for f in concurrent.futures.as_completed(futures):
                    h, st = f.result()
                    if st == "ok":
                        results["success"] += 1
                    elif st == "not_quarantined":
                        results["not_quarantined"] += 1
                    elif st == "failed":
                        results["failed"].append(h)

            _audit_action("quarantine_lift", success=results["success"],
                          failed=len(results["failed"]),
                          not_quarantined=results["not_quarantined"],
                          hrefs=",".join(hrefs))
            return jsonify({"ok": True, "results": results})
        except Exception as e:
            return _err_with_log("quarantine_lift", e, lang=lang)
```

- [ ] **Step 4: 跑端點測試確認通過**

Run: `python3 -m pytest tests/test_gui_quarantine.py -v -k lift`
Expected: 全 PASS。

- [ ] **Step 5: UI（quarantine.js 607 行 isolated 靜態標籤 → 按鈕）+ i18n**

i18n 兩檔加：

```json
  "gui_lift_quarantine": "Lift quarantine",
  "gui_lift_confirm": "Remove quarantine label from this workload?",
  "gui_lift_done": "Quarantine lifted"
```

```json
  "gui_lift_quarantine": "解除隔離",
  "gui_lift_confirm": "確定要移除這台 workload 的隔離標籤嗎？",
  "gui_lift_done": "已解除隔離"
```

`quarantine.js:607` 的 `gui_isolated` 靜態標籤改為按鈕（沿用該列 Isolate 按鈕的建構方式與 class）：

```javascript
  // 已隔離 → 提供解除按鈕（data-action 綁定，CSP 不允許 inline handler）
  btn = h('button', { class: 'btn btn-sm btn-warn', 'data-action': 'liftQuarantine',
                      'data-args': wl.href }, _t('gui_lift_quarantine'));
```

新 handler（與 `applyQuarantine` 同區塊，並在 `_event_dispatcher` 註冊表加 `liftQuarantine`）：

```javascript
async function liftQuarantine(href) {
  if (!confirm(_t('gui_lift_confirm'))) return;
  const r = await post('/api/quarantine/lift', { hrefs: [href] });
  if (r && r.ok && r.results && r.results.success > 0) {
    showToast(_t('gui_lift_done'));   // toast helper 以專案既有者為準
    searchWorkloads();                // 重新整理列表，函式名以現行為準
  } else {
    showToast((r && r.error) || 'failed', true);
  }
}
window.liftQuarantine = liftQuarantine;
```

註：`h()` helper、toast 函式、列表刷新函式的實際名稱以 `quarantine.js` 現行程式為準（559-620 行渲染區、`_event_dispatcher.js` 的註冊方式）。

- [ ] **Step 6: 跑靜態驗證 + Commit**

Run: `python3 -m pytest tests/test_gui_quarantine.py tests/test_csp_compliance.py tests/test_no_external_resources.py -q`
Expected: 全 PASS。

手動驗證（測試機）：隔離一台測試 workload → 列表顯示「解除隔離」→ 點擊確認 → PCE 上 Q 標籤消失、其餘標籤原樣、審計 log 有 `quarantine_lift` 紀錄。結果附在回報。

```bash
git add src/gui/routes/actions.py src/static/js/quarantine.js \
        src/i18n_en.json src/i18n_zh_TW.json tests/test_gui_quarantine.py
git commit -m "feat(quarantine): lift endpoint and per-row unquarantine action"
```

---

### Task 6: 全量回歸

- [ ] **Step 1: 全量測試**

Run: `python3 -m pytest tests/ -q`
Expected: 基準 2237 passed + 本計畫新增（約 10）全 PASS、0 failed。

- [ ] **Step 2: i18n 稽核**

Run: `python3 scripts/audit_i18n_usage.py`（若腳本需參數，看檔頭 usage）
Expected: 新增鍵無缺漏警告。

- [ ] **Step 3: 回報**

回報：測試數字、審計 log 樣本一行、截斷提示與解除隔離的手動驗證結果（含截圖）。

---

## Self-Review 紀錄

- **Spec 覆蓋**：§11.1（審計+確認）→ Task 4；§11.2（lift 端點+UI）→ Task 5；§11.3（截斷統計、search 欄位、分析器提示、top10 badge）→ Task 1/2/3；§11.4 YAGNI 界線已在各任務遵守（未動 500 上限、無 type-to-confirm）。
- **Placeholder 掃描**：無 TBD；所有程式碼步驟含完整程式碼；「以現行程式為準」僅用於變數/函式名對位，均附行號範圍。
- **型別一致性**：`last_query_stats` 三鍵名（Task 1 定義、Task 1 Step 6/Task 2/Task 3 消費一致）；`_audit_action`（Task 4 定義、Task 5 重用）；lift 回應四鍵（Task 5 端點與測試一致）；i18n 鍵名前後一致。
- **已知不確定點（任務內已標註）**：`_make_analyzer` 可否 import、top10 端點實際 URL/回應變數名、`ModuleLog.get` 型態、quarantine.js 內部變數/函式名——實作者現場對位，不盲寫。
