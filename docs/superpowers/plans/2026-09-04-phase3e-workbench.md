# Phase 3E — 工作台（v3.1 修訂）實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 3B 交付的五區 GUI 改成 v3.1 spec 的工作台：左側導覽殼層、清單／詳情／設定三種頁型、告警清單與告警頁（自動 explain＋行動列）、首頁最近的告警、系統設定頁型、文案去工程味；砍掉 3B 的收件匣語意、步進、上下文條、逐列「看規則」。

**Architecture:** 原地演進 `src/static/js/v2/`：新增一支 `components/page.mjs`（頁首、清單列、設定版面、儲存列四個骨架），`shell.mjs` 從頂欄改為左導覽並集中五區子項表，各 area 只保留內容；路由不動（新增 `#/investigate/alerts`，`inbox` 轉址）；後端不動。守門先紅後綠：文案 lint、頁型守門、coverage 重編。

**Tech Stack:** 原生 ES modules、零 build；Flask 靜態；pytest＋in-process Playwright（`tests/v2_e2e_utils.py`）；既有四道 CSS gate、i18n audit、`tools/gate_coverage_live.py`。

**Spec:** `docs/superpowers/specs/2026-09-04-ui-redesign-v3-1-workbench-design.md`（§1 殼層與路由、§2 首頁、§3 告警頁、§5 頁型與文案、§7 守門、§8 順序）；未取代的節見 `2026-09-03-ui-redesign-v3-design.md`。

## Global Constraints

- 原生 ES modules、零 build、無框架、無 npm；新檔放 `src/` 即自動進 offline bundle。
- 後端不動（本階段不新增端點）；CSRF／session 機制不動。
- 資料與文案來自原始碼與快照；mockup／測試資料禁手寫（`design/v2/snapshots/`、真機）。
- i18n：新鍵 `gui_` 前綴，**同時**寫入 `src/i18n_en.json`、`src/i18n_zh_TW.json`、`src/i18n/data/zh_explicit.json`（否則 `tests/test_i18n_zh_explicit_sync.py` 紅、precompute 回滾中文）；i18n 值不得含 `#/`；`scripts/audit_i18n_usage.py` 0 findings；JS 不得有行尾 CJK 註解。
- CSS 只用 `tokens.css` 的 token；四道 gate（`test_color_token_lint`、`test_css_color_tokens`、`test_css_space_type_tokens`、`test_css_spacing_lint`）綠。
- 對比：文字 4.5:1（dark `--accent-on` 已是深墨）；焦點可見；觸控 ≥36px；`prefers-reduced-motion` 尊重；任何寬度不裁字。
- 「全套」＝ CI 每道閘：`scripts/check_no_naive_datetime.py`、`scripts/check_doc_links.py`、`scripts/audit_i18n_usage.py`、`mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py`、`pytest`（本機排除 `tests/test_cache_cli.py::test_cache_flush_json_output`，click 版本差）。**每任務合入前跑全套 pytest**（3B Task 6 只跑 e2e 子集漏了 zh_explicit）。
- CI 沒有 cache DB：`cache_status`／`cache_throughput` 一律軟載入。
- 每任務＝乾淨 commit（英文 conventional commits）＋CI 綠＋部署測試機（`ssh illumio-ops-test 'cd /root/illumio-ops && git pull --ff-only origin main && systemctl restart illumio-ops'`，GUI https://127.0.0.1:5001）。
- 本機截圖 helper 放 `tmp/phase3e-verification/helpers/`，永不放 `tests/`。
- Commit 尾綴：`Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` ＋ `Claude-Session: https://claude.ai/code/session_01K8Qn3S2qBU2nsHhH6RNdHC`。

## 檔案地圖

