# Filter 物件選擇器 Phase 3：FilterBar 前端元件 + 流量分析器落地 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把流量分析器的分欄文字 filter 輸入升級為 PCE 風格的 pill 元件（`createFilterBar`）——輸入時打 `/api/filter-objects/suggest` 顯示分類候選、選定成 pill、可切方向與包含/排除，同時保留手動 IP/CIDR 與 `key=value` 輸入。這是使用者已核可的互動原型（https://claude.ai/code/artifact/2a5fd799-b3f9-4950-b6d5-4112e3c80e30）落地為產品的第一個進入點。

**Architecture:** 三部分——(1) 後端 `api_quarantine_search` 補 forward IP List/Workload 物件 filter key（Phase 1 的 analyzer 層已支援，只差此 GUI 端點 white-list forward）；(2) 前端 `src/static/js/filter-bar.js` 可重複實例化元件（pill 資料模型 + `getFilters()`/`setFilters()` 序列化 + suggest 整合），CSP 下靠 document 層 `_event_dispatcher` 委派（handler 掛 `window.*`）；(3) 流量分析器 `modal-qt-filters` 的分欄輸入換成 FilterBar 實例並接線 `runTrafficAnalyzer`。

**Tech Stack:** vanilla JS（無框架）、Flask（後端 forward）、pytest（靜態掃 + Flask test_client）、Playwright MCP（controller 實機驗證，因專案無 JS 單元框架）。

**Spec:** `docs/superpowers/specs/2026-07-03-pce-style-filter-object-selector-design.md` §5

## 設計定案（盤點與使用者核可）

- **序列化契約**（`getFilters()` 輸出，對齊 Phase 1 native builder 接受的 key）：
  - pill 內部模型：`{cat: 'label'|'iplist'|'workload'|'ip', name, href?, key?, value?, dir: 'src'|'dst'|'any', neg: bool}`。
  - src/dst 方向多值 → 複數 list key：`{ex_}{dir}_labels`（list of `"k=v"`）、`{ex_}{dir}_iplists`（list of href）、`{ex_}{dir}_workloads`（list of href）、`{ex_}{dir}_ip_in`（list；ex_ 用 `ex_{dir}_ip`）。Phase 1 native `_pop_many` 展開 list；label 同 key OR 三路徑完整。
  - any 方向 → Phase 1 既有單值 key：`{ex_}any_label`/`{ex_}any_ip`/`{ex_}any_iplist`/`{ex_}any_workload`。any 方向每類多個 pill 時取最後值（前端在 any 同類第二個 pill 時以 UI 提示，見 Task 2）。
- **多值邊界（使用者核可：native 主路徑，邊界 follow-up）**：手動 IP 多值與 any 方向多值在 client-side fallback / cache df 路徑若不完整，屬 Phase 1 遺留，記 post-merge follow-up。Phase 3 前端完整、後端 forward 完整、多值主走 native async 查詢。
- **測試策略（專案無 JS 單元框架）**：JS 序列化純邏輯無法 CI 單元測。三層驗證：(a) 靜態掃（CSP 無 inline、i18n 齊、檔案/class 存在，仿 `test_component_filter_bar.py`）；(b) 後端 Flask test_client 驗 `/api/quarantine/search` 接受新物件 key（Task 1）；(c) **controller Playwright MCP 實機煙霧**（Task 5）——真瀏覽器 `page.evaluate` 驗 `getFilters()`/`setFilters()` round-trip、pill 互動、送查詢收結果（同 Phase 0 截斷提示的實機驗證法）。
- **命名**：`.filter-bar` class 已被佔用（既有工具列 flex 容器，app.css:1224）。元件用 `.objfb-*` 前綴（object-filter-bar）。
- **CSP 綁定**：document 層委派（`_event_dispatcher.js`），動態 pill/下拉不需重新註冊，只要帶 `data-action`/`data-on-*` 屬性 + handler 掛 `window.*`。絕無 inline `onclick`。

## Global Constraints

- 程式內註解繁體中文、commit message 英文 conventional commits、不用 emoji。
- 只動各 Task 列出的檔案；不順手重構。
- 新 UI 字串進 `src/i18n_en.json` 與 `src/i18n_zh_TW.json` 兩檔（鍵前綴 `gui_fb_`），i18n 稽核測試會擋。
- CSP：JS 不可 inline script/handler；動態元素用 `data-action`/`data-on-*` + `window.*` handler；樣式進 `app.css` 沿用既有 token（`--accent`/`--bg2`/`--border`/`--radius` 等）。
- 欄位過長內容：pill 內 ellipsis、pill 換行不截斷（遵守專案報表/欄位截斷規範，CLAUDE.md）。
- 每 Task 結尾跑該 Task 測試 + commit；Task 5 全量（基準以執行時 main 為準）。
- **worktree 紀律**：隔離 worktree 執行；每個 Bash 命令以絕對 worktree 路徑 `cd` 前綴，commit 前 `git rev-parse --show-toplevel` 驗證、commit 後確認落點；controller 每 task 驗 parent SHA + `git branch --contains` 不在 main。

