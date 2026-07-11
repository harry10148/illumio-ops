# Deferred Minors Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收斂歷次審查 ledger 的 4 項 Defer 殘項（spec：`docs/superpowers/specs/2026-07-11-deferred-minors-hardening-design.md`）：報表 async 測試隔離、traffic 互動查詢失敗可分辨、any×label_group 明確不支援、IP List exclusion 展開對齊 PCE 語意。

**Architecture:** 全部是既有機制收斂：測試隔離（比照 79c51e3 patch 路徑解析）、`last_fetch_error` 訊號屬性＋analyzer 層 typed exception、FilterBar 序列化/建立/建議三點排除、`_iplist_cidrs` per-list CIDR 差集。單分支 `fix/deferred-minors-hardening` 串行。

**Tech Stack:** 既有（pytest、Flask、loguru、orjson、pandas df_filter、原生 JS、stdlib ipaddress）。

## Global Constraints

- TDD：每 task 先寫 RED 測試（或行為釘），再實作到 GREEN。
- Commit message 英文 conventional-commits；一切輸出（碼、註解、commit、文件）不用 emoji。
- i18n 新鍵三檔流程：`src/i18n_en.json` 加 en 值＋`src/i18n/data/zh_explicit.json` 加 zh 值＋跑 `python3 -m scripts.precompute_zh_translations --write` 重生 `src/i18n_zh_TW.json`（三檔一起 commit）；zh 值遵守 `src/i18n/data/glossary.json`（Label/PCE/Workload 等保留詞不中譯）。
- 本機無 `python`，一律 `python3 -m pytest ...`；每 task 後 `ruff check` 改動 Python 檔（零新增 violations）；改 JS 後 `node --check`。
- 測試只用 `tmp_path`／monkeypatch，不得讀寫 repo 真實 `logs/`、`config/`。
- 全部 task 完成後全套 `python3 -m pytest -q` 綠才可合併。
- 行號以檔案現況為準（本 plan 引用行號來自 2026-07-11 main @570c52b 勘查，可能漂移——以符號/內容定位）。

---

### Task 1: test_reports_async_generate 隔離真實 state.json（spec §A）

**Files:**
- Modify: `tests/test_reports_async_generate.py`（加 autouse 隔離 fixture＋2 個新測試）

**Interfaces:**
- Consumes: `src.gui.routes.reports._resolve_state_file`（from-import 綁定，call-time 查 module global——patch 這個綁定同時涵蓋端點與 worker 執行緒）；`src.state_store.update_state_file`（seed 用）。
- Produces: 本測試檔對 `logs/state.json` 零讀寫；flake 機制固化為可執行釘測試。

- [ ] **Step 1: 證據收集（RED 等價物）**——確認現行測試對真實檔的讀寫：

```bash
python3 - <<'EOF'
import json, os
p = "logs/state.json"
jobs = json.load(open(p)).get("adhoc_report_jobs", {}) if os.path.exists(p) else {}
print("before:", len(jobs))
EOF
python3 -m pytest tests/test_reports_async_generate.py -q
python3 - <<'EOF'
import json, os
p = "logs/state.json"
jobs = json.load(open(p)).get("adhoc_report_jobs", {}) if os.path.exists(p) else {}
print("after:", len(jobs))
EOF
```

Expected: after > before（每個 generate 測試把假 job 寫進 repo 真實檔）。把前後數字記進 task 報告。若環境無 `logs/state.json` 且 after 顯示新建了該檔，同樣成立。

- [ ] **Step 2: 加 autouse 隔離 fixture**——`tests/test_reports_async_generate.py` 檔頭（`_login` 之前）加：