| 檔案 | 責任 |
|---|---|
| `src/static/js/v2/components/page.mjs`（新） | `pageHead`、`listRow`、`settingsLayout`、`saveBar`、`sideCard`、`section` 六個骨架 |
| `src/static/js/v2/shell.mjs` | 左導覽（`NAV` 五區＋子項）、使用者列彈出選單、⌘K 入口、告警數圓標、健康燈移除 |
| `src/static/js/v2/app.mjs` | `#area-root` 版面、`#/investigate/alerts` 路由、`inbox` 轉址、`HEALTH_ROUTES` 移除 |
| `src/static/css/v2/app.css` | `.sidenav`、`.workarea`、`.phead`、`.crumbs`、響應規則；刪 `.chrome`／`.topbar`／`.areanav`／`.rail-host` |
| `src/static/css/v2/components.css` | `.lrow`（清單列）、`.chip`、`.settings`、`.savebar`、`.side-card`、`.sect`；刪 `.ctxstrip`／`.stepper`／`.hubseg`／`.rulepanel-host` |
| `src/static/js/v2/areas/alerts.mjs`（新） | `mountAlerts`（清單）、`mountAlert`（告警頁：敘事、自動 explain、行動列、右欄） |
| `src/static/js/v2/areas/investigate.mjs` | 刪 `mountInbox`／`paintStrip`／`explainRow`／stepper／`?alert=` 上下文條；保留 `?alert=`／`?f=` 預填；`areaTop` 改 `pageHead` |
| `src/static/js/v2/areas/home.mjs` | 最近的告警清單＋三張背景卡；刪 HM-03、posture 卡 |
| `src/static/js/v2/areas/cards.mjs` | 刪 `withGoto`／`GO_*`；`panel` 標題改句子；保留卡片供右欄 |
| `src/static/js/v2/areas/system.mjs` | `sysPage` 改 `settingsLayout`；`roField` 鍵名→人話標籤；秘密欄位晶片；`.codepane` 只留 logs |
| `src/static/js/v2/areas/policy_rules.mjs`、`policy_scheduler.mjs`、`reports.mjs` | `areaTop` → `pageHead`；清單頁型；guide 移除 |
| `src/static/js/v2/areas/login.mjs` | 無左導覽；頁首對齊 |
| `design/v3/coverage.yaml` | IN-* → AL-*；HM-03 刪；SH-01..03 新增 |
| `tests/test_gui_copy_lint.py`（新） | §7 文案 lint |
| `tests/test_v2_page_types_e2e.py`（新） | §7 頁型守門（標題句、≤1 primary、設定頁 savebar） |
| `tests/test_v2_alerts_e2e.py`（新，取代 `test_v2_investigate_hub_e2e.py`） | 清單、告警頁、自動 explain、行動 |
| `tests/test_v2_shell_e2e.py`、`test_v2_shell_flows_e2e.py`、`test_v2_home_e2e.py`、`test_v2_system_e2e.py`、`test_v2_coverage_live.py` | 依新殼層與 coverage 更新 |
| `docs/guide/gui-tour.md`、`CHANGELOG.md` | 新殼層與告警頁 |

---

### Task 1: 殼層 — 左側導覽、頁首骨架、使用者彈出選單

**Files:**
- Create: `src/static/js/v2/components/page.mjs`
- Modify: `src/static/js/v2/shell.mjs`（`AREAS`、`buildShell`、`userMenu`、`seedPalette`）、`src/static/js/v2/app.mjs:32-60`（`HEALTH_ROUTES`／`syncRail`）、`src/templates/index.html:18-21`、`src/static/css/v2/app.css:49-110`（chrome/topbar/areanav → sidenav）、`src/static/css/v2/components.css`（`.phead`、`.crumbs`）
- Test: `tests/test_v2_shell_e2e.py`、`tests/test_v2_shell_flows_e2e.py`、`tests/test_v2_page_types_e2e.py`（新，先只放殼層守門）

**Interfaces:**
- Produces（`components/page.mjs`）：
  ```js
  // pageHead({crumbs:[[text, href|null]...], title, sub, actions:[HTMLElement...]}) -> HTMLElement (.phead, data-cov passed through)
  export function pageHead(opts)
  // section(titleText, metaText|null, ...children) -> <section class="sect"> with <h3>
  export function section(title, meta, ...children)
  // sideCard(titleText, ...children) -> <div class="side-card"> with uppercase eyebrow h4
  export function sideCard(title, ...children)
  ```