---

### Task 1: 後端 forward IP List / Workload 物件 filter key

**Files:**
- Modify: `src/gui/routes/actions.py`（`api_quarantine_search` 的 `params` dict，102-124 行）
- Test: `tests/test_gui_quarantine.py`（追加）

**Interfaces:**
- Produces: `POST /api/quarantine/search` 的 `params` 新增 forward 物件 key，FilterBar（Task 2+）送這些 key 才會進 analyzer。

**背景**：`api_quarantine_search` white-list forward filter key 給 analyzer，但只含 label/ip/port/proto/any_label/any_ip/ex_*，缺 IP List/Workload 物件 key。Phase 1 的 analyzer 層（build_traffic_query_spec / _flow_matches_filters / df_filter）已支援這些 key，只差此端點 forward。

- [ ] **Step 1: 寫失敗測試（追加 tests/test_gui_quarantine.py）**

```python
def test_quarantine_search_forwards_object_filter_keys(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    csrf_token = _csrf(login)

    captured = {}
    from src.analyzer import Analyzer
    def fake_query(self, params):
        captured.update(params)
        return []
    monkeypatch.setattr(Analyzer, "query_flows", fake_query)

    client.post('/api/quarantine/search', json={
        "mins": 60,
        "src_labels": ["app=erp", "app=web"],
        "dst_iplists": ["/orgs/1/sec_policy/active/ip_lists/7"],
        "src_workloads": ["/orgs/1/workloads/abc"],
        "ex_dst_workloads": ["/orgs/1/workloads/zzz"],
        "any_iplist": "corp-vpn",
        "ex_any_workload": "/orgs/1/workloads/q",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
       headers={'X-CSRF-Token': csrf_token})

    assert captured.get("src_labels") == ["app=erp", "app=web"]
    assert captured.get("dst_iplists") == ["/orgs/1/sec_policy/active/ip_lists/7"]
    assert captured.get("src_workloads") == ["/orgs/1/workloads/abc"]
    assert captured.get("ex_dst_workloads") == ["/orgs/1/workloads/zzz"]
    assert captured.get("any_iplist") == "corp-vpn"
    assert captured.get("ex_any_workload") == "/orgs/1/workloads/q"
```

註：`base_ana.query_flows` 的實際類別以現場為準（actions.py 內建構的 analyzer 物件）；monkeypatch 目標對齊。

Run: `python3 -m pytest tests/test_gui_quarantine.py -v -k forwards_object`
Expected: FAIL（新 key 未 forward，captured 無這些 key）。

- [ ] **Step 2: 實作 forward（src/gui/routes/actions.py）**

在 `params` dict（123 行 `ex_any_ip` 之後、`}` 之前）加入物件 key forward。src/dst 方向收單複數（複數 list 優先，單數相容）：

```python
                # 物件 filter key（Phase 1 analyzer 已支援；FilterBar 送複數 list）
                "src_labels": d.get("src_labels", []),
                "dst_labels": d.get("dst_labels", []),
                "ex_src_labels": d.get("ex_src_labels", []),
                "ex_dst_labels": d.get("ex_dst_labels", []),
                "src_iplist": d.get("src_iplist", ""),
                "src_iplists": d.get("src_iplists", []),
                "dst_iplist": d.get("dst_iplist", ""),
                "dst_iplists": d.get("dst_iplists", []),
                "ex_src_iplists": d.get("ex_src_iplists", []),
                "ex_dst_iplists": d.get("ex_dst_iplists", []),
                "src_workloads": d.get("src_workloads", []),
                "dst_workloads": d.get("dst_workloads", []),
                "ex_src_workloads": d.get("ex_src_workloads", []),
                "ex_dst_workloads": d.get("ex_dst_workloads", []),
                "any_iplist": d.get("any_iplist", ""),
                "any_workload": d.get("any_workload", ""),
                "ex_any_iplist": d.get("ex_any_iplist", ""),
                "ex_any_workload": d.get("ex_any_workload", ""),
```

