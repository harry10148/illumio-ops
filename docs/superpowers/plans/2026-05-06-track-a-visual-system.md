# Track A — Visual System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 套用 §6.1 B (industrial-editorial) GUI direction + §6.2 B (editorial-magazine) Report direction，引入 Space Grotesk + Inter + JetBrains Mono 三字族 self-host，並將 D.3 共享 signal token (success/warning/danger/info) 落地到 GUI/Report/Email subset，把現有「品牌色 OK 但 Distinctiveness=1」的視覺體質升級到 ≥2。

**Architecture:** 採「parallel token layer + 漸進切換」策略，避免一次大改造成 visual regression：
1. 新增 vendor fonts (~280 KB total, self-host woff2 變體字型)
2. 新增 `--font-heading-2` / `--font-body-2` / `--font-mono-2` token 與 `--color-signal-*` token，**不立即覆蓋**現有 token
3. 各 task 以 1 個 component class（卡片 / 表單 / 表格 / chart legend / report KPI）為單位切換
4. 全部切換完成後把新 token rename 為主 token，移除舊 alias
5. Report (HTML+PDF) 與 Email subset 共用 D.3 signal token

**Tech Stack:** Vanilla CSS (無 build pipeline)；@font-face 變體字型；CSS custom properties；現有 chart_renderer.py / report_css.py / mail_wrapper.html.tmpl 直接修改。

**Reference docs:**
- 評估報告 §6.1 GUI direction Adopted Spec Sheet (industrial-editorial B)
- §6.2 Report+Email direction Adopted Spec Sheet (editorial-magazine B)
- §6.3 共享 signal token 表
- §3.1.3 GUI VI 現況 (12/18, Distinctiveness=1)
- §3.3.3 Report VI 現況 (HTML 12/18, PDF 6/15)

**Touch radius:** 中。涉及檔案：
- `src/static/fonts/` (+3 woff2 files)
- `src/static/css/app.css` (新 token + 漸進切換 selector)
- `src/report/exporters/report_css.py` (parallel updates)
- `src/report/chart_renderer.py` (signal palette)
- `src/alerts/templates/mail_wrapper.html.tmpl` (email subset)
- 各 HTML template 視需要 (login.html 先做示範)

**Hard constraints:**
- C1 offline: 所有字型 self-host (與 Phase 0 a7 修補一致策略)
- 不破現有 functional UI (regression test: 現有 pytest 全綠)
- prefers-reduced-motion 與 prefers-color-scheme 兼容
- WCAG AA 對比度 (text/bg ≥ 4.5:1, large text ≥ 3:1)

**驗收 (整 plan):**
- 評估報告 §3.1.3 Typography 2→3, Distinctiveness 1→2
- §3.3.3 Report HTML 12/18→≥15, PDF 6/15→≥9 (cover/footer/divider)
- §6.3 4 個 signal token (success #2D9B5E / warning #C47A00 / danger #D93025 / info #0077CC) 在 GUI / Report / Email 皆可用
- vendor fonts 增量 ~280 KB compressed (offline bundle 可接受)
- pytest existing tests 100% pass

**Commit / branch 策略：** 全 plan 在單一分支 `plan/track-a-visual-system-2026-05-06` 上 task-by-task 進行，每 task 1-2 commit。每 batch 結束可獨立 PR。建議 PR 兩階段：
- PR1: Task 1-3 (vendor fonts + parallel token layer + login.html demo) — 視覺零變化, 安全 ship
- PR2: Task 4-8 (component 切換 + chart + report + email) — 視覺變化, 需 stakeholder 確認

---

## Task 1: Vendor 3 個變體字型 woff2

**Goal:** 取得 Space Grotesk (heading)、Inter (body)、JetBrains Mono (mono) 變體字型 woff2，self-host 於 `src/static/fonts/`，總大小目標 < 280 KB compressed。

**Files:**
- Create: `src/static/fonts/SpaceGrotesk-VF.woff2` (~50 KB)
- Create: `src/static/fonts/Inter-VF.woff2` (~120 KB)
- Create: `src/static/fonts/JetBrainsMono-VF.woff2` (~80 KB)
- Create: `docs/fonts-vendoring.md` (簡短說明取得來源 + license)

- [ ] **Step 1: 取得 woff2 (擇一路徑)**

**A) npm @fontsource-variable (有 npm + internet)**

```bash
cd /tmp
mkdir -p font-vendor && cd font-vendor
for pkg in space-grotesk inter jetbrains-mono; do
  npm pack @fontsource-variable/$pkg
  tar xzf fontsource-variable-$pkg-*.tgz
  ls package/files/ | grep -E '\.woff2$' | head -3
done
```