- Produces（`shell.mjs`）：
  ```js
  export const NAV = [
    { id: "home", key: "gui_nav_home", route: "#/home", children: [] },
    { id: "investigate", key: "gui_nav_investigate", route: "#/investigate/alerts", children: [
      ["#/investigate/alerts", "gui_nav_alerts"], ["#/investigate/traffic", "gui_nav_traffic_search"],
      ["#/investigate/workloads", "gui_workload_search"], ["#/investigate/events", "gui_event_viewer"]] },
    { id: "policy", key: "gui_nav_policy", route: "#/policy/alert-rules", children: [
      ["#/policy/alert-rules", "gui_policy_tab_alert_rules"], ["#/policy/rulesets", "gui_policy_tab_rulesets"],
      ["#/policy/schedules", "gui_policy_tab_schedules"], ["#/policy/ops", "gui_policy_tab_ops"]] },
    { id: "reports", key: "gui_nav_reports", route: "#/reports", children: [
      ["#/reports", "gui_nav_reports"], ["#/reports/schedules", "gui_tab_report_schedules"]] },
    { id: "system", key: "gui_nav_system", route: "#/system/pce", children: [ /* system.mjs SUB_ROUTES 十項，鍵名照抄 */ ] },
  ];
  export function buildShell(mountPoint) -> { nav, menu, setAlertCount(n) }
  ```
  `AREAS`／`areaOf` 保留（palette、tests 用），由 `NAV` 推導。
- Consumes：`router.onChange`、`palette.open`、`theme`／`density`、`GET /api/alerts?status=new&page_size=1` 的 `counts.new`（圓標；失敗顯示無圓標，不吞錯到 console 以外）。

- [ ] **Step 1: 寫紅的殼層守門**（`tests/test_v2_page_types_e2e.py`）
```python
"""v3.1 §1/§5.1 shell and page-type gates."""
pytest_plugins = ["tests.v2_e2e_utils"]
ROUTES = ["#/home", "#/investigate/traffic", "#/investigate/workloads", "#/investigate/events",
          "#/policy/alert-rules", "#/policy/ops", "#/policy/rulesets", "#/policy/schedules",
          "#/reports", "#/reports/schedules"]
SETTINGS = ["#/system/pce", "#/system/cache", "#/system/siem", "#/system/tls", "#/system/security",
            "#/system/display", "#/system/channels", "#/system/alerting"]

def _open(page, base_url, route):
    page.goto(base_url + "/" + route)
    page.wait_for_selector('body[data-booted="true"]')
    page.wait_for_selector(".workarea .phead h2", timeout=20000)

def test_shell_is_a_left_nav_with_the_five_areas_and_no_top_bar(v2_page):
    page, base_url = v2_page
    _open(page, base_url, "#/home")
    assert page.locator(".sidenav").count() == 1
    assert page.locator(".topbar, .areanav, .rail-host").count() == 0
    assert page.locator('.sidenav > a[href^="#/"]').count() == 5
    assert page.locator('.sidenav a[aria-current="page"][href="#/home"]').count() == 1

def test_current_area_expands_its_children_only(v2_page):
    page, base_url = v2_page
    _open(page, base_url, "#/policy/rulesets")
    assert page.locator('.sidenav .sub a[href="#/policy/rulesets"][aria-current="page"]').count() == 1
    assert page.locator('.sidenav .sub a[href^="#/system/"]').count() == 0

def test_every_page_has_a_sentence_title_and_at_most_one_primary_action(v2_page):
    page, base_url = v2_page
    for route in ROUTES:
        _open(page, base_url, route)
        assert page.locator(".workarea .phead h2").count() == 1, route
        assert page.locator(".workarea .phead .btn.primary").count() <= 1, route

def test_nothing_clips_at_800(v2_page):
    page, base_url = v2_page
    page.set_viewport_size({"width": 800, "height": 700})
    _open(page, base_url, "#/reports")
    over = page.evaluate("Array.from(document.querySelectorAll('.sidenav a, .phead h2')).filter(e => e.scrollWidth > e.clientWidth + 1).length")
    assert over == 0
```
- [ ] **Step 2: 跑，確認紅在 `.sidenav` 不存在**
Run: `timeout 600 python3 -m pytest tests/test_v2_page_types_e2e.py -q -x --show-capture=no`
Expected: FAIL（`.sidenav` count 0）
- [ ] **Step 3: 實作 `components/page.mjs`、`shell.mjs` 左導覽、`app.mjs` 版面**
  - `index.html`：`<div id="shell"></div><main id="area-root" class="workarea"></main>` 包在 `<div class="frame">`（grid `224px 1fr`）。
  - `shell.mjs`：`buildShell` 產 `<nav class="sidenav" data-cov="SH-01">`：品牌列、五區 `<a>`（含 `.sub` 子項，只在 `areaOf(path)` 命中的區渲染）、`spacer`、`<button class="kbd-row" data-cov="SH-03">`（⌘K）、使用者列 `<button class="who" data-cov="SH-02">` 開既有 `userMenu()` 彈出（主題／密度／PCE／版本／時區／登出）。`router.onChange` 更新 `aria-current` 與子項。`setAlertCount(n)` 寫圓標。
  - `app.mjs`：刪 `HEALTH_ROUTES`／`syncRail`／`healthbar` import（healthbar.mjs 保留給首頁卡 Task 4）；boot 後 `api.load("alerts", {status:"new", page_size:1})` → `shell.setAlertCount`。
  - `app.css`：刪 `.chrome`／`.topbar`／`.areanav`／`.kbd-btn`／`.rail-host`；加 `.frame`、`.sidenav`（含 `.sub`、`.cnt`、`.who`、`.kbd-row`）、`.workarea { padding: var(--space-7) var(--space-8) }`；`@media (max-width: 1000px)`：`.frame` 單欄、`.sidenav` 橫列可捲、`.sub` 隱藏。
  - `components.css`：`.phead`（title 句用 `--font-body` 700 24px，`text-wrap: balance`）、`.crumbs`、`.phead .actions`。
  - i18n 新鍵：`gui_nav_alerts`（Alerts／告警）、`gui_nav_traffic_search`（Traffic search／流量搜尋）、`gui_shell_search_jump`（Search or jump to… ⌘K／搜尋或跳轉）、`gui_shell_user_menu`（Account and display／帳號與顯示）。三檔同步。
  - 每個 area 的 `areaTop`／`sysTop`／`systemAreaTop` 暫時改成回傳 `pageHead({crumbs, title: t(區名), sub: null, actions: []})`（Task 3–6 再改成句子）。sub-nav 不再由 area 畫。
