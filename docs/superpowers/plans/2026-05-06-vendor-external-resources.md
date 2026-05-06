# Vendor External Resources (a7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除 `src/templates/login.html` 對 Google Fonts CDN 的引用，改用本地 Montserrat woff2，解除 P0 hard-gate (a7) 並順帶修復 a6 (CSP `font-src='self'` 阻擋 Google Fonts → layout 破版)。

**Architecture:** 字型檔已部分 self-hosted (`src/static/fonts/Montserrat-latin.woff2`, 37 KB), `src/static/css/app.css:1-8` 已宣告對應 `@font-face`。本 plan 僅同步 `login.html`：去除 2 行 CDN `<link>`，把 `@font-face` 區塊 inline 到 login.html 既有 `<style nonce="...">`。Optional 升級：以變體字型 (variable font) 取代現有 37 KB 單一字重檔，避免 weight 400/500/600/700 全 fallback 為合成粗體。

**Tech Stack:** HTML + inline CSS（無 build pipeline）；可選 npm `@fontsource/montserrat` 取得變體字型，或 `fonts.google.com/specimen/Montserrat` 手動下載。

**Reference docs:**
- 評估報告 §3.1.0 a7 + Vendor 化執行 plan: `docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md`
- a6 CSP root cause: `src/gui/__init__.py:251` (`font-src='self'`)
- 既有 @font-face: `src/static/css/app.css:1-8`
- 違規檔: `src/templates/login.html:7-8`

**Scope discovery (重要)：** 評估報告的 B.2 vendor mapping plan 假設需新建 `vendor/fonts/` 並下載 4 個 woff2 (~150 KB)。實際勘查發現 Montserrat 已 self-hosted 於 `src/static/fonts/`，且 `app.css` 已有 @font-face。**真正的修補只是同步 login.html。** 本 plan 反映實際情況。

**驗收 (acceptance):**
- `grep -nE 'https?://' src/templates/login.html` 0 匹配（除非註解）
- `grep -rEn 'https?://' src/templates src/static src/alerts | grep -v ':\s*\(#\|//\|/\*\|\*\)'` 命中數從 7 → 5（保留的 5 筆都是 namespace / placeholder / API endpoint, 不在 a7 範圍）
- 載入 `https://<host>/login` 後瀏覽器 Network 面板無 `fonts.googleapis.com` 請求
- DevTools Console 無 CSP `font-src` violation
- 視覺：login 頁面字型仍為 Montserrat（或 system fallback 不破版）

---

## Task 1: 確認字型檔涵蓋的 weight

**目的：** 判斷現有 `Montserrat-latin.woff2` 是否為變體字型 (能涵蓋 400-700 各字重)，或只是單一 Regular 字重 (browser 將合成 bold)。決定本 plan 走「最小修補」或「升級為變體字型」路徑。

**Files:**
- Read: `src/static/fonts/Montserrat-latin.woff2`

- [ ] **Step 1: 用 fonttools 驗證**

```bash
cd /home/harry/rd/illumio-ops
python3 -c "
try:
    from fontTools.ttLib import TTFont
except ImportError:
    import subprocess; subprocess.check_call(['pip','install','fonttools','brotli'])
    from fontTools.ttLib import TTFont
f = TTFont('src/static/fonts/Montserrat-latin.woff2')
print('flavor:', f.flavor)
print('tables:', sorted(f.keys()))
if 'fvar' in f:
    fvar = f['fvar']
    for axis in fvar.axes:
        print(f'  axis {axis.axisTag}: min={axis.minValue} default={axis.defaultValue} max={axis.maxValue}')
else:
    print('NOT a variable font')
os2 = f['OS/2']
print(f'OS/2 weight class: {os2.usWeightClass}')
name_records = [r for r in f['name'].names if r.nameID in (1,2,4,16,17)]
for r in name_records:
    try: print(f'  name[{r.nameID}]: {r.toUnicode()}')
    except: pass
"
```

