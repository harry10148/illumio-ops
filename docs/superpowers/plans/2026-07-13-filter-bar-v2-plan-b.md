# Plan B：FilterBar v2 — PCE 原生式三欄版面與 Service 類別擴充（前端）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 FilterBar 元件改為 PCE 原生式三欄版面（Source ⇄ Destination + Service、is-not 排除列、AND/OR 模式切換），新增 process/winservice/transmission 三個前端類別與 Service 欄輸入引導，並移除五個 modal 殘留的裸 port/proto/ex_port 欄位。

**Architecture:** 在既有 `filter-bar.js`（834 行單檔元件）內就地重構：公開 API（`createFilterBar`→`getFilters`/`setFilters`/`onChange`/`destroy`）與序列化 key 契約完全不變，內部由「方向分段鈕＋單一搜尋列」改為「zone 模型」——(col ∈ src|dst|any|svc) × (neg ∈ include|exclude) 共 6 個（OR 模式 4 個）pill 容器，各自帶輸入框與下拉面板。後端鏈（Plan A）已全通，本案純前端 + 測試。

**Tech Stack:** Vanilla JS（CSP：data-on-* 委派 + window handler）、app.css（`--space-*` token）、pytest 靜態字串斷言（CI gate）、Playwright e2e（`ILLUMIO_OPS_E2E_BASE_URL` 閘門，opt-in）。

**視覺基準（使用者已核可）：** `.superpowers/brainstorm/426761-1783868999/content/filter-layout-a2.html`（方案 A 修訂版：三欄 + 中央 AND/OR 徽章與 ⇄ 鈕）與 `service-entry.html`（Service 欄三選一候選 + 底部格式提示列）。

## Global Constraints

- 序列化 key 契約不變：`src_*/dst_*/any_*`、`services`/`ex_services`、`ports`/`ex_ports`；新增 `process_name`/`ex_process_name`、`windows_service_name`/`ex_windows_service_name`、`transmission`/`ex_transmission`（僅此三組，spec §4.3）。**任何情況下不得再產生 scalar `port`/`proto`/`ex_port`**；讀取相容續留（filter-bar.js:108-113 的 deserialize 分支不可移除）。
- port token 文法：`<port>[-<to_port>][/<tcp|udp>]`；無 `/proto` 尾碼＝兩者（TCP+UDP）（spec §4.2）。
- Transmission 值域：`unicast`/`broadcast`/`multicast`，僅 Destination 側類別面板（OR 模式的合併欄視為含 Destination，一併提供）。
- `any_*` key 為單值 scalar（後端契約）：OR 模式同類多 pill 仍是「最後值生效」——既有 v1 限制，本案不改後端，CHANGELOG 記為已知限制。
- any 方向（OR 模式）不支援 label_group：序列化端 fail-closed skip 續留；AND→OR 切換遇 label_group pill 一律**擋下並提示**（不得靜默丟資料）。
- CSP：不得有 inline `onclick=`；動態 DOM 一律 data-on-* + `window.*` handler（`_event_dispatcher.js` 委派）。
- CSS：新增樣式間距一律用 `var(--space-*)` token；`tests/test_css_spacing_lint.py` 的魔術數字 margin/padding 門檻 ≤ 80 不得超過。新區段用成對 banner 註解（`/* ══ <標題> ══ */`…`/* ══ end <標題> ══ */`）慣例。
- i18n：每個新 key 必須同時進 `src/i18n_en.json` 與 `src/i18n_zh_TW.json`（平鋪、CI i18n audit gate）。
- 程式註解沿用 repo 慣例（繁中）；commit message 用英文 conventional commits；所有輸出不用 emoji。
- 每個 task 完成時執行元件守門測試：`pytest tests/test_component_object_filter_bar.py tests/test_component_filter_bar.py tests/test_component_abstraction_baseline.py tests/test_css_spacing_lint.py -v`（從 repo 根目錄執行；靜態測試是 CI 硬 gate）。
- Subagent 執行時：在 worktree 內工作，dispatch prompt 必須明文要求驗證 `pwd` 與分支（歷史教訓：subagent 曾在主 checkout 產生懸空 commit）。

## File Structure

| 檔案 | 動作 | 職責 |
|---|---|---|
| `src/static/js/filter-bar.js` | Modify（核心） | zone 模型、序列化新 key、候選產生器、v2 render |
| `src/static/css/app.css` | Modify（:2502-2763 objfb 區段內） | v2 版面 CSS、新類別色點、兩欄下拉 |
| `src/i18n_en.json` / `src/i18n_zh_TW.json` | Modify | 新 gui_fb_* key（兩檔同步） |
| `src/templates/index.html` | Modify | 五 modal 裸欄位移除 |
| `src/static/js/dashboard.js` | Modify | rpt/sched/dq 序列化/回填去 scalar |
| `src/static/js/rules.js` | Modify | tr/bw 序列化/回填去 scalar、cats 擴充 |
| `tests/test_component_object_filter_bar.py` | Modify | 靜態守門測試（RED→GREEN 主戰場） |
| `tests/test_gui_e2e_filterbar_playwright.py` | Modify | v2 DOM selector 與新情境 |
| `CHANGELOG.md` | Modify | Unreleased 條目 |

不動的檔案（明列避免誤傷）：`src/static/js/quarantine.js`（已是目標狀態，僅受 filter-bar.js 行為變更影響）、`src/static/js/object-browser.js`（靠 `fb.addDir`/`fb.dirs` 相容 shim 繼續運作，見 Task 3 Step 4）、後端全部（Plan A 已交付）。

---

### Task 1: filter-bar.js 資料層 — process / winservice / transmission pill 類別

**Files:**
- Modify: `src/static/js/filter-bar.js`（:65-95 serialize、:98-132 deserialize、:153-165 類別 metadata、:304-307 pill 文字）
- Modify: `src/static/css/app.css`（:2628 `.objfb-dot-port` 之後）
- Modify: `src/i18n_en.json`（:4375 `gui_fb_browse_all` 之後）、`src/i18n_zh_TW.json`（對應位置）
- Test: `tests/test_component_object_filter_bar.py`

**Interfaces:**
- Consumes: 既有 `_objfbSerialize`/`_objfbDeserialize`/`_OBJFB_CATS`/`_OBJFB_DIRLESS` 結構。
- Produces: pill cat 字串 `'process'`、`'winservice'`、`'transmission'`；`_objfbPillLabel(p) → string`（Task 3/4 的 pill 與候選顯示都用它）；`_OBJFB_DIRLESS` 含五個無方向類別。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_component_object_filter_bar.py` 檔尾加入：

```python
def test_filter_bar_serializes_new_service_family_keys():
    """Plan B Task 1：process/winservice/transmission pill 序列化成 Plan A 後端白名單 key。"""
    src = _JS.read_text(encoding="utf-8")
    for frag in (
        "push(`${ex}process_name`, p.name)",
        "push(`${ex}windows_service_name`, p.name)",
        "push(`${ex}transmission`, p.name)",
    ):
        assert frag in src, frag


def test_filter_bar_deserializes_new_service_family_keys():
    """回填缺 key 會使編輯時 pill 靜默消失、再存檔即永久遺失（label_group 前例）。
    transmission_excludes 為 spec §4.3 明列的續留別名。"""
    src = _JS.read_text(encoding="utf-8")
    for key in ("process_name", "ex_process_name", "windows_service_name",
                "ex_windows_service_name", "transmission", "ex_transmission",
                "transmission_excludes"):
        assert f"asList(d['{key}'])" in src, key


def test_filter_bar_new_cat_metadata_and_dots():
    src = _JS.read_text(encoding="utf-8")
    css = _CSS.read_text(encoding="utf-8")
    for cat_i18n in ("gui_fb_cat_process", "gui_fb_cat_winservice", "gui_fb_cat_transmission"):
        assert cat_i18n in src, cat_i18n
    # 比照 .objfb-dot-service/-port 慣例：色點直接硬編 hex
    for dot in ("objfb-dot-process", "objfb-dot-winsvc", "objfb-dot-tx"):
        assert dot in src and f".{dot}" in css, dot


def test_filter_bar_new_cats_i18n_bilingual():
    import json
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    for k in ("gui_fb_cat_process", "gui_fb_cat_winservice", "gui_fb_cat_transmission"):
        assert k in en and k in zh, k


def test_filter_bar_pill_label_prefixes():
    """spec §3.2 pill 顯示：443 (TCP+UDP)、proc: httpd、winsvc: Dnscache、TX: broadcast。"""
    src = _JS.read_text(encoding="utf-8")
    fn = src.split("function _objfbPillLabel(p)", 1)[1].split("\nfunction ", 1)[0]
    assert "(TCP+UDP)" in fn
    assert "proc: " in fn and "winsvc: " in fn and "TX: " in fn


def test_filter_bar_new_cats_are_dirless():
    src = _JS.read_text(encoding="utf-8")
    dirless = src.split("const _OBJFB_DIRLESS = new Set(", 1)[1].split(")", 1)[0]
    for cat in ("'service'", "'port'", "'process'", "'winservice'", "'transmission'"):
        assert cat in dirless, cat
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_component_object_filter_bar.py -v -k "new_service_family or new_cat or pill_label or new_cats"`
Expected: 6 個測試 FAIL（frag/key 不存在）。

- [ ] **Step 3: 實作 filter-bar.js 資料層**

(a) `_objfbSerialize`（:70-72，`for` 迴圈開頭）在 `if (p.cat === 'port')` 之後插入三行：

```js
    if (p.cat === 'service') { push(`${ex}services`, p.href || p.name); continue; }
    if (p.cat === 'port')    { push(`${ex}ports`, p.name); continue; }
    if (p.cat === 'process')      { push(`${ex}process_name`, p.name); continue; }
    if (p.cat === 'winservice')   { push(`${ex}windows_service_name`, p.name); continue; }
    if (p.cat === 'transmission') { push(`${ex}transmission`, p.name); continue; }
```

(b) `_objfbDeserialize` 在 `if (d['ex_port']) …`（:113）之後插入：

```js
  // Plan B：service 家族新類別（str | list[str] 皆容忍；transmission_excludes 為續留別名）
  for (const v of asList(d['process_name'])) add('process', v, null, false);
  for (const v of asList(d['ex_process_name'])) add('process', v, null, true);
  for (const v of asList(d['windows_service_name'])) add('winservice', v, null, false);
  for (const v of asList(d['ex_windows_service_name'])) add('winservice', v, null, true);
  for (const v of asList(d['transmission'])) add('transmission', v, null, false);
  for (const v of asList(d['ex_transmission']).concat(asList(d['transmission_excludes']))) add('transmission', v, null, true);
```

(c) `_OBJFB_CATS`（:153-161）補三個 entry：

```js
  process:      { i18n: 'gui_fb_cat_process',      dot: 'objfb-dot-process', fallback: 'Process Name' },
  winservice:   { i18n: 'gui_fb_cat_winservice',   dot: 'objfb-dot-winsvc',  fallback: 'Windows Service' },
  transmission: { i18n: 'gui_fb_cat_transmission', dot: 'objfb-dot-tx',      fallback: 'Transmission' },
