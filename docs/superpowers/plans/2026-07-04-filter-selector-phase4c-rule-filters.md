# Filter 物件選擇器 Phase 4c：規則引擎路徑（traffic/bandwidth/volume 告警規則）— Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 monitor 告警規則（traffic/bandwidth/volume）支援 FilterBar 的物件/複數 filter key（複數 label、iplist、workload、any_*、list 形 IP），規則 modal 換 FilterBar；label_group 在規則路徑**明確拒絕**（結構性不可支援，非靜默丟棄）。

**Architecture:** 規則引擎與 dashboard 查詢共用 `check_flow_match`，但規則的 flow 來源是**共用未過濾 stream**（cache subscriber `poll_new_rows` 或 legacy 未過濾 API stream，analyzer.py:729-750）——沒有 PCE native 過濾可借力，所有語意必須 client-side 完成。Phase 4b 已在 `query_flows` 建立分工樣板（`_OBJECT_FILTER_KEYS` 投影 → `TrafficQueryBuilder._flow_matches_filters` 委派，analyzer.py:1193-1206）；本批把該樣板抽成共用 helper 並套到規則引擎兩個比對點（`_run_rule_engine` analyzer.py:802、規則測試路徑 analyzer.py:1464）。label_group 需要成員展開（不存在 client-side 實作）且規則路徑無 cache-bypass 可用 → 明確不支援：前端 FilterBar 用 `opts.cats` 排除 label_group 類別、後端收到 `*_label_groups` 回 400。

**Tech Stack:** Python（analyzer/Flask rules.py）、vanilla JS（FilterBar 重用，rules.js）、pytest + Playwright MCP（controller 實機）。

**Spec:** `docs/superpowers/specs/2026-07-03-pce-style-filter-object-selector-design.md` §10（分批）。

## 設計定案（基於 2026-07-04 Explore 盤點）

- **現場事實**：
  - 規則存 `alerts.json`（`cm.config["rules"]`，Rule model `extra="allow"`，config_models.py:205）；現行欄位只有 legacy 純量（`src_label`/`dst_label`/`src_ip_in`/`dst_ip_in`/`ex_*` scalar + port/proto/threshold_*，rules.py:169-186）；**規則連 any_* 都沒有**（GUI 無欄位）。
  - 規則儲存端點：`POST /api/rules/traffic`（rules.py:140）、`POST /api/rules/bandwidth`（rules.py:189）、`PUT /api/rules/<int:idx>`（rules.py:242）。`src`/`dst` 文字用 `'=' in src` 啟發式拆 label/IP（rules.py:150-151）。
  - 比對點：`_run_rule_engine`（analyzer.py:768-841，:802 呼叫 `check_flow_match`）與規則測試預覽（analyzer.py:1464）。
  - 可重用：`_OBJECT_FILTER_KEYS`（analyzer.py:45-52，22 key）、`_flow_matches_filters` 支援複數 labels/iplists/workloads/any_label/any_ip/any_iplist/any_workload + port/proto（traffic_query.py:756-845）、4b 分工樣板（analyzer.py:1193-1206）。
  - GUI：traffic modal `tr-*`（index.html 約 2652-2701：tr-src/tr-dst/tr-exsrc/tr-exdst 要換，tr-name/tr-pd/tr-port/tr-proto/tr-expt/tr-cnt/tr-win/tr-cd 保留）；bandwidth modal `bw-*`（約 2715-2768 同型）。rules.js `saveTraffic()`(523)/`saveBw()`(529)/`editRule()`(416，回填 `$('tr-src').value = r.src_label || r.src_ip_in`)。