- [ ] **Step 4: 更新既有殼層測試**
  - `tests/test_v2_shell_e2e.py`：頂欄斷言（`.topbar`、`.areanav a` 六→五、palette 入口 `.kbd-btn`）改為 `.sidenav`／`.kbd-row`；主題／密度分段仍在使用者彈出選單（先點 `.who`）。
  - `tests/test_v2_shell_flows_e2e.py`：路由表加 `#/investigate/alerts`；nav 點擊改 `.sidenav a`。
  - `tests/test_v2_home_e2e.py` 的健康列測試（HOME→PCE→SIEM 讀 rail）先標 `xfail(reason="rail moves into the home card in Task 4")`。
- [ ] **Step 5: 綠**
Run: `timeout 1500 python3 -m pytest tests/test_v2_page_types_e2e.py tests/test_v2_shell_e2e.py tests/test_v2_shell_flows_e2e.py tests/test_v2_core_e2e.py tests/test_v2_teardown_registration.py tests/test_color_token_lint.py tests/test_css_color_tokens.py tests/test_css_space_type_tokens.py tests/test_css_spacing_lint.py -q --show-capture=no`
Expected: PASS；`python3 scripts/audit_i18n_usage.py` → 0 findings
- [ ] **Step 6: 全套＋截圖＋commit**
Run: `timeout 3000 python3 -m pytest -q --show-capture=no --deselect tests/test_cache_cli.py::test_cache_flush_json_output`；本機 helper 截 `#/home`、`#/system/pce` 1280／800 亮／暗到 `tmp/phase3e-verification/task1/` 親看。
```bash
git add src/static/js/v2/components/page.mjs src/static/js/v2/shell.mjs src/static/js/v2/app.mjs src/templates/index.html src/static/css/v2/app.css src/static/css/v2/components.css src/static/js/v2/areas/*.mjs src/i18n_en.json src/i18n_zh_TW.json src/i18n/data/zh_explicit.json tests/test_v2_page_types_e2e.py tests/test_v2_shell_e2e.py tests/test_v2_shell_flows_e2e.py tests/test_v2_home_e2e.py
git commit -m "feat(gui): left-hand navigation shell and page head"
```
合入 main、部署測試機、`gh run watch`。