```python
@pytest.fixture(autouse=True)
def isolated_state_file(tmp_path, monkeypatch):
    """Isolate this module from the repo's real logs/state.json.

    /api/reports/generate and /api/reports/jobs/<id> persist and read
    adhoc job records via src.gui.routes.reports._resolve_state_file()
    (= <repo>/logs/state.json). Sharing that file with the rest of the
    suite is an order-dependent flake vector: stale jobs make
    _save_adhoc_job's most-recent-20 prune evict the fresh job (poll 404),
    and full-suite state.json rewrites / .lock contention can drop it
    mid-poll. Same family as commit 79c51e3 (analyzer STATE_FILE flake).
    """
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr(
        "src.gui.routes.reports._resolve_state_file", lambda: state_file)
    return state_file
```

（`_resolve_state_file` 在 reports.py 是 from-import 綁定；worker 執行緒與端點查的是同一個 module global，patch 一處即可。worker 在測試 poll 到 done/error 前就完成寫入，monkeypatch 函式作用域足夠。）

- [ ] **Step 3: 機制釘測試＋隔離驗證測試（先跑確認 RED/GREEN 形態）**——檔尾加：

```python
def _seed_future_jobs(state_file, n=20):
    """塞 n 筆 started_at 在遠未來的假 job（模擬共享 state 檔的髒殘留）。"""
    from src.state_store import update_state_file

    def _merge(data):
        data["adhoc_report_jobs"] = {
            f"stale{i:02d}": {
                "status": "done", "files": [], "error": "",
                "started_at": f"2099-01-01T00:00:{i:02d}+00:00",
                "finished_at": None,
            } for i in range(n)
        }
        return data
    update_state_file(state_file, _merge)


def test_stale_future_jobs_evict_fresh_job(client_logged_in, isolated_state_file):
    """機制釘測試：state.json 殘留 20 筆未來 started_at 的 job 時，新 job 在
    _save_adhoc_job 的 most-recent-20 prune 中「建立當下」即被剔除 → poll 404。
    這就是本檔曾在全套順序中 flake 的注入式重現——共享 repo logs/state.json
    時，外部殘留可讓本檔的 job 憑空消失。隔離 fixture 後僅在刻意注入時發生。"""
    _seed_future_jobs(isolated_state_file)
    with patch("src.report.report_generator.ReportGenerator") as MockGen:
        inst = MockGen.return_value
        inst.generate_from_api.return_value = SimpleNamespace(record_count=5)
        inst.export.return_value = ["/tmp/x/x.html"]
        inst.last_export_errors = {}
        r = client_logged_in.post("/api/reports/generate", json={
            "source": "api", "format": "html",
            "start_date": "2026-01-01T00:00:00Z",
            "end_date": "2026-01-02T23:59:59Z",
        })
        assert r.status_code == 200
        job_id = r.get_json()["job_id"]
        # prune 在 POST 內同步發生：第一個 poll 就是 404，不需等 worker
        assert client_logged_in.get(f"/api/reports/jobs/{job_id}").status_code == 404


def test_jobs_persist_to_isolated_state_file(client_logged_in, isolated_state_file):
    """隔離驗證：job 記錄落在 tmp state 檔（而非 repo logs/state.json）。"""
    import json as _json
    with patch("src.report.report_generator.ReportGenerator") as MockGen:
        inst = MockGen.return_value
        inst.generate_from_api.return_value = SimpleNamespace(record_count=5)
        inst.export.return_value = ["/tmp/x/x.html"]
        inst.last_export_errors = {}
        r = client_logged_in.post("/api/reports/generate", json={
            "source": "api", "format": "html",
            "start_date": "2026-01-01T00:00:00Z",
            "end_date": "2026-01-02T23:59:59Z",
        })
        job_id = r.get_json()["job_id"]
        for _ in range(50):
            s = client_logged_in.get(f"/api/reports/jobs/{job_id}").get_json()
            if s["status"] in ("done", "error"):
                break
            time.sleep(0.1)
        with open(isolated_state_file, encoding="utf-8") as f:
            assert job_id in _json.load(f)["adhoc_report_jobs"]
```

- [ ] **Step 4: GREEN＋污染復驗＋迴歸**