- **label_group 決定（本批核心設計）**：規則路徑**不支援** label_group。理由：flow 來源是共用未過濾 stream（無 native 可轉嫁）、無 client-side 成員展開實作、dashboard 的 cache-bypass 策略在此不適用（bypass 了也還是未過濾 stream）。落實三道：(1) 前端規則 FilterBar `createFilterBar(el, {cats: ['label','iplist','workload','ip']})` 不提供 label_group 類別；(2) 後端儲存端點收到任何 `*_label_groups`/`*_label_group` key 回 400 + i18n 錯誤訊息（防禦、非靜默）；(3) Task 4 回報明列此限制。
- **儲存格式**：沿 4b 樣式——請求帶 `filters` dict（FilterBar getFilters()）走新分支 flat 展平存 rule dict（只存 truthy）；無 `filters` 走既有啟發式分支不動。規則版 whitelist = 24 key（4b 的 28 key 減 4 個 label_groups key）。
- **比對引擎**：抽 `Analyzer._match_flow_filters(rule, flow, window_start)` 共用 helper = `check_flow_match(rule, flow, window_start)` AND `_flow_matches_filters(flow, object 投影)`（投影非空才呼叫）。三個呼叫點統一：`_run_rule_engine`:802、規則測試:1464、`query_flows`:1202-1206（後者行為不變，對照測試鎖）。`check_flow_match` 對未知 key pass-through、4b 已 list-aware IP——不再動它本身。
- **cache subscriber flow 形狀**：`poll_new_rows` 的列須與 `_flow_matches_filters` 讀的欄位（`src.ip_lists`/`workload.labels` 等）同形——4b 已驗 reader `raw_json` 原封 PCE dict；subscriber 端 Task 1 現場驗證（具名風險）。

## Global Constraints

- 程式內註解繁體中文、commit message 英文 conventional commits、不用 emoji。
- 只動各 Task 列出的檔案；不順手重構。
- 新 UI/錯誤字串進 `src/i18n_en.json` 與 `src/i18n_zh_TW.json` 雙語同步（label_group 拒絕訊息需新鍵 `gui_rule_label_group_unsupported`）。
- **JS 繁中註解格式**：`//` 行首或 `*`-前綴 JSDoc；禁行尾 `code // 中文`。
- CSP：不引入 inline handler。
- 每 Task 結尾跑該 Task 測試 + commit；Task 4 全量（基準以執行時 main 為準，約 2496 passed / 5 skipped）。
- **worktree 紀律**：每個 Bash 命令以絕對 worktree 路徑 `cd` 前綴，commit 前 `git rev-parse --show-toplevel` 驗證；controller 每 task 驗 parent SHA + `git branch --contains`。
- **測試驗真實鏈**：規則引擎測試餵真實形狀的 flow dict 走 `_run_rule_engine`/`_match_flow_filters`，不 stub 比對器。
- **兩套比對器對帳原則（4b 教訓）**：任何 key 語意變更必須同時檢查 `check_flow_match` 與 `_flow_matches_filters` 兩邊，並在報告列對帳表。

---

### Task 1: analyzer 抽共用比對 helper + 規則引擎接物件 key

**Files:**
- Modify: `src/analyzer.py`（新增 `_match_flow_filters`；`_run_rule_engine` :802、規則測試 :1464、`query_flows` :1202-1206 三處改用）
- Test: `tests/test_analyzer_object_filters.py`（追加規則引擎段）

**Interfaces:**
- Produces: `Analyzer._match_flow_filters(rule: dict, flow: dict, window_start) -> bool`——`check_flow_match` AND（物件投影非空時）`TrafficQueryBuilder._flow_matches_filters(flow, projection)`。投影 key = `_OBJECT_FILTER_KEYS`（不含 label_groups——它們在 `_CACHE_UNEVALUABLE_FILTER_KEYS`，規則端點會拒收，此處防禦性忽略並 debug log）。
- Consumes: `_OBJECT_FILTER_KEYS`（analyzer.py:45-52）、`check_flow_match`、`_flow_matches_filters`。

- [ ] **Step 1: 寫失敗測試（追加 tests/test_analyzer_object_filters.py，沿用該檔 4b 建立的 flow fixture 樣式）**