---

### Task 2: 頁型元件與文案守門（先紅）

**Files:**
- Modify: `src/static/js/v2/components/page.mjs`（加 `listRow`、`listFoot`、`settingsLayout`、`saveBar`、`chip`）、`src/static/css/v2/components.css`
- Create: `tests/test_gui_copy_lint.py`
- Modify: `src/static/js/v2/areas/cards.mjs:233-247`（`withGoto` 刪除、`GO_*` 刪除；呼叫端 6 處先改為無 goto）、`src/i18n_*.json`（刪 `gui_health_goto` 及值含 `#/` 的鍵）

**Interfaces:**
- Produces：
  ```js
  // listRow({href, tone:"crit"|"warn"|"info"|"ok"|"neutral", when:{main, sub}, title, sub, who:[[label, valueNode]...], status:chipNode, sample:false}) -> <a class="lrow">
  export function listRow(opts)
  export function listFoot(leftText, rightNode)                 // <div class="lfoot">
  export function chip(text, tone)                              // <span class="chip {tone}"><i></i>text</span>
  // settingsLayout({items:[{id, title, sub, status:chipNode, current:bool, onSelect}], form:HTMLElement}) -> <div class="settings">
  export function settingsLayout(opts)
  // saveBar({dirtyText, onRevert, onSave, primaryText}) -> <div class="savebar"> ; returns {el, setDirty(count)}
  export function saveBar(opts)
  ```
- 文案 lint 規則（`tests/test_gui_copy_lint.py`，掃 `src/static/js/v2/areas/*.mjs`、`components/*.mjs`、`shell.mjs`）：
  ```python
  FORBIDDEN = [
      (r"withGoto\(", "route-literal go-to links (spec §5.2)"),
      (r"\bGO_[A-Z_]+\s*=\s*\"#/", "route constants used as link text"),
      (r"roField\(\"[a-z_]+\.[a-z_.]+\"", "config keys printed on screen"),
      (r"text:\s*\"#/", "hash routes as visible text"),
  ]
  CODEPANE_ALLOWED = {"areas/system.mjs": 2, "areas/policy_scheduler.mjs": 1}   # logs page, debug console
  UPPERCASE_ALLOWED = {".eyebrow", "th", ".chip", ".side-card h4", ".lfoot"}      # components.css / app.css selectors
  ```
  加：i18n 兩檔任何值含 `#/` → fail；`.mono` 出現處的 e2e DOM 掃描放 Task 6。

- [ ] **Step 1: 寫 `tests/test_gui_copy_lint.py`**（含上表 4 條 regex、codepane 白名單計數、uppercase 選擇器白名單、i18n `#/`），跑
Run: `timeout 120 python3 -m pytest tests/test_gui_copy_lint.py -q`
Expected: FAIL（withGoto 37 處、roField 18 處、codepane 12 處、i18n `gui_health_goto`）
- [ ] **Step 2: 實作元件＋CSS**；`cards.mjs` 刪 `withGoto`／`GO_*`（卡片標題句與內容由各頁 Task 4–6 補連結）；i18n 刪 `gui_health_goto`、`gui_ov_goto*`（用 audit 找出未使用鍵一併刪）。
- [ ] **Step 3: 綠（lint 仍紅在 roField／codepane，這兩條在 Task 5 清；本任務用 `pytest.mark.xfail(strict=True)` 標記那兩條子測試，Task 5 移除標記）**
Run: `timeout 900 python3 -m pytest tests/test_gui_copy_lint.py tests/test_v2_page_types_e2e.py tests/test_v2_home_e2e.py tests/test_v2_system_e2e.py tests/test_color_token_lint.py tests/test_css_color_tokens.py tests/test_css_space_type_tokens.py tests/test_css_spacing_lint.py -q --show-capture=no`
- [ ] **Step 4: 全套＋commit** `feat(gui): page-type components and copy lint`

---

### Task 3: 告警清單與告警頁