從 `package/files/` 找 latin (or latin-ext) variable woff2 (檔名通常含 `wght-normal`).

**B) GitHub release 手動下載 (無 npm)**

- Space Grotesk: https://github.com/floriankarsten/space-grotesk/raw/master/fonts/webfonts/SpaceGrotesk%5Bwght%5D.woff2
- Inter: https://github.com/rsms/inter/releases/download/v4.0/Inter-4.0.zip → 解壓 `Inter-Variable.woff2`
- JetBrains Mono: https://github.com/JetBrains/JetBrainsMono/releases/latest/download/JetBrainsMono-2.304.zip → 解壓 `webfonts/JetBrainsMono[wght].woff2`

下載後驗證大小：
```bash
ls -la /tmp/font-vendor/*.woff2
# 預期: SpaceGrotesk ~50KB, Inter ~120KB, JetBrainsMono ~80KB (各 ±20%)
```

- [ ] **Step 2: 用 fontTools 確認變體字型**

```bash
cd /home/harry/rd/illumio-ops
PYTHONPATH=$(pwd)/venv/lib/python3.12/site-packages python3 -c "
from fontTools.ttLib import TTFont
for f in ['/tmp/font-vendor/SpaceGrotesk-VF.woff2',
          '/tmp/font-vendor/Inter-VF.woff2',
          '/tmp/font-vendor/JetBrainsMono-VF.woff2']:
    t = TTFont(f)
    print(f, 'fvar:', 'fvar' in t)
    if 'fvar' in t:
        for a in t['fvar'].axes:
            print(f'  {a.axisTag}: {a.minValue}-{a.maxValue}')
"
```

預期: 三個都 `fvar: True`，wght 至少涵蓋 400-700。

(若取得的不是變體字型，可接受 — 但需在 @font-face 宣告改成 single weight 而非 range。在 Step 4 註明。)

- [ ] **Step 3: 複製到 src/static/fonts/**

```bash
cp /tmp/font-vendor/SpaceGrotesk-VF.woff2 src/static/fonts/
cp /tmp/font-vendor/Inter-VF.woff2 src/static/fonts/
cp /tmp/font-vendor/JetBrainsMono-VF.woff2 src/static/fonts/
ls -la src/static/fonts/
# 確認 3 個新檔加上既有 Montserrat-latin.woff2 + NotoSansCJKtc-Regular.otf
du -sh src/static/fonts/
```

- [ ] **Step 4: 寫 docs/fonts-vendoring.md**

```markdown
# Font Vendoring

All web fonts are self-hosted to satisfy C1 (offline bundle) and avoid CSP/CDN issues.

## Current fonts

| File | License | Source | Size | Used by |
|---|---|---|---|---|
| NotoSansCJKtc-Regular.otf | OFL | https://github.com/notofonts/noto-cjk | 15.7 MB | CJK fallback (PDF, GUI when CJK glyphs needed) |
| Montserrat-latin.woff2 | OFL | https://github.com/JulietaUla/Montserrat | 37 KB | Legacy GUI/email — superseded by Space Grotesk + Inter (Track A migration in progress) |
| SpaceGrotesk-VF.woff2 | OFL | https://github.com/floriankarsten/space-grotesk | ~50 KB | GUI heading (post Track A) |
| Inter-VF.woff2 | OFL | https://github.com/rsms/inter | ~120 KB | GUI body (post Track A); Report body |
| JetBrainsMono-VF.woff2 | OFL | https://github.com/JetBrains/JetBrainsMono | ~80 KB | Code / table figures (tnum) |

## How to update

1. Download new variable woff2 from release page (links above).
2. Verify with `fontTools.ttLib.TTFont(...).flavor == 'woff2'` and `'fvar' in font`.
3. Replace file in `src/static/fonts/`.
4. Update this doc with new size.
5. No build step needed — files served directly by Flask static.

## Why variable fonts

- One file covers all weights 100-900 (avoids 4 separate files for Regular/Medium/SemiBold/Bold)
- Smaller total bundle (~50-120 KB per file vs 4 × 30-40 KB = 120-160 KB)
- Smoother weight interpolation in HTML
```

- [ ] **Step 5: 驗證**

```bash
ls -la src/static/fonts/*.woff2
# 預期: 4 個 woff2 (Montserrat 既有 + 3 新)
test -f docs/fonts-vendoring.md && echo OK
```

- [ ] **Step 6: Commit**

```bash
git add src/static/fonts/SpaceGrotesk-VF.woff2 src/static/fonts/Inter-VF.woff2 src/static/fonts/JetBrainsMono-VF.woff2 docs/fonts-vendoring.md
git commit -m "feat(fonts): vendor Space Grotesk + Inter + JetBrains Mono (Track A prep)

Adds 3 variable woff2 fonts for §6.1 B (industrial-editorial) direction.
Self-hosted to satisfy C1 (offline) and avoid CSP/CDN issues. Total
~250 KB (50 + 120 + 80) — variable fonts cover wght 100-900 in single
file each.

Existing Montserrat-latin.woff2 retained for backward-compat during
Track A migration; will be removed in final cleanup task.

Adds docs/fonts-vendoring.md with license + source + update instructions."
```

---

## Task 2: 加 parallel token layer (新 token, 不覆蓋舊)

**Goal:** 在 app.css 與 report_css.py 加新的 `--font-heading-2` / `--color-signal-*` token，定義但暫不替換 component 引用。確保視覺零變化。

**Files:**
- Modify: `src/static/css/app.css` (top of `:root` + add @font-face for new fonts)
- Modify: `src/report/exporters/report_css.py` (BASE_CSS 區塊)

**為何 parallel:** 直接覆蓋會一次改 ~50+ component selector，難以單元 review。Parallel layer 允許「定義就緒，逐步切換」。

- [ ] **Step 1: 加 @font-face 到 app.css**

在 `src/static/css/app.css` 開頭 (現有 Montserrat @font-face 之後)，加：

```css

@font-face {
  font-family: 'Space Grotesk';
  font-style: normal;
  font-weight: 400 700;
  font-display: swap;
  src: url('/static/fonts/SpaceGrotesk-VF.woff2') format('woff2');
}
@font-face {
  font-family: 'Inter';
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url('/static/fonts/Inter-VF.woff2') format('woff2');
}
@font-face {
  font-family: 'JetBrains Mono';
  font-style: normal;
  font-weight: 100 800;
  font-display: swap;
  src: url('/static/fonts/JetBrainsMono-VF.woff2') format('woff2');
}
```

- [ ] **Step 2: 加新 token 到 :root**

在 `src/static/css/app.css` 的 `:root { ... }` 中既有 `--header-font` / `--body-font` 之後，加：

```css
      /* Track A — new token layer (parallel; do not replace existing yet) */
      --font-heading-2: 'Space Grotesk', 'Montserrat', system-ui, sans-serif;
      --font-body-2:    'Inter', 'Montserrat', system-ui, sans-serif;
      --font-mono-2:    'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;

      /* Signal tokens (D.3 共享) — semantic color, not brand */
      --color-signal-success: #2D9B5E;
      --color-signal-warning: #C47A00;
      --color-signal-danger:  #D93025;
      --color-signal-info:    #0077CC;