Run: `python3 -m pytest tests/test_reports_async_generate.py -q` → 5 個測試全 PASS；重跑 Step 1 的前後計數腳本 → before == after（不再污染）。
Run: `python3 -m pytest tests/ -q -k "reports" && ruff check tests/test_reports_async_generate.py`
Expected: 全 PASS、ruff 零新增。

- [ ] **Step 5: Commit** — `fix(test): isolate reports async-generate tests from repo state file`

---

### Task 2: traffic 互動查詢失敗可分辨（spec §B）

**Files:**
- Modify: `src/exceptions.py`（新增 `TrafficQueryError`）
- Modify: `src/api/traffic_query.py`（`execute_traffic_query_stream` except 分支補訊號）
- Modify: `src/analyzer.py`（`query_flows` 耗盡後檢查→raise）
- Modify: `src/gui/routes/actions.py`（quarantine search 捕捉→502）、`src/gui/routes/dashboard.py`（top-actions 同）
- Modify: `src/i18n_en.json`＋`src/i18n/data/zh_explicit.json`＋重生 `src/i18n_zh_TW.json`（新鍵 `gui_err_traffic_query_failed`）
- Test: `tests/test_traffic_query_retry.py`（擴充）、新檔 `tests/test_query_flows_error_surface.py`、`tests/test_gui_quarantine.py`（擴充）

**Interfaces:**
- Consumes: `ApiClient.last_fetch_error` 慣例（H-Task 1 已覆蓋 submit/no-href/failed/timeout/download 五分支；submit 開頭清 None、重下載復原清 None）；`Analyzer.last_query_source`（"api"/"mixed"/"cache"）。
- Produces: `TrafficQueryError(APIError)`——只由 `Analyzer.query_flows` raise，API 層 generator 維持「空 yield＋訊號屬性」契約（ingest 路徑 `_fetch_window` 零改動）。GUI 回 `{"ok": false, "error": <i18n>}` HTTP 502；前端 `quarantine.js:293` 既有 `if (!r.ok || r.error) throw` 錯誤列渲染直接生效，JS 零改動。

- [ ] **Step 1: 讀現場**——確認 `src/api/traffic_query.py` `execute_traffic_query_stream` 的 `except Exception`（:899-902 一帶）現況只 log＋print 後裸 return；確認 `src/analyzer.py` `query_flows` 的 `if not traffic_stream: return []`（:1467）與比對迴圈結束點；確認 `actions.py api_quarantine_search`／`dashboard.py` top-actions 端點的既有 except 結構與 lang 取用慣例（catch 子句要插在泛用 except 之前、i18n 呼叫照該端點現有寫法帶或不帶 lang）。

- [ ] **Step 2: API 層測試（RED）**——`tests/test_traffic_query_retry.py` 照既有 mock 樣式加：

```python
def test_stream_exception_sets_last_fetch_error(...):
    # monkeypatch builder 讓 _build_native_traffic_payload 丟 ValueError
    # （或照該檔既有手法讓 stream 內部炸出非 APIError 例外）
    flows = list(client.execute_traffic_query_stream("2026-01-01T00:00:00Z",
                 "2026-01-02T00:00:00Z", ["blocked"]))
    assert flows == []
    assert client.last_fetch_error is not None
    assert "exception" in client.last_fetch_error.lower()
```

Run: `python3 -m pytest tests/test_traffic_query_retry.py -q` → 新測試 FAIL（現行 except 不設訊號）。

- [ ] **Step 3: API 層實作**——`except Exception` 分支 return 前加：

```python
            if not c.last_fetch_error:
                c.last_fetch_error = f"traffic query exception: {e}"
```

（`_request` 層丟的 `APIError` 已自行設過訊號，`if not` 保留較精確的底層描述。）

- [ ] **Step 4: exceptions＋analyzer 層測試（RED）**——`src/exceptions.py` 加：

