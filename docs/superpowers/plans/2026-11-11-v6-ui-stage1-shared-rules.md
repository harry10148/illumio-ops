# v6 介面第 1 段：全站呈現規則與共用元件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把規格 §5 的呈現規則做成共用元件與樣式、套到每一頁，並修掉 VEN 總覽動作列與表頭重疊的缺陷；版本 6.7.0。

**Architecture:** 規則先寫成一支可在瀏覽器裡執行的檢查器（`tests/e2e/ui_rules.py`），對每一頁的渲染結果量測（computed style 與外框），不看 class 名稱。
全站巡檢測試帶一份「尚未修好的規則」清單，後面每個 task 修一類、從清單拿掉一項，最後清單必須是空的。元件加在 `web/src/components/ui.tsx`，
樣式改在 `web/src/styles/base.css` 與 `tokens.css`（全站只有這兩個樣式檔）；各頁改用元件，不各自寫樣式。

**Tech Stack:** React 19＋TypeScript＋Vite（`web/`，沒有前端單元測試框架，行為以 pytest＋Playwright 的 e2e 驗證）；Python 3 pytest；i18n 在 `illumio_ops/i18n/{en,zh_TW}.json`。

**Spec:** `docs/superpowers/specs/2026-11-11-v6-purpose-led-ui-design.md`（本計畫只做 §5 與 §11 的第 1 段；§4、§6–§10 是後面三段，另出計畫）。
前規格 `docs/superpowers/specs/2026-11-03-v6-ui-redesign-design.md` 未被 §12 取代的條目仍有效。

## Global Constraints

- 只改呈現：不改任何 API、資料、計算、路由、導覽分組（導覽是第 2 段）。頁面內容與功能不增不減。
- 不換配色、字體家族、卡片與側邊導覽外觀；只有明亮模式。
- 既有 e2e 測試用的 `data-role`、`data-tab`、`data-*` 屬性與 `name` 屬性一律保留。class 名稱改了就同步改用到它的測試，不留假綠：
  改選擇器前先確認舊選擇器在改之前真的選得到元素。
- 文字規則（前規格 §6）：新增的每一句都是固定文字或「模板＋算出的值」；不寫推論、不寫程式算不出來的句子。
- 新 i18n 鍵 en 與 zh_TW 都要有；中文用「VEN 總覽」，不得出現「VEN 車隊」。不留沒人用的鍵（死鍵檢查）。
- 不默默截斷：表格內容放不下時換行，不用省略號。
- 對比達 WCAG AA（4.5:1）；顏色不單獨表達意思。
- 工作目錄 `/home/harry/rd/illumio-ops/.worktrees/v6-ui`，每個指令開頭 `cd` 到這裡。`git add` 只加明確路徑；commit 用英文 conventional commits；
  commit 不接在閘門後用 `;` 或管線串；不 push（由主持人在全部閘門綠後處理）。
- 每個 task 結束前跑：`npm --prefix web run --silent typecheck`、`npm --prefix web run --silent build`、該 task 列的測試。
  e2e 測試讀的是建置後的靜態檔：**改了前端一定要先 build 再跑 e2e**。
- 全套閘門：`bash .superpowers/sdd/2026-11-03-v6-ui-b-rule-scheduling/gates.sh`（主持人在 task 之間跑）。

## Review Focus

1. **很長的主機名稱、Label、規則名稱**進到固定欄寬的表格：應換行顯示完整內容，不撐破版面、不被裁掉、不出現水平捲動。→ Task 4 的測試。
2. **只用鍵盤操作**新的核取方塊、開關、分段選擇：Tab 能到、Space 能切換、有看得見的 focus 外框，讀屏軟體讀得到狀態（`role`、`aria-checked`、`aria-pressed`）。→ Task 3 的測試。
3. **開關切換時儲存失敗**（伺服器回錯或斷線）：開關應回到原狀並顯示錯誤，不能停在使用者以為成功的位置。→ Task 3 的測試。
4. **英文介面**字串比中文長：按鈕與分段選擇不折行、不溢出卡片；狀態標籤不折成兩行。→ 巡檢測試兩種語言都跑（Task 1 建立、各 task 維持）。
5. **基本模式與空資料**：頁面大半是「需要進階模式」與空狀態時，規則一樣成立（不相貼、不重疊、每區一顆主要按鈕）。→ 巡檢測試含基本模式與未灌資料的走訪（Task 1）。

---

### Task 1: 規則檢查器、全站巡檢與實機稽核腳本

先有量尺，而且先證明量尺抓得到現況的問題，後面的 task 才有東西可以對。

**Files:**
- Create: `tests/e2e/ui_rules.py`
- Create: `tests/e2e/test_ui_rules_checker.py`（檢查器自己的測試：每條規則對一段小 HTML）
- Create: `tests/e2e/test_ui_rules_e2e.py`（全站巡檢）
- Create: `tools/ui_audit.py`（對實機跑同一支檢查器）