```

`[data-theme="light"]` block 同樣加一份 (signal token 在 light 維持相同 hex; -2 字型 token 同樣)。

- [ ] **Step 3: report_css.py 同步加新 token**

Read `src/report/exporters/report_css.py`. 找 BASE_CSS 或對應的 :root token 定義段。加入：

```css
/* Track A — Report direction §6.2 B (editorial-magazine) parallel tokens */
:root {
  --font-heading-report: 'Space Grotesk', 'Source Serif 4', Georgia, serif;
  --font-body-report:    'Inter', system-ui, sans-serif;
  --font-mono-report:    'JetBrains Mono', ui-monospace, monospace;
  --color-signal-success: #2D9B5E;
  --color-signal-warning: #C47A00;
  --color-signal-danger:  #D93025;
  --color-signal-info:    #0077CC;
}
```

(注: Report 的 heading 用 Space Grotesk 而非 Source Serif 4 — 因為 Source Serif 4 還沒 vendor。後續 Task 8 視需要追加。預設用 Space Grotesk 達成 editorial 感覺。)

加 @font-face for Inter / Space Grotesk / JetBrains Mono (報告 HTML 與 PDF 都需要 inline 字型 src，因為 PDF render 不通過 Flask static)：

```python
REPORT_FONT_FACE_CSS = """
@font-face {
  font-family: 'Space Grotesk';
  font-style: normal;
  font-weight: 400 700;
  src: url('/static/fonts/SpaceGrotesk-VF.woff2') format('woff2');
}
@font-face {
  font-family: 'Inter';
  font-style: normal;
  font-weight: 100 900;
  src: url('/static/fonts/Inter-VF.woff2') format('woff2');
}
@font-face {
  font-family: 'JetBrains Mono';
  font-style: normal;
  font-weight: 100 800;
  src: url('/static/fonts/JetBrainsMono-VF.woff2') format('woff2');
}
"""
```

(PDF render 路徑可能無法 resolve `/static/...` URL。Step 4 處理。)

- [ ] **Step 4: PDF 字型路徑處理**

WeasyPrint / pdfkit 需要絕對檔案路徑。檢查現有 PDF exporter 怎麼處理 Montserrat：

```bash
cd /home/harry/rd/illumio-ops
grep -nE 'WeasyPrint|weasyprint|HTML\(|font_path|FONT_PATH' src/report/exporters/pdf_exporter.py | head -10
grep -nE 'Montserrat|font.*path' src/report/exporters/pdf_exporter.py src/report/exporters/report_css.py | head -10
```

依現有模式 (例如 `file://{abs_path}` 或 base_url), 對 3 個新字型也提供同樣的解析路徑。如果現有 PDF 字型用法是 inline base64, 此 plan 暫時保留為 system-fallback (PDF 不換字型) 並在 commit 註明 PDF 字型 vendor 為下個 task。