Expected output (one of):
- **Variable font** — `axis wght: min=100 default=400 max=900`（或類似範圍）→ 走 Path A
- **Static single weight** — `NOT a variable font; OS/2 weight class: 400` → 走 Path B

- [ ] **Step 2: 記錄結論**

```bash
# 在 commit message 引用即可，無需新增檔案
echo "Decision: <Path A | Path B>" 
```

無 commit。

---

## Task 2 (Path A — 變體字型): 直接同步 login.html

**前提：** Task 1 結果為「變體字型，覆蓋 400-700」。若不是，跳到 Task 3。

**Files:**
- Modify: `src/templates/login.html` (移除 line 7-8, 在 `<style>` 開頭加 @font-face)

- [ ] **Step 1: 編輯 login.html**

移除 line 7-8：
```html
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap" rel="stylesheet">
```

在 `<style nonce="{{ csp_nonce() }}">` (line 9) 之後、`*, *::before, *::after` (line 10) 之前插入：
```css
    @font-face {
      font-family: 'Montserrat';
      font-style: normal;
      font-weight: 400 700;
      font-display: swap;
      src: url('/static/fonts/Montserrat-latin.woff2') format('woff2');
      unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+2074, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD;
    }

```

(逐字複製 `src/static/css/app.css:1-8`，含 unicode-range)

- [ ] **Step 2: 驗證 login.html 無外部 URL**

```bash
grep -nE 'https?://' src/templates/login.html
```
Expected: 0 matches (或只剩註解/SVG namespace)。

- [ ] **Step 3: 啟動 dev server 與瀏覽器驗證**

```bash
# 開 dev GUI（依環境）
python3 -m src.gui &  # 或對應啟動命令
```

在瀏覽器打開 `http://localhost:5000/login`：
- 開 DevTools → Network → 篩選 `fonts.googleapis.com`：應為 0 請求
- 開 DevTools → Console：無 CSP violation
- 視覺：標題與輸入框字型仍為 Montserrat（與修補前一致）
- 切多個 weight (粗體標題、normal 正文) 仍正常

若 dev server 啟動有困難，至少跑 static syntax check：
```bash
python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('src/templates'))
t = env.get_template('login.html')
# render with stub context
out = t.render(t=lambda k: k, csp_nonce=lambda: 'test')
assert 'fonts.googleapis.com' not in out, 'FAIL: still has Google Fonts URL'
assert '@font-face' in out, 'FAIL: missing @font-face'
print('OK: no CDN, has @font-face')
"
```

- [ ] **Step 4: Commit**

```bash
git add src/templates/login.html
git commit -m "fix(gui): remove Google Fonts CDN from login.html (a7 P0)

login.html 仍從 fonts.googleapis.com 載入 Montserrat 4 字重，違反 C1
offline 硬約束並被 CSP font-src='self' 阻擋（造成 a6 layout 破版）。

字型已 self-hosted 於 src/static/fonts/Montserrat-latin.woff2 (37KB);
app.css:1-8 已宣告 @font-face。本 commit 將相同 @font-face 內聯至
login.html 的 <style nonce> 區塊，並移除 2 行 CDN <link>。

Joint fix:
- a7 P0 hard-gate: BLOCKED → CLEAR
- a6 layout 破版: CSP font-src='self' 不再阻擋"
```

---

## Task 3 (Path B — Static 單字重): 升級為變體字型 + 同步 login.html

**前提：** Task 1 結果為「靜態單字重，OS/2 weight class = 400」。當前所有 weight 400/500/600/700 都會 fallback 為 Regular + browser 合成粗體（視覺退化，但可用）。

**選項：**
- **B1 接受合成粗體**（最小變更，跳到 Task 2 走相同流程）
- **B2 升級為變體字型**（推薦，~80-100 KB 換真實字重）

本 plan 走 B2。若選 B1，跳到 Task 2。