```python
class TestRuleEngineObjectFilters:
    """規則引擎（_run_rule_engine 路徑）的物件/複數 key 比對——Phase 4c。
    修前 check_flow_match 對未知 key pass-through，物件 filter 規則會誤發告警。"""

    def _rule(self, **kw):
        base = {"type": "traffic", "name": "R", "pd": -1,
                "threshold_type": "count", "threshold_count": 1, "threshold_window": 10}
        base.update(kw)
        return base

    def test_rule_plural_src_labels_or_semantics(self, analyzer_with_flows):
        # src_labels 複數：同 key OR——app=erp 或 app=web 命中
        matched = analyzer_with_flows.match(self._rule(src_labels=["app=erp", "app=web"]))
        assert matched == {"erp-flow", "web-flow"}

    def test_rule_src_iplists_href_match(self, analyzer_with_flows):
        matched = analyzer_with_flows.match(self._rule(src_iplists=["/orgs/1/sec_policy/active/ip_lists/7"]))
        assert matched == {"iplist-flow"}

    def test_rule_any_workload_either_side(self, analyzer_with_flows):
        matched = analyzer_with_flows.match(self._rule(any_workload="/orgs/1/workloads/abc"))
        assert matched == {"wl-src-flow", "wl-dst-flow"}

    def test_rule_object_key_no_false_alert(self, analyzer_with_flows):
        # 修前行為：未知 key pass-through → 全部誤命中（本測試是 RED 主鎖）
        matched = analyzer_with_flows.match(self._rule(src_labels=["app=nonexistent"]))
        assert matched == set()

    def test_rule_legacy_scalar_parity(self, analyzer_with_flows):
        # legacy 純量 key 行為逐位不變
        matched = analyzer_with_flows.match(self._rule(src_label="app=erp"))
        assert matched == {"erp-flow"}
```

註：`analyzer_with_flows` fixture 構造 Analyzer 實例 + 真實形狀 flow dicts（含 `src.ip_lists`/`src.workload.href`/`workload.labels`——照該檔 4b 既有 fixture），`match()` helper 走 `_match_flow_filters`（或以最小 stub 的 `_run_rule_engine` 呼叫路徑，以現場既有測試樣式為準；不可 stub 比對器本身）。flow 命名（"erp-flow" 等）用 flow dict 內可識別欄位對映。

Run: `python3 -m pytest tests/test_analyzer_object_filters.py -v -k RuleEngine`
Expected: `no_false_alert` 與物件 key 測試 FAIL（pass-through 誤命中）、`legacy_scalar_parity` PASS。

- [ ] **Step 2: 實作**

analyzer.py 新增（放 `check_flow_match` 附近）：

```python
    def _match_flow_filters(self, rule, flow, window_start):
        """統一的 flow×filter 比對：legacy 純量 key 走 check_flow_match（含
        pd/時間窗/port/proto/list 形 IP），物件/複數 key 投影委派給報表路徑
        同一套 _flow_matches_filters（兩者 AND）。三個呼叫點共用：規則引擎、
        規則測試預覽、dashboard query_flows。label_groups 類 key 無 client-side
        成員展開——規則端點拒收、query_flows 走 cache-bypass；此處防禦性忽略
        並記 debug（不可靜默影響比對結果）。"""
        if not self.check_flow_match(rule, flow, window_start):
            return False
        object_rule = {k: rule[k] for k in _OBJECT_FILTER_KEYS if rule.get(k)}
        if object_rule:
            from src.api.traffic_query import TrafficQueryBuilder
            if not TrafficQueryBuilder._flow_matches_filters(flow, object_rule):
                return False
        return True
```

（import 放置與既有 query_flows 委派段一致；若 4b 已在模組層 import 則直接用。）三個呼叫點改用：
- `_run_rule_engine` :802 的 `check_flow_match(rule, f, r_start)` → `self._match_flow_filters(rule, f, r_start)`。
- 規則測試路徑 :1464 同改。
- `query_flows` :1202-1206 的分工段改呼叫 `self._match_flow_filters(rule, f, start_dt)`（刪去就地投影，行為不變）。

- [ ] **Step 3: 跑測試（新增 + 4b 既有對照不回歸）**

Run: `python3 -m pytest tests/test_analyzer_object_filters.py tests/test_gui_dashboard.py -q`
Expected: 全 PASS（query_flows 改用 helper 後 4b 測試不回歸）。

- [ ] **Step 4: Commit**

```bash
git add src/analyzer.py tests/test_analyzer_object_filters.py
git commit -m "feat(analyzer): unify flow filter matching and support object keys in rule engine"
```

---

### Task 2: 規則儲存端點收 FilterBar filters（+ label_group 明確拒絕）

**Files:**
- Modify: `src/gui/routes/rules.py`（`api_add_traffic_rule` :140、`api_add_bandwidth_rule` :189、`api_update_rule` :242）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（新鍵 `gui_rule_label_group_unsupported`）
- Test: `tests/test_gui_rules.py`（若無此檔，以現場規則端點測試檔為準；追加）

