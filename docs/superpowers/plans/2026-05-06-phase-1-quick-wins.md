# Phase 1 Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 8 個 P1 痛點 (a1, a2, b3, b4, b6, c1, d2, d3) 從 rubric 0-1 拉到 rubric ≥1 (基本可用)，純補丁式修補，不動架構，為 Phase 2 bundled refactor (Track A/B/C/D) 鋪路。

**Architecture:** 4 個獨立 batch 對應 4 個子系統 (GUI/CLI/Report/Email)。每 batch 內 task 互相獨立，可平行 ship。Batch 之間零依賴，可任意順序執行或並行 (subagent-driven 模式可一次跑一 batch)。

**Tech Stack:** Vanilla JS + CSS（無 build pipeline）；Python 3.12 + Click + Rich（CLI）；Jinja2 + WeasyPrint（reports）；Python email.mime + string.Template（email）。

**Reference docs:**
- 評估報告: `docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md`
- §3.x.5/6 推薦組合 (per subsystem)
- §4 痛點卡 (a1/a2 = 4.1/4.2; b3/b4/b6 = 4.7/4.8/4.10; c1 = 4.13; d2/d3 = 4.15/4.16)
- §5.3 Phasing — Phase 1 quick wins 即本 plan

**驗收 (整 plan):**
- 評估報告 §3.1.2 GUI UX rubric §3 perf 0→≥1, §8 forms 1→≥2
- §3.2.4 CLI rule 2★ capability 1→≥2, rule 3★ composability 0→≥2, rule 12 actionability 0→≥2
- §3.3.2 c1 改善：3 份 report 開頭 200 字 standalone exec summary 可讀
- §3.4.2 cross-client 2/8 → ≥6/8; §3.4.4 actionability 0/4 → ≥3/4

**Commit / branch 策略：** 全 plan 在單一分支 `plan/phase-1-quick-wins-2026-05-06` 上 batch by batch 進行，每 task 1 commit。每 batch 結束可獨立 PR 或全部完成後合一個大 PR。

**安全約束 (整 plan)：**
- 所有 DOM 操作禁用 `innerHTML` 寫入 (XSS surface)。改用 `createElement` + `textContent` + `appendChild` 或 `replaceChildren()`。
- 所有 i18n 字串 + 使用者輸入經過 `escapeHtml(...)` (utils.js 已有) 後才注入 DOM。
- Email template `string.Template` 變數值在 reporter 端用 `html.escape` 轉義 (Python stdlib)。

---

## Batch 1 — GUI quick wins (痛點 a1, a2)

對應 §4.1 a1 (GUI tab 載入體驗) + §4.2 a2 (表格篩選/搜尋)。

### Task 1.1: 加 defer 屬性到所有 13 個 script tag

**Files:**
- Modify: `src/templates/index.html` (script tags 在 line 13 + line 1986-1998)

**為何:** A.3 finding — 0/13 用 defer/async，HTML parser 被 `<script>` 阻塞 → cold load 慢。`defer` 讓 script 平行下載、按順序在 DOMContentLoaded 前執行，行為與目前一致 (script 順序保留)。

- [ ] **Step 1: 確認 script 標籤位置**

```bash
cd /home/harry/rd/illumio-ops
grep -nE '<script[^>]*src=' src/templates/index.html
```

預期: 13 行命中 (line 13 + 12 行 in 1986-1998 區塊)。

- [ ] **Step 2: 對每個 script 加 defer 屬性**

用 sed 一次性處理 (定位 `<script src=...></script>` pattern, 加 `defer ` 在 `src=` 前):

```bash
cd /home/harry/rd/illumio-ops
sed -i.bak -E 's|(<script )(src=)|\1defer \2|g' src/templates/index.html
diff src/templates/index.html.bak src/templates/index.html | head -30
rm src/templates/index.html.bak
```

或手動用 Edit tool: 對每個 `<script src=` 改成 `<script defer src=`。

- [ ] **Step 3: 驗證**

```bash
grep -cE '<script defer src' src/templates/index.html
# 預期: 13 (全部)
grep -cE '<script[^>]*src=' src/templates/index.html
# 預期: 13 (沒漏)
```

兩數相等 → OK。

- [ ] **Step 4: Jinja syntax check**

```bash
python3 -c "
from jinja2 import Environment, FileSystemLoader, ChainableUndefined
env = Environment(loader=FileSystemLoader('src/templates'), undefined=ChainableUndefined)
src = open('src/templates/index.html').read()
import re
assert re.findall(r'<script defer src', src).__len__() == 13, 'defer count mismatch'
print('OK: 13 script tags all have defer')
"
```

- [ ] **Step 5: Commit**

```bash
git add src/templates/index.html
git commit -m "fix(gui): add defer attribute to all 13 script tags (a1)

Per assessment Task A.3 finding: 0/13 script tags had defer/async,
causing HTML parser blocking during cold load. defer makes scripts
download in parallel and execute in order before DOMContentLoaded —
identical functional behavior to current sequential blocking, but
without the parser stall.

Touches §3.1.2 §3 Performance rubric: contributes to 0→≥1."
```

---

### Task 1.2: 加 <link rel="preload"> for critical CSS

**Files:**
- Modify: `src/templates/index.html` (in `<head>`)

**為何:** Browser 預先取 CSS，與 HTML parsing 平行，加速 first-paint。

- [ ] **Step 1: 找 critical CSS 引用**

```bash
cd /home/harry/rd/illumio-ops
grep -nE '<link[^>]*\.css' src/templates/index.html | head -5
```

預期看到 app.css 之類 link tag。記下 url_for 路徑。

- [ ] **Step 2: 在 <head> 加 preload**

在 `<head>` 內既有 CSS `<link>` 之前加 (對應實際路徑)：

```html
  <link rel="preload" href="{{ url_for('static', filename='css/app.css') }}" as="style">
```

用 Edit tool 精準插入。

- [ ] **Step 3: 驗證**

```bash
grep -nE 'rel="preload"' src/templates/index.html
# 預期: 1+ 行
```

- [ ] **Step 4: Commit**

```bash
git add src/templates/index.html
git commit -m "fix(gui): preload critical CSS in index.html (a1)

Browser fetches CSS earlier in HTML parse phase. Reduces first-paint
delay perceptibly on cold load.

Touches §3.1.2 §3 Performance rubric: contributes to 0→≥1."
```

---

### Task 1.3: Skeleton placeholder for tab 切換

**Files:**
- Modify: `src/static/css/app.css` (新增 .skeleton class + animation)
- Modify: `src/static/js/tabs.js` (在 tab 切換時插入 skeleton, 內容 ready 後移除)

**為何:** Tab 切換瞬間空白 → 加 shimmer skeleton 降低感知延遲。

**安全注意：** 用 `createElement` + `replaceChildren()` 而非 `innerHTML`，避免 XSS surface。

- [ ] **Step 1: 新增 .skeleton class 到 app.css**

在 `src/static/css/app.css` 末尾追加：

```css

/* ── Skeleton loader (Phase 1 quick win for a1) ─────────────────────────── */
.skeleton {
  display: block;
  background: linear-gradient(90deg, var(--bg-input,#f5f5f5) 0%, rgba(255,255,255,0.6) 50%, var(--bg-input,#f5f5f5) 100%);
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.4s ease-in-out infinite;
  border-radius: 4px;
  height: 16px;
  margin: 8px 0;
}
.skeleton.skeleton-tall { height: 64px; }
.skeleton.skeleton-card { height: 120px; }

@keyframes skeleton-shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

@media (prefers-reduced-motion: reduce) {
  .skeleton { animation: none; }
}
```

- [ ] **Step 2: 加 helper function 到 tabs.js (用 createElement, 不用 innerHTML)**

Read `src/static/js/tabs.js` 找 tab 切換主入口 (例如 `function showTab(name)` or click handler)。

加 helper：