**Files:**
- Replace: `src/static/fonts/Montserrat-latin.woff2`（用變體字型版本覆蓋）
- Modify: `src/templates/login.html`（同 Task 2）

- [ ] **Step 1: 取得變體字型 woff2**

選一條路徑：

**A) npm @fontsource (若有 npm 與 internet)**
```bash
cd /tmp
mkdir mfont && cd mfont
npm pack @fontsource-variable/montserrat
tar xzf fontsource-variable-montserrat-*.tgz
ls package/files/montserrat-latin-wght-normal.woff2
```

**B) GitHub Release 手動下載**
```bash
curl -sL https://github.com/JulietaUla/Montserrat/raw/master/fonts/webfonts/Montserrat-latin-VF.woff2 -o /tmp/Montserrat-latin-VF.woff2
ls -la /tmp/Montserrat-latin-VF.woff2
# Expected: 60-100 KB
```

(若兩個路徑都不可用，回退到 B1 接受合成粗體並跳到 Task 2。)

- [ ] **Step 2: 用 fontTools 驗證取得的檔案是變體字型**

```bash
python3 -c "
from fontTools.ttLib import TTFont
f = TTFont('/tmp/Montserrat-latin-VF.woff2')  # 或 npm 路徑
print('fvar:', 'fvar' in f)
if 'fvar' in f:
    for a in f['fvar'].axes:
        print(f'  {a.axisTag}: {a.minValue}-{a.maxValue} default={a.defaultValue}')
"
```

Expected: `fvar: True; wght: 100-900 default=400`（涵蓋 400-700 即可）。

- [ ] **Step 3: 替換現有檔案**

```bash
cd /home/harry/rd/illumio-ops
# 先備份
cp src/static/fonts/Montserrat-latin.woff2 /tmp/Montserrat-latin.woff2.bak
cp /tmp/Montserrat-latin-VF.woff2 src/static/fonts/Montserrat-latin.woff2
ls -la src/static/fonts/Montserrat-latin.woff2
```

新檔大小應為 60-100 KB（vs 原 37 KB）。

- [ ] **Step 4: 套用 Task 2 Step 1-3**（編輯 login.html、驗證無 CDN、瀏覽器測試）

跨檔效應：`src/static/css/app.css` 的 @font-face 已宣告 `font-weight: 400 700`，自動受惠（main app 的標題粗體會變真實粗體）。

- [ ] **Step 5: Commit**

```bash
git add src/static/fonts/Montserrat-latin.woff2 src/templates/login.html
git commit -m "fix(gui): vendor Montserrat variable font + remove CDN from login.html (a7 P0)

升級 src/static/fonts/Montserrat-latin.woff2 為變體字型版本
(static Regular 37KB → variable 100-style 80KB)，使 weight 400-700
請求得到真實字重而非 browser 合成粗體。

同步移除 login.html 第 7-8 行 Google Fonts CDN <link>，內聯與
app.css 一致的 @font-face 至 login 頁面 <style nonce> 區塊。

Joint fix:
- a7 P0 hard-gate: BLOCKED → CLEAR
- a6 layout 破版: CSP font-src='self' 不再阻擋
- 額外: main app 標題粗體升級為真字重"
```

---

## Task 4: 全 repo 重掃 + 確認 P0 解除

**Files:**
- Read-only

- [ ] **Step 1: 重跑 a7 掃描**

```bash
cd /home/harry/rd/illumio-ops
grep -rEn 'https?://' src/templates src/static src/alerts 2>/dev/null \
  | grep -vE ':\s*(#|//|/\*|\*)' \
  > /tmp/a7-rescan.txt
wc -l /tmp/a7-rescan.txt
cat /tmp/a7-rescan.txt
```

Expected output (5 行)：
```
src/templates/login.html:NN  http://www.w3.org/2000/svg     ← namespace, OK
src/static/js/settings.js:208  https://pce.example.com:8443  ← placeholder, OK
src/static/fonts/LICENSE-NotoSansCJK.txt:5  https://github.com/notofonts/noto-cjk  ← license, OK
src/alerts/plugins.py:80  https://api.line.me/v2/bot/message/push  ← server-side API, OK
src/alerts/metadata.py:95  https://hooks.example.com/events  ← placeholder, OK
```