註：既有單值 `src_label`/`src_ip_in` 等保留不動（向後相容）；新增複數與物件 key。空 list/字串預設對 analyzer 無害（Phase 1 `_pop_many` 略過空值）。

- [ ] **Step 3: 跑測試確認通過**

Run: `python3 -m pytest tests/test_gui_quarantine.py -v -k forwards_object`
Expected: PASS。

- [ ] **Step 4: 跑既有 quarantine search 測試不回歸 + Commit**

Run: `python3 -m pytest tests/test_gui_quarantine.py -q`
Expected: 全 PASS。

```bash
git add src/gui/routes/actions.py tests/test_gui_quarantine.py
git commit -m "feat(gui): forward ip_list and workload object filter keys in quarantine search"
```

---

### Task 2: filter-bar.js 元件核心 + 樣式 + i18n

**Files:**
- Create: `src/static/js/filter-bar.js`
- Modify: `src/static/css/app.css`（新增 `.objfb-*` 樣式，檔尾）
- Modify: `src/templates/index.html`（在既有 JS `<script>` 載入區加入 filter-bar.js；確認載入順序在 utils.js 之後、quarantine.js 之前或之後皆可，需在 _event_dispatcher 之前定義 window handler 不強制——dispatcher 是 document 委派 runtime 查找）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（`gui_fb_*` 鍵）
- Test: `tests/test_component_object_filter_bar.py`（新檔，靜態斷言）

**Interfaces:**
- Produces: `window.createFilterBar(container, options) -> {getFilters(), setFilters(dict), onChange(cb), destroy()}`。
  - `options`: `{dirs: ['src','dst','any'], cats: ['label','label_group','iplist','workload','ip'], initial: {}}`（省略用預設全開）。
  - `getFilters()`: 回序列化 dict（見設計定案的序列化契約）。
  - `setFilters(dict)`: 從 filter dict 反序列化回 pill（解析既有 `{dir}_labels`/`{dir}_iplists`/`{dir}_ip_in`/`any_*` 等）。
  - `onChange(cb)`: pill 變動時呼叫 cb。
- Produces: pill handler 掛 `window.*`（`_objfbAddDir`、`_objfbPillClick`、`_objfbInput`、`_objfbKeydown`、`_objfbPickItem`、`_objfbRemovePill`、`_objfbPopAction` 等——命名以 `_objfb` 前綴避免全域衝突）。

**實作藍本**：使用者核可的互動原型（結構參考 spec §5）。本 task 只做**元件核心 + 純結構 + 序列化**（suggest 整合是 Task 3），可先用「空下拉 / 僅 IP-CIDR 與手動 key=value」驗證 pill 生命週期與序列化。

- [ ] **Step 1: i18n 鍵（兩檔都加）**

`src/i18n_en.json`：

```json
  "gui_fb_dir_src": "Source",
  "gui_fb_dir_dst": "Destination",
  "gui_fb_dir_any": "Either",
  "gui_fb_placeholder": "Search labels, workloads, IP lists… or type IP/CIDR",
  "gui_fb_add_ipcidr": "Add IP/CIDR",
  "gui_fb_include": "Include",
  "gui_fb_exclude": "Exclude",
  "gui_fb_remove": "Remove",
  "gui_fb_or": "or",
  "gui_fb_any_slow": "includes either-side condition — query is slower",
  "gui_fb_offline": "PCE unreachable — object search unavailable (manual input still works)",
  "gui_fb_no_match": "No matching objects",
  "gui_fb_cat_label": "Labels",
  "gui_fb_cat_label_group": "Label Groups",
  "gui_fb_cat_iplist": "IP Lists",
  "gui_fb_cat_workload": "Workloads",
  "gui_fb_scope_hint": "Type to search all categories, or pick a category to narrow",
```

`src/i18n_zh_TW.json`：

```json
  "gui_fb_dir_src": "來源",
  "gui_fb_dir_dst": "目的",
  "gui_fb_dir_any": "任一",
  "gui_fb_placeholder": "搜尋 Labels、Workloads、IP Lists… 或輸入 IP/CIDR",
  "gui_fb_add_ipcidr": "加入 IP/CIDR",
  "gui_fb_include": "包含",
  "gui_fb_exclude": "排除",
  "gui_fb_remove": "移除",
  "gui_fb_or": "或",
  "gui_fb_any_slow": "含任一側條件——查詢較慢",
  "gui_fb_offline": "PCE 無法連線——物件搜尋暫不可用（手動輸入仍可用）",
  "gui_fb_no_match": "沒有符合的物件",
  "gui_fb_cat_label": "Labels",
  "gui_fb_cat_label_group": "Label Groups",
  "gui_fb_cat_iplist": "IP Lists",
  "gui_fb_cat_workload": "Workloads",
  "gui_fb_scope_hint": "輸入文字搜尋所有類別，或點類別縮小範圍",
```