```python
class TrafficQueryError(APIError):
    """Interactive traffic query failed on the PCE side (submit/poll/download).

    Raised by Analyzer.query_flows so GUI callers can distinguish "query
    failed" from "0 flows matched". The API-layer generator never raises
    this: ingest depends on its empty-yield + last_fetch_error contract.
    """
```

新檔 `tests/test_query_flows_error_surface.py`（Analyzer 建構照 `tests/test_analyzer_object_filters.py` 既有 stub 樣式；核心兩測試）：

```python
def test_query_flows_raises_on_api_fetch_error(analyzer_fixture, monkeypatch):
    ana = analyzer_fixture  # 照 test_analyzer_object_filters.py 的建構樣式
    monkeypatch.setattr(ana, "_fetch_query_flows",
                        lambda *a, **kw: (iter([]), "api"))
    ana.api.last_fetch_error = "submit failed: 406 - unsupported payload"
    with pytest.raises(TrafficQueryError, match="406"):
        ana.query_flows({"start_time": "2026-01-01T00:00:00Z",
                         "end_time": "2026-01-02T00:00:00Z"})


def test_query_flows_empty_without_error_returns_list(analyzer_fixture, monkeypatch):
    ana = analyzer_fixture
    monkeypatch.setattr(ana, "_fetch_query_flows",
                        lambda *a, **kw: (iter([]), "api"))
    ana.api.last_fetch_error = None
    assert ana.query_flows({"start_time": "2026-01-01T00:00:00Z",
                            "end_time": "2026-01-02T00:00:00Z"}) == []
```

（另加一個 `("cache")` 來源＋殘留 last_fetch_error 不 raise 的對照測試，釘住「僅 api/mixed 檢查」。）

Run: `python3 -m pytest tests/test_query_flows_error_surface.py -q` → FAIL。

- [ ] **Step 5: analyzer 實作**——`Analyzer` 加私有方法並在兩處呼叫：

```python
    def _raise_if_query_fetch_failed(self) -> None:
        """互動查詢失敗須可分辨（spec §B）：API/混合來源在串流耗盡後，
        last_fetch_error 非空即代表本次查詢在 PCE 側失敗（submit 406、
        poll failed/timeout、download 失敗、stream 例外），不得與 0 筆
        同形回傳。cache/archive 來源不打 PCE，不檢查。"""
        if self.last_query_source in ("api", "mixed"):
            err = getattr(self.api, "last_fetch_error", None)
            if err:
                raise TrafficQueryError(str(err))
```

呼叫點一：`if not traffic_stream:` 分支內 `return []` 前（mixed 空結果但 gap 拉取失敗）；呼叫點二：`for f in traffic_stream:` 比對迴圈結束後、排序/回傳之前。import 加 `from src.exceptions import TrafficQueryError`。

- [ ] **Step 6: GUI 層測試（RED）**——`tests/test_gui_quarantine.py` 照既有 client 樣式加：

```python
def test_quarantine_search_surfaces_query_failure(client_logged_in_or_equiv):
    with patch("src.analyzer.Analyzer.query_flows",
               side_effect=TrafficQueryError("submit failed: 406 - bad payload")):
        r = <POST /api/quarantine/search with minimal payload>
        assert r.status_code == 502
        body = r.get_json()
        assert body["ok"] is False
        assert "406" in body["error"]
```

Run: `python3 -m pytest tests/test_gui_quarantine.py -q` → FAIL（現行泛用 except 回別的形狀或 ok:true 空資料）。

- [ ] **Step 7: GUI 實作＋i18n 三檔**——`actions.py api_quarantine_search` 與 `dashboard.py` top-actions 的泛用 except 之前各加：

```python
        except TrafficQueryError as e:
            return jsonify({"ok": False, "error": t(
                "gui_err_traffic_query_failed", detail=str(e))}), 502
```

（lang 帶法照各端點現場慣例；import `TrafficQueryError`。）

i18n：`src/i18n_en.json` 字母序位置加