**Files:**
- Create: `src/static/js/v2/areas/alerts.mjs`
- Modify: `src/static/js/v2/app.mjs`（註冊 `#/investigate/alerts`；`#/investigate/inbox` → `router.replace("#/investigate/alerts", ctx.query)`）、`src/static/js/v2/areas/investigate.mjs`（刪 `mountInbox`、`inboxRow`、`inboxColumns`、`dispatchList`、`alertDetail`、`paintStrip`、`stepper`、`explainRow`、`ruleHit`、`STEPS`、`R_INBOX`；`mountTraffic` 刪 strip／ruleHost／`handles.explain`／`handles.markDone`／act 欄「看規則」；保留 `hub.query` 預填與 `?f=`；`?alert=` 時頁首副標一句「由告警 #N 帶入條件」＋連結回告警頁）、`src/static/js/v2/core/store-map.mjs`（不變）、`design/v3/coverage.yaml`、`src/static/css/v2/components.css`（刪 `.ctxstrip`／`.stepper`／`.hubseg`／`.rulepanel-host`／`.rulehit*`／`.hubactions`；加 `.lede`、`.figs`、`.flows`、`.todo`）、i18n
- Create: `tests/test_v2_alerts_e2e.py`；Delete: `tests/test_v2_investigate_hub_e2e.py`

**Interfaces:**
- `alerts.mjs`：
  ```js
  export async function mountAlerts(root, ctx)   // #/investigate/alerts (list) or ?id= (alert page)
  // internal
  function headline(a, explainSummary)  -> string   // spec §3 template: "{scope} {what}" e.g. "onlineboutique 內 4,662 條連線在 10 分鐘內被擋"
  function narrative(a, flows, verdicts) -> string  // "發生了什麼" paragraph from template pieces (i18n keys gui_al_story_*)
  async function explainFlows(flows, N=8) -> Promise<verdict[]>  // parallel POST /api/policy/explain; verdict = {kind:"allow"|"none"|"unresolved"|"error", ruleset, rule_href, ruleset_href}
  function actions(a, flows, verdicts) -> [{title, sub, btn}]     // isolate(first flow with workload href) / schedule change(first allow hit or "create ruleset") / mark done
  ```
- coverage 重編：`IN-01..06` → `AL-01` 清單（route `#/investigate/alerts`）、`AL-02` 狀態切換（`?id=1`）、`AL-03` 告警頁、`AL-04` 規則判定欄、`AL-05` 行動列；`tools/gate_coverage_live.py` 的種子告警維持（payload 需含 `raw_data` 1 條 flow，加 `src_href`／`dst_href` 為 null 即可讓 AL-04 顯示「未解析」）。

- [ ] **Step 1: 寫 `tests/test_v2_alerts_e2e.py`**（沿用 hub 測試的 `_seed`，traffic 告警 payload `raw_data` 8 條真快照 flow）：
  - 清單：兩列、色條與晶片、點列到 `?id=`；狀態分段 PATCH 後 UI 回顯（回清單再進頁不讀舊快取）。
  - 告警頁：`.phead h2` 含「4,662」或 seed 的連線數；`[data-cov="AL-04"] .chip` 數＝raw_data 條數（explain 在 e2e 環境回錯 → 全部「PCE 沒回答」晶片，數量仍正確）；`[data-cov="AL-05"] button` ≥2；「標記已處理」→ API 狀態 done、頁首晶片變更。
  - 事件型告警：無流量表，「發生了什麼」列出 actor／action／resource。
  - `#/investigate/inbox?id=N` → 轉址到 `#/investigate/alerts?id=N`。
  - `#/investigate/traffic?alert=N`：仍自動查詢（沿用 hub 測試的 request 斷言），頁首副標含「告警」且無 `.ctxstrip`。
- [ ] **Step 2: 跑，紅在路由不存在**
- [ ] **Step 3: 實作**（列表用 `listRow`；告警頁用 `pageHead`＋`section`×3＋`details`＋`sideCard`×3；explain 並行 `Promise.allSettled`，逐列回填；行動列文案帶對象名 `tf("gui_al_act_isolate", {name})`）
- [ ] **Step 4: coverage 重編＋`tests/test_v2_coverage_live.py` 計數更新**（路由 24→24：`inbox`、`inbox?id=1` 換 `alerts`、`alerts?id=1`；`traffic?alert=1` 保留）
- [ ] **Step 5: 綠**
Run: `timeout 1800 python3 -m pytest tests/test_v2_alerts_e2e.py tests/test_v2_investigate_e2e.py tests/test_v2_coverage_live.py tests/test_v2_page_types_e2e.py tests/test_gui_copy_lint.py -q --show-capture=no`
- [ ] **Step 6: 全套＋截圖（清單／告警頁 1280／800 亮／暗）＋commit** `feat(gui): alerts list and alert page with automatic rule explain`；部署後用測試機真告警（rule 27）開 `#/investigate/alerts?id=1` 以 curl 確認 200＋`api/policy/explain` 對真 flow 回 200。