**Interfaces:**
- Produces: 三端點接受 `filters` dict（FilterBar getFilters() 格式）→ 24-key whitelist flat 展平存 rule dict；收到任何 label_group key（`src_label_groups`/`dst_label_groups`/`ex_src_label_groups`/`ex_dst_label_groups` 及 singular 變體）回 **400** `{"ok": False, "error": t("gui_rule_label_group_unsupported", ...)}`。無 `filters` 走既有啟發式分支不動。
- Consumes: Task 1 的比對語意（存進去的 key 引擎都認）。

- [ ] **Step 1: 寫失敗測試**

```python
def test_add_traffic_rule_stores_filterbar_keys(client_fixture):
    r = client.post('/api/rules/traffic', json={
        "name": "R1", "pd": -1, "threshold_count": 5, "threshold_window": 10,
        "filters": {
            "src_labels": ["app=erp", "app=web"],
            "dst_iplists": ["/orgs/1/sec_policy/active/ip_lists/7"],
            "src_workloads": ["/orgs/1/workloads/abc"],
            "src_ip_in": ["10.0.0.1"],
            "ex_dst_ip": ["10.9.9.9"],
            "any_label": "env=prod",
            "any_workload": "/orgs/1/workloads/xyz",
        },
    }, ...)
    assert r.get_json()["ok"] is True
    rule = <GET /api/rules 或讀 cm.config["rules"]>[-1]
    assert rule["src_labels"] == ["app=erp", "app=web"]
    assert rule["dst_iplists"] == ["/orgs/1/sec_policy/active/ip_lists/7"]
    assert rule["src_ip_in"] == ["10.0.0.1"]
    assert rule["any_label"] == "env=prod"
    assert rule["any_workload"] == "/orgs/1/workloads/xyz"


def test_add_traffic_rule_rejects_label_groups(client_fixture):
    r = client.post('/api/rules/traffic', json={
        "name": "R2", "threshold_count": 5, "threshold_window": 10,
        "filters": {"src_label_groups": ["PG-Prod"]},
    }, ...)
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
    # 規則未被寫入
    assert all(x.get("name") != "R2" for x in <rules>)


def test_add_traffic_rule_legacy_branch_unchanged(client_fixture):
    r = client.post('/api/rules/traffic', json={
        "name": "L1", "src": "app=erp", "dst": "10.0.0.5",
        "threshold_count": 5, "threshold_window": 10,
    }, ...)
    rule = <rules>[-1]
    assert rule["src_label"] == "app=erp"
    assert rule["dst_ip_in"] == "10.0.0.5"
```

（登入/CSRF/fixture 樣式以現場規則端點既有測試為準；bandwidth 端點與 PUT update 各加一個 filters 分支測試——PUT 帶 filters 更新後 rule 內物件 key 被替換而非殘留混存。）

Run: `python3 -m pytest <測試檔> -v -k "filterbar or label_groups or legacy"`
Expected: 新格式與拒絕測試 FAIL、legacy PASS。

- [ ] **Step 2: 實作**

rules.py 模組層加常數與 helper：

```python
# Phase 4c：規則版 FilterBar key whitelist（= dashboard 28 key 減 label_groups 4 key）。
# label_group 在規則路徑結構性不可支援（共用未過濾 stream、無 client-side 成員展開），
# 收到一律 400 明確拒絕——不可靜默丟棄。
_RULE_FB_KEYS = (
    "src_labels", "dst_labels", "ex_src_labels", "ex_dst_labels",
    "src_iplists", "dst_iplists", "ex_src_iplists", "ex_dst_iplists",
    "src_workloads", "dst_workloads", "ex_src_workloads", "ex_dst_workloads",
    "src_ip_in", "dst_ip_in", "ex_src_ip", "ex_dst_ip",
    "any_label", "any_ip", "any_iplist", "any_workload",
    "ex_any_label", "ex_any_ip", "ex_any_iplist", "ex_any_workload",
)
_RULE_REJECTED_KEYS = (
    "src_label_groups", "dst_label_groups", "ex_src_label_groups", "ex_dst_label_groups",
    "src_label_group", "dst_label_group", "ex_src_label_group", "ex_dst_label_group",
)


def _extract_rule_filters(f, lang):
    """filters dict → (flat_dict, error_response|None)。label_group key 回 400。"""
    bad = [k for k in _RULE_REJECTED_KEYS if f.get(k)]
    if bad:
        return None, (jsonify({"ok": False, "error": t("gui_rule_label_group_unsupported", lang=lang)}), 400)
    out = {}
    for k in _RULE_FB_KEYS:
        v = f.get(k)
        if v:
            out[k] = v
    return out, None
```