```json
"gui_err_traffic_query_failed": "Traffic query failed on the PCE side: {detail}",
```

`src/i18n/data/zh_explicit.json` 對應加

```json
"gui_err_traffic_query_failed": "PCE 流量查詢失敗：{detail}",
```

Run: `python3 -m scripts.precompute_zh_translations --write`（重生 `src/i18n_zh_TW.json`；glossary 檢查由腳本執行——PCE 為保留詞，無違規）。

- [ ] **Step 8: GREEN＋迴歸（含 ingest 不變釘）**

Run: `python3 -m pytest tests/test_traffic_query_retry.py tests/test_query_flows_error_surface.py tests/test_gui_quarantine.py tests/ -q -k "traffic_query or ingest or watchdog or quarantine or i18n" && ruff check src/api/traffic_query.py src/analyzer.py src/gui/routes/actions.py src/gui/routes/dashboard.py src/exceptions.py tests/test_query_flows_error_surface.py`
Expected: 全 PASS——特別確認 ingest/watchdog 既有測試不變綠（API 層契約未動）。

- [ ] **Step 9: Commit** — `fix(analyzer): surface PCE traffic query failures to interactive callers`

---

### Task 3: any 方向明確不支援 label_group（spec §C，採 (b) 案）

**Files:**
- Modify: `src/static/js/filter-bar.js`（序列化 :79、`_objfbAddPill` :130、hint 區 :246-250、suggest types :492、分類快選 :342、suggest 結果迭代 :545、`_objfbAddDir` :683）
- Modify: `src/i18n_en.json`＋`src/i18n/data/zh_explicit.json`＋重生 `src/i18n_zh_TW.json`（新鍵 `gui_fb_any_label_group_unsupported`）
- Test: `tests/test_component_object_filter_bar.py`（擴充；該檔是靜態文字斷言樣式，無 JS runtime）

**Interfaces:**
- Consumes: `state.addDir`／`state.cats`／既有 `gui_fb_any_slow` hint 列寫法（data-i18n）＋ `_OBJFB_SUGGEST_CATS`。
- Produces: any 方向下 label_group 不可選、不可建、不序列化；其餘方向與其他類別行為零變更。後端與 CLI 零改動（設計文件 §C 已裁決：`any_label_group` key 不存在於任何白名單、CLI 無 any 槽位）。

- [ ] **Step 1: 靜態斷言測試（RED）**——`tests/test_component_object_filter_bar.py` 照該檔樣式加：

```python
def test_any_direction_label_group_not_serialized_as_any_label():
    src = _JS.read_text(encoding="utf-8")
    # 舊映射（語意靜默錯誤：group 名被當 label 查）必須消失
    assert "setScalar(`${ex}any_label`, p.name);" in src  # label 分支仍在
    assert src.count("setScalar(`${ex}any_label`") == 1   # label_group 分支不再共用
    # 序列化端防禦性 skip 必須存在
    assert "label_group pill is not supported for the any direction" in src


def test_any_direction_label_group_pill_guard_present():
    src = _JS.read_text(encoding="utf-8")
    assert "obj.cat === 'label_group' && state.addDir === 'any'" in src


def test_any_label_group_i18n_hint_present():
    import json
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    assert "gui_fb_any_label_group_unsupported" in en
    assert "gui_fb_any_label_group_unsupported" in zh
    assert "gui_fb_any_label_group_unsupported" in _JS.read_text(encoding="utf-8")
```

Run: `python3 -m pytest tests/test_component_object_filter_bar.py -q` → 新 3 測試 FAIL。

- [ ] **Step 2: 序列化端防禦（:73-80 區塊）**——`_objfbSerialize` 的 any 分支改為：