- [ ] **Step 2: 寫靜態斷言測試（tests/test_component_object_filter_bar.py）**

仿 `tests/test_component_filter_bar.py` 的模式（讀檔 regex 斷言）：

```python
from pathlib import Path

_JS = Path("src/static/js/filter-bar.js")
_CSS = Path("src/static/css/app.css")
_EN = Path("src/i18n_en.json")
_ZH = Path("src/i18n_zh_TW.json")


def test_filter_bar_js_exists_and_exports_factory():
    src = _JS.read_text(encoding="utf-8")
    assert "window.createFilterBar" in src


def test_filter_bar_handlers_on_window():
    src = _JS.read_text(encoding="utf-8")
    for fn in ("_objfbInput", "_objfbKeydown", "_objfbPillClick", "_objfbAddDir"):
        assert f"window.{fn}" in src, f"{fn} must be on window for CSP dispatcher"


def test_filter_bar_no_inline_onclick():
    src = _JS.read_text(encoding="utf-8")
    # 元件不得用 inline onclick=（CSP）；事件走 data-action 委派
    assert "onclick=" not in src


def test_filter_bar_css_class_present():
    css = _CSS.read_text(encoding="utf-8")
    assert ".objfb-bar" in css
    assert ".objfb-pill" in css


def test_filter_bar_i18n_keys_present():
    import json
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    for k in ("gui_fb_placeholder", "gui_fb_add_ipcidr", "gui_fb_any_slow",
              "gui_fb_offline", "gui_fb_or"):
        assert k in en and k in zh, f"{k} missing in i18n"
```

Run: `python3 -m pytest tests/test_component_object_filter_bar.py -v`
Expected: FAIL（filter-bar.js 不存在）。

- [ ] **Step 3: 實作 filter-bar.js 元件核心**

建立 `src/static/js/filter-bar.js`。核心資料模型與序列化（**必須完整實作**；渲染細節參考互動原型與 spec §5，用 `document.createElement` 建 DOM、`data-action`/`data-on-*` 綁事件、handler 掛 `window.*`）：