```javascript
// Phase 1 quick win for a1: skeleton placeholder during async loads.
// Uses DOM construction (createElement + replaceChildren) — no innerHTML
// to avoid any XSS surface even though content is static.
function showSkeleton(containerSelector, count = 3) {
  const el = document.querySelector(containerSelector);
  if (!el) return;
  const fragment = document.createDocumentFragment();
  for (let i = 0; i < count; i++) {
    const div = document.createElement('div');
    div.className = 'skeleton';
    if (i % 3 === 0) div.classList.add('skeleton-card');
    fragment.appendChild(div);
  }
  el.replaceChildren(fragment);
}

function hideSkeleton(containerSelector) {
  const el = document.querySelector(containerSelector);
  if (!el) return;
  // Caller is expected to replace skeleton with real content via existing
  // render flow. This helper is a noop hook for explicit cleanup paths.
}
```

(如已有 showSkeleton in rules.js per A.3 finding, reuse 不複製。檢查 `grep -rEn 'showSkeleton' src/static/js/`。若已存在但用 innerHTML，順手改成 createElement 版。)

- [ ] **Step 3: 在 tab 切換時呼叫 skeleton**

在 tabs.js 主切換點加：

```javascript
// Before triggering async data load:
showSkeleton('#p-' + tabName + ' .data-area', 3);
// After data arrives, real content overwrites #p-{tab} content (existing flow).
```

(具體 selector 依現有 DOM 結構，先 grep `id="p-` 確認 panel 命名規範)

- [ ] **Step 4: 視覺驗證 (jinja syntax + grep only)**

```bash
grep -cE '@keyframes skeleton-shimmer' src/static/css/app.css
# 預期: 1
grep -cE 'function showSkeleton' src/static/js/tabs.js src/static/js/rules.js
# 預期: 1 (只在一處定義)
grep -cE 'innerHTML\s*=' src/static/js/tabs.js
# 預期: 0 (本 task 新增的 helper 不該有 innerHTML)
```

- [ ] **Step 5: Commit**

```bash
git add src/static/css/app.css src/static/js/tabs.js
git commit -m "feat(gui): skeleton placeholder for tab switch (a1)

Adds .skeleton class with shimmer animation + showSkeleton/hideSkeleton
helpers in tabs.js. On tab switch, render N skeleton cards while async
data loads, replaced by real content when ready.

Implementation uses createElement + replaceChildren (no innerHTML, no
XSS surface). Respects prefers-reduced-motion.

Touches §3.1.2 §3 Performance + §9 Navigation patterns."
```

---

### Task 1.4: Form input debounce 300ms + visual loading state

**Files:**
- Modify: `src/static/js/utils.js` (新增 debounce helper)
- Modify: `src/static/js/rules.js` 或對應 filter input 處 (套用 debounce)
- Modify: `src/static/css/app.css` (加 .input-loading class)

**為何:** §4.2 a2 — 表格篩選打字後立即觸發查詢 → 反覆請求。300ms debounce + spinner 降低後端負載與 UI 抖動。

- [ ] **Step 1: 加 debounce helper 到 utils.js**

Read `src/static/js/utils.js`，在末尾追加：

```javascript
// Phase 1 quick win for a2: debounce filter inputs
window.debounce = function debounce(fn, wait = 300) {
  let timer;
  return function debounced(...args) {
    clearTimeout(timer);
    const ctx = this;
    timer = setTimeout(() => fn.apply(ctx, args), wait);
  };
};
```

- [ ] **Step 2: 加 .input-loading CSS**

在 `src/static/css/app.css` 末尾追加：

```css
/* Phase 1 quick win for a2: input loading indicator */
.input-loading {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='10' stroke='%23999' stroke-width='3' fill='none' stroke-dasharray='30 30'%3E%3CanimateTransform attributeName='transform' type='rotate' from='0 12 12' to='360 12 12' dur='0.8s' repeatCount='indefinite'/%3E%3C/circle%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 8px center;
  background-size: 14px;
  padding-right: 28px;
}
```

- [ ] **Step 3: 套用 debounce 到 filter input**

找 filter input 的 oninput / addEventListener('input', ...) handler。例如 in rules.js:

```bash
cd /home/harry/rd/illumio-ops
grep -rnE 'addEventListener\(.input.|oninput' src/static/js/ | head -10
```

對每個 input handler，把：
```javascript
input.addEventListener('input', applyFilter);
```
改成：
```javascript
const debouncedFilter = debounce(function() {
  this.classList.add('input-loading');
  applyFilter.call(this);
  // Caller's applyFilter should remove .input-loading when done; if synchronous, remove now:
  setTimeout(() => this.classList.remove('input-loading'), 50);
}, 300);
input.addEventListener('input', debouncedFilter);
```

(逐一處理；保守做法是先處理 1-2 個高頻 input，commit 後再擴及其他)

- [ ] **Step 4: 驗證**

```bash
grep -cE 'window\.debounce|debounce\(' src/static/js/utils.js
grep -cE '\.input-loading' src/static/css/app.css
grep -rnE 'debounce\(' src/static/js/ | wc -l
# 預期 ≥1 處 input handler 已套用
```

- [ ] **Step 5: Commit**

```bash
git add src/static/js/utils.js src/static/js/rules.js src/static/css/app.css
git commit -m "feat(gui): debounce filter inputs (300ms) + spinner (a2)

Adds window.debounce helper and .input-loading CSS class with inline
SVG spinner. Filter inputs trigger query 300ms after last keystroke
(reduces backend load) and show right-aligned spinner during processing
(reduces UI 抖動 perception).

Touches §3.1.2 §8 Forms & Feedback rubric: contributes to 1→≥2."
```

---

### Task 1.5: aria-invalid + inline 錯誤 helper (示範 1-2 個套用點)

**Files:**
- Modify: `src/static/js/utils.js` (新增 setFieldError / clearFieldError helper)
- Modify: `src/static/css/app.css` (.field-error style)
- Modify: 各 form 處 (例如 settings.js, rules.js — 高頻場景優先)

**為何:** §4.2 a2 — 162 個 input 無 aria-invalid，無 inline 即時驗證。先加 helper + 高頻場景套用。其他低頻場景下次再補（避免 1 個 commit 動 162 處）。

**安全注意：** helper 內 `err.textContent = message` 而非 `innerHTML`，i18n 字串不會被當 HTML 解析。

- [ ] **Step 1: 加 setFieldError / clearFieldError helper to utils.js**

在 `src/static/js/utils.js` 末尾：

```javascript
// Phase 1 quick win for a2: inline form validation.
// Uses textContent (not innerHTML) so i18n strings are never parsed as HTML.
window.setFieldError = function setFieldError(input, message) {
  input.setAttribute('aria-invalid', 'true');
  let err = input.parentElement.querySelector('.field-error');
  if (!err) {
    err = document.createElement('span');
    err.className = 'field-error';
    err.setAttribute('role', 'alert');
    input.insertAdjacentElement('afterend', err);
  }
  err.textContent = message;  // safe: text only, no HTML parsing
};
window.clearFieldError = function clearFieldError(input) {
  input.removeAttribute('aria-invalid');
  const err = input.parentElement.querySelector('.field-error');
  if (err) err.remove();
};
```

- [ ] **Step 2: 加 .field-error CSS**

在 `src/static/css/app.css` 末尾：

```css
/* Phase 1 quick win for a2: inline field error */
.field-error {
  display: block;
  color: var(--danger, #BE122F);
  font-size: 0.85em;
  margin-top: 4px;
  line-height: 1.3;
}
input[aria-invalid="true"],
textarea[aria-invalid="true"],
select[aria-invalid="true"] {
  border-color: var(--danger, #BE122F);
  outline-color: var(--danger, #BE122F);
}
```

- [ ] **Step 3: 套用到高頻 input 場景 (1-2 處示範)**

選 settings.js 中「PCE URL」input 與 rules.js 中「rule name」input 各 1 處示範。例如：

```javascript
// settings.js, in PCE URL save handler:
const urlInput = document.querySelector('#s-pce-url');
const url = urlInput.value.trim();
if (!url || !/^https?:\/\//.test(url)) {
  setFieldError(urlInput, _t('error_invalid_url') || 'URL must start with http:// or https://');
  return;
}
clearFieldError(urlInput);
// ... existing save flow
```

(具體 selector 依現有 code，先 grep `s-pce-url` 確認)

- [ ] **Step 4: 驗證**