從 7 → 5 命中，且 0 個會被瀏覽器執行載入 → P0 hard-gate **CLEAR**。

- [ ] **Step 2: 更新評估報告 §3.1.0 a7 P0 狀態**

可選 — 如下游 plan 也要納入此狀態變更:

```bash
# 在另一分支 (assessment-execution-2026-05-04) 執行，本分支不動
# 或開另一個 docs-only commit 在 main 後續處理
```

本 plan 不要求修改 assessment 報告（assessment 是「當下狀態」snapshot）。

無 commit。

---

## Task 5: 加入 regression 測試

**Files:**
- Create: `tests/templates/test_no_external_resources.py`

- [ ] **Step 1: 寫測試**

```python
"""
Regression test for a7 P0 hard-gate.
Ensures no template loads external (CDN) resources at runtime, which
would violate C1 offline 硬約束 and the CSP font-src='self' policy.
"""
import re
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent.parent.parent / "src" / "templates"
STATIC_DIR = Path(__file__).parent.parent.parent / "src" / "static"

# URL patterns that ARE allowed (not browser-loaded):
ALLOW_PATTERNS = [
    re.compile(r'http://www\.w3\.org/'),  # XML namespaces
    re.compile(r'pce\.example\.com'),      # placeholder text
    re.compile(r'hooks\.example\.com'),    # placeholder text
]

URL_RE = re.compile(r'https?://[^\s"\'<>)]+')


def _scan_file(path: Path) -> list[tuple[int, str]]:
    violations = []
    for i, line in enumerate(path.read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
        # Skip comments
        stripped = line.lstrip()
        if stripped.startswith(('#', '//', '/*', '*')):
            continue
        for m in URL_RE.finditer(line):
            url = m.group(0)
            if any(p.search(url) for p in ALLOW_PATTERNS):
                continue
            violations.append((i, url))
    return violations


def test_no_external_urls_in_templates():
    failures = []
    for tmpl in TEMPLATE_DIR.rglob('*.html'):
        for line, url in _scan_file(tmpl):
            failures.append(f'{tmpl.relative_to(TEMPLATE_DIR.parent.parent)}:{line}: {url}')
    assert not failures, (
        'External URLs found in templates (violates a7 P0 hard-gate / C1 offline):\n' +
        '\n'.join(failures)
    )


def test_no_external_urls_in_static_css_js():
    failures = []
    for ext in ('*.css', '*.js'):
        for f in STATIC_DIR.rglob(ext):
            for line, url in _scan_file(f):
                failures.append(f'{f.relative_to(STATIC_DIR.parent.parent)}:{line}: {url}')
    assert not failures, (
        'External URLs found in static assets:\n' + '\n'.join(failures)
    )
```

- [ ] **Step 2: 執行測試**

```bash
pytest tests/templates/test_no_external_resources.py -v
```

Expected: 2 passed.

若測試失敗（命中未在白名單的 URL）：擴充 `ALLOW_PATTERNS` 或回頭修正模板。

- [ ] **Step 3: Commit**

```bash
mkdir -p tests/templates
git add tests/templates/test_no_external_resources.py
git commit -m "test(templates): regression test for a7 no-external-resources gate"
```

---

## Task 6: 確認 offline bundle 包含 fonts dir

**Files:**
- Read-only inspection

- [ ] **Step 1: 確認 bundle 腳本涵蓋 fonts**

```bash
cd /home/harry/rd/illumio-ops
grep -nE 'static|fonts|woff2' scripts/build_offline_bundle.sh 2>/dev/null
ls scripts/ | grep -i bundle
```

預期 `src/static/` 目錄已被 bundle 腳本納入（fonts 是 static/ 子目錄）。若未明確列出 `static/fonts/`，但腳本以 `cp -r src/` 之類整目錄複製，仍涵蓋。