```javascript
    if (p.dir === 'any') {
      // any 方向：Phase 1 單值 key（多個同類取最後值）
      if (p.cat === 'label')         setScalar(`${ex}any_label`, p.name);
      else if (p.cat === 'iplist')   setScalar(`${ex}any_iplist`, p.href || p.name);
      else if (p.cat === 'workload') setScalar(`${ex}any_workload`, p.href);
      else if (p.cat === 'ip')       setScalar(`${ex}any_ip`, p.name);
      else if (p.cat === 'label_group') {
        // any 方向不支援 label_group（design §C）：不得降格成 any_label
        // （group 名被當 label spec，fallback 比對 fail-closed 0 筆）。
        // 正常流程在 _objfbAddPill 已擋，這裡是序列化邊界的防禦性拒絕。
        console.warn('objfb: label_group pill is not supported for the any direction; skipped:', p.name);
      }
      continue;
    }
```

- [ ] **Step 3: pill 建立拒絕＋hint**——`_objfbAddPill` 函式開頭加 guard：

```javascript
function _objfbAddPill(state, obj) {
  if (obj.cat === 'label_group' && state.addDir === 'any' && !_OBJFB_DIRLESS.has(obj.cat)) {
    // any 方向不支援 label_group：不建 pill，顯示提示（design §C）
    state.anyLabelGroupHint = true;
    _objfbRender(state);
    return;
  }
  state.anyLabelGroupHint = false;
  ...（原內容不動）
```

hint 列（比照 :246-250 的 `gui_fb_any_slow` 寫法，緊接其後）：

```javascript
      // any 方向不支援 label_group 的提示（嘗試建立時顯示，換方向清除）
      const lgHint = document.createElement('div');
      lgHint.className = 'objfb-hint';
      lgHint.setAttribute('data-i18n', 'gui_fb_any_label_group_unsupported');
      lgHint.hidden = !state.anyLabelGroupHint;
      c.appendChild(lgHint);
```

（與既有 `gui_fb_any_slow` hint 完全同構：只設 `data-i18n` 與 `hidden`，文字由頁面既有 data-i18n 翻譯機制套用，JS 不自行取字串；`_objfbAddDir` 切換方向時 `state.anyLabelGroupHint = false` 一併清除。）

- [ ] **Step 4: suggest 三點排除**——
  1. `_objfbQuerySuggest`（:492）types 導出改：

```javascript
  const types = scope ? scope : _OBJFB_SUGGEST_CATS.filter((c) =>
    state.cats.includes(c) && !(state.addDir === 'any' && c === 'label_group')).join(',');
```

（join 分隔符照現場既有寫法。）
  2. 下拉分類快選鈕（:342）filter 條件加 `&& !(state.addDir === 'any' && c === 'label_group')`。
  3. suggest 結果迭代（:545）同條件過濾（避免方向切到 any 後殘留回應仍渲染 label_group 區塊）。
  4. `_objfbAddDir`（:683）：切到 `'any'` 時若 `s.scopeCat === 'label_group'` 呼叫既有 `_objfbClearScope` 清除。

- [ ] **Step 5: i18n 三檔**——`src/i18n_en.json` 在 `gui_fb_any_slow` 附近（字母序）加：

```json
"gui_fb_any_label_group_unsupported": "Label groups are not supported for the S/D (any) direction. Add separate source and destination Label Group conditions instead.",
```

`src/i18n/data/zh_explicit.json` 對應加：

```json
"gui_fb_any_label_group_unsupported": "S/D（any）方向不支援 Label Group，請分別加入來源與目的 Label Group 條件。",
```

Run: `python3 -m scripts.precompute_zh_translations --write`（glossary：Label 為保留詞，zh 文案保留英文 Label Group——無違規）。

- [ ] **Step 6: GREEN＋語法＋迴歸**

Run: `node --check src/static/js/filter-bar.js && python3 -m pytest tests/test_component_object_filter_bar.py tests/test_component_filter_bar.py tests/ -q -k "filter_bar or i18n or suggest" && git diff --stat`
Expected: node 語法過、測試全 PASS、diff 只含 filter-bar.js＋i18n 三檔＋測試檔。