三端點各加分支（照 4b dashboard.py 樣式）：`f = d.get('filters')`；`isinstance(f, dict)` 時呼叫 `_extract_rule_filters`，錯誤直接 return，否則 rule dict = 共同欄位（name/pd/port/proto/ex_port/threshold_*/cooldown/throttle，讀值照既有）+ flat 展平；else 走既有啟發式組裝（一行不動）。`api_update_rule` 同樣處理（filters 分支時物件 key 全量替換：先移除 rule 中所有 `_RULE_FB_KEYS`+legacy scalar filter key 再套新值，避免新舊混存——與 4b「整物件替換」語意一致，實作以現場 update 端點結構為準）。

i18n 兩檔加 `gui_rule_label_group_unsupported`：en "Label Groups are not supported in alert rules (rules match a shared unfiltered stream client-side). Use individual labels instead."；zh_TW「告警規則不支援 Label Group（規則在共用未過濾流量上做客戶端比對，無法展開群組成員），請改用個別 Label。」

- [ ] **Step 3: 跑測試**

Run: `python3 -m pytest <測試檔> tests/test_analyzer_object_filters.py -q`
Expected: 全 PASS。

- [ ] **Step 4: Commit**

```bash
git add src/gui/routes/rules.py src/i18n_en.json src/i18n_zh_TW.json <測試檔>
git commit -m "feat(rules): accept filter-bar dict on rule save and reject label groups explicitly"
```

---

### Task 3: 規則 modal（traffic + bandwidth）換 FilterBar

**Files:**
- Modify: `src/templates/index.html`（traffic modal 約 2652-2701 的 tr-src/tr-dst/tr-exsrc/tr-exdst；bandwidth modal 約 2715-2768 的 bw-src/bw-dst/bw-exsrc/bw-exdst；行號以現場為準）
- Modify: `src/static/js/rules.js`（`saveTraffic` :523、`saveBw` :529、`editRule` :416、開 modal reset 段）
- Test: `tests/test_component_object_filter_bar.py`（追加）

**Interfaces:**
- Consumes: `window.createFilterBar(el, {cats: ['label', 'iplist', 'workload', 'ip']})`（**不含 label_group**——後端會 400，前端直接不提供該類別）、getFilters/setFilters。
- Produces: 兩 modal 各一掛載點 `<div id="tr-filter-bar"></div>`/`<div id="bw-filter-bar"></div>`；save 送 `filters: fb.getFilters()`；編輯回填 `fb.setFilters(r)`（flat rule dict 直接餵，legacy scalar 原生相容）。

- [ ] **Step 1: index.html 換掛載點**

tr-src/tr-dst/tr-exsrc/tr-exdst 四欄 → `<div id="tr-filter-bar"></div>`（說明 label 沿用 `rpt_filter_objects` 鍵）；bw 同型。**保留** tr-name/tr-pd/tr-port/tr-proto/tr-expt/tr-cnt/tr-win/tr-cd 與 bw 對應欄位。

- [ ] **Step 2: rules.js 接線**

1. `_ensureTrFilterBar()`/`_ensureBwFilterBar()` lazy singleton（照 4a/4b 樣式；**傳 cats 選項**：`createFilterBar(document.getElementById('tr-filter-bar'), {cats: ['label', 'iplist', 'workload', 'ip']})`）。
2. `saveTraffic`/`saveBw`：移除 src/dst/ex_src/ex_dst 讀值，改 `filters: _ensureTrFilterBar().getFilters()`；保留其餘欄位。
3. `editRule`（:416）：移除 `$('tr-src').value = r.src_label || r.src_ip_in` 等拼接回填，改 `_ensureTrFilterBar().setFilters(r)`（bw 分支同）；新增規則開 modal reset 段改 `setFilters({})`。
4. grep `tr-src|tr-dst|tr-exsrc|tr-exdst|bw-src|bw-dst|bw-exsrc|bw-exdst` 全 JS/模板，殘留引用一併處理。