**Interfaces:**
- Produces: `ui_rules.RULES: tuple[str, ...]`＝`("one_primary", "styled_checkbox", "tag_not_button", "cards_apart", "no_overlap", "header_one_line", "no_overflow_x", "button_font", "link_not_accent")`。
- Produces: `ui_rules.violations(page) -> dict[str, list[str]]`：對目前頁面執行一段 JS，回每條規則的違規清單（每筆是「元素描述：量到的值」的短字串，最多 10 筆）；沒有違規的規則不在 dict 裡。
- Produces: `test_ui_rules_e2e.PENDING: dict[str, str]`：尚未修好的規則 → 由哪個 task 修。巡檢對 `PENDING` 裡的規則要求**仍有違規**（修好了卻沒從清單拿掉會失敗），對其餘規則要求零違規。

規則的量測定義（在已渲染的 `main` 區域內，只看可見元素）：

| 規則 | 違規的定義 |
|---|---|
| `one_primary` | 同一個「區域」內，背景色等於 `--accent-fg`（`rgb(194, 67, 0)`）的按鈕或連結超過一顆。區域＝最近的祖先 `.page-head`、`.card`、`.panel`、`[role=dialog]`、`aside`；都沒有就是整頁 |
| `styled_checkbox` | 可見的 `input[type=checkbox]` 其 computed `appearance` 不是 `none` |
| `tag_not_button` | `.tag` 或 `.badge` 元素的任一邊 `border-width` 大於 0，或文字折成多行（高度大於 `line-height` 的 1.5 倍） |
| `cards_apart` | 兩個相鄰的兄弟 `.card`／`.panel` 上下排列時，垂直間距小於 16px（`--space-6`） |
| `no_overlap` | 兩個可見的互動元素（`button`、`a`、`input`、`select`、`textarea`、`th`）外框相交超過 2px，且彼此不是祖孫 |
| `header_one_line` | `th` 的高度大於它 `line-height` 的 1.5 倍加上下 padding |
| `no_overflow_x` | `document.documentElement.scrollWidth` 大於 `clientWidth` 1px 以上 |
| `button_font` | `button` 或 `a[class^=btn]` 的 `font-size` 不是 14px（分段選擇的 12px 例外，以 `[data-seg]` 祖先辨識） |
| `link_not_accent` | `main` 內不是按鈕外觀的 `a`，其 `color` 等於 `--accent-text`（`rgb(186, 64, 0)`） |

- [ ] **Step 1: 寫檢查器的失敗測試** `tests/e2e/test_ui_rules_checker.py`

每條規則兩個案例，用 `page.set_content(...)` 放一段最小 HTML（inline style，不依賴產品樣式）：一段有該違規、一段沒有。

```python
@pytest.mark.parametrize("rule", ui_rules.RULES)
def test_each_rule_catches_its_defect_and_passes_the_clean_case(rule, context):
    page = context.new_page()
    page.set_content(BAD[rule]);  assert rule in ui_rules.violations(page)
    page.set_content(GOOD[rule]); assert rule not in ui_rules.violations(page)
```

`BAD`／`GOOD` 是這個檔案裡的 dict，鍵必須涵蓋 `ui_rules.RULES` 的每一項（另寫一個測試斷言鍵集合相等）。`BAD["no_overlap"]` 用 .106 量到的實況：
一個 `button` 底邊在 467px、一個 `th` 頂邊在 455px。

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && timeout 300 .venv/bin/python -m pytest tests/e2e/test_ui_rules_checker.py -x -q -p no:logging`
Expected: FAIL（`ui_rules` 不存在）

- [ ] **Step 3: 實作 `tests/e2e/ui_rules.py`**

一個 JS 字串常數加 `violations(page)`。顏色用 computed 值比對上表的 rgb；「可見」＝外框寬高大於 0 且 `visibility` 不是 `hidden`。

- [ ] **Step 4: 跑測試確認通過**（同 Step 2 的指令）Expected: PASS

- [ ] **Step 5: 寫全站巡檢** `tests/e2e/test_ui_rules_e2e.py`

```python
PATHS = ("/", "/detect", "/investigate", "/hosts", "/fleet", "/rule-schedules", "/rule-schedules/rulesets", "/reports",
         "/reports?tab=schedules", "/reports?tab=produced", "/siem", "/siem/dlq", "/alert-rules", "/alert-rules?tab=channels",
         "/alerts/rules/new", "/system/collection", "/system/pce", "/system/lateral", "/system/jobs", "/system/tls",
         "/system/security", "/system/logs", "/system/display")
PENDING = {"one_primary": "Task 2", "tag_not_button": "Task 2", "button_font": "Task 2", "link_not_accent": "Task 2",
           "styled_checkbox": "Task 3", "cards_apart": "Task 4", "no_overlap": "Task 4", "header_one_line": "Task 4"}