---

### Task 4: 首頁 — 最近的告警＋三張背景卡

**Files:**
- Modify: `src/static/js/v2/areas/home.mjs`（`cardNeedsYou` → 清單區塊 `listRow`×10＋未處理／全部切換＋「看全部」；`cardHealth` 改 `sideCard` 六燈＋每燈一句（沿用 `healthbar.computeLights`）；`cardToday` 改 `sideCard`；新 `cardPolicyWeek`（provision 次數、ruleset delta、posture 分數一行＋「看報表」）；刪 `cardDecisions`、posture 卡）、`src/static/js/v2/components/healthbar.mjs`（只保留 `computeLights`；rail 渲染刪除）、`design/v3/coverage.yaml`（HM-03 刪、OV-02 刪、HM-01 描述改）、`tests/test_v2_home_e2e.py`（rail 測試改讀首頁健康卡；HM-03 測試刪；新增：標題句含未處理數、切換全部後列數變化、列連到 `?id=`）
- i18n：`gui_home_title_fmt`（"{n} alerts still open, {m} things to look at" ／「{n} 件告警還沒處理，系統有 {m} 項要看一下」）、`gui_home_recent`、`gui_home_see_all`、`gui_home_policy_week`…

- [ ] **Step 1: 改測試先紅** → **Step 2: 實作** → **Step 3: 綠**
Run: `timeout 900 python3 -m pytest tests/test_v2_home_e2e.py tests/test_v2_coverage_live.py tests/test_v2_page_types_e2e.py tests/test_gui_copy_lint.py -q --show-capture=no`
- [ ] **Step 4: 全套＋截圖＋commit** `feat(gui): home leads with recent alerts`

---

### Task 5: 系統區 — 設定頁型、鍵名與 JSON 清除

**Files:**
- Modify: `src/static/js/v2/areas/system.mjs`（`sysPage` → `settingsLayout`＋`saveBar`；十頁各自：左清單項＝該頁的區段或目的地／通道，右表單分節；`roField(key, …)` 改 `roField(labelKey, …)` 人話標籤（既有 `gui_sy_*` 鍵有的直接用，缺的補）；秘密欄位改 `chip("已設定"/"尚未設定")`＋「設定／更換」按鈕（既有 `secret` 遮罩邏輯不動，只換呈現）；`kvRow` 的 mono 只留 IP／URL；`.codepane` 只留 logs 頁與 module log；channels 頁刪重複的狀態卡）、`src/static/css/v2/components.css`、`tests/test_v2_system_e2e.py`（sysPage 選擇器改；secret 遮罩測試改斷言晶片文字；新增每頁 `.savebar` 存在）、`tests/test_gui_copy_lint.py`（移除 Task 2 的 xfail）

- [ ] **Step 1: 移除 xfail，lint 紅在 roField／codepane** → **Step 2: 逐頁改（順序：channels、siem、pce、tls、security、display、cache、alerting、jobs、logs）** → **Step 3: 綠**
Run: `timeout 1800 python3 -m pytest tests/test_v2_system_e2e.py tests/test_gui_copy_lint.py tests/test_v2_page_types_e2e.py tests/test_v2_coverage_live.py -q --show-capture=no`
- [ ] **Step 4: 全套＋截圖（channels、siem、pce）＋commit** `feat(gui): system pages on the settings layout`

---

### Task 6: 政策、報表、流量搜尋 — 清單→詳情頁型、guide 移除、mono 守門