```javascript
'use strict';
/* PCE 風格 filter 物件選擇器元件（Phase 3）。
   可重複實例化：createFilterBar(container, options) → { getFilters, setFilters, onChange, destroy }。
   CSP：動態 pill/下拉用 data-action/data-on-* 委派（_event_dispatcher），handler 掛 window.*。
   suggest 整合在 Task 3；本檔核心為 pill 資料模型 + 序列化 + 生命週期。 */

// 每個 FilterBar 實例存於此註冊表，供 window handler 依 container id 找回實例
const _objfbInstances = {};
let _objfbSeq = 0;

function _objfbIsIpLike(s) {
  const t = String(s).trim();
  return /^\d{1,3}(\.\d{1,3}){3}(\/\d{1,2})?$/.test(t) &&
    t.split('/')[0].split('.').every(o => +o <= 255);
}

function createFilterBar(container, options) {
  const opts = options || {};
  const dirs = opts.dirs || ['src', 'dst', 'any'];
  const cats = opts.cats || ['label', 'label_group', 'iplist', 'workload', 'ip'];
  const id = 'objfb-' + (++_objfbSeq);
  const state = {
    id, container, dirs, cats,
    pills: [],          // {cat, name, href, key, value, dir, neg}
    addDir: dirs[0],
    scopeCat: null,
    changeCb: null,
  };
  _objfbInstances[id] = state;
  container.dataset.objfbId = id;
  container.classList.add('objfb-bar');
  _objfbRender(state);
  return {
    getFilters: () => _objfbSerialize(state),
    setFilters: (dict) => { _objfbDeserialize(state, dict); _objfbRender(state); },
    onChange: (cb) => { state.changeCb = cb; },
    destroy: () => { delete _objfbInstances[id]; container.innerHTML = ''; },
  };
}

/* ── 序列化：pill → filter dict（對齊 Phase 1 native builder key）── */
function _objfbSerialize(state) {
  const out = {};
  const push = (k, v) => { (out[k] = out[k] || []).push(v); };
  const setScalar = (k, v) => { out[k] = v; };
  for (const p of state.pills) {
    const ex = p.neg ? 'ex_' : '';
    if (p.dir === 'any') {
      // any 方向：Phase 1 單值 key（多個同類取最後值）
      if (p.cat === 'label')         setScalar(`${ex}any_label`, p.name);
      else if (p.cat === 'iplist')   setScalar(`${ex}any_iplist`, p.href || p.name);
      else if (p.cat === 'workload') setScalar(`${ex}any_workload`, p.href);
      else if (p.cat === 'ip')       setScalar(`${ex}any_ip`, p.name);
      else if (p.cat === 'label_group') setScalar(`${ex}any_label`, p.name);
      continue;
    }
    const d = p.dir; // src | dst
    if (p.cat === 'label')            push(`${ex}${d}_labels`, p.name);
    else if (p.cat === 'label_group') push(`${ex}${d}_label_groups`, p.name);
    else if (p.cat === 'iplist')      push(`${ex}${d}_iplists`, p.href || p.name);
    else if (p.cat === 'workload')    push(`${ex}${d}_workloads`, p.href);
    else if (p.cat === 'ip')          push(ex ? `ex_${d}_ip` : `${d}_ip_in`, p.name);
  }
  return out;
}

/* ── 反序列化：filter dict → pill（供 setFilters 回填既有查詢定義）── */
function _objfbDeserialize(state, dict) {
  state.pills = [];
  const add = (cat, name, dir, neg, extra) =>
    state.pills.push(Object.assign({ cat, name, href: null, key: null, value: null, dir, neg }, extra || {}));
  const d = dict || {};
  const asList = (v) => Array.isArray(v) ? v : (v ? [v] : []);
  for (const dir of ['src', 'dst']) {
    for (const spec of asList(d[`${dir}_labels`]).concat(asList(d[`${dir}_label`]))) add('label', spec, dir, false);
    for (const spec of asList(d[`ex_${dir}_labels`]).concat(asList(d[`ex_${dir}_label`]))) add('label', spec, dir, true);
    for (const h of asList(d[`${dir}_iplists`]).concat(asList(d[`${dir}_iplist`]))) add('iplist', h, dir, false, { href: h });
    for (const h of asList(d[`ex_${dir}_iplists`])) add('iplist', h, dir, true, { href: h });
    for (const h of asList(d[`${dir}_workloads`])) add('workload', h, dir, false, { href: h });
    for (const h of asList(d[`ex_${dir}_workloads`])) add('workload', h, dir, true, { href: h });
    for (const ip of asList(d[`${dir}_ip_in`]).concat(asList(d[`${dir}_ip`]))) add('ip', ip, dir, false);
    for (const ip of asList(d[`ex_${dir}_ip`])) add('ip', ip, dir, true);
  }
  for (const [k, cat] of [['any_label', 'label'], ['any_ip', 'ip'], ['any_iplist', 'iplist'], ['any_workload', 'workload']]) {
    if (d[k]) add(cat, d[k], 'any', false, cat === 'iplist' || cat === 'workload' ? { href: d[k] } : {});
    if (d['ex_' + k]) add(cat, d['ex_' + k], 'any', true, cat === 'iplist' || cat === 'workload' ? { href: d['ex_' + k] } : {});
  }
}

/* ── 加 pill / 移除 / 方向 / 排除（handler 掛 window，供 dispatcher 委派）── */
function _objfbAddPill(state, obj) {
  state.pills.push({
    cat: obj.cat, name: obj.name, href: obj.href || null,
    key: obj.key || null, value: obj.value || null, dir: state.addDir, neg: false,
  });
  _objfbRender(state);
  if (state.changeCb) state.changeCb();
}

/* 以下 render / 下拉 / 事件 handler 依 spec §5 與互動原型實作（用 createElement +
   data-action/data-on-* + window handler）。關鍵渲染點：
   - 方向分段按鈕（dirs）：data-on-click="_objfbAddDir" data-args='[id, dir]'
   - 輸入框：data-on-input="_objfbInput" data-args='[id]'、data-on-keydown="_objfbKeydown"
   - pill：.objfb-pill，含方向 tag、cat 色點、名稱（ellipsis）、× 移除鈕；
     同側同 key label pill 相鄰間插 <span class="objfb-or">gui_fb_or</span>
   - any pill：.objfb-pill.objfb-any + 列尾 gui_fb_any_slow 提示
   - pill 點擊開 popover：改方向 / 包含(gui_fb_include)排除(gui_fb_exclude) / 移除
   - 下拉：無輸入顯示類別捷徑（gui_fb_scope_hint）；有輸入顯示分類分組候選（Task 3 填 suggest 資料）
   - IP/CIDR：_objfbIsIpLike(input) 為真時下拉置頂「gui_fb_add_ipcidr」項，Enter 成 ip pill
   所有 window handler：window._objfbAddDir/_objfbInput/_objfbKeydown/_objfbPillClick/
   _objfbPickItem/_objfbRemovePill/_objfbPopAction = 對應函式。 */

function _objfbRender(state) { /* 依上述結構實作 */ }

// 掛載 window（CSP dispatcher 查找 window[fnName]）
window.createFilterBar = createFilterBar;
window._objfbAddDir = function (id, dir) { const s = _objfbInstances[id]; if (s) { s.addDir = dir; _objfbRender(s); } };
window._objfbInput = function (id) { /* Task 3: debounce suggest；本 task 先處理 IP/CIDR 置頂 */ };
window._objfbKeydown = function (id, ev) { /* ↑↓/Enter/Esc/Backspace */ };
window._objfbPillClick = function (id, idx) { /* 開 popover */ };
window._objfbPickItem = function (id, payload) { /* 選候選成 pill */ };
window._objfbRemovePill = function (id, idx) { const s = _objfbInstances[id]; if (s) { s.pills.splice(idx, 1); _objfbRender(s); if (s.changeCb) s.changeCb(); } };
window._objfbPopAction = function (id, idx, action, val) { /* 改 dir / 切 neg / 移除 */ };
```