```bash
grep -cE 'window\.setFieldError|setFieldError\(' src/static/js/utils.js
grep -cE '\.field-error' src/static/css/app.css
grep -rnE 'setFieldError\(' src/static/js/ | wc -l
# 預期 ≥2 處示範
grep -cE 'innerHTML\s*=' src/static/js/utils.js
# 預期: 0 (helper 全用 textContent / createElement)
```

- [ ] **Step 5: 補 i18n key**

在 `src/i18n_en.json` + `src/i18n_zh_TW.json` 加：
```json
"error_invalid_url": "URL must start with http:// or https://"
```
(zh_TW 版: "網址必須以 http:// 或 https:// 開頭")

- [ ] **Step 6: Commit**

```bash
git add src/static/js/utils.js src/static/css/app.css src/static/js/settings.js src/static/js/rules.js src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(gui): inline aria-invalid + field error helper (a2)

Adds setFieldError/clearFieldError helpers and .field-error CSS.
Demonstrates usage at 2 high-frequency input sites (PCE URL, rule
name). Remaining ~160 inputs to be migrated incrementally.

Helpers use textContent (not innerHTML) — i18n strings cannot be
parsed as HTML.

Adds i18n key error_invalid_url (en + zh_TW).

Touches §3.1.2 §8 Forms & Feedback rubric: contributes to 1→≥2."
```

---

## Batch 2 — CLI quick wins (痛點 b3, b4, b6, b7)

對應 §4.7 b3 (輸出格式), §4.8 b4 (錯誤訊息), §4.10 b6 (isatty/NO_COLOR), §4.11 b7 (exit codes)。

### Task 2.1: isatty 條件渲染 + NO_COLOR / TERM=dumb 處理 (合併)

**Files:**
- Modify: `src/cli/_render.py` (`_get_console()` line 356-365)
- Create: `tests/cli/test_render_tty.py`

**為何:** §4.10 b6 — `_stdout_is_tty()` 已存在但 `_get_console()` 用 `force_terminal=None` (auto-detect) — rich 自家偵測在某些 CI 環境誤判仍輸出 ANSI。改成顯式用 `_stdout_is_tty()` 結果，並讓 NO_COLOR 短路關閉顏色。本 task 合併原 plan Task 2.1 + 2.2。

- [ ] **Step 1: 寫測試**

新建 `tests/cli/test_render_tty.py`:

```python
"""Test that Console respects TTY status and NO_COLOR."""
import os
from unittest.mock import patch
import sys

import pytest

from src.cli import _render


def _reset_singleton():
    _render._CONSOLE_SINGLETON = None


@pytest.fixture(autouse=True)
def reset():
    _reset_singleton()
    saved = {k: os.environ.get(k) for k in ('NO_COLOR', 'TERM')}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _reset_singleton()


def test_console_no_color_when_NO_COLOR_env_set():
    os.environ['NO_COLOR'] = '1'
    c = _render._get_console()
    assert c.no_color is True or c.color_system is None


def test_console_no_color_when_term_dumb():
    os.environ.pop('NO_COLOR', None)
    os.environ['TERM'] = 'dumb'
    c = _render._get_console()
    assert c.no_color is True or c.color_system is None


def test_console_not_terminal_when_stdout_not_tty(monkeypatch):
    os.environ.pop('NO_COLOR', None)
    os.environ.pop('TERM', None)
    monkeypatch.setattr(_render, '_stdout_is_tty', lambda: False)
    c = _render._get_console()
    assert c.is_terminal is False
```

- [ ] **Step 2: 跑測試確認失敗 (RED)**

```bash
cd /home/harry/rd/illumio-ops
mkdir -p tests/cli
pytest tests/cli/test_render_tty.py -v 2>&1 | tail -20
```

預期: 至少 2 個 fail (NO_COLOR / TERM=dumb 沒被處理)。

- [ ] **Step 3: 改 _get_console() 連接 isatty + NO_COLOR**

Edit `src/cli/_render.py` 的 `_get_console()` (line 356-365)：

```python
def _get_console() -> _RichConsole:
    """Lazily build a shared Console honoring TTY status and NO_COLOR.

    Phase 1 quick win for b6: explicit capability detection instead of
    rich's auto-detect.
    """
    global _CONSOLE_SINGLETON
    if _CONSOLE_SINGLETON is None:
        # Capability detection in priority order:
        # 1. NO_COLOR env (https://no-color.org/) — disables color even in TTY
        # 2. TERM=dumb — disables color
        # 3. _stdout_is_tty() — controls is_terminal (force_terminal=False if not)
        no_color = (
            os.environ.get('NO_COLOR') is not None
            or os.environ.get('TERM') == 'dumb'
        )
        is_tty = _stdout_is_tty()
        _CONSOLE_SINGLETON = _RichConsole(
            force_terminal=is_tty,
            no_color=no_color,
            safe_box=True,
            highlight=False,
        )
    return _CONSOLE_SINGLETON
```

確認 `import os` 在檔頂 (若無則加)。

- [ ] **Step 4: 跑測試 GREEN**

```bash
pytest tests/cli/test_render_tty.py -v 2>&1 | tail -10
```

預期: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cli/_render.py tests/cli/test_render_tty.py
git commit -m "fix(cli): explicit TTY + NO_COLOR detection in Console (b6)

Replaces rich's force_terminal=None auto-detect with explicit
_stdout_is_tty() result and NO_COLOR/TERM=dumb env honoring. CI/pipe
contexts no longer get ANSI escape codes when stdout is not a terminal,
and operators can opt-out of color via NO_COLOR=1.

Adds tests/cli/test_render_tty.py with 3 tests covering NO_COLOR,
TERM=dumb, and non-TTY scenarios.

Touches §3.2.4 CLI rule 2★ capability 1→≥2 + rule 3★ composability 0→≥1."
```

---

### Task 2.2: --json / --quiet / --verbose flag 統一

**Files:**
- Create: `src/cli/_global_flags.py` (helper for global flag handling)
- Modify: `src/cli/root.py` (add group-level options)
- Modify: 1-2 個 sample 命令套用 (e.g., `src/cli/cache.py` `cache list`)
- Create: `tests/cli/test_global_flags.py`

**為何:** §4.7 b3 — 0/24 命令支援 --json/--quiet/--verbose。先建 helper + group-level option + 示範套用 1-2 個命令。其他命令下個 sprint 增量補上。

- [ ] **Step 1: 寫 helper test**

新建 `tests/cli/test_global_flags.py`:

```python
"""Test global flag context (--json, --quiet, --verbose)."""
import json
import pytest
import click
from click.testing import CliRunner

from src.cli._global_flags import inject_global_flags, get_global_flags


@pytest.fixture
def runner():
    return CliRunner()


def test_global_flags_default(runner):
    @click.group()
    @inject_global_flags
    def cli():
        pass

    @cli.command()
    @click.pass_context
    def cmd(ctx):
        flags = get_global_flags(ctx)
        click.echo(json.dumps({"json": flags["json"], "quiet": flags["quiet"], "verbose": flags["verbose"]}))

    result = runner.invoke(cli, ['cmd'])
    assert result.exit_code == 0
    assert json.loads(result.output) == {"json": False, "quiet": False, "verbose": False}


def test_global_flags_json(runner):
    @click.group()
    @inject_global_flags
    def cli():
        pass

    @cli.command()
    @click.pass_context
    def cmd(ctx):
        flags = get_global_flags(ctx)
        click.echo(str(flags["json"]))

    result = runner.invoke(cli, ['--json', 'cmd'])
    assert result.exit_code == 0
    assert result.output.strip() == "True"


def test_global_flags_quiet_verbose_mutually_exclusive(runner):
    @click.group()
    @inject_global_flags
    def cli():
        pass

    @cli.command()
    def cmd():
        click.echo("ok")

    result = runner.invoke(cli, ['--quiet', '--verbose', 'cmd'])
    assert result.exit_code != 0
    assert 'mutually exclusive' in result.output.lower()