- [ ] **Step 5: 驗證 CSS 語法 + token 存在**

```bash
cd /home/harry/rd/illumio-ops
grep -cE "font-family: 'Space Grotesk'" src/static/css/app.css
# 預期: 1 (在 @font-face)
grep -cE '\-\-font-heading-2' src/static/css/app.css
# 預期: ≥1
grep -cE '\-\-color-signal-success' src/static/css/app.css src/report/exporters/report_css.py
# 預期: ≥2 (各 1 處定義)
# 啟動現有 GUI test (若可) 確認無回歸
PYTHONPATH=$(pwd)/venv/lib/python3.12/site-packages python3 -m pytest tests/ -x --ignore=tests/test_render_tty.py 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add src/static/css/app.css src/report/exporters/report_css.py
git commit -m "feat(visual): add parallel token layer for Track A (Space Grotesk / Inter / JetBrains Mono + signal palette)

Defines --font-heading-2 / --font-body-2 / --font-mono-2 in app.css and
parallel --font-heading-report / --font-body-report / --font-mono-report
in report_css.py. All three new fonts have @font-face declarations
pointing to vendored woff2 (Task 1).

Adds 4 D.3 signal tokens (success/warning/danger/info) to both surfaces
for cross-surface verdict color consistency.

NO existing token replaced — visual zero-change. Component migration
happens in Tasks 3-7."
```

---

## Task 3: login.html demo migration (低風險示範)

**Goal:** 把 login.html 從 Montserrat 改用新字型，作為 visual sanity check。Login 是孤立頁面 (不 share app.css 變數)，scope 最小。

**Files:**
- Modify: `src/templates/login.html` (font-family 與 @font-face)

- [ ] **Step 1: 更新 login.html @font-face 與 font-family**

Read `src/templates/login.html`。Phase 0 (Task 0.1 a7) 已加入 Montserrat @font-face。修改：

1. 把 line 33 附近的 `font-family: 'FK Grotesk', Montserrat, Arial, sans-serif;` 改成 `font-family: 'Inter', system-ui, sans-serif;`

2. 把現有 Montserrat @font-face 加上 Space Grotesk + Inter 對應宣告 (放在同一個 `<style nonce>` 區塊內)：

```css
@font-face {
  font-family: 'Space Grotesk';
  font-style: normal;
  font-weight: 400 700;
  font-display: swap;
  src: url('/static/fonts/SpaceGrotesk-VF.woff2') format('woff2');
}
@font-face {
  font-family: 'Inter';
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url('/static/fonts/Inter-VF.woff2') format('woff2');
}
```

3. 標題 (h1 / login title) 加 `font-family: 'Space Grotesk', system-ui, sans-serif; font-weight: 600;`

(若 login.html 有特定 selector for 標題, e.g., `.login-title`, 套用該處)

- [ ] **Step 2: Verify Jinja render**

```bash
cd /home/harry/rd/illumio-ops
python3 -c "
from jinja2 import Environment, FileSystemLoader, ChainableUndefined
env = Environment(loader=FileSystemLoader('src/templates'), undefined=ChainableUndefined)
src = open('src/templates/login.html').read()
assert 'fonts.googleapis.com' not in src, 'CDN slipped back in'
assert \"'Inter'\" in src, 'Inter not referenced'
assert \"'Space Grotesk'\" in src, 'Space Grotesk not referenced'
print('OK: login.html migration syntactically valid')
"
```

- [ ] **Step 3: Commit**

```bash
git add src/templates/login.html
git commit -m "feat(visual): migrate login.html to Space Grotesk + Inter (Track A demo)

Switches login page from Montserrat to Space Grotesk (heading) + Inter
(body) per §6.1 B direction. Smallest-scope migration site (login is
isolated, doesn't share app.css). Validates @font-face wiring before
broader app migration.

Touches §3.1.3 Typography 2→3 on login surface (validation page only)."
```