**Files:**
- Modify: `src/static/js/v2/areas/policy_rules.mjs`（規則清單 `listRow`；drawer 不動）、`policy_scheduler.mjs`（rulesets 清單／排程清單 `listRow`；`?rs=&rule=` 深連結不動；debug 主控台 codepane 保留）、`reports.mjs`（報表目錄與產出清單；右側摘要卡改 `sideCard`）、`investigate.mjs`（流量搜尋：`pageHead` 句子「查最近 1 小時的流量」＋副標；查詢表單保留；右欄 guide 刪，改 `?` 開 `m-help`；排行維持）、`cards.mjs`（標題句化）、i18n
- Test: `tests/test_v2_page_types_e2e.py` 加 `.mono` DOM 掃描（每條路由：`.mono` 節點文字須匹配 `^[\d.:/a-fA-F\-\[\]]+$|^/orgs/|^\d{4}-\d{2}-\d{2}`，白名單 `.codepane`）；`tests/test_v2_policy_rules_e2e.py`、`test_v2_policy_scheduler_e2e.py`、`test_v2_reports_e2e.py`、`test_v2_investigate_e2e.py` 選擇器更新

- [ ] **Step 1: 加 mono 守門先紅** → **Step 2: 逐區改** → **Step 3: 綠**
Run: `timeout 2400 python3 -m pytest tests/test_v2_policy_rules_e2e.py tests/test_v2_policy_scheduler_e2e.py tests/test_v2_reports_e2e.py tests/test_v2_investigate_e2e.py tests/test_v2_filterbar_e2e.py tests/test_v2_page_types_e2e.py tests/test_gui_copy_lint.py -q --show-capture=no`
- [ ] **Step 4: 全套＋截圖（rulesets、reports、traffic）＋commit** `feat(gui): policy, reports and traffic search on the list and detail page types`

---

### Task 7: 登入頁、coverage 收尾、文件、CHANGELOG

**Files:**
- Modify: `src/static/js/v2/areas/login.mjs`（頁首對齊 `pageHead` 樣式；無左導覽）、`design/v3/coverage.yaml`（最終盤點：SH-01..03、AL-01..05、HM 重編；每項可達）、`tests/test_v2_coverage_live.py`、`docs/guide/gui-tour.md`（殼層、五區子項、告警頁一節；移除 3B 過渡註記）、`docs/reference/rest-api.md`（標題路由更新 `alerts`）、`CHANGELOG.md`（Unreleased「Changed」補：左導覽、告警頁、設定頁型、文案）、`tmp/phase3e-verification/report.md`

- [ ] **Step 1: 實作＋文件** → **Step 2: 驗證**
Run: 全套閘門；`python3 tools/gate_coverage_live.py -v` 100%；本機 helper 截全部路由 1280／800 亮／暗到 `tmp/phase3e-verification/final/` 親看；測試機部署後 curl smoke＋真告警頁 200。
- [ ] **Step 3: commit** `feat(gui): login alignment, v3.1 coverage map, docs`；報告寫 `tmp/phase3e-verification/report.md`（每任務 commit／CI／測試機、兩次以上 CI 紅的根因、與計畫偏離）。

---

## 自審紀錄（撰寫時）

- Spec 覆蓋：§1 殼層＝Task 1；§1.1 路由（alerts、inbox 轉址）＝Task 3；§2 首頁＝Task 4；§3 告警頁＝Task 3；§5.1 頁型＝Task 2＋4–6；§5.2 文案＝Task 2（lint）＋5／6（清除）；§5.3 設定＝Task 5；§5.4 響應＝Task 1（守門 `test_nothing_clips_at_800`）；§7 守門＝Task 1／2／6；§8 順序一致。
- Placeholder 掃描：無 TBD；Task 4／5／6 的「先紅→實作→綠」步驟未展開測試碼，因為斷言對象是既有測試檔的選擇器更新，實作者以 Task 1／3 的測試碼為樣板；`NAV.system.children` 明列「照抄 `system.mjs` SUB_ROUTES 十項」。
- 型別一致：`pageHead`／`listRow`／`chip`／`sideCard`／`section`／`settingsLayout`／`saveBar` 名稱在 Task 1–6 一致；`AL-01..05`、`SH-01..03` 在 Task 3／7 與 spec §7 一致。
- 風險：`system.mjs` 2,729 行改頁型是最大單一任務，若一次改十頁超過一個 commit 的可審量，拆成 5a（channels／siem／pce）與 5b（其餘七頁）兩個 commit，同一任務。