- [ ] **Step 2: 試打包驗證**

```bash
# 若有 dev 可跑 bundle 腳本
bash scripts/build_offline_bundle.sh /tmp/test-bundle 2>&1 | tail -20
ls /tmp/test-bundle/**/Montserrat-latin.woff2 2>/dev/null || \
  find /tmp/test-bundle -name 'Montserrat-latin.woff2' 2>/dev/null
```

Expected: 字型檔在 bundle 內。

若不在：在 bundle 腳本明確加入 `src/static/fonts/`。

無 commit（除非 bundle 腳本需修改）。

---

## Task 7: 文件更新

**Files:**
- Modify: `docs/Installation.md` 與 `docs/Installation_zh.md`（如有提及外部依賴的段落）

- [ ] **Step 1: 檢查是否提及 Google Fonts**

```bash
grep -nE 'Google Fonts|fonts\.googleapis|CDN' docs/*.md 2>/dev/null
```

若無命中：跳過 Step 2。

- [ ] **Step 2: 修補文件**

如果文件有「需 internet 載入字型」之類描述，改為「字型已 self-host 於 `src/static/fonts/`，offline 環境無需額外配置」。

- [ ] **Step 3: Commit (僅當 Step 2 有改)**

```bash
git add docs/Installation.md docs/Installation_zh.md
git commit -m "docs(install): clarify Montserrat font is self-hosted, no CDN needed"
```

---

## Self-review checklist

執行完所有 Task 後驗證：

- [ ] `grep -nE 'fonts\.googleapis' src/templates/` → 0 命中
- [ ] `pytest tests/templates/test_no_external_resources.py` → 2 passed
- [ ] login.html 在瀏覽器渲染 — 字型顯示為 Montserrat（或 system fallback 不破版）
- [ ] DevTools 無 CSP violation 訊息
- [ ] DevTools Network 無 fonts.googleapis.com 請求
- [ ] (若走 Path B2) 字型檔大小從 37 KB 升至 60-100 KB
- [ ] 評估報告 §3.1.0 a7 hard-gate 重評：BLOCKED → CLEAR
- [ ] git log 顯示 1-3 個 focused commit (依 Path A/B 與 Task 5/7 是否觸發)

---

## §12 Next steps (post-merge)

本 plan 完成後可解鎖：

1. **a6 hand-off** 可再驗證：CSP font-src='self' 已不再阻擋（無 Google Fonts 載入）→ a6 假設 3 確認解除；剩 hypothesis 1 (mixed-content) 與 hypothesis 4 (cookie) 須 DevTools 實測。
2. **Track A — Visual System** 可啟動：assessment §6.1 B industrial-editorial direction 推薦升級至 Space Grotesk + Inter + JetBrains Mono；本 plan 已示範 self-host 流程，可重用。
3. **Phase 1 quick wins**（assessment §3.1.5 / §3.2.6 / §3.3.6 / §3.4.6 推薦組合的優化路線）可開新 plan。

---

## Self-review of this plan

- ✅ Goal/Architecture/Tech Stack header 完整
- ✅ Reference docs 列出
- ✅ Path A vs Path B 分支決策有 Task 1 預判
- ✅ 每 Task 有 file paths + 完整指令 / code block (無 placeholder)
- ✅ Regression 測試 (Task 5) 防止未來 CDN 引用回潮
- ✅ 文件更新 (Task 7) 條件性 (僅當文件提及外部依賴)
- ⚠️ Browser 端視覺驗證需要可運作的 dev server；plan 提供 Jinja syntax check fallback
- ⚠️ Path B2 需 internet 取得變體字型；plan 提供 B1 fallback（接受合成粗體）

預計執行時間：
- Path A: 30-60 分鐘 (1 commit + 測試)
- Path B2: 1-2 小時 (含字型下載 + 驗證 + 2 commits)