---

## Task 4: GUI body font 切換 (--body-font 改指 Inter)

**Goal:** 把 app.css 內 `--body-font` 從 Montserrat 改指 Inter，所有引用 `var(--body-font)` 的 component 同時切換。預期影響 ~40+ selector，但不需個別改。

**Files:**
- Modify: `src/static/css/app.css` (`--body-font` value)

- [ ] **Step 1: 把 --body-font 換值**

在 `src/static/css/app.css` 的 `:root` 與 `[data-theme="light"]` 區塊：

```css
/* Before: */
--body-font: 'Montserrat', system-ui, sans-serif;
/* After: */
--body-font: var(--font-body-2);
```

(用 fallback chain: --font-body-2 已在 Task 2 定義為 Inter + Montserrat fallback。)

- [ ] **Step 2: 視覺 sanity check — 用 Playwright (若可) 截圖前後**

```bash
cd /home/harry/rd/illumio-ops
PYTHONPATH=$(pwd)/venv/lib/python3.12/site-packages python3 -m pytest tests/ -x --ignore=tests/test_render_tty.py 2>&1 | tail -10
# 若有 Playwright/screenshot test, 跑：
# pytest tests/visual/ -v
```

如果沒有 visual regression test, 寫一個簡單的 manual checklist 在 commit message：

```
Manual visual check (recommended):
- /login — body text: Inter (not Montserrat)
- /dashboard — table cells: Inter
- /rules — input fields: Inter
- /settings — form labels: Inter
```

- [ ] **Step 3: Commit**

```bash
git add src/static/css/app.css
git commit -m "feat(visual): switch GUI --body-font to Inter (Track A)

Single-line change: --body-font now resolves through --font-body-2
(Task 2) → Inter → Montserrat fallback → system-ui. All ~40 component
selectors that use var(--body-font) inherit the change automatically.

Touches §3.1.3 Typography 2→3 (body axis); paves for heading change
in next task. Visual regression risk: low (same x-height, similar
metrics; tabular figures via tnum still resolve from JetBrains Mono
in mono contexts)."
```

---

## Task 5: GUI heading font 切換 (--header-font 改指 Space Grotesk)

**Goal:** 同 Task 4，但 heading 軸。

**Files:**
- Modify: `src/static/css/app.css` (`--header-font` value)

- [ ] **Step 1: 換值**

```css
/* Before: */
--header-font: 'Montserrat', system-ui, sans-serif;
/* After: */
--header-font: var(--font-heading-2);
```

- [ ] **Step 2: Visual check**

(同 Task 4)

- [ ] **Step 3: Commit**

```bash
git add src/static/css/app.css
git commit -m "feat(visual): switch GUI --header-font to Space Grotesk (Track A)

Headings (h1-h4, panel titles, card titles) now use Space Grotesk via
--header-font → --font-heading-2 chain. Industrial-editorial direction
characteristic: heading typeface visually distinct from body, creating
hierarchy without color/size alone.

Touches §3.1.3 Typography 2→3 (heading axis); §3.1.3 Distinctiveness
1→2 (字族對比 = identity lever per §6.1)."
```

---

## Task 6: GUI mono font 切換 (--mono-font 改指 JetBrains Mono)

**Files:**
- Modify: `src/static/css/app.css` (`--mono-font` 加入或更新)

- [ ] **Step 1: 換值**

現有 `var(--mono-font, 'Courier New', monospace)` (line 199) 顯示有 fallback 但 `--mono-font` 可能未定義。在 :root 加：

```css
--mono-font: var(--font-mono-2);
```

(Task 2 已定義 --font-mono-2 = JetBrains Mono + ui-monospace fallback)

- [ ] **Step 2: 同步替換 hardcoded mono fallback**

```bash
grep -nE "ui-monospace|SFMono|Cascadia|Fira Code|'Courier" src/static/css/app.css
```

對命中的 selector，改用 `var(--mono-font)` 統一。例如 line 256 與 712 (Cascadia/Fira) → `var(--mono-font)`.

- [ ] **Step 3: Commit**

```bash
git add src/static/css/app.css
git commit -m "feat(visual): switch GUI --mono-font to JetBrains Mono (Track A)

Code blocks, IP addresses, log lines, IDs now use JetBrains Mono via
--mono-font → --font-mono-2 chain. Replaces 3 hardcoded fallback
chains (Cascadia/Fira/Courier) with the unified token.

JetBrains Mono has tnum (tabular figures) by default — numeric columns
in tables align without extra font-feature-settings declaration.

Touches §3.1.3 Typography 2→3 (mono axis)."
```

---

