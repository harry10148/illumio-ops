# Rules / Alerts UX Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Fix the user-facing UX issues found while reviewing the rules/alerts forms and overview: oversized icons, stray emoji, an English placeholder leak, a broken event-type label, and cramped field spacing.

**Architecture:** Pure front-end cleanup (templates + static JS/CSS + a few i18n values). No backend/data changes. Standardise on the existing inline-SVG `#icon-*` symbol system and the `sw sw-*` icon classes; remove emoji glyphs.

**Tech Stack:** `src/templates/index.html`, `src/static/js/*.js`, inline `<style>` / CSS in index.html, i18n JSON.

**Scope note (corrected during review):** "Policy 判定" / the "Policy" category label are NOT bugs — the project glossary intentionally keeps `Policy`/`Workload`/`Service`/`PCE`/`VEN` in English. Do NOT "translate" these.

---

## Task B1: Fix oversized icons in the Operations panel

**Problem:** `#icon-cpu` (模組日誌) and `#icon-stop` (停止) render huge because their `<svg class="icon">` carries no width/height and the `.icon` CSS rule does not constrain size for `<use>`-based symbols (`src/templates/index.html:173,180`). Contrast lines 123/149 which set inline `style="width:24px;height:24px"`.

**Files:** Modify `src/templates/index.html` (the `.icon` CSS rule).

- [ ] **Step 1:** Find the `.icon` CSS rule in the `<style>` block of `index.html`. Confirm whether it sets `width`/`height`.
- [ ] **Step 2:** Add a default size + flex-shrink guard so every `svg.icon` (including `<use>` symbol icons) is bounded:
```css
.icon { width: 18px; height: 18px; flex: 0 0 auto; vertical-align: middle; }
```
(Keep any existing `.icon` declarations; only add the sizing if absent. Inline `style` width/height on specific icons still override this.)
- [ ] **Step 3: Verify visually** — login to the test GUI (browser, see Verification section), open Operations panel, confirm 模組日誌 + 停止 icons are small/aligned.
- [ ] **Step 4: Commit** `git commit -m "fix(gui): constrain .icon svg size so symbol icons don't render oversized"`

---

## Task B2: Remove emoji, replace with icons/text

**Problem:** ~15 emoji glyphs across 6 files: `src/static/js/settings.js:354 (✓)`, `rules.js:79 (✅), :96 (✏️)`, `dashboard.js:1174 (✏️), :1232 (⚠)`, `integrations.js:119/120/322/942/943/970/973 (✓/✗)`, `index.html:2406 (🟢)`, `utils.js:431/433 (✕/⚠/✓)`.

**Files:** the 6 files above.

- [ ] **Step 1: Write a guard test** `tests/test_no_emoji_in_ui.py`:
```python
import re, glob
EMOJI = re.compile("[\U0001F000-\U0001FAFF✂-➰✅✔✖❌✨⚠⚙✏⭐\U0001F195✅⬛-⬜\U0001F7E0-\U0001F7EB]")
def test_no_emoji_in_frontend():
    bad = []
    for f in glob.glob("src/static/js/*.js") + ["src/templates/index.html"]:
        for i, line in enumerate(open(f, encoding="utf-8"), 1):
            if EMOJI.search(line):
                bad.append(f"{f}:{i}: {line.strip()[:60]}")
    assert not bad, "emoji found:\n" + "\n".join(bad)
```
- [ ] **Step 2: Run, confirm FAIL** (lists the ~15 occurrences): `venv/bin/python -m pytest tests/test_no_emoji_in_ui.py -v`
- [ ] **Step 3: Replace each occurrence.** Mapping rules: status ✓/✅ → text label or `<svg class="icon"><use href="#icon-check"></use></svg>` if such a symbol exists, else a CSS dot `<span class="status-ok">`; ✗/✕ → `#icon-x` or text; ✏️ (edit button) → `#icon-edit` symbol or the text label `編輯` (the button already has a title); ⚠ → `#icon-warn` or the existing `sw sw-*`/`--warn` colour; 🟢/status dots → the existing coloured `<span class="dot">` pattern already used elsewhere (e.g. VEN health uses a coloured dot). Inspect each call site and pick the closest existing non-emoji idiom already in that file. If no suitable `#icon-*` symbol exists, add a minimal `<symbol>` to the SVG sprite block near `#icon-stop` in index.html.
- [ ] **Step 4: Run, confirm PASS** + `venv/bin/python -m pytest tests/test_no_emoji_in_ui.py -q` and `node --check` each modified JS file.
- [ ] **Step 5: Commit** `git commit -m "fix(gui): replace emoji glyphs with icons/text across rules/alerts UI"`