- [ ] **Step 7: Commit** — `fix(gui): reject label_group pills in any direction instead of silently degrading to any_label`

---

### Task 4: IP List exclusion ranges 對齊 PCE 語意（spec §D）

**Files:**
- Modify: `src/api/labels.py`（`expand_object_filters_for_df` 內部的 `_iplist_cidrs` :593-613 改寫＋兩個內部 helper）
- Test: `tests/test_object_filter_df_expand.py`（擴充；照該檔既有 fake client fixture 樣式）

**Interfaces:**
- Consumes: `c.get_ip_lists()` 回傳的 `ip_ranges` 條目（`from_ip`/`to_ip`/`exclusion`）。
- Produces: `_iplist_cidrs` 回傳「inclusion 聯集 − exclusion 聯集」的扁平 CIDR list——`df_filter`／`report_generator`／`_*_object_cidrs` 內部 key 消費端零改動；native 與 fallback 路徑本已正確（design §D 查證），不動。

- [ ] **Step 1: 失敗測試（RED）**——`tests/test_object_filter_df_expand.py` 照既有樣式加 5 個案例（fake client 的 `get_ip_lists` 回帶 exclusion 條目的 IP List）：

```python
def test_iplist_exclusion_subtracted_from_inclusion(resolver_fixture):
    # ip_ranges: [{"from_ip": "10.0.0.0/24"}, {"from_ip": "10.0.0.128/25", "exclusion": True}]
    out = resolver.expand_object_filters_for_df({"src_iplists": ["corp"]})
    assert sorted(out["_src_object_cidrs"]) == ["10.0.0.0/25"]

def test_iplist_exclusion_only_yields_empty(resolver_fixture):
    # ip_ranges 只有 exclusion 條目 → 展開為空（key 不產生）
    out = resolver.expand_object_filters_for_df({"src_iplists": ["excl-only"]})
    assert "_src_object_cidrs" not in out

def test_iplist_exclusion_range_form(resolver_fixture):
    # exclusion 用 from-to range 形：include 10.0.0.0/24、exclude 10.0.0.128-10.0.0.255
    assert sorted(...) == ["10.0.0.0/25"]

def test_iplist_exclusion_disjoint_is_noop(resolver_fixture):
    # exclusion 192.168.0.0/24 與 inclusion 10.0.0.0/24 相離 → 原樣
    assert sorted(...) == ["10.0.0.0/24"]

def test_multi_iplist_union_not_cross_subtracted(resolver_fixture):
    # list A: include 10.0.0.0/24 + exclusion 10.1.0.0/16
    # list B: include 10.1.0.0/16（無 exclusion）
    # per-list 扣除：A 的 exclusion 不得吃掉 B 的 inclusion（OR 聯集語意）
    out = resolver.expand_object_filters_for_df({"src_iplists": ["A", "B"]})
    assert "10.1.0.0/16" in out["_src_object_cidrs"]
```

（fixture／resolver 建構、斷言 key 形狀照該檔既有測試；exclusion-only 案例的「key 不產生」對齊 :637 `if cidrs:` 既有行為。）

Run: `python3 -m pytest tests/test_object_filter_df_expand.py -q` → 新 5 測試 FAIL（現行把 exclusion 一併展開）。

- [ ] **Step 2: 實作**——`_iplist_cidrs` 改為（helper 同層定義，維持閉包用 `c` 與 `logger` 的現狀）：