```

- [ ] **Step 2: 跑測試確認失敗 (RED)**

```bash
pytest tests/cli/test_global_flags.py -v 2>&1 | tail -10
```

預期: ImportError (module not yet created).

- [ ] **Step 3: 寫 helper module**

新建 `src/cli/_global_flags.py`:

```python
"""Global CLI flags: --json, --quiet, --verbose.

Phase 1 quick win for b3 (composability). Provides a decorator to
inject these flags at group level and a getter for downstream commands.
"""
from __future__ import annotations

import functools

import click


def inject_global_flags(group_callback):
    """Decorator to add --json/--quiet/--verbose to a Click group."""
    @click.option('--json', 'json_output', is_flag=True, default=False,
                  help='Emit machine-readable JSON to stdout (one object per result).')
    @click.option('--quiet', '-q', is_flag=True, default=False,
                  help='Suppress non-essential output. Errors still go to stderr.')
    @click.option('--verbose', '-v', is_flag=True, default=False,
                  help='Verbose output, including debug-level details.')
    @click.pass_context
    @functools.wraps(group_callback)
    def wrapper(ctx, json_output, quiet, verbose, *args, **kwargs):
        if quiet and verbose:
            raise click.UsageError("--quiet and --verbose are mutually exclusive.")
        ctx.ensure_object(dict)
        ctx.obj['_global_flags'] = {
            'json': json_output,
            'quiet': quiet,
            'verbose': verbose,
        }
        return group_callback(*args, **kwargs)
    return wrapper


def get_global_flags(ctx: click.Context) -> dict:
    """Read the global flags dict from the click context.

    Walks parents until found; returns defaults if not present.
    """
    cur = ctx
    while cur is not None:
        if cur.obj and isinstance(cur.obj, dict) and '_global_flags' in cur.obj:
            return cur.obj['_global_flags']
        cur = cur.parent
    return {'json': False, 'quiet': False, 'verbose': False}
```

- [ ] **Step 4: 跑測試 GREEN**

```bash
pytest tests/cli/test_global_flags.py -v 2>&1 | tail -10
```

預期: 3 passed.

- [ ] **Step 5: 套用到 root.py**

Read `src/cli/root.py`. 找 `@click.group()` 主入口，加 `@inject_global_flags`：

```python
from src.cli._global_flags import inject_global_flags

@click.group()
@inject_global_flags
def cli():
    """Illumio Ops CLI."""
    pass
```

- [ ] **Step 6: 示範套用到 1 個命令 (cache list)**

Edit `src/cli/cache.py` 找 `cache list` 命令：

```python
import json as _json
from src.cli._global_flags import get_global_flags

@cache.command(name='list')
# ... existing options ...
@click.pass_context
def cache_list(ctx, ...):
    flags = get_global_flags(ctx)
    rows = _fetch_cache_rows(...)  # existing fetch logic
    if flags['json']:
        click.echo(_json.dumps([r.to_dict() for r in rows], ensure_ascii=False))
        return
    if flags['quiet']:
        for r in rows:
            click.echo(r.id)
        return
    # default: rich table (existing behavior)
    _render_rich_table(rows)
```

(具體 row → dict / id 取法依現有 model)

- [ ] **Step 7: Verify**

```bash
grep -nE 'inject_global_flags|get_global_flags' src/cli/root.py src/cli/cache.py
# 預期: 各 1+ 命中
```

- [ ] **Step 8: Commit**

```bash
git add src/cli/_global_flags.py src/cli/root.py src/cli/cache.py tests/cli/test_global_flags.py
git commit -m "feat(cli): add --json/--quiet/--verbose global flags (b3)

New module src/cli/_global_flags.py provides @inject_global_flags
decorator (group-level) and get_global_flags(ctx) reader. Mutually
exclusive --quiet/--verbose. Wired to root.py group; demonstrated on
'cache list' command (--json emits JSON list, --quiet emits IDs only).

Remaining 23 commands to be migrated incrementally; see assessment §4.7
for the roster.

Touches §3.2.4 CLI rule 3★ composability 0→≥1."
```

---

### Task 2.3: Error helper — cause + recovery + did-you-mean

**Files:**
- Create: `src/cli/_errors.py` (helper)
- Modify: `src/cli/root.py` (top-level exception handler)
- Create: `tests/cli/test_errors.py`

**為何:** §4.8 b4 — 錯誤訊息直暴 Python exception，無 cause + recovery 結構。加 wrapper 提供結構化錯誤 + did-you-mean (typo)。

- [ ] **Step 1: 寫 test**

新建 `tests/cli/test_errors.py`:

```python
"""Test error formatting and did-you-mean."""
import pytest

from src.cli._errors import format_error, suggest_command


def test_format_error_basic():
    msg = format_error(
        cause="Failed to connect to PCE",
        recovery="Check PCE_HOST in config.json and confirm network reachability.",
    )
    assert "Failed to connect to PCE" in msg
    assert "Try:" in msg
    assert "Check PCE_HOST" in msg


def test_format_error_with_did_you_mean():
    msg = format_error(
        cause="Unknown command 'lst'",
        recovery="Run 'illumio-ops --help' to see available commands.",
        did_you_mean="list",
    )
    assert "Did you mean: list?" in msg


def test_suggest_command_close_match():
    suggestion = suggest_command('lst', ['list', 'show', 'create'])
    assert suggestion == 'list'


def test_suggest_command_no_match():
    suggestion = suggest_command('xyzzy', ['list', 'show', 'create'])
    assert suggestion is None
```

- [ ] **Step 2: 跑測試 RED**

```bash
pytest tests/cli/test_errors.py -v 2>&1 | tail -10
```

預期: ImportError.

- [ ] **Step 3: 寫 helper**

新建 `src/cli/_errors.py`:

```python
"""Structured CLI error formatting + did-you-mean (typo suggestion).

Phase 1 quick win for b4. Wrap raw exceptions / usage errors with:
- clear cause statement
- actionable recovery hint
- optional 'Did you mean: <closest>?' for typos
"""
from __future__ import annotations

import difflib
import sys


def format_error(cause: str, recovery: str | None = None,
                 did_you_mean: str | None = None) -> str:
    """Format a structured error message.

    Layout:
        Error: <cause>
        Did you mean: <suggestion>?      (optional)
        Try: <recovery hint>             (optional)
    """
    lines = [f"Error: {cause}"]
    if did_you_mean:
        lines.append(f"Did you mean: {did_you_mean}?")
    if recovery:
        lines.append(f"Try: {recovery}")
    return "\n".join(lines)