- [ ] **Step 3: 靜態斷言 + 測試**

追加 tests/test_component_object_filter_bar.py：index.html 含 `id="tr-filter-bar"` 與 `id="bw-filter-bar"`、不含 `id="tr-src"`/`id="bw-src"`；rules.js 含 `_ensureTrFilterBar` 與 `_ensureBwFilterBar` 且兩處都帶 `cats:`（鎖 label_group 排除）。

Run: `python3 -m pytest tests/test_component_object_filter_bar.py tests/test_csp_compliance.py -q` + `node --check src/static/js/rules.js`
Expected: 全 PASS。

- [ ] **Step 4: Commit**

```bash
git add src/templates/index.html src/static/js/rules.js tests/test_component_object_filter_bar.py
git commit -m "feat(gui): wire filter-bar into traffic and bandwidth rule modals"
```

---

### Task 4: 全量回歸 + i18n + Playwright 實機煙霧（controller）

- [ ] **Step 1: 全量** `python3 -m pytest tests/ -q`（基準約 2496 passed）。
- [ ] **Step 2: i18n 稽核** `python3 scripts/audit_i18n_usage.py` → 0 findings。
- [ ] **Step 3: Playwright 實機**（scratch config + HTTP + 真實 PCE，同 4a/4b）：
  1. 規則 tab → 開 traffic 規則 modal → `#tr-filter-bar` 掛載、**類別下拉無 Label Groups**、真實 suggest → label + iplist + IP pill → 儲存 → 讀 `/api/rules` 驗 flat key。
  2. 編輯該規則 → setFilters 回填一致；建一條 legacy 規則（直接 API 舊格式）→ 編輯回填 scalar → pill 正確。
  3. 後端拒絕鏈：直接 POST 帶 `src_label_groups` → 400 + 雙語訊息。
  4. bandwidth modal 同 1 抽驗。
  5. console 零錯誤、截圖存證。
- [ ] **Step 4: 回報 + 收尾**：final whole-branch review（含「兩套比對器對帳表」複核）→ --no-ff merge（merge-tree 預檢）→ push。**明列限制**：label_group 規則不支援（明確 400）；規則引擎為共用未過濾 stream 的 client-side 比對（iplist/workload 比對靠 flow 內嵌物件 href，PCE flow 才有——cache subscriber 列 4b 已驗同形）。

---

## Self-Review 紀錄

- **Spec 覆蓋**：規則路徑物件 key（§10 分批的最後一個 Web 入口）→ Task 1（引擎）+ Task 2（儲存）+ Task 3（GUI）；label_group 不可支援的結構性理由與三道防線已記設計定案。
- **兩套比對器對帳（4b 教訓）**：本批不新增第三套——統一為 `_match_flow_filters` helper，三呼叫點共用；`check_flow_match` 本身不動（其 list IP 4b 已修）。
- **每個進入點的第二道 whitelist**：規則端點原本無 filter whitelist（模型無這些 key）→ Task 2 新建 24-key whitelist + 明確拒絕清單；引擎端投影 key 用既有 `_OBJECT_FILTER_KEYS`。
- **型別一致性**：`_RULE_FB_KEYS`（Task 2）= `_OBJECT_FILTER_KEYS` ∪ check_flow_match 純量 key ∩ FilterBar 輸出（Task 1/3 對齊）；`_ensureTrFilterBar`/`_ensureBwFilterBar` cats 參數與 filter-bar.js:22 `opts.cats` 契約一致；`_match_flow_filters` 簽名 Task 1 定義、三處消費。
- **已知不確定點（任務內標註）**：規則端點測試檔名與 fixture 樣式（Task 2）；`analyzer_with_flows` fixture 構造與 :1464 測試路徑的呼叫形狀（Task 1 現場對位）；PUT update 的物件 key 全量替換實作細節（Task 2）；cache subscriber 列形狀（Task 1 具名風險，4b 已驗 reader 同源）。
- **Placeholder 掃描**：helper/常數/i18n 給完整碼；端點分支與 modal 接線給結構 + 現場對位點；測試給可執行骨架（fixture 樣式現場為準已明標）。