**實作者注意**：序列化（`_objfbSerialize`/`_objfbDeserialize`）與資料模型上面已完整給出，**照抄**；渲染（`_objfbRender`）與事件 handler 主體依 spec §5 條列與互動原型的視覺行為實作（原型已由使用者核可），務必：(a) 無 inline onclick；(b) handler 全掛 `window.*`；(c) pill 名稱 ellipsis、換行不截斷；(d) 同側同 key label pill 間顯「or」。

- [ ] **Step 4: app.css 樣式（檔尾追加 .objfb-* 區塊）**

依互動原型的 CSS adapt，沿用 app.css 既有 token（`--accent`/`--bg2`/`--bg3`/`--border`/`--radius`/`--dim`/`--danger`/`--warn`）。至少定義：`.objfb-bar`（flex-wrap pill 容器）、`.objfb-pill`（inline-flex + ellipsis）、`.objfb-pill.objfb-excl`（排除紅框）、`.objfb-any`（任一區別樣式）、`.objfb-dd`（下拉）、`.objfb-pop`（pill popover）、`.objfb-or`（同 key 間小字）、`.objfb-dir-seg`（方向分段按鈕）。禁用外部資源、禁 inline。

- [ ] **Step 5: 載入 filter-bar.js（index.html）**

在既有 static JS `<script src="/static/js/...">` 載入區（quarantine.js 附近）加入 `<script src="/static/js/filter-bar.js"></script>`。順序：utils.js 之後即可（用到 window.debounce 在 Task 3）。

- [ ] **Step 6: 跑靜態測試 + Commit**

Run: `python3 -m pytest tests/test_component_object_filter_bar.py tests/test_csp_compliance.py tests/templates/test_no_external_resources.py -q`
Expected: 全 PASS（CSP 無 inline、無外部資源、class/i18n/window handler 齊）。

```bash
git add src/static/js/filter-bar.js src/static/css/app.css src/templates/index.html \
        src/i18n_en.json src/i18n_zh_TW.json tests/test_component_object_filter_bar.py
git commit -m "feat(gui): filter-bar pill component core with serialization and styles"
```

---

### Task 3: suggest 整合（debounce + AbortController + 分類下拉）

**Files:**
- Modify: `src/static/js/filter-bar.js`（填實 `_objfbInput` 的 suggest 查詢與下拉渲染）
- Test: `tests/test_component_object_filter_bar.py`（追加靜態斷言）

**Interfaces:**
- Consumes: `GET /api/filter-objects/suggest`（Phase 2）、`window.debounce`（utils.js:462）、`get()`（utils.js）。
- Produces: `_objfbInput` debounce 250ms 後打 suggest、AbortController 取消舊請求、分類分組渲染下拉、離線降級。

- [ ] **Step 1: 追加靜態斷言（tests/test_component_object_filter_bar.py）**

```python
def test_filter_bar_uses_suggest_endpoint():
    src = _JS.read_text(encoding="utf-8")
    assert "/api/filter-objects/suggest" in src


def test_filter_bar_uses_debounce_and_abort():
    src = _JS.read_text(encoding="utf-8")
    assert "AbortController" in src
    assert "debounce" in src


def test_filter_bar_handles_offline():
    src = _JS.read_text(encoding="utf-8")
    # 消費 workload 的 pce_unreachable error 欄
    assert "pce_unreachable" in src
```