## Task 7: chart_renderer 套用 signal palette

**Goal:** chart_renderer.py 中各 chart 的 verdict color 改用 D.3 signal palette。Cross-cutting：影響 GUI dashboard 與 Report 中所有圖表。

**Files:**
- Modify: `src/report/chart_renderer.py`

- [ ] **Step 1: 找現有 verdict color 用法**

```bash
cd /home/harry/rd/illumio-ops
grep -nE 'green|#2|red|#D|amber|#C|orange|#F' src/report/chart_renderer.py | head -30
grep -nE 'Allowed|Blocked|allowed|blocked|color\b|colour\b|palette' src/report/chart_renderer.py | head -30
```

找硬編碼 color hex / 名稱。

- [ ] **Step 2: 抽出 SIGNAL_COLORS 常數**

在 `src/report/chart_renderer.py` 頂部加：

```python
# D.3 共享 signal palette — must match --color-signal-* in app.css and report_css.py
SIGNAL_COLORS = {
    'success':  '#2D9B5E',  # Allowed / Online / passing
    'warning':  '#C47A00',  # Potentially-Blocked / Warning
    'danger':   '#D93025',  # Blocked / Critical / Lost
    'info':     '#0077CC',  # Info / metadata
}

# Convenience aliases for verdict labels (Illumio terminology — 留英 per OQ-10)
VERDICT_COLORS = {
    'Allowed':              SIGNAL_COLORS['success'],
    'Blocked':              SIGNAL_COLORS['danger'],
    'Potentially-Blocked':  SIGNAL_COLORS['warning'],
    'Potentially_Blocked':  SIGNAL_COLORS['warning'],  # alt spelling
    'Unknown':              SIGNAL_COLORS['info'],
}
```

- [ ] **Step 3: 替換硬編碼 color**

對每個 chart 函式找 `colors=[...]` / `color=...` 引用，改用 SIGNAL_COLORS 或 VERDICT_COLORS lookup。

例如：
```python
# Before:
colors = ['#28a745', '#dc3545', '#ffc107']
# After:
colors = [SIGNAL_COLORS['success'], SIGNAL_COLORS['danger'], SIGNAL_COLORS['warning']]
```

或 Plotly：
```python
# Before:
fig.update_traces(marker_colors=['green','red','orange'])
# After:
fig.update_traces(marker_colors=[SIGNAL_COLORS['success'], SIGNAL_COLORS['danger'], SIGNAL_COLORS['warning']])
```

逐個函式 commit 過於 細，本 task 一次處理整個 chart_renderer.py。

- [ ] **Step 4: 驗證**

```bash
grep -cE 'SIGNAL_COLORS\[' src/report/chart_renderer.py
# 預期: ≥3 (至少幾個 chart 使用)
PYTHONPATH=$(pwd)/venv/lib/python3.12/site-packages python3 -m pytest tests/ -x -k 'chart or report' 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add src/report/chart_renderer.py
git commit -m "feat(visual): apply D.3 signal palette to chart_renderer (Track A)

Adds SIGNAL_COLORS + VERDICT_COLORS module-level constants matching
--color-signal-* hex values in app.css and report_css.py. Replaces
hardcoded chart color hex codes with semantic lookups.

Cross-surface consistency: same verdict color appears identically in
GUI dashboard chart (via app.css), report HTML chart (via report_css),
report PDF chart (via inline svg fill), and email subset (Track A
Task 8 follow-up).

Touches §3.3.3 Visual Identity Color: 3→3 (now token-driven, not
literal hex);  §3.3.6 推薦組合 — 跨 surface 視覺一致."
```

---

## Task 8: Email subset signal token + Source Serif 4 fallback