def suggest_command(typed: str, candidates: list[str], cutoff: float = 0.6) -> str | None:
    """Return closest candidate to `typed`, or None if nothing close enough."""
    matches = difflib.get_close_matches(typed, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def print_error(cause: str, recovery: str | None = None,
                did_you_mean: str | None = None, exit_code: int = 1) -> None:
    """Print formatted error to stderr and exit with given code."""
    print(format_error(cause, recovery, did_you_mean), file=sys.stderr)
    sys.exit(exit_code)


def install_top_level_handler(app_name: str = "illumio-ops") -> None:
    """Wrap sys.excepthook so unhandled exceptions show structured error."""
    def handler(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.exit(130)
        cause = str(exc) or exc_type.__name__
        recovery = None
        if 'ConnectionError' in exc_type.__name__ or 'ConnectTimeout' in exc_type.__name__:
            recovery = f"Check network reachability and {app_name} config (PCE_HOST, PCE_PORT)."
        elif 'PermissionError' in exc_type.__name__:
            recovery = "Check file permissions for the path mentioned above."
        elif 'FileNotFoundError' in exc_type.__name__:
            recovery = "Verify the file path or run setup if this is the first run."
        else:
            recovery = "Re-run with --verbose for more detail."
        print(format_error(cause, recovery), file=sys.stderr)
        sys.exit(1)
    sys.excepthook = handler
```

- [ ] **Step 4: 跑測試 GREEN**

```bash
pytest tests/cli/test_errors.py -v 2>&1 | tail -10
```

預期: 4 passed.

- [ ] **Step 5: 接到 root.py**

Edit `src/cli/root.py` 在 entry 函式呼叫前:

```python
from src.cli._errors import install_top_level_handler

if __name__ == '__main__':
    install_top_level_handler()
    cli()
```

(若 root.py 結構不同，把 `install_top_level_handler()` 放在實際 main entry 前即可)

- [ ] **Step 6: Commit**

```bash
git add src/cli/_errors.py src/cli/root.py tests/cli/test_errors.py
git commit -m "feat(cli): structured error helper + did-you-mean (b4)

New module src/cli/_errors.py:
- format_error(cause, recovery, did_you_mean) — structured 3-line layout
- suggest_command(typed, candidates) — difflib.get_close_matches wrapper
- install_top_level_handler() — sys.excepthook wrapper with type-aware
  recovery hints (ConnectionError/PermissionError/FileNotFoundError)

Wired to root.py entry. Click's UsageError typo suggestions to be added
incrementally per command.

Touches §3.2.4 CLI rule 12 actionability 0→≥2."
```

---

## Batch 3 — Report quick wins (痛點 c1)

對應 §4.13 c1 (Report 摘要 / 長度)。

### Task 3.1: Per-report 200 字 standalone executive summary block

**Files:**
- Create: `src/report/exporters/_exec_summary.py`
- Modify: `src/report/exporters/audit_html_exporter.py`
- Modify: `src/report/exporters/policy_usage_html_exporter.py`
- Modify: `src/report/exporters/ven_html_exporter.py`
- Modify: `src/report/exporters/html_exporter.py` (traffic, if shares)
- Modify: `src/report/exporters/report_css.py`

**為何:** §4.13 c1 — 各 report 的 mod00 executive summary 已存在於 generator 層 (`results['mod00']`)，但 HTML 輸出未必在頂部呈現為 standalone 200 字塊。本 task 確保每份 report 的 `<body>` 開頭即為一個 `<section class="exec-summary">` 含人類可讀 200 字摘要。

**安全注意：** mod00 內容可能含 user-influenced data (e.g., rule names from PCE)。helper 用 `html.escape` 處理所有插入值。

- [ ] **Step 1: 確認 mod00 的 shape**

```bash
cd /home/harry/rd/illumio-ops
python3 -c "
from src.report.analysis.audit.audit_mod00_executive import audit_executive_summary
import inspect
print(inspect.signature(audit_executive_summary))
print(inspect.getdoc(audit_executive_summary) or '(no docstring)')
"
ls src/report/analysis/ven_status/ 2>/dev/null
```

讀 mod00 各檔，找其輸出 dict 的 keys (kpis / verdict / summary_text / etc)。

- [ ] **Step 2: 加 helper renderer (用 html.escape, 無 raw HTML 拼接 user 內容)**

新建 `src/report/exporters/_exec_summary.py`:

```python
"""Render a 200-word standalone executive summary block.

Phase 1 quick win for c1. All user-influenced values escape via html.escape.
"""
from __future__ import annotations

from html import escape


def render_exec_summary_html(mod00: dict, report_name: str) -> str:
    """Return an <section> HTML block for the report header.

    mod00 is the executive-summary dict produced by analysis.{report}_mod00.
    Output target: ≤200 words, standalone (no need to read further sections).
    All inserted values are escape()-ed.
    """
    if not mod00:
        return ''
    kpis = mod00.get('kpis', []) or []
    verdict = mod00.get('verdict') or mod00.get('overall_status') or ''
    summary_text = mod00.get('summary_text') or mod00.get('exec_summary') or ''
    notes = mod00.get('execution_notes', []) or []

    # KPI strip (escape both label and value)
    kpi_html = ''
    if kpis:
        items = []
        for k in kpis[:6]:
            label = escape(str(k.get('label', '')))
            value = escape(str(k.get('value', '')))
            items.append(
                f'<div class="kpi"><span class="kpi-label">{label}</span>'
                f'<span class="kpi-value">{value}</span></div>'
            )
        kpi_html = f'<div class="kpi-strip">{"".join(items)}</div>'

    verdict_html = f'<p class="verdict">{escape(str(verdict))}</p>' if verdict else ''
    summary_html = f'<p class="summary-text">{escape(str(summary_text))}</p>' if summary_text else ''

    notes_html = ''
    if notes:
        items = ''.join(f'<li>{escape(str(n))}</li>' for n in notes[:2])
        notes_html = f'<ul class="notes">{items}</ul>'

    return (
        f'<section class="exec-summary" aria-labelledby="exec-summary-title">'
        f'<h2 id="exec-summary-title">Executive Summary — {escape(report_name)}</h2>'
        f'{verdict_html}{kpi_html}{summary_html}{notes_html}'
        f'</section>'
    )
```

- [ ] **Step 3: 加 CSS for exec-summary block**

在 `src/report/exporters/report_css.py` 加：

```python
EXEC_SUMMARY_CSS = """
.exec-summary {
  border: 2px solid var(--color-signal-info, #0077CC);
  border-radius: 8px;
  padding: 24px;
  margin: 0 0 32px 0;
  background: rgba(0,119,204,0.04);
}
.exec-summary h2 {
  margin-top: 0;
  font-size: 1.4rem;
  color: var(--color-signal-info, #0077CC);
}
.exec-summary .verdict { font-weight: 600; font-size: 1.1rem; }
.exec-summary .kpi-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 12px;
  margin: 16px 0;
}
.exec-summary .kpi { display: flex; flex-direction: column; align-items: flex-start; }
.exec-summary .kpi-label { font-size: 0.85rem; color: var(--color-text-secondary, #6F7274); }
.exec-summary .kpi-value {
  font-size: 1.6rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.exec-summary .summary-text { margin: 12px 0; line-height: 1.6; }
.exec-summary .notes { margin: 12px 0 0 20px; color: var(--color-text-secondary, #6F7274); }
"""
# Append EXEC_SUMMARY_CSS to existing CSS bundle (find the export point)
```

(具體拼接點依 report_css.py 結構)

- [ ] **Step 4: 嵌入到各 HTML exporter**

對 audit / policy_usage / ven_status / traffic 4 份 HTML exporter，找 `<body>` 開頭：

```python
# in audit_html_exporter.py (or base):
from src.report.exporters._exec_summary import render_exec_summary_html

# In the body-building section:
mod00 = result.module_results.get('mod00', {})
exec_html = render_exec_summary_html(mod00, report_name='Audit')
body_html = exec_html + body_html  # prepend
```

(找 `mod00 = result.module_results.get('mod00'`-style line per A.6 inventory)

- [ ] **Step 5: 視覺/文字驗證**

```bash
cd /home/harry/rd/illumio-ops
grep -rnE 'render_exec_summary_html' src/report/ | wc -l
# 預期: 4+ 命中 (1 helper + 4 exporter)
grep -cE 'EXEC_SUMMARY_CSS' src/report/exporters/report_css.py
# 預期: 1+
```

(若有 dev 環境可跑 sample report 並 grep `<section class="exec-summary"`，最佳)

- [ ] **Step 6: Commit**

```bash
git add src/report/exporters/_exec_summary.py src/report/exporters/audit_html_exporter.py src/report/exporters/policy_usage_html_exporter.py src/report/exporters/ven_html_exporter.py src/report/exporters/html_exporter.py src/report/exporters/report_css.py
git commit -m "feat(report): standalone exec summary block at top of each report (c1)

New helper render_exec_summary_html() reads mod00 (executive summary
already produced by generators) and renders a <section class='exec-summary'>
block prepended to each report body. Block contains: verdict line, ≤6
KPI strip, mod00 summary_text, top 2 execution notes — designed to stay
under 200 words and be standalone (P5 manager can read just this).

All inserted values escape via html.escape (defense in depth — KPI
labels can carry rule/scope names from PCE).

CSS added to report_css.py with verdict color band + KPI grid +
tabular-nums for KPI values.

Applied to 4 reports: audit / policy_usage / ven_status / traffic.

Touches §3.3.2 c1 length/summary; addresses Phase 1 §3.3.6 推薦."
```

---

### Task 3.2: 跨報告 sidebar nav

**Files:**
- Create: `src/report/exporters/_sidebar.py`
- Modify: 4 HTML exporters
- Modify: `src/report/exporters/report_css.py`

**為何:** §3.3.6 — 三/四份報告各自獨立，無相互連結 → 主管切換要重新 navigate。加 sidebar 列出 sibling reports + 當前報告高亮。

- [ ] **Step 1: 加 helper**

新建 `src/report/exporters/_sidebar.py`:

```python
"""Render a sidebar with cross-report navigation.

Phase 1 quick win for c1. Static label set, no user input — but escape
report_name through html.escape as defense in depth.
"""
from __future__ import annotations

from html import escape


REPORTS = [
    ('audit', 'Audit Report', 'audit_report.html'),
    ('policy_usage', 'Policy Usage Report', 'policy_usage_report.html'),
    ('ven_status', 'VEN Status Report', 'ven_status_report.html'),
    ('traffic', 'Traffic Report', 'traffic_report.html'),
]


def render_sidebar_html(current: str) -> str:
    """Return an <aside> HTML block listing sibling reports."""
    items = []
    for key, label, href in REPORTS:
        label_html = escape(label)
        href_html = escape(href, quote=True)
        if key == current:
            items.append(f'<li class="current" aria-current="page">{label_html}</li>')
        else:
            items.append(f'<li><a href="{href_html}">{label_html}</a></li>')
    return (
        f'<aside class="report-sidebar" aria-label="Report navigation">'
        f'<h3>Reports</h3><ul>{"".join(items)}</ul></aside>'
    )
```

- [ ] **Step 2: 加 CSS**

在 `src/report/exporters/report_css.py` 加：

```python
SIDEBAR_CSS = """
.report-sidebar {
  position: sticky;
  top: 16px;
  float: right;
  width: 200px;
  margin-left: 24px;
  padding: 16px;
  border: 1px solid var(--color-border, #D6D7D7);
  border-radius: 6px;
  background: var(--color-surface, #FFFFFF);
  font-size: 0.9rem;
}
.report-sidebar h3 { margin: 0 0 12px; font-size: 1rem; }
.report-sidebar ul { list-style: none; padding: 0; margin: 0; }
.report-sidebar li { margin: 6px 0; }
.report-sidebar li.current {
  font-weight: 600;
  color: var(--color-signal-info, #0077CC);
  border-left: 3px solid currentColor;
  padding-left: 8px;
}
.report-sidebar a { color: var(--color-text-primary, #313638); text-decoration: none; }
.report-sidebar a:hover { text-decoration: underline; }

@media print { .report-sidebar { display: none; } }
"""
```

- [ ] **Step 3: 嵌入 4 exporters**

對每個 HTML exporter，在 body content 開始時插入：

```python
from src.report.exporters._sidebar import render_sidebar_html
sidebar_html = render_sidebar_html('audit')  # or 'policy_usage' / 'ven_status' / 'traffic'
body_html = sidebar_html + body_html
```

- [ ] **Step 4: Commit**

```bash
git add src/report/exporters/_sidebar.py src/report/exporters/report_css.py src/report/exporters/audit_html_exporter.py src/report/exporters/policy_usage_html_exporter.py src/report/exporters/ven_html_exporter.py src/report/exporters/html_exporter.py
git commit -m "feat(report): cross-report sidebar nav (c1)

Adds .report-sidebar aside listing sibling reports (audit/policy_usage/
ven_status/traffic) with current page highlighted. Helps P5 managers
navigate between reports without leaving the browser tab.

Hidden in @media print (PDF export not affected).

Touches §3.3.6 推薦 — 跨報告連結 from absent to present."
```

---

### Task 3.3: VEN 餅圖標籤 i18n key 化

**Files:**
- Modify: `src/report/chart_renderer.py` 或對應 VEN pie chart 渲染處
- Modify: `src/i18n_en.json` + `src/i18n_zh_TW.json`

**為何:** §C.4 finding — VEN 餅圖標籤 hardcoded 英文，繞過 i18n，zh_TW 翻譯不到。

- [ ] **Step 1: 找 hardcoded 英文位置**

```bash
cd /home/harry/rd/illumio-ops
grep -rnE 'Online|Offline|Lost|Unmanaged' src/report/chart_renderer.py src/report/ven*.py 2>/dev/null | head -10
```

定位 hardcoded 字串 (e.g., `labels=['Online', 'Offline', 'Lost']`).

- [ ] **Step 2: 改成 t() i18n call**

```python
# Before:
labels = ['Online', 'Offline', 'Lost']
# After:
from src.i18n import t
labels = [t('chart_ven_online'), t('chart_ven_offline'), t('chart_ven_lost')]
```

- [ ] **Step 3: 加 i18n keys**

在 `src/i18n_en.json` 加:
```json
"chart_ven_online": "Online",
"chart_ven_offline": "Offline",
"chart_ven_lost": "Lost"
```

在 `src/i18n_zh_TW.json` 加（依 OQ-10 留英策略 — VEN status 是 Illumio 術語）:
```json
"chart_ven_online": "Online",
"chart_ven_offline": "Offline",
"chart_ven_lost": "Lost"
```

(注: zh_TW 仍保留英文 per OQ-10. 此 task 的目的是「過 i18n 系統」，避免 hardcoded — 未來改翻譯只動 JSON 不動 code)

- [ ] **Step 4: Verify**

```bash
grep -rnE 'chart_ven_online|chart_ven_offline|chart_ven_lost' src/i18n_en.json src/i18n_zh_TW.json src/report/ | wc -l
# 預期: ≥4 命中 (2 i18n files + 1+ usage)
```

- [ ] **Step 5: Commit**

```bash
git add src/report/chart_renderer.py src/i18n_en.json src/i18n_zh_TW.json
git commit -m "fix(report): route VEN pie chart labels through i18n (c1/c3)

Per assessment §C.4: VEN pie chart labels (Online/Offline/Lost) were
hardcoded English in chart_renderer, bypassing i18n. Now routed through
t() with new keys chart_ven_online/_offline/_lost.

zh_TW values intentionally retained as English per OQ-10 (Illumio terms
留英 strategy) — but routing through i18n means future relabeling
touches JSON, not code."
```

---

## Batch 4 — Email quick wins (痛點 d2, d3)

對應 §4.15 d2 (cross-client) + §4.16 d3 (actionability)。

### Task 4.1: Subject pattern with severity + object

**Files:**
- Modify: `src/i18n_en.json` + `src/i18n_zh_TW.json` (add structured subject keys)
- Modify: `src/reporter.py` line ~540 (subject build site)

**為何:** §C.7 — 目前 subject = "Illumio PCE Ops Alert (N issue(s))" — 無 severity / 無 object，inbox 排序失效。改成 `[<severity>] <object>: <action>` pattern.

- [ ] **Step 1: 加 i18n keys**

在 `src/i18n_en.json` 加:
```json
"mail_subject_structured": "[{severity}] {object}: {action}",
"mail_severity_critical": "CRITICAL",
"mail_severity_warning": "WARNING",
"mail_severity_info": "INFO",
"mail_object_default": "PCE Ops",
"mail_action_default": "alert"
```

`src/i18n_zh_TW.json` 同 (per OQ-10 severity 留英)。

- [ ] **Step 2: 改 reporter.py 主旨組裝**

Read `src/reporter.py` 找 `mail_subject` template 使用點 (line ~540)。

```python
# Before:
subject = t("mail_subject", count=total_issues)

# After:
def _highest_severity(issues):
    """Pick highest severity from a list of issues; defaults to 'info'."""
    levels = {'critical': 3, 'warning': 2, 'info': 1}
    cur = 0
    out = 'info'
    for i in issues:
        sev = (i.get('severity') or 'info').lower()
        if levels.get(sev, 0) > cur:
            cur = levels[sev]
            out = sev
    return out

if total_issues > 0 and not test_mode:
    sev = _highest_severity(issues_list)
    sev_label = t(f'mail_severity_{sev}')
    primary = issues_list[0] if issues_list else {}
    obj = primary.get('object') or primary.get('source') or t('mail_object_default')
    action = primary.get('summary') or t('mail_action_default')
    subject = t('mail_subject_structured', severity=sev_label, object=obj, action=action)
else:
    subject = t("mail_subject_test") if test_mode else t("mail_subject", count=total_issues)
```

(具體變數名依 reporter.py 上下文；如 issues_list 不存在於該 scope，往上溯找 dispatch site)

- [ ] **Step 3: Verify**

```bash
cd /home/harry/rd/illumio-ops
grep -nE 'mail_subject_structured|_highest_severity' src/reporter.py src/i18n_en.json src/i18n_zh_TW.json | head -10
```

- [ ] **Step 4: Commit**

```bash
git add src/reporter.py src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(email): structured subject pattern [severity] object: action (d3)

Per assessment §C.7 / §4.16: subject 'Illumio PCE Ops Alert (N issue(s))'
lacks severity and object — inbox sorting fails. New pattern:
[CRITICAL|WARNING|INFO] <object>: <action> via mail_subject_structured
i18n key, picks highest severity from issue list.

Falls back to existing mail_subject for empty / test cases.

Touches §3.4.4 actionability subject 0→1."
```

---

### Task 4.2: Hidden preheader 50-90 chars

**Files:**
- Modify: `src/alerts/templates/mail_wrapper.html.tmpl` (insert preheader at top)
- Modify: `src/reporter.py` `_build_mail_html()` (pass preheader var)

**為何:** §C.7 — preheader 完全缺席，inbox 預覽顯示 "Official Alert Notification" (無資訊)。加 hidden div 50-90 字 standalone 摘要。

**安全注意：** preheader 內容來自 issue summary (PCE 來源)。reporter 端用 `html.escape` 處理後傳入 string.Template。

- [ ] **Step 1: 加 preheader 區塊到 mail_wrapper**

Read `src/alerts/templates/mail_wrapper.html.tmpl` 找 `<body>` 開頭。在第一個元素之前插入:

```html
<div style="display:none;font-size:1px;color:#fff;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">$preheader</div>
```

(string.Template 用 `$varname` 而非 Jinja `{{ }}`)

- [ ] **Step 2: 在 _build_mail_html 帶 preheader 變數 (帶 escape)**

Read `src/reporter.py` 找 `_build_mail_html`。加 helper:

```python
import html

def _build_preheader_text(self, issues_list, max_chars=90):
    """Build a 50-90 char standalone preview shown in inbox.

    Picks first 1-2 issues and joins their summaries; truncates with
    ellipsis if over budget. HTML-escapes the result before returning
    so it's safe to interpolate into the template via string.Template.
    """
    if not issues_list:
        return ''
    parts = []
    for i in issues_list[:2]:
        s = i.get('summary') or i.get('title') or ''
        if s:
            parts.append(s)
    text = ' • '.join(parts)
    if len(text) > max_chars:
        text = text[:max_chars - 1].rsplit(' ', 1)[0] + '…'
    return html.escape(text)
```

在 render_alert_template 呼叫處傳 preheader:

```python
preheader = self._build_preheader_text(issues_list)
ctx = {
    # ... existing keys
    'preheader': preheader,
}
```

- [ ] **Step 3: Verify**

```bash
grep -E 'preheader|\$preheader' src/alerts/templates/mail_wrapper.html.tmpl
grep -nE '_build_preheader_text|preheader' src/reporter.py | head -10
```

- [ ] **Step 4: Commit**

```bash
git add src/alerts/templates/mail_wrapper.html.tmpl src/reporter.py
git commit -m "feat(email): hidden preheader 50-90 chars (d3)

Per assessment §C.7 / §4.16: preheader was missing, inbox previews
showed 'Official Alert Notification' (no info). Adds hidden div with
issue summaries at top of mail_wrapper template + _build_preheader_text
helper that picks 1-2 top issues and truncates to 90 chars.

Helper escapes via html.escape before interpolation — issue summaries
from PCE could contain HTML chars.

Touches §3.4.4 actionability preheader 0→1."
```

---

### Task 4.3: Table layout for mail_wrapper (Outlook compat)

**Files:**
- Modify: `src/alerts/templates/mail_wrapper.html.tmpl` (div+flex → table)

**為何:** §C.6 — 全 div 結構 + display:flex 在 Outlook 會塌陷。改成 `<table role="presentation">` 結構。

- [ ] **Step 1: 重寫 mail_wrapper 為 table-based**

Read 現有 `src/alerts/templates/mail_wrapper.html.tmpl`，把外層結構改：

```html
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="color-scheme" content="light dark" />
  <meta name="supported-color-schemes" content="light dark" />
  <title>$title</title>
</head>
<body style="margin:0;padding:0;background:#F4F4F4;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen-Sans,Ubuntu,Cantarell,'Helvetica Neue',Arial,sans-serif;">
  <div style="display:none;font-size:1px;color:#F4F4F4;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">$preheader</div>
  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background:#F4F4F4;">
    <tr>
      <td align="center" style="padding:24px 12px;">
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="600" style="max-width:600px;background:#FFFFFF;border-radius:8px;">
          <tr>
            <td style="padding:24px;color:#313638;">
              <h1 style="margin:0 0 16px;font-size:20px;color:#313638;">$title</h1>
              $body_html
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
```

(具體保留現有的 placeholder 變數 — `$title`, `$body_html`, `$preheader`)

- [ ] **Step 2: 確保渲染端 (reporter.py) 仍提供同名變數**

```bash
cd /home/harry/rd/illumio-ops
grep -nE '_build_mail_html|render_alert_template.*mail_wrapper' src/reporter.py src/alerts/template_utils.py | head -10
```

確認傳給 string.Template 的 dict 包含 `title`, `body_html`, `preheader`. 若缺 default 值，加上。

- [ ] **Step 3: Verify**

```bash
grep -cE '<table role="presentation"' src/alerts/templates/mail_wrapper.html.tmpl
# 預期: ≥1
grep -E 'display:flex' src/alerts/templates/mail_wrapper.html.tmpl
# 預期: 無命中
```

- [ ] **Step 4: Commit**

```bash
git add src/alerts/templates/mail_wrapper.html.tmpl
git commit -m "fix(email): replace div+flex layout with <table> (d2)

Per assessment §C.6: Outlook (Win/Mac/365) collapses display:flex
because Word HTML engine doesn't support it. Rewrites mail_wrapper
with <table role='presentation'> bulletproof layout + 600px max
container — works in Outlook 2007+ / Gmail / Apple Mail / Thunderbird.

Adds <meta name='color-scheme' content='light dark'> for dark mode.

Touches §3.4.2 cross-client 2/8 → 4/8 (table-based + dark-mode meta)."
```

---

### Task 4.4: multipart/alternative + line_digest.txt fallback

**Files:**
- Modify: `src/alerts/plugins.py` (line 28: MIMEMultipart → MIMEMultipart('alternative'); attach .txt)
- Modify: `src/reporter.py` (新增 _build_mail_plain helper)

**為何:** §C.6 — `MIMEMultipart()` 預設 'mixed', 需 'alternative' 讓 client 自選 plain/html。`line_digest.txt.tmpl` 已存在但未被 attach。

- [ ] **Step 1: 改 MailPlugin.send**

Read `src/alerts/plugins.py` 的 MailPlugin.send method (line ~21-32):

```python
# Before:
msg = MIMEMultipart()
msg["From"] = ...
msg["To"] = ...
msg["Subject"] = subject
msg.attach(MIMEText(body, "html"))

# After:
msg = MIMEMultipart('alternative')
msg["From"] = ...
msg["To"] = ...
msg["Subject"] = subject
# Plain text fallback FIRST (RFC 2046: client picks last that it can render)
plain_body = reporter._build_mail_plain(subject)
msg.attach(MIMEText(plain_body, "plain", _charset='utf-8'))
msg.attach(MIMEText(body, "html", _charset='utf-8'))
```

- [ ] **Step 2: 加 _build_mail_plain helper to reporter.py**

```python
def _build_mail_plain(self, subject: str) -> str:
    """Render a plain-text version of the alert email using line_digest.txt.tmpl.

    Reuses the existing _build_line_message ctx (or its renderable subset)
    to keep parity with LINE channel.
    """
    return self._build_line_message(subject)
```

(對齊現有 `_build_line_message` 的 ctx — 如果 line_digest 已用於 LINE channel，直接 reuse 該函式即可)

- [ ] **Step 3: Verify**

```bash
grep -nE "MIMEMultipart\('alternative'\)|_build_mail_plain" src/alerts/plugins.py src/reporter.py | head -5
```

- [ ] **Step 4: Commit**

```bash
git add src/alerts/plugins.py src/reporter.py
git commit -m "fix(email): add multipart/alternative with text fallback (d2)

Per assessment §C.6: MIMEMultipart() defaults to 'mixed', not
'alternative' — clients can't pick plain/html. Also line_digest.txt.tmpl
existed but was never attached. Now:
- MIMEMultipart('alternative')
- Plain text part attached BEFORE HTML (RFC 2046 ordering)
- _build_mail_plain() helper renders line_digest.txt.tmpl content

Pure text clients (terminal mail readers, accessibility tools) now
receive a usable alert.

Touches §3.4.2 cross-client → +1 to /8 (multipart fallback)."
```

---

### Task 4.5: CTA 補到所有 alert 區段

**Files:**
- Modify: `src/reporter.py` `_build_mail_html` 各 alert 區段組裝處
- Modify: `src/i18n_en.json` + `src/i18n_zh_TW.json`

**為何:** §C.7 — CTA "View on PCE" 僅在 event 區段；health/traffic/metric 全無。每個區段補一個 deep-link CTA，帶參數導向對應 GUI 頁面。

**安全注意：** label 與 url 用 `html.escape`/`urllib.parse.quote_plus` 處理；尤其 url 內 query string 若帶動態 id 必須 quote_plus。

- [ ] **Step 1: 加 _render_cta helper**

加到 `src/reporter.py`:

```python
import html
from urllib.parse import quote_plus, urlencode

def _render_cta(self, label: str, url: str) -> str:
    """Render a bulletproof CTA button.

    Uses table-based bulletproof button pattern (Outlook-safe).
    label is html.escape-d; url is escaped via html.escape with quote=True.
    Caller is responsible for urlencoding query string parameters.
    """
    label_html = html.escape(label)
    url_html = html.escape(url, quote=True)
    return (
        f'<table role="presentation" border="0" cellpadding="0" cellspacing="0" '
        f'style="margin:16px 0;">'
        f'<tr><td bgcolor="#0077CC" style="border-radius:4px;">'
        f'<a href="{url_html}" '
        f'style="display:inline-block;padding:10px 20px;color:#FFFFFF;'
        f'text-decoration:none;font-weight:600;">{label_html}</a>'
        f'</td></tr></table>'
    )
```

- [ ] **Step 2: 套用到各 alert 區段**

找 `_build_mail_html` 中每個 alert section 的組裝處 (health / traffic / metric / event)。為每個加一行 CTA：

```python
gui_base = self._gui_base_url()  # e.g., from config; assume ends without trailing /
# health section:
section_html += self._render_cta(
    label=t('mail_cta_view_health'),
    url=f'{gui_base}/dashboard?tab=health'
)
# traffic section:
section_html += self._render_cta(
    label=t('mail_cta_view_traffic'),
    url=f'{gui_base}/traffic'
)
# metric section: similar
# event section: keep existing if present, harmonize style; if event id is dynamic:
event_id = quote_plus(str(event.get('id', '')))
section_html += self._render_cta(
    label=t('mail_cta_view_event'),
    url=f'{gui_base}/events?id={event_id}'
)
```

加 i18n keys:
```json
"mail_cta_view_health": "View Health Dashboard →",
"mail_cta_view_traffic": "View Traffic Report →",
"mail_cta_view_metric": "View Metrics →",
"mail_cta_view_event": "View Event Detail →"
```

- [ ] **Step 3: Verify**

```bash
grep -cE '_render_cta|mail_cta_view_' src/reporter.py src/i18n_en.json src/i18n_zh_TW.json
```

- [ ] **Step 4: Commit**

```bash
git add src/reporter.py src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(email): bulletproof CTA on every alert section (d3)

Per assessment §C.7: CTA 'View on PCE' only existed in event section;
health/traffic/metric had no actionable links. Adds _render_cta()
helper using bulletproof table-based button (Outlook-safe), applied
to all 4 alert sections with deep links carrying tab/route parameters.

Helper escapes label/url via html.escape; dynamic ids in query strings
must be quote_plus()-d at call site.

New i18n keys: mail_cta_view_{health,traffic,metric,event}.

Touches §3.4.4 actionability CTA 0→1; §3.4.2 bulletproof CTA +1/8."
```

---

## Self-review checklist

執行完所有 Task 後驗證：

### Batch 1 (GUI)
- [ ] `grep -cE '<script defer src' src/templates/index.html` = 13
- [ ] `grep -cE 'rel="preload"' src/templates/index.html` ≥ 1
- [ ] `grep -cE '\.skeleton\b' src/static/css/app.css` ≥ 1
- [ ] `grep -cE 'window\.debounce|window\.setFieldError' src/static/js/utils.js` ≥ 2
- [ ] `grep -cE 'innerHTML\s*=' src/static/js/{tabs,utils}.js` = 0 (新增 helper 無 innerHTML)
- [ ] (manual) login + dashboard 仍可載入無 JS error

### Batch 2 (CLI)
- [ ] `grep -cE 'NO_COLOR' src/cli/_render.py` ≥ 1
- [ ] `pytest tests/cli/test_render_tty.py tests/cli/test_global_flags.py tests/cli/test_errors.py -v` → 10 passed
- [ ] `illumio-ops --json cache list` (若可跑) → 輸出 JSON

### Batch 3 (Report)
- [ ] `grep -rcE 'render_exec_summary_html|render_sidebar_html' src/report/exporters/` ≥ 8 (4 exporters × 2 helpers)
- [ ] `grep -cE 'chart_ven_online' src/i18n_en.json` ≥ 1
- [ ] helper 用 `html.escape` (grep `from html import escape` ≥ 2)

### Batch 4 (Email)
- [ ] `grep -E '<table role="presentation"' src/alerts/templates/mail_wrapper.html.tmpl` 命中
- [ ] `grep -E 'preheader' src/alerts/templates/mail_wrapper.html.tmpl` 命中
- [ ] `grep -nE "MIMEMultipart\('alternative'\)" src/alerts/plugins.py` 命中
- [ ] `grep -cE 'mail_cta_view_' src/i18n_en.json` ≥ 4

---

## §12 後續 (Phase 2 入口)

本 plan 完成後可解鎖 Phase 2 並行執行:

- **Track A — Visual System**: 套用 §6.1 B industrial-editorial direction (Space Grotesk + Inter + JetBrains Mono); 替換現有 Montserrat-only typography; 共用到 GUI / Report / Email subset (D.3 signal token)
- **Track B — CLI Output Layer**: 把 Task 2.2 的 _global_flags 推廣到全 24 個命令; 把 Task 2.3 的 error helper 拓展為完整 error/warning/notice 分流; 統一 exit code map (sysexits.h)

每個 Track 開新 plan，引用本 plan 的 helper modules (`_global_flags.py`, `_errors.py`, `_exec_summary.py`, `_sidebar.py`) 為起點。

---

## Self-review of this plan

- ✅ Goal/Architecture/Tech Stack header 完整
- ✅ Reference docs 列出 (assessment 報告 + 痛點卡 anchor)
- ✅ 4 batch × 16 task 結構清晰，task 互相獨立
- ✅ 每 task 有 file paths + 完整 code (無 placeholder)
- ✅ TDD 模式套用於有 test affordance 的 task (2.1/2.2/2.3)
- ✅ 非 TDD task 有 grep / wc 驗證 step
- ✅ 安全約束: 所有 DOM 操作禁 innerHTML; helper 用 textContent / createElement; 報告/Email helper 用 html.escape
- ⚠️ 部分 task 涉及 dev server / sample report 視覺驗證；plan 已給 grep / pytest fallback 不依賴 live env
- ⚠️ Task 1.5 / 2.2 / 4.5 採「示範 1-2 個套用點 + 增量補齊」策略，避免單次 commit 動 162 input / 24 命令

預計執行時間（subagent-driven 模式）:
- Batch 1: ~3-4 hours (5 tasks)
- Batch 2: ~2-3 hours (3 tasks, 2.1+2.2 合併)
- Batch 3: ~2-3 hours (3 tasks)
- Batch 4: ~3-4 hours (5 tasks)
- 總計: ~10-14 hours subagent time