Run: `python3 -m pytest tests/test_component_object_filter_bar.py -v -k "suggest or debounce or offline"`
Expected: FAIL。

- [ ] **Step 2: 實作 suggest 整合（filter-bar.js 的 _objfbInput 與下拉渲染）**

在 `_objfbInput` 內實作（藍本 `rule-scheduler.js:134-178` 的 AbortController + `utils.js` 的 debounce/get）：

```javascript
// 每實例一個 debounced 查詢器 + AbortController
function _objfbQuerySuggest(state, q) {
  if (state._abort) state._abort.abort();
  const ctrl = new AbortController();
  state._abort = ctrl;
  const scope = state.scopeCat;
  const types = scope ? scope : 'label,label_group,iplist,workload';
  const url = `/api/filter-objects/suggest?q=${encodeURIComponent(q)}&types=${types}&limit=10`;
  fetch(url, { signal: ctrl.signal, credentials: 'same-origin' })
    .then(r => r.json())
    .then(body => { state._suggest = body.results || {}; _objfbRenderDropdown(state, q); })
    .catch(e => {
      if (e.name === 'AbortError') return;
      state._suggest = { _error: true };
      _objfbRenderDropdown(state, q);
    });
}
```

`window._objfbInput` 用 `window.debounce` 包裝（250ms）呼叫 `_objfbQuerySuggest`；同時同步處理 IP/CIDR 置頂（`_objfbIsIpLike`）。`_objfbRenderDropdown` 依 suggest 回應的分類分組渲染候選（label/label_group/iplist/workload 各一組、每組標題 + 項目），workload 組讀 `results.workload.error === 'pce_unreachable'` 時顯示 `gui_fb_offline` 警示、其他類照常；整體錯誤（`_error`）顯示錯誤列但輸入框仍可自由輸入（降級）。候選項帶 `data-on-click="_objfbPickItem" data-args='[id, {cat,name,href,...}]'`。

- [ ] **Step 3: 跑靜態測試 + Commit**

Run: `python3 -m pytest tests/test_component_object_filter_bar.py tests/test_csp_compliance.py -q`
Expected: 全 PASS。

```bash
git add src/static/js/filter-bar.js tests/test_component_object_filter_bar.py
git commit -m "feat(gui): filter-bar suggest integration with debounce, abort, offline degrade"
```

---

### Task 4: 流量分析器 modal 落地

**Files:**
- Modify: `src/templates/index.html`（`modal-qt-filters`，2435-2507 行——src/dst/any/ex 分欄換成 FilterBar 掛載點；保留 port/proto/PD radio）
- Modify: `src/static/js/quarantine.js`（`runTrafficAnalyzer` 序列化改讀 FilterBar `getFilters()`；modal 開啟時 `setFilters()` 回填；初始化 FilterBar 實例）
- Test: `tests/test_component_object_filter_bar.py`（追加 index.html 落地斷言）+ `tests/test_gui_quarantine.py`（確認送查詢不回歸）

**Interfaces:**
- Consumes: `window.createFilterBar`（Task 2）、getFilters/setFilters。
- Produces: 流量分析器用 FilterBar 取代分欄文字輸入，送查詢帶物件 filter key（Task 1 forward）。

- [ ] **Step 1: index.html 換掛載點**

`modal-qt-filters`（2452-2460、2490-2498 行的 `#qt-src`/`#qt-dst`/`#qt-any-label`/`#qt-any-ip`/`#qt-exsrc`/`#qt-exdst`/`#qt-ex-any-label`/`#qt-ex-any-ip` 分欄）替換為單一 FilterBar 掛載容器 `<div id="qt-filter-bar"></div>`（含說明 label）。保留 `#qt-port`/`#qt-proto`/PD radio group（不屬 FilterBar 範圍）。加靜態斷言：index.html 含 `id="qt-filter-bar"`。

- [ ] **Step 2: quarantine.js 接線**

`runTrafficAnalyzer`（254-311 行）的 `#qt-src` 等讀值序列化段，改為：先取 FilterBar 實例的 `getFilters()`、把回傳的 key 併進 payload（`Object.assign(payload, fb.getFilters())`），移除舊 `#qt-src`/`#qt-dst`/`#qt-any-*`/`#qt-ex*` 的 `=` 啟發式讀值（port/proto/PD/mins/sort/search/source 維持）。modal 開啟（`applyQtFilters` 或開 modal 的 handler）時若要回填既有值用 `fb.setFilters(currentFilters)`。初始化：在頁面/分頁初始化處建 FilterBar 實例 `const _qtFb = createFilterBar(document.getElementById('qt-filter-bar'), {})`，存於模組作用域供 runTrafficAnalyzer 取用。