**Goal:** mail_wrapper.html.tmpl 與 reporter.py 的 _render_cta / signal-color 套用 D.3 signal hex (而非 hardcoded #0077CC)。Email 字型保留 system serif fallback (跨 client safe), 不引入 webfont (Email subset 限制)。

**Files:**
- Modify: `src/alerts/templates/mail_wrapper.html.tmpl` (font-family + signal hex)
- Modify: `src/reporter.py` `_render_cta` (signal hex)

- [ ] **Step 1: mail_wrapper font-family 升級**

Phase 1 Task 4.3 已重寫 mail_wrapper 為 table layout。現有 font-family 是 system fallback chain:
```
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,...
```

維持系統 chain (Email subset 不引入 webfont per §6.2 B Email constraint)，但加 Georgia 作為 serif 化 (editorial 感):

```html
<body style="margin:0;padding:0;background:#F4F4F4;font-family:Georgia,'Times New Roman',serif;...">
```

(如果 stakeholder 偏好 sans-serif, 維持原 chain — 不強求 serif。本步驟可省略或變 sans-serif chain 加 'Inter Fallback' 等。)

- [ ] **Step 2: _render_cta signal token 化**

Read src/reporter.py `_render_cta`。把 hardcoded `#0077CC` 抽成參數 + signal lookup：

```python
# In reporter.py, near _render_cta:
SIGNAL_HEX = {
    'success': '#2D9B5E',
    'warning': '#C47A00',
    'danger':  '#D93025',
    'info':    '#0077CC',
}

@staticmethod
def _render_cta(label: str, url: str, severity: str = 'info') -> str:
    """Render a bulletproof CTA button (Outlook-safe, table-based).

    severity: one of 'success', 'warning', 'danger', 'info' (default).
    Picks bg color from SIGNAL_HEX dict.
    """
    import html
    label_html = html.escape(label)
    url_html = html.escape(url, quote=True)
    bg = SIGNAL_HEX.get(severity, SIGNAL_HEX['info'])
    return (
        f'<table role="presentation" border="0" cellpadding="0" cellspacing="0" '
        f'style="margin:16px 0;">'
        f'<tr><td bgcolor="{bg}" style="border-radius:4px;">'
        f'<a href="{url_html}" '
        f'style="display:inline-block;padding:10px 20px;color:#FFFFFF;'
        f'text-decoration:none;font-weight:600;">{label_html}</a>'
        f'</td></tr></table>'
    )
```

- [ ] **Step 3: Health/Event/Traffic/Metric CTA 加 severity hint**

Phase 1 Task 4.5 wired CTAs without severity. 改成傳入 severity:

```python
section_html += self._render_cta(
    label=t('mail_cta_view_health'),
    url=f'{gui_base}/dashboard?tab=health',
    severity='success',  # health 通常是 OK 狀態
)
section_html += self._render_cta(
    label=t('mail_cta_view_event'),
    url=f'{gui_base}/dashboard?tab=events',
    severity='danger' if event_alerts else 'info',  # 有 events = critical
)
# ... etc
```

(severity 對應依 section 的 alert 數量 / max severity 判定。可簡化為固定 mapping 也可。)

- [ ] **Step 4: 驗證**

```bash
cd /home/harry/rd/illumio-ops
grep -cE 'SIGNAL_HEX' src/reporter.py
# 預期: ≥1 dict + ≥1 use
grep -cE 'severity=' src/reporter.py | head -5
python3 -c "
import ast
ast.parse(open('src/reporter.py').read())
print('OK: reporter.py parses')
"
```

- [ ] **Step 5: Commit**

```bash
git add src/alerts/templates/mail_wrapper.html.tmpl src/reporter.py
git commit -m "feat(visual): apply D.3 signal palette to email CTAs (Track A)

_render_cta now takes severity param (success/warning/danger/info) and
picks bg color from SIGNAL_HEX dict. Defaults to info (existing
behavior).

Wires section-specific severity:
- health → success
- event → danger when alerts present, info otherwise
- traffic → warning
- metric → info

Cross-surface consistency: email signal hex matches GUI/Report (Track
A Task 7).

mail_wrapper font-family chain unchanged (Email subset constraint:
no webfont). Editorial direction adopts system serif fallback for
optional serif feel.

Touches §3.4.2 cross-client +1/8 (signal-driven CTA color);
§3.4.4 actionability strengthened by visual severity cue."
```

---

## Task 9: Cleanup — remove parallel layer aliases (optional, 收尾)

**Goal:** Tasks 4-8 完成後，把 `--font-heading-2` rename 為主 token，移除舊 Montserrat fallback。可選: 若 Montserrat 不再使用，從 src/static/fonts/ 刪除。

**Files:**
- Modify: `src/static/css/app.css`
- Optional: Remove `src/static/fonts/Montserrat-latin.woff2` (if confirmed unused)

- [ ] **Step 1: Rename token**

```css
/* Before: */
--font-heading-2: 'Space Grotesk', 'Montserrat', system-ui, sans-serif;
--header-font: var(--font-heading-2);
/* After: */
--header-font: 'Space Grotesk', system-ui, sans-serif;
```

(去掉 -2 alias 與 Montserrat fallback。)

- [ ] **Step 2: 確認 Montserrat 是否還有引用**

```bash
cd /home/harry/rd/illumio-ops
grep -rnE 'Montserrat' src/static/css/ src/templates/ src/static/js/ src/report/ | head -10
```

如果 0 命中 (除了 docs/fonts-vendoring.md 的 legacy 註記), 可 commit 移除 Montserrat-latin.woff2:

```bash
git rm src/static/fonts/Montserrat-latin.woff2
```

- [ ] **Step 3: 更新 docs/fonts-vendoring.md**

把 Montserrat 那行從表格刪掉 (或標 "removed YYYY-MM-DD")。

- [ ] **Step 4: Commit**

```bash
git add src/static/css/app.css docs/fonts-vendoring.md
# 若 step 2 移除字型，也加 git rm
git commit -m "chore(visual): finalize Track A — remove Montserrat parallel layer

Tasks 4-8 完成 Space Grotesk + Inter + JetBrains Mono 全套用後，移除
parallel -2 token alias 與 Montserrat fallback. <若移除字型: 同時 git rm
src/static/fonts/Montserrat-latin.woff2 (37 KB 解放)>.

vendor/ size: <new total> KB (down from <old total> KB if removed).

Touches: cleanup; no functional change."
```

---

## Self-review checklist

執行完所有 Task 後驗證：

### Vendor + tokens
- [ ] `ls src/static/fonts/*.woff2` ≥ 4 (新 3 + 既有 NotoSansCJK + 視 Task 9 是否移除 Montserrat)
- [ ] `grep -cE "font-family: 'Space Grotesk'" src/static/css/app.css` ≥ 1
- [ ] `grep -cE '\-\-color-signal-success' src/static/css/app.css src/report/exporters/report_css.py` ≥ 2

### GUI migration
- [ ] `grep -cE 'var\(--header-font\)' src/static/css/app.css` ≥ 8 (heading 用法保留, 但底層字型換新)
- [ ] `grep -cE "'Cascadia Code'|'Fira Code'" src/static/css/app.css` = 0 (已統一成 --mono-font)
- [ ] login.html 載入後字型為 Inter / Space Grotesk (manual visual check)

### Charts + Reports
- [ ] `grep -cE 'SIGNAL_COLORS\[|VERDICT_COLORS\[' src/report/chart_renderer.py` ≥ 3
- [ ] `grep -cE '#28a745|#dc3545|#ffc107' src/report/chart_renderer.py` = 0 (硬編碼移除)

### Email
- [ ] `grep -cE 'SIGNAL_HEX' src/reporter.py` ≥ 2 (dict + use)
- [ ] `grep -cE 'severity=' src/reporter.py` ≥ 4 (4 sections)

### Tests
- [ ] `pytest tests/` 全綠 (existing tests + Phase 1 new tests)

---

## §12 Next Steps

Track A 完成後可解鎖:

1. **Phase 2 Track B (CLI Output Layer)** — 可獨立 ship, 無 Track A 依賴 (見另一份 plan)
2. **Phase 3 Track C (CLI Entry Unification)** — 需 Track B 已 ship
3. **Phase 3 Track D (Email System MJML)** — 可獨立 ship, 但會利用 Track A 的 SIGNAL_HEX module-level constant
4. **Phase 4 Track E (Backend Async)** — conditional, 視 Phase 1-3 完成後 a1/c1 重評

執行此 plan 時注意:
- 評估報告 §3.1.3 Distinctiveness 1→2 是 user-perceptible change, **建議 Phase 2 結束時請 stakeholder review** (showcase before/after)
- 若 stakeholder 偏好維持 Montserrat, Tasks 4-9 可 revert 而 Tasks 1-3 (vendor + parallel token) 仍可保留為可用基礎

---

## Self-review of this plan

- ✅ Goal/Architecture/Tech Stack header 完整
- ✅ Reference docs 列出 (§6.1/§6.2/§6.3 from assessment)
- ✅ 9 tasks 結構: vendor → parallel layer → demo → 4 component swaps → cross-cutting → cleanup
- ✅ Parallel token strategy 降低 visual regression 風險
- ✅ 每 task 有 file paths + 完整 code/CSS (無 placeholder)
- ✅ Hard constraints (C1 offline / a11y / WCAG AA) 在 header
- ⚠️ Task 7 chart 替換是廣度大的 mechanical 工作，subagent 可能需多輪
- ⚠️ Task 8 email severity 對應是設計判斷, stakeholder 可能想客製
- ⚠️ Task 9 cleanup optional，不執行也 OK (parallel layer 維持，下次再清)

預計執行時間（subagent-driven 模式）:
- Tasks 1-2: ~1-2 hours (vendor + token, mechanical)
- Task 3: ~1 hour (login demo)
- Tasks 4-6: ~2-3 hours total (3 single-line token swaps + visual checks)
- Task 7: ~3-4 hours (chart_renderer mechanical replacement)
- Task 8: ~2 hours (email severity wiring)
- Task 9: ~30 min (cleanup if applicable)
- 總計: ~10-13 hours subagent time