```

(d) `_OBJFB_DIRLESS`（:165）改為：

```js
// 無方向類別：pill 不帶 src/dst/any、序列化不吃 dir。transmission 序列化亦無方向
// （flat key），但版面歸 Destination 欄（_objfbPillCol，Task 3）。
const _OBJFB_DIRLESS = new Set(['service', 'port', 'process', 'winservice', 'transmission']);
```

(e) 在 `_objfbApplyI18n`（:171）之前新增顯示函式，並讓 `_objfbBuildPill` 用它（:306 改 `txt.textContent = (p.neg ? '! ' : '') + _objfbPillLabel(p);`）：

```js
/* ── pill 顯示文字（spec §3.2）：port 無 proto 尾碼＝兩者；新類別帶語意前綴 ── */
function _objfbPillLabel(p) {
  if (p.cat === 'port' && !String(p.name).includes('/')) return `${p.name} (TCP+UDP)`;
  if (p.cat === 'process') return `proc: ${p.name}`;
  if (p.cat === 'winservice') return `winsvc: ${p.name}`;
  if (p.cat === 'transmission') return `TX: ${p.name}`;
  return p.name;
}
```

(f) `app.css` :2628（`.objfb-dot-port` 行）之後加三行（硬編 hex 比照 dot-service/dot-port 慣例）：

```css
.objfb-dot-process { background: #d98c3f; }
.objfb-dot-winsvc  { background: #5a9bd5; }
.objfb-dot-tx      { background: #c05c8e; }
```

(g) i18n 兩檔在 `gui_fb_browse_all` 之後各加（en / zh_TW）：

```json
"gui_fb_cat_process": "Process Name",
"gui_fb_cat_winservice": "Windows Service",
"gui_fb_cat_transmission": "Transmission",
```

```json
"gui_fb_cat_process": "程序名稱",
"gui_fb_cat_winservice": "Windows 服務",
"gui_fb_cat_transmission": "傳輸型態",
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_component_object_filter_bar.py -v`
Expected: 全數 PASS（含既有 41 個測試不回歸）。

- [ ] **Step 5: Commit**

```bash
git add src/static/js/filter-bar.js src/static/css/app.css src/i18n_en.json src/i18n_zh_TW.json tests/test_component_object_filter_bar.py
git commit -m "feat(filter-bar): process/winservice/transmission pill categories (data layer)"
```

---

### Task 2: Service / Transmission 候選產生器（純函式層）

**Files:**
- Modify: `src/static/js/filter-bar.js`（`_objfbIsPortLike` :30 之後）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_component_object_filter_bar.py`

**Interfaces:**
- Consumes: 無（純函式，不碰 state/DOM）。
- Produces:
  - `_objfbSvcCandidates(q) → Array<{grp: 'portproto'|'freetext'|'rangehint', items?: Array<{cat, name, tagI18n?, dflt?}>}>` — Task 4 下拉面板消費。
  - `_OBJFB_TX_VALUES`（`['unicast','broadcast','multicast']`）與 `_objfbTxCandidates(q) → Array<{cat:'transmission', name}>` — Task 3/4 消費。

- [ ] **Step 1: 寫失敗測試**

```python
def test_filter_bar_service_candidate_generator_present():
    """spec §3.2：數字→三選一（兩者預設）；範圍→三選一；文字→process/winservice 自由值。"""
    src = _JS.read_text(encoding="utf-8")
    fn = src.split("function _objfbSvcCandidates(q)", 1)[1].split("\nfunction ", 1)[0]
    assert "/tcp" in fn and "/udp" in fn
    assert "gui_fb_svc_both" in fn and "dflt: true" in fn
    assert "'process'" in fn and "'winservice'" in fn
    assert "rangehint" in fn


def test_filter_bar_transmission_candidate_generator_present():
    src = _JS.read_text(encoding="utf-8")
    assert "const _OBJFB_TX_VALUES = ['unicast', 'broadcast', 'multicast'];" in src
    assert "function _objfbTxCandidates(q)" in src


def test_filter_bar_svc_guidance_i18n_bilingual():
    import json
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    for k in ("gui_fb_svc_both", "gui_fb_svc_tcp_only", "gui_fb_svc_udp_only",
              "gui_fb_svc_range_hint", "gui_fb_fmt_hint", "gui_fb_kbd_hint",
              "gui_fb_grp_portproto", "gui_fb_grp_freetext"):
        assert k in en and k in zh, k
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_component_object_filter_bar.py -v -k "candidate_generator or svc_guidance"`
Expected: 3 個 FAIL。

- [ ] **Step 3: 實作候選產生器**

在 `_objfbIsPortLike`（:30）之後插入：

```js
/* ── Service 欄輸入引導（spec §3.2）：純函式，回傳分組候選供下拉渲染。
 * 數字 → 三選一（無尾碼＝兩者 TCP+UDP，預設）+ 範圍起點提示；
 * 範圍 → 三選一（已帶 /proto 則單一候選）；
 * 文字 → Process Name / Windows Service 自由值（Policy Services 走既有 suggest 流程，不在此函式）。
 */
function _objfbSvcCandidates(q) {
  const t = String(q).trim().toLowerCase();
  const inRange = (n) => n >= 1 && n <= 65535;
  let m = t.match(/^(\d{1,5})$/);
  if (m && inRange(+m[1])) {
    return [
      { grp: 'portproto', items: [
        { cat: 'port', name: m[1], tagI18n: 'gui_fb_svc_both', dflt: true },
        { cat: 'port', name: `${m[1]}/tcp`, tagI18n: 'gui_fb_svc_tcp_only' },
        { cat: 'port', name: `${m[1]}/udp`, tagI18n: 'gui_fb_svc_udp_only' },
      ] },
      { grp: 'rangehint' },
    ];
  }
  m = t.match(/^(\d{1,5})-(\d{1,5})(?:\/(tcp|udp))?$/);
  if (m && inRange(+m[1]) && inRange(+m[2])) {
    const base = `${m[1]}-${m[2]}`;
    return [{ grp: 'portproto', items: m[3]
      ? [{ cat: 'port', name: `${base}/${m[3]}` }]
      : [
        { cat: 'port', name: base, tagI18n: 'gui_fb_svc_both', dflt: true },
        { cat: 'port', name: `${base}/tcp`, tagI18n: 'gui_fb_svc_tcp_only' },
        { cat: 'port', name: `${base}/udp`, tagI18n: 'gui_fb_svc_udp_only' },
      ] }];
  }
  // 明確帶 proto 的單埠（443/tcp）交給 _objfbIsPortLike 的手動加入路徑，不出三選一
  if (t && !/^\d/.test(t) && !_objfbIsPortLike(t)) {
    return [{ grp: 'freetext', items: [
      { cat: 'process', name: String(q).trim() },
      { cat: 'winservice', name: String(q).trim() },
    ] }];
  }
  return [];
}

/* ── Transmission 候選（僅 Destination 側面板；值域固定，無後端查詢）── */
const _OBJFB_TX_VALUES = ['unicast', 'broadcast', 'multicast'];
function _objfbTxCandidates(q) {
  const t = String(q).trim().toLowerCase();
  const vals = t ? _OBJFB_TX_VALUES.filter((v) => v.startsWith(t)) : _OBJFB_TX_VALUES;
  return vals.map((v) => ({ cat: 'transmission', name: v }));
}
```

i18n 兩檔新增（en / zh_TW）：

```json
"gui_fb_svc_both": "Both (TCP + UDP)",
"gui_fb_svc_tcp_only": "TCP only",
"gui_fb_svc_udp_only": "UDP only",
"gui_fb_svc_range_hint": "Add \"-\" and an end port for a range, e.g. 1000-2000 (both ends inclusive)",
"gui_fb_fmt_hint": "443 = both · 443/tcp · 443/udp · 1000-2000 · 1000-2000/udp · text = Process / Win Service / Service name",
"gui_fb_kbd_hint": "↑↓ select · Enter add · Esc close",
"gui_fb_grp_portproto": "Port and/or Protocol",
"gui_fb_grp_freetext": "Process / Windows Service",
```

```json
"gui_fb_svc_both": "兩者（TCP + UDP）",
"gui_fb_svc_tcp_only": "僅 TCP",
"gui_fb_svc_udp_only": "僅 UDP",
"gui_fb_svc_range_hint": "輸入「-」接結束埠成為範圍，例 1000-2000（起訖皆含）",
"gui_fb_fmt_hint": "443＝兩者 · 443/tcp · 443/udp · 1000-2000 · 1000-2000/udp · 文字＝Process / Win Service / Service 名稱",
"gui_fb_kbd_hint": "↑↓ 選擇 · Enter 加入 · Esc 關閉",
"gui_fb_grp_portproto": "Port 與通訊協定",
"gui_fb_grp_freetext": "程序 / Windows 服務",
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_component_object_filter_bar.py -v`
Expected: 全數 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/static/js/filter-bar.js src/i18n_en.json src/i18n_zh_TW.json tests/test_component_object_filter_bar.py
git commit -m "feat(filter-bar): service/transmission candidate generators (pure fns)"
```

---

### Task 3: v2 三欄 zone 版面 + AND/OR 切換 + ⇄ 對調

本 task 是核心重構：把「方向分段鈕＋單一搜尋列」換成 zone 模型。公開 API 與序列化不變；`state.dirs`/`state.addDir` 保留為 object-browser.js 相容欄位。

**Files:**
- Modify: `src/static/js/filter-bar.js`（`createFilterBar`、`_objfbRender` 全段、handlers、deserialize 尾端）
- Modify: `src/static/css/app.css`（objfb 區段：移除 `.objfb-dir-seg`/`.objfb-dir-btn`/`.objfb-pill-dir`，新增 v2 版面 class）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_component_object_filter_bar.py`

**Interfaces:**
- Consumes: Task 1 的 `_objfbPillLabel`/`_OBJFB_DIRLESS`；Task 2 的 `_objfbTxCandidates`。
- Produces（Task 4/5/6 依賴的確切名稱）:
  - state 欄位：`state.mode ('and'|'or')`、`state.zone ({col, neg}|null)`、`state.zoneEls ({'col:neg': {fbar, input, dd}})`、`state.exclOpen (bool)`、`state.pop (Element)`；`state.dirs`、`state.addDir` 續留（相容）。
  - 函式：`_objfbCols(state) → string[]`、`_objfbZoneCats(state, col) → string[]`、`_objfbPillCol(state, p) → 'src'|'dst'|'any'|'svc'`、`_objfbFocusZone(state, col, neg)`、`_objfbBuildMid(state, neg)`、`_objfbBuildZone(state, col, neg)`、`_objfbRenderTxList(state)`。
  - window handlers：`_objfbZoneClick(id, col, neg)`、`_objfbToggleMode(id)`、`_objfbSwapCols(id)`、`_objfbToggleExcl(id)`；`_objfbInput`/`_objfbKeydown` 簽名改為 `(id, col, neg[, ev])`；**`window._objfbAddDir` 移除**。
  - DOM 契約（e2e 依賴）：`.objfb-col[data-zone="src:false"]` 等 zone 容器；`.objfb-mode`、`.objfb-swap`、`.objfb-excl-toggle`。

- [ ] **Step 1: 更新/新增靜態測試（RED）**

修改既有測試：

```python
def test_filter_bar_handlers_on_window():
    src = _JS.read_text(encoding="utf-8")
    for fn in ("_objfbInput", "_objfbKeydown", "_objfbPillClick",
               "_objfbZoneClick", "_objfbToggleMode", "_objfbSwapCols", "_objfbToggleExcl"):
        assert f"window.{fn}" in src, f"{fn} must be on window for CSP dispatcher"
    # v1 方向分段鈕已由 zone 模型取代
    assert "window._objfbAddDir" not in src


def test_any_direction_label_group_pill_guard_present():
    src = _JS.read_text(encoding="utf-8")
    assert "obj.cat === 'label_group' && z.col === 'any'" in src
```

新增：

```python
def test_filter_bar_v2_zone_model():
    """Plan B Task 3：zone 模型（col×neg）。transmission 歸 Destination 欄；
    svc 欄容納四個無方向 service 家族類別。"""
    src = _JS.read_text(encoding="utf-8")
    for fn in ("function _objfbCols(state)", "function _objfbZoneCats(state, col)",
               "function _objfbPillCol(state, p)", "function _objfbFocusZone(state, col, neg)"):
        assert fn in src, fn
    zc = src.split("function _objfbZoneCats(state, col)", 1)[1].split("\nfunction ", 1)[0]
    assert "'service', 'port', 'process', 'winservice'" in zc
    assert "col === 'dst' || col === 'any'" in zc  # transmission 僅 Destination（含 OR 合併欄）
    pc = src.split("function _objfbPillCol(state, p)", 1)[1].split("\nfunction ", 1)[0]
    assert "p.cat === 'transmission'" in pc


def test_filter_bar_v2_mode_and_swap():
    src = _JS.read_text(encoding="utf-8")
    tm = src.split("window._objfbToggleMode = function (id)", 1)[1].split("\nwindow.", 1)[0]
    # AND→OR：src/dst 併入 any；label_group 擋下切換（不得靜默丟 pill）
    assert "p.dir = 'any'" in tm
    assert "lgroupOrBlockHint" in tm
    # OR→AND：any 拆回 Source 欄並提示（spec §2 決策）
    assert "p.dir = 'src'" in tm and "movedAnyHint" in tm
    sw = src.split("window._objfbSwapCols = function (id)", 1)[1].split("\nwindow.", 1)[0]
    assert "p.dir = 'dst'" in sw and "p.dir = 'src'" in sw


def test_filter_bar_v2_deserialize_mode_detection():
    src = _JS.read_text(encoding="utf-8")
    de = src.split("function _objfbDeserialize(state, dict)", 1)[1].split("\nfunction ", 1)[0]
    assert "state.mode = 'or'" in de and "state.mode = 'and'" in de
    assert "state.exclOpen" in de


def test_filter_bar_v2_css_classes():
    css = _CSS.read_text(encoding="utf-8")
    for cls in (".objfb-grid", ".objfb-row", ".objfb-col", ".objfb-col-label",
                ".objfb-mid", ".objfb-mode", ".objfb-swap", ".objfb-excl-toggle",
                ".objfb-fbar-excl"):
        assert cls in css, cls
    # v1 方向分段鈕與 pill 方向徽章樣式已移除
    assert ".objfb-dir-seg" not in css and ".objfb-dir-btn" not in css
    assert ".objfb-pill-dir" not in css


def test_filter_bar_v2_zone_dom_contract():
    """e2e 依賴的 DOM 契約：zone 容器帶 data-zone=col:neg。"""
    src = _JS.read_text(encoding="utf-8")
    assert "zone.dataset.zone = zoneKey" in src


def test_filter_bar_v2_i18n_bilingual():
    import json
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    for k in ("gui_fb_col_svc", "gui_fb_col_any", "gui_fb_col_src_not", "gui_fb_col_dst_not",
              "gui_fb_col_svc_not", "gui_fb_col_any_not", "gui_fb_mode_title",
              "gui_fb_swap_title", "gui_fb_excl_toggle", "gui_fb_moved_any_src",
              "gui_fb_lgroup_or_blocked", "gui_fb_svc_placeholder"):
        assert k in en and k in zh, k


def test_filter_bar_object_browser_compat_shim():
    """object-browser.js 以 fb.addDir/fb.dirs 加 pill；shim 把 addDir 映射回 zone。"""
    src = _JS.read_text(encoding="utf-8")
    shim = src.split("window._objfbAddPillPublic", 1)[1].split("\nwindow.", 1)[0]
    assert "state.addDir" in shim and "neg: false" in shim
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_component_object_filter_bar.py -v -k "v2 or handlers_on_window or label_group_pill_guard or browser_compat"`
Expected: 新增/修改的測試 FAIL；其餘 PASS。

- [ ] **Step 3: 實作 zone 模型與 v2 render**

(a) `createFilterBar`（:32-62）改為（回傳物件四方法不變）：

```js
function createFilterBar(container, options) {
  const opts = options || {};
  const cats = opts.cats || ['label', 'label_group', 'iplist', 'workload', 'ip',
    'service', 'port', 'process', 'winservice', 'transmission'];
  const id = 'objfb-' + (++_objfbSeq);
  const state = {
    id, container, cats,
    pills: [],          // {cat, name, href, key, value, dir, neg}
    mode: 'and',        // 'and'＝Source/Destination 分欄；'or'＝合併 Source OR Destination 欄
    dirs: ['src', 'dst'],  // object-browser.js 相容（依 mode 派生，_objfbRender 維護）
    addDir: 'src',         // object-browser.js 相容：外部加 pill 的方向
    zone: null,         // 作用中欄位 {col, neg}；col ∈ src|dst|any|svc
    zoneEls: {},        // `${col}:${neg}` → {fbar, input, dd}
    exclOpen: false,    // is-not 排除列展開狀態（modal 預設收合，spec §3.1）
    scopeCat: null,
    changeCb: null,
    _abort: null,
    _suggest: null,
    _suggestQ: null,
  };
  state._debouncedSuggest = window.debounce((q) => _objfbQuerySuggest(state, q), 250);
  _objfbInstances[id] = state;
  container.dataset.objfbId = id;
  container.classList.add('objfb-bar');
  if (opts.initial) _objfbDeserialize(state, opts.initial);
  _objfbRender(state);
  return {
    getFilters: () => _objfbSerialize(state),
    setFilters: (dict) => { _objfbDeserialize(state, dict); _objfbRender(state); },
    onChange: (cb) => { state.changeCb = cb; },
    destroy: () => { delete _objfbInstances[id]; container.innerHTML = ''; },
  };
}
```

(b) 在 `_OBJFB_DIR_TAG`（:162，此常數可一併刪除——pill 不再帶方向徽章）位置改放 zone 模型常數與函式：

```js
/* ── v2 zone 模型（Plan B）：col ∈ src|dst|any|svc × neg ∈ include|exclude。
 * [include i18n, exclude i18n, include fallback, exclude fallback] ── */
const _OBJFB_ZONE_LABELS = {
  src: ['gui_fb_dir_src', 'gui_fb_col_src_not', 'Source', 'Source is not'],
  dst: ['gui_fb_dir_dst', 'gui_fb_col_dst_not', 'Destination', 'Destination is not'],
  any: ['gui_fb_col_any', 'gui_fb_col_any_not', 'Source OR Destination', 'Source OR Destination is not'],
  svc: ['gui_fb_col_svc', 'gui_fb_col_svc_not', 'Service', 'Service is not'],
};

function _objfbCols(state) { return state.mode === 'or' ? ['any', 'svc'] : ['src', 'dst', 'svc']; }

function _objfbZoneCats(state, col) {
  if (col === 'svc') {
    return ['service', 'port', 'process', 'winservice'].filter((c) => state.cats.includes(c));
  }
  const out = ['label', 'label_group', 'iplist', 'workload', 'ip'].filter((c) =>
    state.cats.includes(c) && !(col === 'any' && c === 'label_group'));
  // Transmission 僅 Destination 側（OR 模式合併欄包含 Destination，一併提供）——spec §3.1
  if ((col === 'dst' || col === 'any') && state.cats.includes('transmission')) out.push('transmission');
  return out;
}

function _objfbPillCol(state, p) {
  if (p.cat === 'transmission') return state.mode === 'or' ? 'any' : 'dst';
  if (p.dir === null) return 'svc';
  return p.dir;
}
```

(c) `_objfbRender`（:179-283）整段替換：

```js
/* ── 完整重繪（v2）：兩列（include / is-not）× 三欄（OR 模式兩欄）zone，
 * 中央 AND/OR 徽章 + ⇄ 鈕，排除列預設收合。下拉候選仍由 _objfbUpdateDropdown
 * 局部更新（作用中 zone 的 dd），避免每鍵重建失焦。 ── */
function _objfbRender(state) {
  const c = state.container;
  c.innerHTML = '';
  state.dirs = state.mode === 'or' ? ['any'] : ['src', 'dst'];
  if (!state.dirs.includes(state.addDir)) state.addDir = state.dirs[0];
  state.zoneEls = {};

  const grid = document.createElement('div');
  grid.className = 'objfb-grid';
  for (const neg of [false, true]) {
    const row = document.createElement('div');
    row.className = 'objfb-row' + (neg ? ' objfb-row-excl' : '');
    if (neg && !state.exclOpen) row.hidden = true;
    _objfbCols(state).forEach((col, ci) => {
      if (ci === 1) row.appendChild(_objfbBuildMid(state, neg));
      row.appendChild(_objfbBuildZone(state, col, neg));
    });
    grid.appendChild(row);
  }
  c.appendChild(grid);

  const exclBtn = document.createElement('button');
  exclBtn.type = 'button';
  exclBtn.className = 'objfb-excl-toggle';
  exclBtn.setAttribute('aria-expanded', state.exclOpen ? 'true' : 'false');
  exclBtn.setAttribute('data-i18n', 'gui_fb_excl_toggle');
  exclBtn.textContent = 'Exclusions (is not)';
  exclBtn.setAttribute('data-on-click', '_objfbToggleExcl');
  exclBtn.dataset.args = JSON.stringify([state.id]);
  c.appendChild(exclBtn);

  // 提示列：OR/any 較慢、any×label_group 不支援、label_group 擋 OR、OR→AND 搬移
  const mkHint = (i18nKey, hidden) => {
    const el = document.createElement('div');
    el.className = 'objfb-hint';
    el.setAttribute('data-i18n', i18nKey);
    el.hidden = hidden;
    c.appendChild(el);
  };
  mkHint('gui_fb_any_slow', !(state.mode === 'or' && state.pills.length > 0));
  mkHint('gui_fb_any_label_group_unsupported', !state.anyLabelGroupHint);
  mkHint('gui_fb_lgroup_or_blocked', !state.lgroupOrBlockHint);
  mkHint('gui_fb_moved_any_src', !state.movedAnyHint);

  const pop = document.createElement('div');
  pop.className = 'objfb-pop';
  c.appendChild(pop);

  state.els = null;   // 作用中 zone 的 {fbar, input, dd}；_objfbFocusZone 指定
  state.pop = pop;
  state.ddItems = [];
  state.actIdx = -1;
  state.popIdx = -1;

  _objfbApplyI18n(c);
}

function _objfbBuildMid(state, neg) {
  const mid = document.createElement('div');
  // 排除列的中央控制只佔位對齊（比照 mockup visibility:hidden）
  mid.className = 'objfb-mid' + (neg ? ' objfb-mid-ghost' : '');
  const mode = document.createElement('button');
  mode.type = 'button';
  mode.className = 'objfb-mode' + (state.mode === 'or' ? ' or' : '');
  mode.textContent = state.mode === 'or' ? 'OR' : 'AND';
  mode.setAttribute('data-i18n-title', 'gui_fb_mode_title');
  mode.setAttribute('data-on-click', '_objfbToggleMode');
  mode.dataset.args = JSON.stringify([state.id]);
  mid.appendChild(mode);
  if (state.mode === 'and') {
    const swap = document.createElement('button');
    swap.type = 'button';
    swap.className = 'objfb-swap';
    swap.textContent = '⇄';
    swap.setAttribute('data-i18n-title', 'gui_fb_swap_title');
    swap.setAttribute('data-on-click', '_objfbSwapCols');
    swap.dataset.args = JSON.stringify([state.id]);
    mid.appendChild(swap);
  }
  return mid;
}

function _objfbBuildZone(state, col, neg) {
  const zoneKey = col + ':' + neg;
  const zone = document.createElement('div');
  zone.className = 'objfb-col' + (col === 'svc' ? ' objfb-col-svc' : '');
  zone.dataset.zone = zoneKey;

  const lbl = document.createElement('div');
  lbl.className = 'objfb-col-label';
  const zmeta = _OBJFB_ZONE_LABELS[col];
  lbl.setAttribute('data-i18n', zmeta[neg ? 1 : 0]);
  lbl.textContent = zmeta[neg ? 3 : 2];
  zone.appendChild(lbl);

  const fbar = document.createElement('div');
  fbar.className = 'objfb-fbar' + (neg ? ' objfb-fbar-excl' : '');
  fbar.setAttribute('data-on-click', '_objfbZoneClick');
  fbar.dataset.args = JSON.stringify([state.id, col, neg]);

  // 同 key label pill 之間插入 or 分隔（zone 內比對即可——同欄已隱含同方向）
  let prevKey = null;
  state.pills.forEach((p, i) => {
    if (_objfbPillCol(state, p) !== col || p.neg !== neg) return;
    const derivedKey = p.key || (p.cat === 'label' && String(p.name).includes('=') ? String(p.name).split('=')[0] : null);
    if (prevKey && p.cat === 'label' && derivedKey && prevKey === derivedKey) {
      const orEl = document.createElement('span');
      orEl.className = 'objfb-or';
      orEl.setAttribute('data-i18n', 'gui_fb_or');
      orEl.textContent = 'or';
      fbar.appendChild(orEl);
    }
    fbar.appendChild(_objfbBuildPill(state, p, i));
    prevKey = (p.cat === 'label' && derivedKey) ? derivedKey : null;
  });

  const isActive = state.zone && state.zone.col === col && state.zone.neg === neg;
  if (isActive && state.scopeCat) {
    const chip = document.createElement('span');
    chip.className = 'objfb-scope-chip';
    const label = document.createElement('span');
    const meta = _OBJFB_CATS[state.scopeCat];
    if (meta && meta.i18n) label.setAttribute('data-i18n', meta.i18n);
    label.textContent = meta ? meta.fallback : state.scopeCat;
    chip.appendChild(label);
    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'objfb-scope-x';
    x.textContent = '×';
    x.setAttribute('data-on-click', '_objfbClearScope');
    x.dataset.args = JSON.stringify([state.id]);
    chip.appendChild(x);
    fbar.appendChild(chip);
  }

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'objfb-input';
  input.autocomplete = 'off';
  input.setAttribute('data-i18n-placeholder', col === 'svc' ? 'gui_fb_svc_placeholder' : 'gui_fb_placeholder');
  input.placeholder = 'Search…';
  input.setAttribute('aria-label', 'Filter search');
  input.setAttribute('data-on-input', '_objfbInput');
  input.dataset.args = JSON.stringify([state.id, col, neg]);
  input.setAttribute('data-on-keydown', '_objfbKeydown');
  input.setAttribute('data-pass-event', '1');
  fbar.appendChild(input);

  const dd = document.createElement('div');
  dd.className = 'objfb-dd';
  dd.setAttribute('role', 'listbox');
  fbar.appendChild(dd);

  zone.appendChild(fbar);
  state.zoneEls[zoneKey] = { fbar, input, dd };
  return zone;
}
```

(d) `_objfbBuildPill`（:285-320）：移除 `p.dir !== null` 的方向徽章區塊（欄位已隱含方向）；`txt.textContent` 已在 Task 1 改用 `_objfbPillLabel`；其餘不變，另補 `el.dataset.pillIdx = String(idx);`（popover 重開定位用，見 (h)）。

(e) 焦點/輸入 handler（取代 `window._objfbAddDir` 與原 `_objfbInput`）：

```js
function _objfbFocusZone(state, col, neg) {
  const z = state.zoneEls[col + ':' + neg];
  if (!z) return;
  const changed = !state.zone || state.zone.col !== col || state.zone.neg !== neg;
  if (changed) {
    state.scopeCat = null;
    for (const k in state.zoneEls) state.zoneEls[k].dd.classList.remove('open');
  }
  state.zone = { col, neg };
  if (col !== 'svc' && col !== 'any') state.addDir = col;      // object-browser.js 相容
  else if (col === 'any') state.addDir = 'any';
  state.els = z;
  z.input.focus();
  _objfbUpdateDropdown(state);
}

window._objfbZoneClick = function (id, col, neg) {
  const s = _objfbInstances[id];
  if (s) _objfbFocusZone(s, col, neg);
};

window._objfbInput = function (id, col, neg) {
  const s = _objfbInstances[id];
  if (s) _objfbFocusZone(s, col, neg);
};
```

(f) `window._objfbKeydown` 簽名改 `(id, col, neg, ev)`，函式開頭加 `if (!s.zone || s.zone.col !== col || s.zone.neg !== neg) _objfbFocusZone(s, col, neg);`。Enter 的手動 fallback 分支改依 zone 判斷；Backspace 只刪本 zone 最後一顆：

```js
  } else if (key === 'Enter') {
    ev.preventDefault();
    if (s.actIdx >= 0 && s.ddItems[s.actIdx]) {
      window._objfbPickItem(id, s.ddItems[s.actIdx].o);
    } else {
      const q = s.els.input.value.trim();
      if (col === 'svc' && _objfbIsPortLike(q) && s.cats.includes('port')) {
        window._objfbPickItem(id, { cat: 'port', name: q });
      } else if (col !== 'svc' && _objfbIsIpLike(q)) {
        window._objfbPickItem(id, { cat: 'ip', name: q });
      } else if (col !== 'svc') {
        const eq = q.indexOf('=');
        if (eq > 0 && eq < q.length - 1) {
          const k = q.slice(0, eq).trim();
          const v = q.slice(eq + 1).trim();
          if (k && v) window._objfbPickItem(id, { cat: 'label', name: q, key: k, value: v });
        }
      }
    }
  } else if (key === 'Escape') {
    s.els.dd.classList.remove('open');
    s.actIdx = -1;
  } else if (key === 'Backspace' && !s.els.input.value) {
    if (s.scopeCat) { window._objfbClearScope(id); return; }
    for (let i = s.pills.length - 1; i >= 0; i--) {
      const p = s.pills[i];
      if (_objfbPillCol(s, p) === col && p.neg === neg) { window._objfbRemovePill(id, i); return; }
    }
  }
```

(g) 模式切換 / 對調 / 排除列 toggle：

```js
window._objfbToggleMode = function (id) {
  const s = _objfbInstances[id];
  if (!s) return;
  s.anyLabelGroupHint = false;
  s.movedAnyHint = false;
  if (s.mode === 'and') {
    // label_group 不能進 any（序列化 fail-closed 會丟棄）：擋切換並提示，不動資料
    if (s.pills.some((p) => p.cat === 'label_group')) {
      s.lgroupOrBlockHint = true;
      _objfbRender(s);
      return;
    }
    s.lgroupOrBlockHint = false;
    for (const p of s.pills) if (p.dir === 'src' || p.dir === 'dst') p.dir = 'any';
    s.mode = 'or';
  } else {
    s.lgroupOrBlockHint = false;
    let moved = 0;
    for (const p of s.pills) if (p.dir === 'any') { p.dir = 'src'; moved++; }
    s.mode = 'and';
    s.movedAnyHint = moved > 0;  // any 拆回 AND：pill 放 Source 欄並提示（spec §2）
  }
  s.zone = null;
  _objfbRender(s);
  if (s.changeCb) s.changeCb();
};

window._objfbSwapCols = function (id) {
  const s = _objfbInstances[id];
  if (!s || s.mode !== 'and') return;
  // transmission pill dir=null，天然不受對調影響（僅 Destination 側，spec §3.1）
  for (const p of s.pills) {
    if (p.dir === 'src') p.dir = 'dst';
    else if (p.dir === 'dst') p.dir = 'src';
  }
  s.zone = null;
  _objfbRender(s);
  if (s.changeCb) s.changeCb();
};

window._objfbToggleExcl = function (id) {
  const s = _objfbInstances[id];
  if (!s) return;
  s.exclOpen = !s.exclOpen;
  _objfbRender(s);
};
```

(h) `_objfbAddPill`（:135-150）與 `_objfbAddPillPublic`（:818）：

```js
function _objfbAddPill(state, obj) {
  const z = state.zone || { col: state.addDir, neg: false };
  if (obj.cat === 'label_group' && z.col === 'any') {
    // any（OR）方向不支援 label_group：不建 pill，顯示提示（design §C）
    state.anyLabelGroupHint = true;
    _objfbRender(state);
    return;
  }
  state.anyLabelGroupHint = false;
  state.pills.push({
    cat: obj.cat, name: obj.name, href: obj.href || null,
    key: obj.key || null, value: obj.value || null,
    dir: _OBJFB_DIRLESS.has(obj.cat) || z.col === 'svc' ? null : z.col,
    neg: z.neg,
  });
  _objfbRender(state);
  if (state.changeCb) state.changeCb();
}
```

```js
window._objfbAddPillPublic = function (state, obj) {
  // object-browser.js 以 fb.addDir 指定方向；映射回 zone 模型（include 列）
  const saved = state.zone;
  state.zone = { col: state.addDir || _objfbCols(state)[0], neg: false };
  _objfbAddPill(state, obj);
  state.zone = saved;
};
```

(i) `_objfbOpenPop`/`_objfbPopAction`：`state.els.pop` 全改 `state.pop`；方向列只在 `state.mode === 'and'` 且 `!_OBJFB_DIRLESS.has(p.cat)` 時渲染，方向選項固定 `['src', 'dst']`；`neg` 設為 true 時同步 `s.exclOpen = true;`；action 後重開 popover 改用 `s.container.querySelector('.objfb-pill[data-pill-idx="' + idx + '"]')` 定位（pill 已按 zone 分散，原本的 `querySelectorAll('.objfb-pill')[idx]` 全域索引會錯位）。

(j) 下拉 zone 過濾（本 task 沿用 v1 單欄下拉內容；Task 4 才換兩欄面板）：
- `_objfbUpdateDropdown` 空輸入分支：`scopeCat === 'transmission'` 時走 `_objfbRenderTxList(state)`；`scopeCat` 為 `'process'`/`'winservice'` 時顯示 `gui_fb_type_to_search` note（比照 workload）；其餘不變。
- `_objfbRenderCatChips` 的迭代清單改為 `_objfbZoneCats(state, state.zone ? state.zone.col : _objfbCols(state)[0]).filter((c) => c !== 'ip' && c !== 'port' && state.cats.includes(c))`。
- `_objfbQuerySuggest` types 導出改為：

```js
  if (scope && !_OBJFB_SUGGEST_CATS.includes(scope)) return; // process/winservice/transmission 無後端 suggest
  const zoneCats = state.zone ? _objfbZoneCats(state, state.zone.col) : state.cats;
  const types = scope ? scope : _OBJFB_SUGGEST_CATS.filter((c) =>
    state.cats.includes(c) && zoneCats.includes(c)).join(',');
  if (!types) return;
```

- `_objfbRenderDropdown`：IP/CIDR 候選限 `state.zone && state.zone.col !== 'svc'`；port 候選限 `state.zone && state.zone.col === 'svc'`；suggest 分組迭代過濾同樣交集 `zoneCats`（保留 `state.cats.includes(c)` 字面——守門測試鎖定）；scope 為 process/winservice 時渲染自由值候選；dst/any 欄輸入文字時附 `_objfbTxCandidates(q)` 分組（非空才加）。
- 新增：

```js
function _objfbRenderTxList(state) {
  const dd = state.els.dd;
  dd.innerHTML = '';
  state.ddItems = [];
  _objfbAddDdGroup(state, _objfbTxCandidates(state.els.input.value.trim()),
    'gui_fb_cat_transmission', 'Transmission');
  _objfbApplyI18n(dd);
  state.actIdx = state.ddItems.length ? 0 : -1;
  _objfbMarkActive(state);
  dd.classList.add('open');
}
```

(k) `_objfbDeserialize` 尾端（Task 1 新增區塊之後、`for (const [k, cat] of …any…)` 迴圈之後）加模式判定：

```js
  // v2 模式判定：純 any_* → OR 模式；混雜（v1 歷史資料）→ AND，any pill 放
  // Source 欄並提示（spec §2「any 拆回時放 Source 欄並提示」）。重存後 key 隨之正規化。
  const hasAny = state.pills.some((p) => p.dir === 'any');
  const hasSided = state.pills.some((p) => p.dir === 'src' || p.dir === 'dst');
  if (hasAny && !hasSided) {
    state.mode = 'or';
    state.movedAnyHint = false;
  } else {
    state.mode = 'and';
    let moved = 0;
    for (const p of state.pills) if (p.dir === 'any') { p.dir = 'src'; moved++; }
    state.movedAnyHint = moved > 0;
  }
  state.exclOpen = state.pills.some((p) => p.neg);
  state.zone = null;
```

(l) 檔尾 outside-click listener 改為逐 zone：

```js
document.addEventListener('click', function (e) {
  for (const id in _objfbInstances) {
    const s = _objfbInstances[id];
    for (const k in s.zoneEls) {
      if (!s.zoneEls[k].fbar.contains(e.target)) s.zoneEls[k].dd.classList.remove('open');
    }
    if (s.pop && !s.pop.contains(e.target) && !e.target.closest('.objfb-pill')) s.pop.classList.remove('open');
  }
});
```

(m) 移除孤兒：`window._objfbAddDir`、`_OBJFB_DIR_TAG` 常數、`_objfbRender` 舊 body 內的 dirSeg 區塊。序列化的 any 分支、`gui_fb_dir_any` i18n key 續留（OR 模式仍serialize any_*；object-browser 方向 tab 仍用 gui_fb_dir_*）。

- [ ] **Step 4: CSS**

`app.css`：刪除 `.objfb-dir-seg`/`.objfb-dir-btn`/`.objfb-dir-btn:last-child`/`.objfb-dir-btn.on`（:2516-2534）與 `.objfb-pill-dir` 兩條規則（:2583-2593）。在 `.objfb-fbar` 區塊前插入：

```css
/* ── v2 三欄 zone 版面（Plan B）：flex-wrap + min-width，窄 modal 自然垂直堆疊 ── */
.objfb-grid { display: flex; flex-direction: column; gap: var(--space-2); width: 100%; }
.objfb-row { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: stretch; }
.objfb-col { flex: 1 1 220px; min-width: 200px; display: flex; flex-direction: column; gap: var(--space-1); }
.objfb-col-svc { flex: 1 1 180px; }
.objfb-col-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--dim);
  text-transform: uppercase;
  letter-spacing: .05em;
}
.objfb-row-excl .objfb-col-label { color: var(--danger); }
.objfb-mid { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-1); flex: none; }
.objfb-mid-ghost { visibility: hidden; }
.objfb-mode {
  border: 0;
  border-radius: var(--radius-sm, 6px);
  background: var(--accent);
  color: #fff;
  font: inherit;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: .05em;
  padding: var(--space-1) var(--space-2);
  cursor: pointer;
}
.objfb-mode.or { background: var(--warn); }
.objfb-swap {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 6px);
  background: var(--bg3);
  color: var(--dim);
  font: inherit;
  font-size: 13px;
  padding: var(--space-1) var(--space-2);
  cursor: pointer;
}
.objfb-swap:hover { border-color: var(--accent); color: var(--fg); }
.objfb-fbar-excl { border-style: dashed; }
.objfb-fbar-excl:focus-within {
  border-color: var(--danger);
  box-shadow: 0 0 0 2px color-mix(in oklab, var(--danger) 18%, transparent);
}
.objfb-excl-toggle {
  border: 0;
  background: none;
  color: var(--dim);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  padding: var(--space-1) 0;
  text-align: left;
}
.objfb-excl-toggle:hover { color: var(--fg); }
.objfb-excl-toggle[aria-expanded="true"] { color: var(--danger); }
```

- [ ] **Step 5: i18n 新 key（兩檔）**

en：

```json
"gui_fb_col_svc": "Service",
"gui_fb_col_any": "Source OR Destination",
"gui_fb_col_src_not": "Source is not",
"gui_fb_col_dst_not": "Destination is not",
"gui_fb_col_svc_not": "Service is not",
"gui_fb_col_any_not": "Source OR Destination is not",
"gui_fb_mode_title": "Toggle AND (separate Source/Destination) / OR (either side)",
"gui_fb_swap_title": "Swap Source and Destination",
"gui_fb_excl_toggle": "Exclusions (is not)",
"gui_fb_moved_any_src": "Either-side conditions were moved to the Source column; adjust before saving if needed",
"gui_fb_lgroup_or_blocked": "Label Group conditions are not supported in OR mode; remove them before switching",
"gui_fb_svc_placeholder": "443 · 1000-2000 · process / service name…",
```

zh_TW：

```json
"gui_fb_col_svc": "服務",
"gui_fb_col_any": "來源或目的",
"gui_fb_col_src_not": "來源排除",
"gui_fb_col_dst_not": "目的排除",
"gui_fb_col_svc_not": "服務排除",
"gui_fb_col_any_not": "來源或目的排除",
"gui_fb_mode_title": "切換 AND（來源／目的分欄）／ OR（任一側）",
"gui_fb_swap_title": "對調來源與目的",
"gui_fb_excl_toggle": "排除條件（is not）",
"gui_fb_moved_any_src": "「任一側」條件已移入來源欄；如需調整請於儲存前處理",
"gui_fb_lgroup_or_blocked": "OR 模式不支援標籤群組條件；請先移除再切換",
"gui_fb_svc_placeholder": "443 · 1000-2000 · 程序／服務名稱…",
```

- [ ] **Step 6: 跑測試確認通過**

Run: `pytest tests/test_component_object_filter_bar.py tests/test_component_filter_bar.py tests/test_component_abstraction_baseline.py tests/test_css_spacing_lint.py -v`
Expected: 全數 PASS。若 `test_css_spacing_lint` 超標，把新 CSS 中硬編 margin/padding 換成 `var(--space-*)`。

- [ ] **Step 7: 手動冒煙（本機服務）**

啟動本機服務後開瀏覽器檢查：流量分析器 modal（qt）三欄呈現、AND/OR 切換 pill 搬移、⇄ 對調、排除列收合展開、label pill 加入/移除/popover 移欄。無 console error。

- [ ] **Step 8: Commit**

```bash
git add src/static/js/filter-bar.js src/static/css/app.css src/i18n_en.json src/i18n_zh_TW.json tests/test_component_object_filter_bar.py
git commit -m "feat(filter-bar): v2 three-column zone layout with AND/OR toggle and swap"
```

---

### Task 4: 兩欄式下拉面板 + Service 欄輸入引導整合

把每個 zone 的下拉改為「左候選、右類別清單、底部鍵盤/格式提示」的兩欄面板（mockup `.cat-panel` 結構），並接上 Task 2 的候選產生器。

**Files:**
- Modify: `src/static/js/filter-bar.js`（`_objfbBuildZone` 的 dd 結構、`_objfbUpdateDropdown`/`_objfbRenderCatChips`（改名 `_objfbRenderCatPane`）/`_objfbRenderDropdown`/`_objfbRenderBrowse*`/`_objfbAddDd*`）
- Modify: `src/static/css/app.css`
- Test: `tests/test_component_object_filter_bar.py`

**Interfaces:**
- Consumes: Task 2 `_objfbSvcCandidates`/`_objfbTxCandidates`；Task 3 zone 模型。
- Produces: `state.zoneEls[key]` 增加 `ddMain`/`ddCats` 欄位；候選渲染目標由 `state.els.dd` 改 `state.els.ddMain`（`dd` 仍是 open/close 的容器）。

- [ ] **Step 1: 寫失敗測試**

```python
def test_filter_bar_two_pane_dropdown():
    """Plan B Task 4：下拉面板＝左候選 + 右類別清單 + 底部提示列（mockup .cat-panel）。"""
    src = _JS.read_text(encoding="utf-8")
    css = _CSS.read_text(encoding="utf-8")
    for frag in ("objfb-dd-body", "objfb-dd-main", "objfb-dd-catlist", "objfb-dd-foot",
                 "gui_fb_kbd_hint", "gui_fb_cat_all"):
        assert frag in src, frag
    for cls in (".objfb-dd-body", ".objfb-dd-main", ".objfb-dd-catlist",
                ".objfb-dd-foot", ".objfb-cat-item", ".objfb-dd-tag"):
        assert cls in css, cls


def test_filter_bar_svc_zone_uses_candidate_generator():
    src = _JS.read_text(encoding="utf-8")
    fn = src.split("function _objfbRenderDropdown(state, q)", 1)[1].split("\nfunction ", 1)[0]
    assert "_objfbSvcCandidates(q)" in fn
    assert "gui_fb_svc_range_hint" in fn
    # 既有守門契約續留：候選分類迭代仍照 state.cats 過濾
    assert "state.cats.includes(c)" in fn


def test_filter_bar_svc_zone_format_hint_persistent():
    """Service 欄面板底部常駐格式提示列（spec §3.2）。"""
    src = _JS.read_text(encoding="utf-8")
    fn = src.split("function _objfbBuildZone(state, col, neg)", 1)[1].split("\nfunction ", 1)[0]
    assert "gui_fb_fmt_hint" in fn and "col === 'svc'" in fn


def test_filter_bar_cat_all_i18n_bilingual():
    import json
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    assert "gui_fb_cat_all" in en and "gui_fb_cat_all" in zh
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_component_object_filter_bar.py -v -k "two_pane or svc_zone or cat_all"`
Expected: 4 個 FAIL。

- [ ] **Step 3: 實作兩欄面板**

(a) `_objfbBuildZone` 的 dd 建構段改為：

```js
  const dd = document.createElement('div');
  dd.className = 'objfb-dd';
  const body = document.createElement('div');
  body.className = 'objfb-dd-body';
  const ddMain = document.createElement('div');
  ddMain.className = 'objfb-dd-main';
  ddMain.setAttribute('role', 'listbox');
  const ddCats = document.createElement('div');
  ddCats.className = 'objfb-dd-catlist';
  body.appendChild(ddMain);
  body.appendChild(ddCats);
  dd.appendChild(body);
  const foot = document.createElement('div');
  foot.className = 'objfb-dd-foot';
  const kbd = document.createElement('span');
  kbd.className = 'objfb-kbd-hint';
  kbd.setAttribute('data-i18n', 'gui_fb_kbd_hint');
  foot.appendChild(kbd);
  if (col === 'svc') {
    const fmt = document.createElement('span');
    fmt.className = 'objfb-fmt-hint';
    fmt.setAttribute('data-i18n', 'gui_fb_fmt_hint');
    foot.appendChild(fmt);
  }
  dd.appendChild(foot);
  fbar.appendChild(dd);
  …
  state.zoneEls[zoneKey] = { fbar, input, dd, ddMain, ddCats };
```

(b) 右欄類別清單（每次開啟面板都重建，取代原 `_objfbRenderCatChips`；原函式刪除）：

```js
/* ── 右欄類別清單：Search All Categories + 本 zone 可用類別（totals 沿用實例快取）── */
function _objfbRenderCatPane(state) {
  const pane = state.els.ddCats;
  pane.innerHTML = '';
  const all = document.createElement('button');
  all.type = 'button';
  all.className = 'objfb-cat-item objfb-cat-item-hd' + (!state.scopeCat ? ' act' : '');
  all.setAttribute('data-i18n', 'gui_fb_cat_all');
  all.textContent = 'Search All Categories';
  all.setAttribute('data-on-click', '_objfbClearScope');
  all.dataset.args = JSON.stringify([state.id]);
  pane.appendChild(all);
  for (const c of _objfbZoneCats(state, state.zone ? state.zone.col : _objfbCols(state)[0])) {
    const meta = _OBJFB_CATS[c];
    if (!meta) continue;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'objfb-cat-item' + (state.scopeCat === c ? ' act' : '');
    const dot = document.createElement('i');
    dot.className = 'objfb-cat-dot ' + meta.dot;
    b.appendChild(dot);
    const label = document.createElement('span');
    if (meta.i18n) label.setAttribute('data-i18n', meta.i18n);
    label.textContent = meta.fallback;
    b.appendChild(label);
    const n = state._totals && state._totals[c];
    if (typeof n === 'number') {
      const cnt = document.createElement('span');
      cnt.className = 'objfb-chip-cnt';
      cnt.textContent = ` (${n})`;
      b.appendChild(cnt);
    }
    b.setAttribute('data-on-click', '_objfbSetScope');
    b.dataset.args = JSON.stringify([state.id, c]);
    pane.appendChild(b);
  }
  const browseAll = document.createElement('button');
  browseAll.type = 'button';
  browseAll.className = 'objfb-cat-item';
  browseAll.setAttribute('data-i18n', 'gui_fb_browse_all');
  browseAll.textContent = 'Browse all…';
  browseAll.setAttribute('data-on-click', '_objfbOpenBrowser');
  browseAll.dataset.args = JSON.stringify([state.id]);
  pane.appendChild(browseAll);
}
```

`_totals` 惰性 fetch 邏輯（原 `_objfbRenderCatChips` 尾段的 `/api/filter-objects/browse?type=_totals`）搬進 `_objfbUpdateDropdown`（開啟面板時觸發一次，回應到時若面板仍開著重呼叫 `_objfbRenderCatPane`）。

(c) `_objfbUpdateDropdown` 重構：每次呼叫先 `_objfbRenderCatPane(state)`、`dd.classList.add('open')`；主欄內容依輸入狀態分派（空輸入＋無 scope → `gui_fb_scope_hint` note；空輸入＋scope → browse/tx/type-to-search；非空 → `_objfbRenderDropdown`）。所有原本寫 `state.els.dd.innerHTML` 的渲染函式（`_objfbRenderDropdown`、`_objfbRenderBrowse`、`_objfbRenderBrowseList`、`_objfbRenderTxList`、`_objfbAddDdNote`/`_objfbAddDdGroup`/`_objfbAddDdGroupItems` 的 `dd` 參數來源）改寫入 `state.els.ddMain`；`dd.classList.add('open')`/`remove('open')` 維持掛在外層 `dd`。

(d) `_objfbRenderDropdown` svc 欄整合（IP/label 分支之後、suggest 併入之前）：

```js
  if (state.zone && state.zone.col === 'svc' && !state.scopeCat) {
    for (const grp of _objfbSvcCandidates(q)) {
      if (grp.grp === 'rangehint') {
        _objfbAddDdNote(main, 'gui_fb_svc_range_hint', 'Add "-" and an end port for a range');
        continue;
      }
      _objfbAddDdGroup(state, grp.items,
        grp.grp === 'portproto' ? 'gui_fb_grp_portproto' : 'gui_fb_grp_freetext',
        grp.grp === 'portproto' ? 'Port and/or Protocol' : 'Process / Windows Service');
    }
  }
```

（svc 欄的 `_objfbIsPortLike` 手動「Add Port」分支保留——它涵蓋 `443/tcp`、`80-90:6` 等產生器不出三選一的形式。）

(e) `_objfbAddDdGroupItems` 支援候選 tag（三選一的「預設/兩者」標籤）與顯示標籤：

```js
    const txt = document.createElement('span');
    txt.textContent = o.summary ? `${o.name} — ${o.summary}` : _objfbPillLabel(o);
    el.appendChild(txt);
    if (o.tagI18n) {
      const tag = document.createElement('span');
      tag.className = 'objfb-dd-tag' + (o.dflt ? ' objfb-dd-tag-both' : '');
      tag.setAttribute('data-i18n', o.tagI18n);
      el.appendChild(tag);
    }
```

（`_objfbPillLabel({cat:'port', name:'443'})` → `443 (TCP+UDP)`，候選與 pill 顯示天然一致。）

(f) CSS（objfb 區段內，Task 3 新區塊之後；刪除 `.objfb-dd-cats` 舊 chips 規則）：

```css
.objfb-dd-body { display: flex; align-items: stretch; }
.objfb-dd-main { flex: 1; min-width: 0; max-height: 320px; overflow-y: auto; }
.objfb-dd-catlist {
  flex: none;
  width: 180px;
  border-left: 1px solid var(--border);
  max-height: 320px;
  overflow-y: auto;
  padding: var(--space-1) 0;
}
.objfb-cat-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  text-align: left;
  border: 0;
  background: none;
  color: var(--fg);
  font: inherit;
  font-size: 12.5px;
  padding: var(--space-2) var(--space-3);
  cursor: pointer;
}
.objfb-cat-item:hover,
.objfb-cat-item.act { background: color-mix(in oklab, var(--accent) 12%, transparent); }
.objfb-cat-item-hd { font-weight: 700; color: var(--dim); font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }
.objfb-dd-foot {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-3);
  justify-content: space-between;
  border-top: 1px dashed var(--border);
  padding: var(--space-2) var(--space-3);
  color: var(--dim);
  font-size: 11px;
}
.objfb-dd-tag {
  flex: none;
  margin-left: auto;
  font-size: 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 5px;
  color: var(--dim);
}
.objfb-dd-tag-both { background: var(--accent); border-color: var(--accent); color: #fff; }
```

(g) i18n：`gui_fb_cat_all` → en `"Search All Categories"`、zh `"搜尋全部類別"`。

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_component_object_filter_bar.py tests/test_css_spacing_lint.py -v`
Expected: 全數 PASS。

- [ ] **Step 5: 手動冒煙**

Service 欄輸入 `443` → 三選一（兩者為預設高亮）+ 範圍提示 + Policy Services suggest；輸入 `1000-2000` → 範圍三選一；輸入 `htt` → Process/WinService 自由值 + Policy Services；Destination 欄右清單有 Transmission、Source 欄沒有；底部提示列常駐。

- [ ] **Step 6: Commit**

```bash
git add src/static/js/filter-bar.js src/static/css/app.css src/i18n_en.json src/i18n_zh_TW.json tests/test_component_object_filter_bar.py
git commit -m "feat(filter-bar): two-pane dropdown with service input guidance"
```

---

### Task 5: 五 modal 裸欄位收斂（HTML + JS）

移除五個 modal 的 PORT／通訊協定／排除 PORT 裸欄位與其序列化，port/proto 一律走 FilterBar Service 欄。舊設定讀取相容由 filter-bar.js:108-113（scalar→pill）承接，零遷移。

**Files:**
- Modify: `src/templates/index.html`（:1689-1704、:2417-2427、:2719-2727、:2733-2736、:2782-2783、:2789-2792、:2872-2887）
- Modify: `src/static/js/dashboard.js`（:669-676、:786-817、:829-860、:862-878、:1809-1832、:1851-1863、:428 註解）
- Modify: `src/static/js/rules.js`（:33、:40、:470-493、:540-557）
- Test: `tests/test_component_object_filter_bar.py`

**Interfaces:**
- Consumes: FilterBar v2 完整 UI（Task 3/4）。
- Produces: 五入口 payload 不再含 scalar `port`/`proto`/`ex_port`（頂層與 `filters` 內皆然）；rules 的 cats 擴充為 `['label', 'iplist', 'workload', 'ip', 'service', 'port', 'process', 'winservice', 'transmission']`。

- [ ] **Step 1: 翻轉守門測試（RED）**

修改既有四組 modal 測試——把「保留」斷言翻成「移除」：

```python
# test_instant_report_modal_mounts_filter_bar 尾段（:126-130）改為：
    # Plan B：pd checkbox 保留；proto/port/ex-port 裸欄位收斂進 FilterBar Service 欄
    assert 'id="rpt-pd-blocked"' in html
    for removed_id in ("rpt-proto", "rpt-port", "rpt-ex-port"):
        assert f'id="{removed_id}"' not in html, f"{removed_id} should be removed (Plan B)"

# test_scheduled_report_modal_mounts_filter_bar 尾段（:155-159）改為：
    assert 'id="sched-pd-blocked"' in html
    for removed_id in ("sched-proto", "sched-port", "sched-ex-port"):
        assert f'id="{removed_id}"' not in html, f"{removed_id} should be removed (Plan B)"

# test_dashboard_query_modal_mounts_filter_bar 尾段（:192-199）改為：
    assert 'id="dq-name"' in html
    assert 'id="dq-rank"' in html
    assert 'name="dq-pd"' in html
    assert 'id="dq-idx"' in html
    for removed_id in ("dq-port", "dq-proto", "dq-expt"):
        assert f'id="{removed_id}"' not in html, f"{removed_id} should be removed (Plan B)"

# test_traffic_rule_modal_mounts_filter_bar 尾段（:240-248）改為：
    assert 'id="tr-name"' in html
    assert 'name="tr-pd"' in html
    assert 'id="tr-cnt"' in html
    assert 'id="tr-win"' in html
    assert 'id="tr-cd"' in html
    for removed_id in ("tr-port", "tr-proto", "tr-expt"):
        assert f'id="{removed_id}"' not in html, f"{removed_id} should be removed (Plan B)"

# test_bw_rule_modal_mounts_filter_bar 尾段（:257-264）改為：
    assert 'id="bw-name"' in html
    assert 'name="bw-mt"' in html
    assert 'name="bw-pd"' in html
    assert 'id="bw-val"' in html
    assert 'id="bw-win"' in html
    assert 'id="bw-cd"' in html
    for removed_id in ("bw-port", "bw-expt"):
        assert f'id="{removed_id}"' not in html, f"{removed_id} should be removed (Plan B)"
```

新增 JS 端守門（照抄 fn-slice 慣例）：

```python
def test_report_and_sched_collect_no_scalar_port_keys():
    """Plan B spec §7：儲存時不再產生 scalar port/proto/ex_port。"""
    js = Path("src/static/js/dashboard.js").read_text(encoding="utf-8")
    for fn_name in ("_collectReportFilters", "_collectSchedFilters"):
        fn_src = js.split(f"function {fn_name}()", 1)[1].split("\nfunction ", 1)[0]
        for removed in ("port:", "proto:", "rpt-port", "rpt-proto", "rpt-ex-port",
                        "sched-port", "sched-proto", "sched-ex-port"):
            assert removed not in fn_src, f"{removed} still in {fn_name}"


def test_save_dashboard_query_no_scalar_port_keys():
    js = Path("src/static/js/dashboard.js").read_text(encoding="utf-8")
    fn_src = js.split("async function saveDashboardQuery()", 1)[1].split("\nasync function ", 1)[0]
    for removed in ("port:", "proto:", "dq-port", "dq-proto", "dq-expt"):
        assert removed not in fn_src, removed


def test_save_rules_no_scalar_port_keys():
    js = Path("src/static/js/rules.js").read_text(encoding="utf-8")
    for fn_name in ("saveTraffic", "saveBW"):
        fn_src = js.split(f"async function {fn_name}()", 1)[1].split("\nasync function ", 1)[0]
        for removed in ("port:", "proto:", "tr-port", "tr-proto", "tr-expt", "bw-port", "bw-expt"):
            assert removed not in fn_src, f"{removed} still in {fn_name}"


def test_dashboard_rules_js_no_scalar_field_ids_anywhere():
    """裸欄位 id 必須從 JS 徹底消失（含重置/回填路徑），比照 qt-port 前例。"""
    dj = Path("src/static/js/dashboard.js").read_text(encoding="utf-8")
    rj = Path("src/static/js/rules.js").read_text(encoding="utf-8")
    for fid in ("rpt-port", "rpt-proto", "rpt-ex-port", "sched-port", "sched-proto",
                "sched-ex-port", "dq-port", "dq-proto", "dq-expt"):
        assert fid not in dj, fid
    for fid in ("tr-port", "tr-proto", "tr-expt", "bw-port", "bw-expt"):
        assert fid not in rj, fid


def test_rules_filter_bars_include_service_family_cats():
    """rules 後端白名單（_RULE_FB_KEYS）已收 process/winservice/transmission；
    前端 cats 同步開放（label_group 仍排除）。"""
    js = Path("src/static/js/rules.js").read_text(encoding="utf-8")
    assert js.count("'service', 'port', 'process', 'winservice', 'transmission'") >= 2


def test_filter_bar_legacy_scalar_backfill_retained():
    """讀取相容不可移除：舊 rule/query/schedule 的 scalar port/proto/ex_port
    仍須回填成 port pill（filter-bar.js deserialize 分支）。"""
    js = _JS.read_text(encoding="utf-8")
    assert "if (d['port'])" in js
    assert "if (d['ex_port'])" in js
    assert "{ '6': 'tcp', '17': 'udp' }" in js
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_component_object_filter_bar.py -v`
Expected: 本 task 修改/新增的測試 FAIL，其餘 PASS。

- [ ] **Step 3: index.html 移除裸欄位**

1. m-sched：刪 :1689-1704（Protocol/Port/Exclude Port 三個 `<div>`；grid 與 `sched-filter-bar` 跨欄 div 保留）。
2. m-query：刪 :2417-2425 的 `.form-row`（dq-port/dq-proto）與 :2426-2427 的 Exclude Port `.form-group`（dq-expt）。
3. m-traffic：刪 :2719-2727 的 `.form-row`（tr-port/tr-proto）；刪 :2733-2736 起整個 `Excludes (Optional)` fieldset（tr-expt 是其唯一內容，含閉合 `</fieldset>`）。
4. m-bw：刪 :2782-2783 的 Port `.form-group`（bw-port）；刪 :2789-2792 起整個 `Excludes (Optional)` fieldset（bw-expt，含閉合 `</fieldset>`）。
5. m-gen-report：刪 :2872-2887（rpt-proto/rpt-port/rpt-ex-port 三個 `<div>`；`rpt-filter-bar` 跨欄 div 保留）。

（行號為現行 main 快照；實作時以 id 錨定定位，刪除後前後結構須保持合法 HTML——fieldset 不得殘留空殼。）

- [ ] **Step 4: dashboard.js 去 scalar**

(a) :673-675 重置迴圈整段刪除（`['rpt-proto','rpt-port','rpt-ex-port'].forEach…`；:670-672 的 pd 重置與 :676 的 `setFilters({})` 保留）。

(b) `_collectReportFilters`（:786-817）整函式替換：

```js
function _collectReportFilters() {
  const pdBlocked  = document.getElementById('rpt-pd-blocked');
  const pdPotential = document.getElementById('rpt-pd-potential');
  const pdAllowed  = document.getElementById('rpt-pd-allowed');

  let pds = [];
  if (pdBlocked  && pdBlocked.checked)   pds.push('blocked');
  if (pdPotential && pdPotential.checked) pds.push('potentially_blocked');
  if (pdAllowed  && pdAllowed.checked)   pds.push('allowed');
  if (!pds.length) pds = null; // null means all

  const objFilters = _ensureRptFilterBar().getFilters();
  const hasFilter = pds || Object.keys(objFilters).length > 0;
  if (!hasFilter) return null;

  const filters = { policy_decisions: pds };
  Object.assign(filters, objFilters);
  return filters;
}
```

(c) `_collectSchedFilters`（:829-860）同型替換（`sched-pd-*` id、`_ensureSchedFilterBar()`）。

(d) `_populateSchedFilters`（:862-878）替換：

```js
// 排程編輯回填：filters 可能是舊格式（scalar port/proto/ex_port、src_ip scalar）或
// 新格式（FilterBar getFilters() 輸出）；FilterBar setFilters（_objfbDeserialize）
// 兩種皆認（舊 scalar 回填成 port pill），此處不需分流。
function _populateSchedFilters(filters) {
  const setChk = (id, arr, val) => {
    const el = document.getElementById(id);
    if (el) el.checked = Array.isArray(arr) && arr.includes(val);
  };
  setChk('sched-pd-blocked',  filters && filters.policy_decisions, 'blocked');
  setChk('sched-pd-potential', filters && filters.policy_decisions, 'potentially_blocked');
  setChk('sched-pd-allowed',  filters && filters.policy_decisions, 'allowed');
  _ensureSchedFilterBar().setFilters(filters || {});
}
```

（:428 的註解 `// pd/proto/port/ex-port 與 FilterBar 皆由…` 改為 `// pd 與 FilterBar 皆由 _populateSchedFilters 統一重置與回填`。）

(e) `openQueryModal`（:1809-1832 重點段）：刪 :1816-1817（`$('dq-port').value = ''; $('dq-proto').value = '';` 與 `$('dq-expt').value = '';`）、刪 :1826-1828（scalar 回填三行；`setFilters(q)` 已把舊 scalar 回填成 pill）。

(f) `saveDashboardQuery`（:1854-1863）的 `d` 物件刪 `port:`/`proto:`/`ex_port:` 三行：

```js
  const d = {
    idx: idx >= 0 ? idx : null,
    name: $('dq-name').value,
    rank_by: $('dq-rank').value,
    pd: pdMatch ? parseInt(pdMatch.value) : 3,
    filters: _ensureDqFilterBar().getFilters(),
  };
```

- [ ] **Step 5: rules.js 去 scalar + cats 擴充**

(a) :33 與 :40 的 cats 改為：

```js
    _trFb = createFilterBar(document.getElementById('tr-filter-bar'), { cats: ['label', 'iplist', 'workload', 'ip', 'service', 'port', 'process', 'winservice', 'transmission'] });
```

```js
    _bwFb = createFilterBar(document.getElementById('bw-filter-bar'), { cats: ['label', 'iplist', 'workload', 'ip', 'service', 'port', 'process', 'winservice', 'transmission'] });
```

（:28-29 註解補一句：`// Plan B：service 家族三類（process/winservice/transmission）已入 _RULE_FB_KEYS，一併開放。`）

(b) 編輯回填：刪 :473-475（tr-port/tr-proto/tr-expt 三行）與 :486-487（bw-port/bw-expt 兩行）；`setFilters(r)` 保留（scalar→pill 回填）。

(c) `saveTraffic`（:542）data 物件刪 `port:`/`proto:`/`ex_port:`：

```js
  const data = { name, pd: rv('tr-pd'), threshold_count: $('tr-cnt').value, threshold_window: $('tr-win').value, cooldown_minutes: $('tr-cd').value, filters: _ensureTrFilterBar().getFilters() };
```

(d) `saveBW`（:548-554）刪 `port:`/`ex_port:`：

```js
  const data = {
    name, rule_type: rv('bw-mt'), pd: rv('bw-pd'),
    threshold_count: $('bw-val').value, threshold_window: $('bw-win').value, cooldown_minutes: $('bw-cd').value,
    filters: _ensureBwFilterBar().getFilters()
  };
```

- [ ] **Step 6: 跑測試確認通過**

Run: `pytest tests/test_component_object_filter_bar.py tests/test_component_filter_bar.py tests/test_component_abstraction_baseline.py -v`
Expected: 全數 PASS。

- [ ] **Step 7: 手動冒煙（本機）**

五個 modal 逐一開啟：裸欄位消失、FilterBar v2 呈現；建一條含 `443/tcp` port pill 的連線規則存檔→重開 modal→pill 回填正確；用 API 建一條帶舊 scalar `port: 443, proto: 6` 的規則→開編輯 modal→出現 `443/tcp` pill（讀取相容）。

- [ ] **Step 8: Commit**

```bash
git add src/templates/index.html src/static/js/dashboard.js src/static/js/rules.js tests/test_component_object_filter_bar.py
git commit -m "feat(gui): converge bare port/proto/ex_port fields into FilterBar service column (5 modals)"
```

---

### Task 6: Playwright e2e 更新 + 全套驗證 + CHANGELOG

**Files:**
- Modify: `tests/test_gui_e2e_filterbar_playwright.py`
- Modify: `CHANGELOG.md`（`## [Unreleased]` 下）

**Interfaces:**
- Consumes: Task 3 的 DOM 契約（`.objfb-col[data-zone="col:neg"]`、`.objfb-mode`、`.objfb-swap`、`.objfb-excl-toggle`、`.objfb-dd-catlist`）。
- Produces: 可對測試機執行的 e2e 套件（`ILLUMIO_OPS_E2E_BASE_URL` 閘門，CI 不跑）。

- [ ] **Step 1: e2e selector 遷移**

v2 後每個 FilterBar 有多個 `.objfb-input`（Playwright strict mode 會炸）。在 `FB = "#qt-filter-bar"` 之後加 helper，全檔既有測試的 `.objfb-input`/`.objfb-dd` 定位改走 zone scope：

```python
def _zone(col="src", neg="false"):
    return f"{FB} .objfb-col[data-zone='{col}:{neg}']"


def _zone_input(page, col="src", neg="false"):
    return page.locator(f"{_zone(col, neg)} .objfb-input")
```

既有測試遷移對照（逐一過檔修正；沒列到的斷言若仍綠可不動）：
- 點方向鈕（`.objfb-dir-btn`）選 src/dst/any → 改為直接點對應 zone 的輸入框（`_zone_input(page, 'dst').click()`）；「any 方向」情境改為先點 `.objfb-mode` 切 OR 再操作 `any:false` zone。
- port token 輸入（如既有 `test_manual_port_token_pill_and_popover` 的 `inp.fill("443/tcp")`）→ 改用 `_zone_input(page, 'svc')`；「Add Port」組頭 selector（`gui_fb_add_port`）不變。
- pill popover 斷言：port pill 無方向列的斷言不變；label pill 方向列從三鈕（src/dst/any）變兩鈕（src/dst），`dir_btns.count()` 相關斷言改 `== 2`。
- 下拉分類 chips（`.objfb-cat-btn`）→ 右欄 `.objfb-cat-item`。

- [ ] **Step 2: 新增 v2 情境測試**

```python
def test_v2_three_column_layout_and_excl_collapse(page):
    _open_traffic_filter_modal(page)
    for col in ("src", "dst", "svc"):
        assert page.locator(_zone(col)).count() == 1, f"include column {col} missing"
    # is-not 排除列預設收合（spec §3.1）
    assert not page.locator(_zone("src", "true")).is_visible()
    page.locator(f"{FB} .objfb-excl-toggle").click()
    page.wait_for_selector(_zone("src", "true"), state="visible", timeout=10000)


def test_v2_mode_toggle_migrates_pills(page):
    _open_traffic_filter_modal(page)
    inp = _zone_input(page, "src")
    inp.click()
    inp.fill("10.0.0.1")
    page.wait_for_selector(f"{FB} .objfb-dd-hdr[data-i18n='gui_fb_add_ipcidr']",
                           state="visible", timeout=10000)
    inp.press("Enter")
    page.wait_for_selector(f"{_zone('src')} .objfb-pill", state="visible", timeout=10000)
    page.locator(f"{FB} .objfb-mode").first.click()   # AND → OR
    page.wait_for_selector(f"{_zone('any')} .objfb-pill", state="visible", timeout=10000)
    assert "OR" in page.locator(f"{FB} .objfb-mode").first.inner_text()
    page.locator(f"{FB} .objfb-mode").first.click()   # OR → AND：回 Source 欄 + 提示
    page.wait_for_selector(f"{_zone('src')} .objfb-pill", state="visible", timeout=10000)
    assert page.locator(f"{FB} .objfb-hint[data-i18n='gui_fb_moved_any_src']").is_visible()


def test_v2_swap_moves_pill_between_columns(page):
    _open_traffic_filter_modal(page)
    inp = _zone_input(page, "src")
    inp.click()
    inp.fill("10.0.0.2")
    page.wait_for_selector(f"{FB} .objfb-dd-hdr[data-i18n='gui_fb_add_ipcidr']",
                           state="visible", timeout=10000)
    inp.press("Enter")
    page.wait_for_selector(f"{_zone('src')} .objfb-pill", state="visible", timeout=10000)
    page.locator(f"{FB} .objfb-swap").first.click()
    page.wait_for_selector(f"{_zone('dst')} .objfb-pill", state="visible", timeout=10000)
    assert page.locator(f"{_zone('src')} .objfb-pill").count() == 0


def test_v2_service_column_three_way_candidates(page):
    """spec §3.2：輸入 443 → 兩者（預設）/tcp/udp 三選一；Enter 取預設成 443 (TCP+UDP) pill。"""
    _open_traffic_filter_modal(page)
    inp = _zone_input(page, "svc")
    inp.click()
    inp.fill("443")
    page.wait_for_selector(f"{FB} .objfb-dd-tag-both", state="visible", timeout=10000)
    items = page.locator(f"{FB} .objfb-dd-main .objfb-dd-item")
    texts = " | ".join(items.all_inner_texts())
    assert "443/tcp" in texts and "443/udp" in texts
    inp.press("Enter")
    pill = page.locator(f"{_zone('svc')} .objfb-pill").first
    pill.wait_for(state="visible", timeout=10000)
    assert "443 (TCP+UDP)" in pill.inner_text()


def test_v2_transmission_category_only_in_destination(page):
    _open_traffic_filter_modal(page)
    _zone_input(page, "dst").click()
    page.wait_for_selector(f"{_zone('dst')} .objfb-dd.open", state="visible", timeout=10000)
    dst_cats = " | ".join(page.locator(f"{_zone('dst')} .objfb-cat-item").all_inner_texts())
    assert "Transmission" in dst_cats or "傳輸型態" in dst_cats
    _zone_input(page, "src").click()
    page.wait_for_selector(f"{_zone('src')} .objfb-dd.open", state="visible", timeout=10000)
    src_cats = " | ".join(page.locator(f"{_zone('src')} .objfb-cat-item").all_inner_texts())
    assert "Transmission" not in src_cats and "傳輸型態" not in src_cats
```

- [ ] **Step 3: 對本機服務跑 e2e**

```bash
ILLUMIO_OPS_E2E_BASE_URL=https://127.0.0.1:5001 \
ILLUMIO_OPS_E2E_USER=illumio ILLUMIO_OPS_E2E_PASSWORD=illumio \
pytest tests/test_gui_e2e_filterbar_playwright.py -v
```

Expected: 全數 PASS（PCE 無資料的 browse 情境允許 skip）。逐一修正遷移遺漏。

- [ ] **Step 4: 全套測試**

Run: `pytest --tb=short`
Expected: 全數 PASS（基準 3028+ 測試）。

- [ ] **Step 5: CHANGELOG**

`## [Unreleased]` 下新增：

```markdown
### Changed

- FilterBar v2: PCE-native three-column layout (Source / Destination / Service with
  is-not exclusion rows), AND/OR mode toggle with pill migration, source/destination
  swap, per-column category panels (Transmission is destination-only), and service
  input guidance (numeric input offers both/TCP/UDP with both as default; `-` extends
  to a range; text matches Process Name / Windows Service / Policy Services).
- The five GUI modals (instant report, scheduled report, saved query, traffic rule,
  bandwidth rule) no longer render bare Port / Protocol / Exclude Port fields; port
  and protocol filters are entered as FilterBar service pills. Saved configs with
  legacy scalar `port`/`proto`/`ex_port` are still read back as port pills and are
  normalized to `ports`/`ex_ports` tokens on next save.
- Known limitation (pre-existing): in OR mode the `any_*` filter keys remain
  single-valued on the backend, so multiple pills of the same category in the merged
  column still resolve to the last value.
```

- [ ] **Step 6: Commit**

```bash
git add tests/test_gui_e2e_filterbar_playwright.py CHANGELOG.md
git commit -m "test(e2e): filter-bar v2 scenarios; docs(changelog): plan b entries"
```

---

## 完成後整合與真機驗證（執行期，非計畫任務）

1. 依 `superpowers:finishing-a-development-branch` 合併 worktree 分支回 main、push。
2. 部署測試機並驗證服務存活：

```bash
ssh illumio-ops-test 'cd /root/illumio-ops && git pull --ff-only origin main && systemctl restart illumio-ops && sleep 5 && systemctl is-active illumio-ops'
```

3. 對測試機跑 Playwright e2e（真 PCE 資料）：

```bash
ILLUMIO_OPS_E2E_BASE_URL=https://<測試機>:5001 ILLUMIO_OPS_E2E_USER=<user> ILLUMIO_OPS_E2E_PASSWORD=<pass> \
pytest tests/test_gui_e2e_filterbar_playwright.py -v
```

4. 端到端人工抽查（比照 Plan A Task 6 的真 PCE 驗證精神）：在測試機 GUI 各建一次含 `range`／`process`／`winservice`／`transmission` pill 的查詢，確認回傳筆數合理、後端 log 無 4xx。

## Self-Review 紀錄

- Spec 覆蓋：§3.1 版面（Task 3）、§3.2 引導（Task 2+4）、§4.2 token 顯示（Task 1）、§4.3 新 key 前端層（Task 1）、§6 第 1 層（Task 1）＋第 7 層守門（Task 1-5 靜態測試）、§7 收斂（Task 5）、§9 Playwright（Task 6）。§5/§6 後端層與 §8 print PDF 已由 Plan A 交付，不在本案。§10 範圍外項目未觸碰。
- 型別/名稱一致性：`_objfbPillLabel`（Task 1 定義，Task 4 候選共用）、`_objfbSvcCandidates`/`_objfbTxCandidates`（Task 2 定義，Task 3(j)/Task 4(d) 消費）、zone 模型三函式與 window handler 名稱在 Task 3 Interfaces 與測試字面一致、`ddMain`/`ddCats`（Task 4 引入，Task 4 內自洽）。
- 已知風險已定案：object-browser.js 靠 `addDir`/`dirs` shim 不改檔；mixed any+src/dst 歷史資料 → AND 模式 + Source 欄 + 提示；label_group 擋 OR 切換不丟資料；`any_*` 單值限制記入 CHANGELOG。