- [ ] **Step 3: 跑靜態 + 端點測試**

Run: `python3 -m pytest tests/test_component_object_filter_bar.py tests/test_gui_quarantine.py tests/test_csp_compliance.py -q`
Expected: 全 PASS（送查詢的 payload 仍被後端接受；CSP 無違規）。

- [ ] **Step 4: Commit**

```bash
git add src/templates/index.html src/static/js/quarantine.js tests/test_component_object_filter_bar.py
git commit -m "feat(gui): wire filter-bar into traffic analyzer modal, replace field inputs"
```

---

### Task 5: 全量回歸 + CSP/i18n 靜態 + controller Playwright 實機煙霧

**Files:**
- Test: 全部（controller 執行）

- [ ] **Step 1: 全量測試**

Run: `python3 -m pytest tests/ -q`
Expected: 執行時 main 基準 + 本計畫新增全 PASS、0 failed。

- [ ] **Step 2: i18n 稽核**

Run: `python3 scripts/audit_i18n_usage.py`
Expected: 0 findings（`gui_fb_*` 鍵雙語齊全）。

- [ ] **Step 3: controller Playwright MCP 實機煙霧（無 JS 單元框架的核心驗證）**

以 scratch config + HTTP 本機 server（同 Phase 0 煙霧法）啟動 GUI，用 Playwright MCP：
1. 登入 → 流量與 Workloads 分頁 → 開 Advanced Filters modal。
2. `page.evaluate` 驗序列化 round-trip：`_qtFb.setFilters({src_labels:['app=erp','app=web'], dst_iplists:['/orgs/1/.../7']})` → `_qtFb.getFilters()` 回相同結構（pill 正確重建、複數 list 正確）。
3. 驗 pill 互動：注入輸入觸發 IP/CIDR 置頂候選、Enter 成 ip pill、pill popover 切排除 → getFilters 反映 `ex_` key。
4. 驗 CSP：console 零錯誤、無 CSP 違規。
5. 若測試機 PCE 可連：實際輸入觸發 suggest、選一個真實 label 成 pill、送查詢收到結果。
截圖存證、結果附回報。

- [ ] **Step 4: 回報**

回報：全量數字、i18n 稽核、Playwright 實機（序列化 round-trip、pill 互動、CSP 零錯誤、suggest 實查若可）結果與截圖。

---

## Self-Review 紀錄

- **Spec §5 覆蓋**：createFilterBar 介面（getFilters/setFilters/onChange）→ Task 2；方向/包含排除/pill popover → Task 2；debounce+AbortController suggest、分類下拉、鍵盤導航、IP/CIDR 置頂、離線降級 → Task 3；同 key「or」小字、任一 pill 提示 → Task 2 渲染；CSP data-action、i18n gui_fb_*、app.css token、ellipsis 不截斷 → Task 2；流量分析器落地 → Task 4。
- **後端缺口**：物件 key forward → Task 1（盤點發現 api_quarantine_search 白名單缺 iplist/workload）。
- **測試策略缺口（無 JS 單元框架）**：靜態掃 + 後端 payload 測 + controller Playwright 實機 → 設計定案已記錄，Task 2/3/4 靜態 + Task 5 實機。
- **多值邊界**：native 主路徑、fallback/df 多值 IP/any post-merge follow-up（使用者核可）→ 序列化契約已記錄。
- **Placeholder 掃描**：序列化/資料模型/i18n/測試給完整碼；渲染 `_objfbRender` 主體標為「依 spec §5 + 互動原型實作」並列出所有關鍵渲染點與 window handler 契約——這是前端 UI 唯一無法逐行預寫的部分（視覺行為已由核可原型定義），非 placeholder 而是有界的實作指引。
- **型別一致性**：序列化 key 名（Task 1 後端 forward ↔ Task 2 `_objfbSerialize` 輸出）逐一對應；window handler 名（Task 2 定義 ↔ Task 3 填實 ↔ index.html data-action 引用）一致；`createFilterBar` 介面 Task 2 定義、Task 4 消費。
- **已知不確定點（任務內標註）**：actions.py 內 analyzer 實際類別（Task 1 monkeypatch 目標）、index.html JS 載入區位置與 FilterBar 初始化時機（Task 2/4）、`applyQtFilters` 現行流程與 setFilters 回填時機（Task 4）——實作者現場對位。