---

## Task B3: Fix English placeholder leak + broken event-type label

**Files:** `src/static/js/rules.js`, i18n JSON, and wherever the `agent.upgrade_successful` label string originates.

- [ ] **Step 1:** `rules.js:310` uses `data-i18n="gui_select">Select...`. Check the zh_TW value of `gui_select`. If it is "Select..." (English) in zh_TW, change the category placeholder to a dedicated key `gui_select_category` = en "Select category…" / zh "選擇分類…" (add to both i18n files, keep parity). Update `rules.js:310` to use that key.
- [ ] **Step 2:** Locate the source of the broken label "Agent升級Successful" for `agent.upgrade_successful` (grep `升級` and `Successful` in i18n + the option-label builder in `rules.js`). Fix the label to consistent Traditional Chinese (e.g. "Agent 升級成功"), keeping product terms per glossary. If it is auto-generated by a humanizer, add a proper label key instead.
- [ ] **Step 3:** Run `venv/bin/python -m pytest tests/test_i18n_strings_parity.py tests/test_i18n_glossary.py -q` → must pass.
- [ ] **Step 4: Commit** `git commit -m "fix(i18n): localise category placeholder and fix agent.upgrade_successful label"`

---

## Task B4: Field spacing in forms + overview

**Problem:** User reports cramped field spacing. The 門檻值 (threshold) row in the event/traffic/bandwidth modals is tight; help boxes dominate; overview/alert page field spacing needs breathing room.

**Files:** `src/templates/index.html` CSS (`.form-group`, `.modal` fieldset, threshold grid, card spacing).

- [ ] **Step 1:** Inspect current `.form-group` / fieldset / threshold layout CSS in index.html. Identify the threshold container (the `數量 / 分鐘 / 冷卻` grid) and the modal form spacing.
- [ ] **Step 2:** Increase vertical rhythm modestly and consistently — e.g. `.modal .form-group { margin-bottom: 14px; }`, give the threshold grid `gap: 16px` and align labels; ensure help/`<small>` text has `margin-top:4px` and is not larger than inputs. Do NOT restructure markup; CSS-only adjustments.
- [ ] **Step 3: Verify visually** in the browser (event + traffic + bandwidth modals + overview cards) — capture before/after screenshots.
- [ ] **Step 4: Commit** `git commit -m "style(gui): improve field spacing in rule modals and overview"`

---

## Task B5 (optional): Event-form help text & advanced-conditions affordance

**Files:** `src/templates/index.html`, i18n.

- [ ] **Step 1:** The advanced-conditions input exposes raw `created_by.user.username=admin@example.com` key=value syntax. Add a short inline hint (i18n) clarifying the `field=value`, one-per-line format and that it is optional; keep the example. Trim the pre-selection generic help (`gui_ev_capability_basic`) to one line.
- [ ] **Step 2:** Run i18n parity test, commit `style(gui): clarify advanced-condition hint and trim event help text`.

---

## Verification (browser, self-signed cert)
The Playwright MCP cannot bypass the test GUI's self-signed cert directly. Use `browser_run_code_unsafe` with a fresh `ignoreHTTPSErrors` context:
```js
const ctx = await page.context().browser().newContext({ ignoreHTTPSErrors: true, viewport:{width:1440,height:1100} });
const p = await ctx.newPage();
await p.goto('https://172.16.15.106:5001/'); await p.fill('#username','illumio'); await p.fill('#password','<pw>'); await p.click('#login-btn');
```
(Note: the test machine runs OLD code until this branch is deployed — visual verification of these fixes requires deploying the branch first, OR running a local GUI instance.)

## Self-Review notes
- B1/B2/B3 are deterministic and testable (size rule, emoji guard test, i18n parity). B4/B5 are visual/CSS — verify by screenshot.
- Corrected scope: "Policy 判定" is intentional glossary style — excluded.