```

- `walk(page, base_url) -> dict[str, list[str]]`：逐一開 `PATHS`，等 `.page` 出現，合併 `ui_rules.violations`（每筆前面加路徑）。
- 四個測試，都用現有的 `live_app`、`sign_in`：
  - `test_rules_hold_with_data`：先灌資料再走訪。資料用現有 e2e 的灌資料函式（`tests/e2e/test_alerts_e2e.py` 的 `seed`、`test_hosts_e2e.py`、
    `test_lateral_e2e.py` 的 `_seed`，`test_fleet_e2e.py`、`test_quarantine_e2e.py` 的 `_setup`），匯入重用，不另寫；灌完另外開一則告警的詳情頁（`/alerts/<id>`）與一台主機的頁面（`/hosts?key=…`）加入走訪。
  - `test_rules_hold_without_data`：不灌資料（空狀態）。
  - `test_rules_hold_in_basic_mode`：把收集模式設成 lightweight（`tests/e2e/test_basic_mode_e2e.py` 的 `_basic`）。
  - `test_rules_hold_in_english_and_at_760`：語言設 en、視窗 760 寬（`NARROW`）。
- 每個測試的斷言：不在 `PENDING` 的規則零違規；`test_rules_hold_with_data` 另外斷言 `PENDING` 的每條規則**至少有一筆違規**
  （訊息寫「這條已經修好了，從 PENDING 拿掉」）。
- 若某條 `PENDING` 規則在灌了資料的走訪中其實零違規（測試環境重現不了，例如 `no_overlap` 要 1440 寬），把重現它需要的視窗寬度或資料補進
  這個測試，直到抓得到為止。抓不到就不能列在 `PENDING`，也不能宣稱它被這支測試保護。

- [ ] **Step 6: build 後跑巡檢，確認現況被抓到**

Run: `cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && npm --prefix web run --silent build > /dev/null && timeout 900 .venv/bin/python -m pytest tests/e2e/test_ui_rules_e2e.py -x -q -p no:logging`
Expected: PASS（`PENDING` 的八條都抓到違規，`no_overflow_x` 零違規）。把每條規則抓到的筆數記在回報裡。

- [ ] **Step 7: 實機稽核腳本** `tools/ui_audit.py`

`python tools/ui_audit.py <base-url> [--width 1440] [--out DIR]`：密碼讀環境變數 `V6_SMOKE_PASSWORD`（同 `tests/e2e/test_smoke_remote.py`，不印出），
登入後走訪同一份 `PATHS`（從測試模組匯入），印每頁每條規則的違規筆數，`--out` 有給就存每頁整頁截圖
（先量最大 `scrollHeight` 再把視窗撐高截圖；判斷重疊與相貼用一般 900px 高的視窗量，不用撐高後的）。只讀，不點任何會寫入的按鈕。
結束碼：有違規為 1。

- [ ] **Step 8: Commit**

```bash
git add tests/e2e/ui_rules.py tests/e2e/test_ui_rules_checker.py tests/e2e/test_ui_rules_e2e.py tools/ui_audit.py
git commit -m "test(v6-ui): a checker for the shared presentation rules, with the pages that break them listed"
```

---

### Task 2: 顏色、按鈕三級、狀態標籤、字體

**Files:**
- Modify: `web/src/styles/tokens.css`、`web/src/styles/base.css`
- Modify: `web/src/components/ui.tsx`
- Modify: `web/src/pages/**/*.tsx`、`web/src/shell/*.tsx` 中用到 `btn-*`、`badge`、`mono` 的地方（`className="btn-quiet"` 108 處／27 檔、`btn-primary` 36 處／26 檔、`badge` 29 處／13 檔、`mono` 14 處／9 檔）
- Modify: `tests/e2e/test_ui_rules_e2e.py`（`PENDING` 拿掉四項）；用到 `.badge` 選擇器的既有測試
- Test: `tests/e2e/test_ui_rules_e2e.py`、`tests/e2e/test_ui_controls_e2e.py`（新）

**Interfaces:**
- Produces（`ui.tsx`）:
  - `Button(props: ButtonHTMLAttributes<HTMLButtonElement> & { kind?: "primary" | "secondary" | "text" | "danger" })`，預設 `secondary`；
    渲染的 class 依序是 `btn-primary`／`btn-quiet`／`btn-text`／`btn-danger`（前兩個與 `btn-danger` 沿用既有名稱，讓既有測試的選擇器不變）。
  - `LinkButton(props: LinkProps & { kind?: 同上 })`：外觀是按鈕的 `<Link>`。
  - `Tag` 是唯一的狀態標籤元件；`.badge` 樣式與用法全部併入 `Tag`（`<span className="badge" data-tone=…>` 改成 `<Tag tone=…>`）。
  - `DisabledWhy({ children })`：按鈕下方的一行原因文字（`<p className="hint" data-role="disabled-why">`）。
- Consumes: Task 1 的 `PENDING`。

規則（規格 §5.1–§5.3）：
- 連結：`main` 內的一般連結用 `--text-1`、底線色 `--line-strong`、`text-underline-offset: 3px`，停留時底線變 `--text-1`。`--accent-text` 不再用於連結。
- 按鈕字級一律 `--fs-ui`（14px）。`btn-text` 無框無底、文字色加底線。
- 每個區域最多一顆主要按鈕。逐頁處理：一個區域有兩顆以上 `btn-primary` 的，留下「這個區域最該按的一個」，其餘降為次要。
  判斷不了哪個最該按時，留「完成這個區域目的」的那顆（儲存、產生、套用），其餘降級；把每一處的取捨列在回報裡。
- 同一列次要按鈕超過三顆的，第四顆起改成文字按鈕（不做「更多」選單，YAGNI；回報列出這些位置）。
- 停用按鈕把原因寫在按鈕文字裡的（例：告警側欄「隔離 · Idle 或 Visibility Only，不會生效」），改成短標籤加 `DisabledWhy`。
  新增或拆開的字串放 i18n 兩種語言。
- 狀態標籤：有底色、無外框、高 20px、`white-space: nowrap`。告警清單與詳情的「只記錄（規則設定）」改成純文字（`className="hint"`，不是標籤）。
- 等寬字只留給 IP、port、href、事件類型字串、憑證與指令。時間戳、統計數字（KPI、表格數字欄）、主機名稱改一般字體並加
  `font-variant-numeric: tabular-nums`：`.kpi-value` 與 `td[data-kind="num"]` 用 `--font-ui`；逐一檢視 `className="mono"` 的 14 處與
  `data-kind="mono"` 的欄位，只保留上面列的幾種。

- [ ] **Step 1: 寫失敗測試** `tests/e2e/test_ui_controls_e2e.py`

```python
def test_a_disabled_action_says_why_below_the_button(live_app, context):
    # 灌一則偵測類告警，對象是 Idle 模式的受管主機（做法見 test_alerts_e2e.py 的 seed 與 test_quarantine_e2e.py）
    ...
    button = page.locator("[data-role=quarantine]")  # AlertsHome.tsx 側欄現有的屬性
    assert "Idle" not in button.inner_text() and len(button.inner_text()) <= 12
    assert page.locator("[data-role=disabled-why]").is_visible()

def test_times_and_counts_are_not_monospace(live_app, context):
    # 告警清單的時間欄與 KPI 數字：computed font-family 不含 "JetBrains Mono"
    ...

def test_an_ip_address_is_monospace(live_app, context):
    # 灌一則來源是 ip: 鍵的告警；該位址的 computed font-family 含 "JetBrains Mono"
    ...
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && npm --prefix web run --silent build > /dev/null && timeout 600 .venv/bin/python -m pytest tests/e2e/test_ui_controls_e2e.py -x -q -p no:logging`
Expected: FAIL

- [ ] **Step 3: 實作**：`tokens.css`／`base.css` 的樣式、`ui.tsx` 的 `Button`、`LinkButton`、`DisabledWhy`、`Tag` 合併 `.badge`；各頁改用。
- [ ] **Step 4: 從 `PENDING` 拿掉 `one_primary`、`tag_not_button`、`button_font`、`link_not_accent`**
- [ ] **Step 5: build 後跑本 task 測試與巡檢**

Run: `cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && npm --prefix web run --silent typecheck && npm --prefix web run --silent build > /dev/null && timeout 900 .venv/bin/python -m pytest tests/e2e/test_ui_controls_e2e.py tests/e2e/test_ui_rules_e2e.py tests/e2e/test_alerts_e2e.py tests/i18n -q -p no:logging`
Expected: PASS

- [ ] **Step 6: Commit**（`git add` 列出實際改到的檔案）

```bash
git commit -m "feat(v6-ui): three button levels, one tag shape, links in ink, monospace only for values to copy"
```

---

### Task 3: 核取方塊、開關、分段選擇

**Files:**
- Modify: `web/src/components/ui.tsx`、`web/src/styles/base.css`
- Modify: 用到 `type="checkbox"`（43 處／18 檔）與 `chip-btn`（13 處／6 檔）的頁面
- Modify: `tests/e2e/test_ui_rules_e2e.py`（`PENDING` 拿掉 `styled_checkbox`）
- Test: `tests/e2e/test_ui_controls_e2e.py`

**Interfaces:**
- Produces（`ui.tsx`）:
  - `Checkbox(props: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { label?: ReactNode })`：仍是真正的 `<input type="checkbox">`
    （`appearance: none` 自繪，16px，與文字基線對齊，`:focus-visible` 有外框），所以既有測試的 `.check()`、`name` 選擇器照用。
  - `Switch({ checked, onChange, label, name, disabled }: { checked: boolean; onChange: (next: boolean) => Promise<boolean>; label: string; name?: string; disabled?: boolean })`：
    `<button role="switch" aria-checked>`。按下後立刻顯示新狀態並呼叫 `onChange`；回 `true` 時在元素上設 `data-state="saved"` 1.5 秒；
    回 `false` 或丟例外時回到原狀並設 `data-state="failed"`，錯誤文字由呼叫端顯示。等待期間 `disabled`。
  - `Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string; count?: number }[]; onChange: (v: T) => void; label: string })`：
    `<div role="group" aria-label data-seg>` 內每個選項一顆 `<button aria-pressed>`；每顆帶 `data-value`。

套用規則（規格 §5.3）：
- 「一按就生效」的核取方塊改 `Switch`：告警規則表的啟用與送通知（`Rules.tsx` 的 `toggle`）、報表排程清單的啟用（`Schedules.tsx`）、
  SIEM 的「開啟 SIEM 轉送」與每個目的地的「送到這個目的地」（**只有**現況是按了立即存的才改；現況要按「儲存」才生效的維持 `Checkbox`。
  逐一讀程式確認，回報列出每一處的判定）。
- 互斥篩選改 `Segmented`：各頁的 `chip-btn` 分頁與篩選（告警頁類型、調查頁「流量／事件」「明細／排名」、報表與告警規則頁的分頁）、
  告警頁的「只看未處理」核取方塊（改成兩個選項的 `Segmented`，文字沿用現有鍵的意思：全部／只看未處理；語意在第 2 段才改）。
  既有測試用的 `data-tab` 等屬性要保留在按鈕上：`options` 的項目可帶額外的 `data-*`（實作成 `attrs?: Record<string, string>`）。
- 其餘核取方塊改 `Checkbox`。偵測頁樞紐主機清單的核取方塊現在高 34px、與文字不對齊，改完應對齊。

- [ ] **Step 1: 寫失敗測試**（加在 `tests/e2e/test_ui_controls_e2e.py`）

```python
def test_a_switch_that_fails_to_save_goes_back_and_says_so(live_app, context):
    # 開告警規則頁；用 page.route 讓 PUT /api/alert-rules/* 回 500；按第一條規則的啟用開關
    sw = page.locator("[role=switch]").first
    before = sw.get_attribute("aria-checked")
    sw.click()
    expect(sw).to_have_attribute("data-state", "failed")
    assert sw.get_attribute("aria-checked") == before
    assert page.locator(".form-error").is_visible()

def test_a_switch_that_saves_shows_it(live_app, context):
    # 不攔截；按下後 aria-checked 反轉、data-state="saved"；重新整理後仍是新值

def test_controls_work_from_the_keyboard(live_app, context):
    # 告警頁：Tab 走到分段選擇的第二個選項，按 Space，aria-pressed 變 true；
    # 焦點所在元素的 computed outline-style 不是 none

def test_checkboxes_line_up_with_their_text(live_app, context):
    # 偵測頁（灌樞紐資料）：每個核取方塊的垂直中心與同列文字第一行的垂直中心相差不超過 3px
```

- [ ] **Step 2: 跑測試確認失敗**（指令同 Task 2 Step 2）
- [ ] **Step 3: 實作三個元件與樣式，各頁改用**
- [ ] **Step 4: 從 `PENDING` 拿掉 `styled_checkbox`**
- [ ] **Step 5: build 後跑測試**

Run: `cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && npm --prefix web run --silent typecheck && npm --prefix web run --silent build > /dev/null && timeout 900 .venv/bin/python -m pytest tests/e2e -q -p no:logging -n auto --dist loadfile`
Expected: PASS（整個 e2e 目錄：這個 task 動到幾乎每一頁的控制項）

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(v6-ui): styled checkboxes, switches that report the save, segmented filters"
```

---

### Task 4: 間距、表格、動作列

**Files:**
- Modify: `web/src/styles/base.css`、`web/src/components/ui.tsx`（`DataTable`、`Panel`）
- Modify: `web/src/pages/fleet/Fleet.tsx`、`web/src/pages/hosts/HostProfile.tsx`、`web/src/pages/alerts/Rules.tsx`、`web/src/pages/alerts/AlertsHome.tsx`、
  `web/src/pages/lateral/LateralMovement.tsx`、`web/src/pages/siem/Siem.tsx`、`web/src/pages/reports/Reports.tsx`，以及巡檢指出的其他頁
- Modify: `tests/e2e/test_ui_rules_e2e.py`（`PENDING` 清空並刪掉這個 dict 與「仍有違規」的斷言）
- Test: `tests/e2e/test_ui_rules_e2e.py`、`tests/e2e/test_ui_layout_e2e.py`（新）

**Interfaces:**
- Produces: `Column<R>` 新增選填 `width?: string`（CSS 長度）與 `nowrap?: boolean`；`DataTable` 改用 `table-layout: fixed` 加 `<colgroup>`。
  手寫的 `<table className="table">`（27 處／16 檔）以 class 規則達成同樣效果：時間、等級、狀態、數字欄不換行；`th` 一律 `white-space: nowrap`。
- Produces: `ActionBar({ children })`（`ui.tsx`）：表格正上方的動作列，自己佔一列（`display: flex; flex-wrap: wrap; gap`，下方留 `--space-5`）。

規則（規格 §5.4）：
- 卡片之間固定 `--space-6`：相鄰 `.card`／`.panel` 以父層的 `gap` 或相鄰選擇器的 `margin-top` 保證，不靠各頁自己記得。
- VEN 總覽：動作列改用 `ActionBar`，不再與表頭重疊；「主機清單」卡片與上方卡片分開；四張分布卡片依內容高度、靠上對齊（`align-items: start`）。
- 主機頁：各段卡片分開；同一句資料缺口提示（`wb_gaps`）在頁首出現一次，不在四張卡片各出現一次。
- 表頭不折行：欄太窄的加寬或縮短表頭文字（「嚴重度」可用現有較短的鍵「等級」；新鍵兩種語言都加）。告警規則表的名稱欄給足寬度，名稱不折成兩三行。
- 只裝一顆按鈕的卡片取消：告警規則頁「立即評估」併入規則清單上方的 `ActionBar`，說明文字改成按鈕的 `title` 與其下的一行 `hint`。
- 整列寬的按鈕改一般寬度靠左：偵測頁「再顯示 N 項」「隔離所選的主機」。
- 整欄都沒有值的欄不顯示：告警規則表的「狀態」欄只在至少一列有值時出現。
- SIEM 頁：卡片標題列的「重新整理」按鈕與「SIEM DLQ」連結靠右對齊在同一列；「移除」不緊貼開關，移到該目的地卡片的右上角。
- 報表範本頁：四欄卡片改成每欄內卡片等寬、同一橫列頂端對齊（CSS grid，`align-items: start`）；標題字體統一用 `--font-display`
  （現況含中文的標題落到後備字體、純英文的用 Montserrat；中文標題用 `--font-ui` 粗體，不混用）。

- [ ] **Step 1: 寫失敗測試** `tests/e2e/test_ui_layout_e2e.py`

```python
LONG = "a-very-long-host-name-that-keeps-going." + "x" * 60 + ".example.internal"

def test_a_long_name_wraps_inside_its_cell(live_app, context):
    # 用 test_fleet_e2e.py 的 `_setup`／`_wl`，放一台名稱是 LONG 的主機與一條名稱很長的告警規則；
    # 開 /fleet、/alert-rules、/ 三頁，各自斷言：
    #   頁面沒有水平捲動；該格的 scrollWidth <= clientWidth + 1；
    #   該格的 innerText 含完整的 LONG（沒有省略號、沒有被 overflow:hidden 裁掉）

def test_the_fleet_action_bar_is_above_the_table_head(live_app, context):
    # 1440x900；捲到主機清單；動作列每顆按鈕的 bottom <= 表頭 top

def test_a_notice_about_missing_data_appears_once_on_the_host_page(live_app, context):
    # 用 test_hosts_e2e.py 的方式灌一段資料缺口；page.locator("[data-role=caveat]") 中同一句文字只出現一次

def test_an_empty_column_is_not_drawn(live_app, context):
    # 告警規則頁、沒有規則被冷卻或頻率限制擋下：表頭不含「狀態」；
    # 讓一條規則進入冷卻（做法見 test_alerts_e2e.py 的 hold 參數）後該欄出現
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && npm --prefix web run --silent build > /dev/null && timeout 600 .venv/bin/python -m pytest tests/e2e/test_ui_layout_e2e.py -x -q -p no:logging`
Expected: FAIL

- [ ] **Step 3: 實作**
- [ ] **Step 4: 刪掉 `PENDING` 與「仍有違規」的斷言**：巡檢從此對每條規則都要求零違規。
- [ ] **Step 5: build 後跑整個 e2e**（指令同 Task 3 Step 5）Expected: PASS
- [ ] **Step 6: Commit**

```bash
git commit -m "fix(v6-ui): cards keep their distance, tables keep their columns, the fleet action bar no longer covers the table head"
```

---

### Task 5: 頁面骨架：用途句、收合的說明、空狀態

**Files:**
- Modify: `web/src/components/ui.tsx`（`PageHead`、新增 `Disclosure`、`EmptyState`）
- Modify: 每個頁面元件的頁首（`PageHead` 目前只有 8 檔在用，其餘頁面是手寫 `<h1>`）
- Modify: `illumio_ops/i18n/en.json`、`illumio_ops/i18n/zh_TW.json`
- Test: `tests/e2e/test_ui_skeleton_e2e.py`（新）

**Interfaces:**
- Produces: `PageHead({ title, purpose, children })`：`purpose: string` 必填（原本的 `sub` 改名並改必填，讓型別檢查擋住沒寫用途的頁）；
  渲染 `<p data-role="page-purpose">`。`children` 是頁首右側的控制項。
- Produces: `Disclosure({ summary, children })`：`<details>`，預設收合，`summary` 預設文字用鍵 `ui_what_is_this`。
- Produces: `EmptyState({ text, action })`：`<div data-role="empty-state">`，`action` 是選填的連結或按鈕。

每頁的用途句（固定文字，兩種語言；鍵名 `purpose_<頁>`；取代現有的 `*_sub` 鍵，被取代的舊鍵刪除）：

| 頁 | zh_TW | en |
|---|---|---|
| 告警 `/` | 最近發生了哪些需要注意的事，以及牽涉到哪些設備。 | What recently needs attention, and which hosts are involved. |
| 告警詳情 | 這則告警發生了什麼、依據是什麼、可以怎麼處理。 | What this alert is, what it is based on, and what can be done. |
| 偵測 | 目前的攻擊面有多大，以及哪些連線被偵測為可疑。 | How large the attack surface is now, and which connections were detected as suspicious. |
| 調查 | 依條件查看流量與事件，找出一條連線的來龍去脈。 | Look through traffic and events by condition to trace a connection. |
| 主機 | 一台設備的狀態、平常的樣子與最近的異常。 | One host: its state, what is usual for it, and what recently was not. |
| VEN 總覽 | 所有受管主機的 VEN 狀態、強制模式與政策同步，可篩選並批次操作。 | Every managed host's VEN state, enforcement mode and policy sync, with filters and bulk actions. |
| 規則排程 | 依時間自動啟用或停用 PCE 上的規則。 | Enable or disable PCE rules on a schedule. |
| 規則集 | PCE 上已生效的規則集與規則，唯讀。 | The PCE's active rule sets and rules, read-only. |
| 報表 | 產生報表、設定定期寄送，以及取得已產出的報表。 | Generate reports, schedule their delivery, and get the ones already made. |
| SIEM 轉送 | 把事件、告警與新連線送到你的 SIEM，以及每個目的地送到哪裡了。 | Send events, alerts and new connections to your SIEM, and see how far each destination has got. |
| SIEM DLQ | 送不出去的訊息，以及重送或清除。 | Messages that could not be sent, to resend or clear. |
| 告警規則與通知 | 哪些情況會變成告警，以及告警送到哪裡。 | Which situations become alerts, and where alerts are sent. |
| 新增／編輯規則 | 設定一條告警規則的條件、門檻與通知。 | One alert rule: its condition, threshold and notification. |
| 系統 › 模式與資料來源 | 收集哪些資料、保留多久，以及目前收集的狀態。 | What is collected, how long it is kept, and how collection is doing. |
| 系統 › PCE 連線 | 連到哪一台 PCE、用哪把 API key，以及連線是否正常。 | Which PCE, with which API key, and whether the connection works. |
| 系統 › 橫向移動設定 | 偵測器的狀態，以及它們依據的 port、群組與門檻。 | The detectors' states, and the ports, groups and thresholds they go by. |
| 系統 › 背景工作 | 每個背景工作多久跑一次、上次結果如何。 | How often each background job runs and how its last run went. |
| 系統 › 憑證 | 這個網站使用的 TLS 憑證。 | The TLS certificate this site uses. |
| 系統 › 安全 | 登入帳號、密碼與可連線的來源位址。 | The sign-in account, its password, and the addresses allowed to connect. |
| 系統 › 日誌 | 這個工具自己的執行日誌。 | This tool's own logs. |
| 系統 › 顯示 | 介面語言與時區。 | Interface language and time zone. |

（系統各頁的實際內容以程式為準：若某頁的內容與上面那句不符，改那句使它對得上，並在回報寫出。）

規則（規格 §5.5）：
- 每頁用 `PageHead`，`purpose` 取上表。
- 超過一行的說明文字收進 `Disclosure`：卡片開頭整段的解釋（例：告警規則頁內建規則說明、SIEM 頁首說明、偵測頁各區塊的定義、模式頁的資源需求）。
  **不收**的：資料缺口、涵蓋範圍、截斷、需要進階模式的原因（`.notice`、`NeedsAdvanced`、`Reason`、`data-role=caveat`），這些影響判讀，必須一直看得到。
- 空狀態用 `EmptyState` 並寫下一步：清單為空時說明原因與去處（例：告警規則頁沒有通道時連到通知通道分頁；報表已產出為空時連到範本分頁）。
  只用既有資料判斷得出的原因，不寫「一切正常」。
- 本 task 不加結論句（各頁的結論句需要新資料，屬第 2 段）。

- [ ] **Step 1: 寫失敗測試** `tests/e2e/test_ui_skeleton_e2e.py`

```python
def test_every_page_says_what_it_is_for(live_app, context):
    # 走訪 test_ui_rules_e2e.PATHS：每頁恰好一個 h1、恰好一個 [data-role=page-purpose]，文字非空、不是 i18n 鍵（不含底線）

def test_long_explanations_start_closed_and_caveats_stay_visible(live_app, context):
    # 告警規則頁：details 預設沒有 open 屬性，點 summary 後內容可見
    # 主機頁（灌資料缺口）：[data-role=caveat] 不在任何 details 裡面

def test_an_empty_list_says_what_to_do_next(live_app, context):
    # 未灌資料：/reports?tab=produced 與 /alert-rules?tab=channels 各有一個 [data-role=empty-state]，裡面有一個連結
```

- [ ] **Step 2: 跑測試確認失敗**（指令比照 Task 4 Step 2，換檔名）
- [ ] **Step 3: 實作**
- [ ] **Step 4: build 後跑整個 e2e 與 i18n 測試**

Run: `cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && npm --prefix web run --silent typecheck && npm --prefix web run --silent build > /dev/null && timeout 900 .venv/bin/python -m pytest tests/e2e tests/i18n tests/web/test_i18n_route.py -q -p no:logging -n auto --dist loadfile`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(v6-ui): every page says what it is for, long explanations start closed, empty lists say what to do next"
```

---

### Task 6: 沒看過的畫面補看、兩台實機驗收、發版

規格 §11 載明盤點時沒有逐張讀過的畫面；巡檢測試走不到的（對話框、抽屜、展開的表單）也在這裡處理。

**Files:**
- Modify: 補看後發現違規的頁面與 `tests/e2e/test_ui_rules_e2e.py`（把走得到的互動狀態加入走訪）
- Modify: `CHANGELOG.md`、`illumio_ops/__init__.py`（`__version__ = "6.7.0"`）、`README.md` 版本徽章、`web/package.json` 不動
- Modify: `docs/superpowers/specs/2026-11-11-v6-purpose-led-ui-design.md`（§11 第 1 段那段「沒看到的」改成實際看過的清單與日期）

**Interfaces:**
- Consumes: `tools/ui_audit.py`、`ui_rules.violations`。

- [ ] **Step 1: 把互動狀態加入巡檢**：`test_rules_hold_with_data` 另外開啟並檢查——VEN 總覽「變更強制模式…」對話框（勾一台主機後按）、
  「加快流量回報…」對話框、隔離對話框（主機頁）、報表「產生…」展開的表單、報表排程編輯、告警規則的試算結果、新增通知通道表單、
  規則排程的新增側欄、調查頁的儲存區塊。每個都只開啟不送出。跑測試，修掉抓到的違規。

Run: `cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && npm --prefix web run --silent build > /dev/null && timeout 900 .venv/bin/python -m pytest tests/e2e/test_ui_rules_e2e.py -x -q -p no:logging`
Expected: PASS

- [ ] **Step 2: 全套閘門**

Run: `cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && bash .superpowers/sdd/2026-11-03-v6-ui-b-rule-scheduling/gates.sh`
Expected: 最後一行 `ALL GATES GREEN`

- [ ] **Step 3: 版本與變更紀錄**：`CHANGELOG.md` 新增 6.7.0 條目（寫使用者看得到的改變：按鈕層級、標籤、開關的回饋、表格與卡片間距、
  VEN 總覽動作列缺陷、每頁用途句、收合的說明），`__version__`、README 徽章。Commit：

```bash
git commit -m "chore(v6): version 6.7.0"
```

- [ ] **Step 4: 部署到 .106 與 .135**（離線 bundle 升級，程序同 6.6.1：見 `docs/superpowers/plans/2026-11-11-v6-6.4.5-handoff.md` 的「6.6.1」一節）。
  這一步由主持人執行，不交給 implementer。

- [ ] **Step 5: 實機稽核**（密碼只經環境變數注入單一子行程，不印出）

Run（兩台、兩種寬度各一次，共四次）：
`cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && .venv/bin/python tools/ui_audit.py https://172.16.15.106:5001 --width 1440 --out <scratchpad>/s1-106-1440`
Expected: 每頁每條規則 0 筆，結束碼 0。.135 是基本模式、英文介面，.106 是進階模式、中文介面。

- [ ] **Step 6: 逐張看截圖**：四組截圖每一張都打開看（不是只看程式輸出）。檢查器量不到的項目用眼睛確認：每區主要按鈕選得對不對、
  用途句與內容相符、收合了不該收的東西沒有、等寬字只剩該用的地方、整體有沒有比改之前難讀的地方。
  把「看了哪幾張、各發現什麼」列在回報；發現問題就修、重新部署、重跑 Step 5。

- [ ] **Step 7: 更新規格 §11 的已看清單，Commit**

```bash
git add docs/superpowers/specs/2026-11-11-v6-purpose-led-ui-design.md
git commit -m "docs(v6): stage 1 of the purpose-led UI is on both boxes; what was looked at"
```

## 不在這份計畫裡

導覽分組、告警頁的「新的」與涉及設備、主機頁空白狀態與錨點、隔離頁、名稱統一（規格 §4、§6–§8）是第 2 段；報表（§9）是第 3 段；
規則表單（§10）是第 4 段。白話用語對照（§5.6）會改到告警與主機頁的內容文字，跟著第 2 段做。

## 實作後與本計畫的差異（2026-11-11，後面三段引用名稱時以這裡為準）

- **`ActionNote`**（`data-role="action-note"`）取代計畫裡的 `DisabledWhy`：告警側欄的隔離按鈕不是停用，是按了也不會生效，所以叫說明不叫停用原因。
- **沒有做 `ActionBar` 元件**。VEN 總覽的重疊是 `.panel-body > .table-wrap` 的負邊界把表格拉到動作列上面；改成樣式規則（`.panel-body > * + .table-wrap`），不需要元件。
- **`.badge` 沒有逐一改成 `<Tag>`**：`.tag, .badge` 在樣式上併成同一條規則，外觀相同；標記沒動，既有測試的選擇器不變。
- **核取方塊沒有 `Checkbox` 元件**：全站的 `input[type=checkbox]` 由樣式自繪，43 處標記不用改。
- **`Segmented` 元件只用在告警頁的「全部／只看未處理」**；其餘 `chips-row`／`chip-btn`（分頁、類別）由樣式改成同樣的分段外觀。
- **`EmptyState` 只用在「已產出」報表為空時**；`Disclosure` 用在三處（告警規則頁的內建規則、SIEM 頁首說明、VEN 總覽的在線定義）。偵測頁各區塊的定義沒有收，留給第 2 段整理偵測頁時處理。
- **按鈕層級以 class 套用**（`btn-primary`／`btn-quiet`／`btn-text`／`btn-danger`），`Button`、`LinkButton` 元件提供給新寫的頁面。
  改成危險的：SIEM 移除目的地、DLQ 三個清除、報表排程刪除、已產出報表批次刪除、自訂報表刪除、告警規則刪除與其確認、切換 PCE 時的清除資料。
  改成文字的：報表卡片「排程寄送」、自訂報表移除章節、告警詳情的「主機側寫」「在 PCE 主控台開啟」「在主機頁隔離」、告警側欄「標為已知」、移除已知標記、移除竄改備註。
  改前後數量（原始碼中的出現次數）：主要 37→37、次要 116→98、危險 6→16、文字 1→9。
- **`one_primary` 從一開始就沒有違規**（測試資料與 .106 都是），所以它是守門不是修復項；`PENDING` 一開始列七條不是八條。
- **`Column` 多了 `kind: "time"` 與 `nowrap`**；`HostName` 元件把位址排成等寬字、主機名稱排成一般字體。
- **`.page` 本身是一欄的 grid**（間距 `--space-6`），頁面不必各自加 `stack`。
- **巡檢的互動狀態**是六個（VEN 總覽兩個對話框、主機頁隔離對話框、報表產生表單、報表排程編輯、調查頁存成章節）；
  規則試算結果需要候選事件，沒有納入。
- **沒做、留到後面**：`.wb-dim-label`（調查頁左欄）仍以省略號收尾，但加了 `title` 可看完整值；偵測頁細節區塊的預設收合（規格 §6.5，第 2 段）。