```python
        def _range_to_cidrs(r, list_name):
            frm = r.get("from_ip")
            to = r.get("to_ip")
            if not frm:
                return []
            if not to or "/" in frm:
                return [frm]
            try:
                return [str(n) for n in ipaddress.summarize_address_range(
                    ipaddress.ip_address(frm), ipaddress.ip_address(to))]
            except ValueError:
                logger.warning("Bad ip_range in {}: {}-{}", list_name, frm, to)
                return []

        def _subtract_cidrs(include, exclude):
            """per-IP List 的 CIDR 集合差（PCE 語意：exclusion 從 inclusion
            扣除）。range 已先化為 CIDR，兩 CIDR 非相離即巢狀，逐一
            address_exclude 即為精確差集。無法解析的 inclusion 字串原樣
            保留（fail-open 保守：寧可 over-include 也不無聲丟 inclusion）。"""
            if not exclude:
                return include
            passthrough, inc_nets, exc_nets = [], [], []
            for s in include:
                try:
                    inc_nets.append(ipaddress.ip_network(str(s).strip(), strict=False))
                except ValueError:
                    passthrough.append(s)
            for s in exclude:
                try:
                    exc_nets.append(ipaddress.ip_network(str(s).strip(), strict=False))
                except ValueError:
                    pass  # 解析不了的 exclusion 忽略（無從扣除）
            for exc in exc_nets:
                remaining = []
                for n in inc_nets:
                    if n.version != exc.version or not n.overlaps(exc):
                        remaining.append(n)
                    elif exc.supernet_of(n):
                        continue  # 整塊被排除
                    else:  # n 真包含 exc → 切分
                        remaining.extend(n.address_exclude(exc))
                inc_nets = remaining
            return passthrough + [str(n) for n in inc_nets]

        def _iplist_cidrs(value):
            """IP List → 有效 CIDR 清單（inclusion 聯集 − exclusion；PCE 語意）。
            修正前 exclusion:true 條目被一併展開成 inclusion，cache df 路徑
            over-include；native（PCE 端自套 exclusion）與 fallback
            （_iplist_hit 比 PCE 標注 membership）本已正確——修這裡即三路一致。"""
            value = str(value).strip()
            for ipl in (c.get_ip_lists() or []):
                if ipl.get("name") == value or ipl.get("href") == value:
                    include, exclude = [], []
                    for r in ipl.get("ip_ranges", []) or []:
                        bucket = exclude if r.get("exclusion") else include
                        bucket.extend(_range_to_cidrs(r, value))
                    return _subtract_cidrs(include, exclude)
            return []
```

- [ ] **Step 3: GREEN＋迴歸**

Run: `python3 -m pytest tests/test_object_filter_df_expand.py tests/test_df_filter.py tests/ -q -k "object_filter or df_filter or iplist" && ruff check src/api/labels.py tests/test_object_filter_df_expand.py`
Expected: 全 PASS（既有無 exclusion 條目的展開測試逐位元不變——`_subtract_cidrs` 在 `exclude` 空時原樣回傳）。

- [ ] **Step 4: Commit** — `fix(api): honor ip_list exclusion ranges in cache df expansion`

---

## 收尾

全部 task 完成後：`python3 -m pytest -q` 全套綠 → whole-branch review → 合入 main → push。部署測試機後可抽驗：GUI quarantine search 造一個必 406 的查詢（或暫斷 PCE 憑證）確認錯誤列取代 0 列（Task 2）；FilterBar 切 any 方向確認 label_group 不出現在建議（Task 3）。

## Self-Review 紀錄

- Spec 覆蓋：§A=Task 1、§B=Task 2、§C=Task 3、§D=Task 4；§3 非目標未混入（無產品碼 prune 改動、無 any_label_group 全鏈、無 fallback/native iplist 改動）。
- ingest 語意保護：Task 2 僅在 analyzer 層 raise，API generator 契約不變；Step 8 明定跑 ingest/watchdog 迴歸釘。
- i18n：Task 2/3 各一個新鍵，三檔 precompute 流程＋glossary 核對（PCE、Label 保留詞）已載明。
- 佔位掃描：各 task 代碼完整；「照該檔既有樣式」僅限 fixture/建構細節且均指名具體參照檔（test_analyzer_object_filters.py、test_gui_quarantine.py、test_object_filter_df_expand.py 既有測試），非 TBD。
- 行號漂移防護：Global Constraints 已載明以符號定位。
