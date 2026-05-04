# UX / CLI / Report / Email 全域評估執行 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依 `docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-design.md` 定義的結構與 rubric，實際執行掃描、打分、繪製 mockup，產出單一「評估報告」doc 並 commit。

**Architecture:** 計畫產出一份新檔 `docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md`，其結構鏡像 design spec，但所有 `_TBD_` 表格 / 候選評分 / 痛點卡 / 推薦組合皆填入實際資料。Mockup 經由 Visual Companion（已在執行中：`http://localhost:54403`）產出 HTML 片段，存於 `.superpowers/brainstorm/3034647-1777877764/content/`，並把 screenshot/連結回引到 §7 appendix。

**Tech Stack:** ripgrep、wc、stat、radon、git；Python 3.12 venv；Visual Companion server（已啟動）；Playwright（用於 GUI 截圖證據，可選）。

**Reference docs:**
- Design spec: `docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-design.md`
- Methodology rubric: design spec §2 全章
- Pain card 模板: design spec §4 開頭

---

## Phase 0 — Setup

### Task 0.1: 建立評估報告骨架

**Files:**
- Create: `docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md`

- [ ] **Step 1: 確認 Python venv 與工具可用**

```bash
cd /home/harry/rd/illumio-ops
python3 -c "import radon" 2>&1 || pip install radon
which rg && which wc && which stat
```

Expected: 所有指令存在；radon 可 import。若 radon 缺失，pip install。

- [ ] **Step 2: 建立 report skeleton（複製 design spec 標題結構，去掉所有 spec 描述、保留章節骨架）**

把 design spec 的標題結構（§1 - §11）複製到新檔，標題下加 placeholder「（評估執行階段尚未填入）」並保留所有表格 schema。報告檔案頂部 frontmatter：

```markdown
---
Title: UX / CLI / Report / Email 全域評估報告
Source spec: docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-design.md
Status: in-progress (Phase 0 complete, 後續 Phase A-H 填入)
Generated: 2026-05-04
---

# UX / CLI / Report / Email 全域評估報告

> 本檔依 design spec 結構鏡像產出。每個 §X.Y 對應 design spec 同編號章節的「填入結果」。
> 方法學 / rubric 定義皆引用 design spec，不在此重複。

[僅保留 §1 - §11 章節標題與必要表格骨架，不複製 spec 的方法學內容]
```

- [ ] **Step 3: Verify**

```bash
test -f docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md && echo OK
grep -c '^##\|^###' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
```

Expected: file exists；至少 30 個 ## / ### 標題。

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "docs(assessment): bootstrap report skeleton mirroring design spec structure"
```

---

## Phase A — Inventory & Scanning

### Task A.1: External resource 掃描 (§3.1.0 a7) — P0 hard-gate

**Files:**
- Modify: `report.md` §3.1.0 a7 子節
- Create: `.superpowers/brainstorm/3034647-1777877764/data/a7-external-resources.tsv`（暫存掃描結果）

- [ ] **Step 1: 執行掃描**

```bash
cd /home/harry/rd/illumio-ops
mkdir -p .superpowers/brainstorm/3034647-1777877764/data
rg -n --no-heading 'https?://' src/templates src/static src/alerts \
  | rg -v ':\s*(#|//|/\*|\*)' \
  | tee .superpowers/brainstorm/3034647-1777877764/data/a7-external-resources-raw.txt
wc -l .superpowers/brainstorm/3034647-1777877764/data/a7-external-resources-raw.txt
```

Expected: 列出每個 `https?://` 命中（檔:行:內容）。若 0 行 → 還是要記為「無違規」並繼續。

- [ ] **Step 2: 整理為違規清單表（手動分類每個命中）**

對每行命中：
1. 判定資源類型：CSS / JS / font / img / icon / favicon / link 文件
2. 判定是否為「執行階段被瀏覽器載入」（vs 註解 / 文件連結 / API endpoint 配置）
3. 對「真正會被載入的外部資源」給出替代本地 asset 建議：
   - Google Fonts → vendor/fonts/ + 自託管
   - jsdelivr/unpkg/cdnjs/cloudflare-cdn → vendor/{js,css}/
   - icon CDN → vendor/icons/ SVG sprite
   - favicon → src/static/

把整理結果寫入 TSV：

```
file<TAB>line<TAB>url<TAB>resource_type<TAB>blocked_by_https<TAB>vendor_mapping
```

存到 `.superpowers/.../data/a7-external-resources.tsv`。

- [ ] **Step 3: 把整理後的表格寫入 report.md §3.1.0 a7**

格式（沿用 design spec §3.1.0 a7 表格 schema）：

```markdown
##### a7 — UI 依賴 external resources（違反 C1）

掃描日期：2026-05-04
總命中數：N（其中真正違反 = M）

| 檔案 | 行 | URL | 資源類型 | 被 HTTPS 阻擋 | 替代本地 asset 建議 |
|---|---|---|---|---|---|
| ... | ... | ... | ... | ✓/✗ | ... |

Vendor 化目標位置（彙整）：
- vendor/fonts/ ← N 個 webfont
- vendor/js/ ← N 個 JS
- vendor/css/ ← N 個 CSS
- vendor/icons/ ← N 個 icon

P0 hard-gate 狀態：BLOCKED / CLEAR
```

- [ ] **Step 4: Verify**

```bash
grep -A 5 '^##### a7' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md | head -30
```

Expected: 看到「掃描日期」+「總命中數」+ 至少一行表格資料（或明確「無違規」）。

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(a7): external resources scan — N hits, M真正違反 (P0 hard-gate)"
```

---

### Task A.2: GUI bundle / asset sizing (§3.1.1)

**Files:**
- Modify: `report.md` §3.1.1
- Create: `.superpowers/.../data/gui-bundle-sizes.txt`

- [ ] **Step 1: 量化檔案大小**

```bash
cd /home/harry/rd/illumio-ops
{
  echo "=== templates ==="
  wc -l -c src/templates/*.html
  echo "=== JS ==="
  wc -l -c src/static/js/*.js
  echo "=== CSS ==="
  wc -l -c src/static/css/*.css
  echo "=== TOTAL JS bytes ==="
  wc -c src/static/js/*.js | tail -1
  echo "=== TOTAL CSS bytes ==="
  wc -c src/static/css/*.css | tail -1
} | tee .superpowers/brainstorm/3034647-1777877764/data/gui-bundle-sizes.txt
```

- [ ] **Step 2: 跑 radon CC + MI 對 JS 之外的 src/gui + src/templates 渲染邏輯（Python side）**

```bash
radon cc src/gui/ -s -a -nc | tee -a .superpowers/.../data/gui-bundle-sizes.txt
radon mi src/gui/ -s | tee -a .superpowers/.../data/gui-bundle-sizes.txt
```

註：JS 沒有 radon 對應工具，只看大小 + 行數即可。

- [ ] **Step 3: 整理進 report.md §3.1.1**

寫入：
- 檔案大小表（按大小降冪排序，>5KB 標 yellow flag、>20KB red flag）
- 總計（JS 總 KB / CSS 總 KB / template 總 KB）
- radon CC 高 complexity（>10）函式清單
- radon MI 低分（<20）模組清單
- `dashboard.js` 與 `dashboard_v2.js` 共存的觀察 → 確認是否其一已棄用（讀檔頂部 docstring / git log 末次修改時間）
- 進行中重構訊號：blueprint split (h5)、settings reorg (h6)
- 外部資源計數（從 §3.1.0 a7 匯總）

- [ ] **Step 4: Verify**

```bash
grep -A 30 '^#### §3.1.1' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md | head -50
```

Expected: 看到實際 KB 數字、至少 5 個檔案行、red/yellow flag 標記。

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(gui): bundle sizing + radon CC/MI for §3.1.1"
```

---

### Task A.3: GUI 模組依賴圖 (§3.1.1 補充)

**Files:**
- Modify: `report.md` §3.1.1（接續 A.2）

- [ ] **Step 1: 建構 JS 引用關係**

```bash
cd /home/harry/rd/illumio-ops
# 找 templates/ 中的 <script src=> 引用順序
rg -no '<script[^>]*src="[^"]+"' src/templates/index.html
# 找 JS 模組之間的 import / require / include
rg -n 'import\s|require\(' src/static/js/
```

- [ ] **Step 2: 整理依賴關係 ASCII 圖**

寫入 report.md §3.1.1 末段：

```
Bundle 載入順序（由 index.html）：
1. utils.js
2. _event_dispatcher.js
3. tabs.js
...

JS 模組關聯：
[繪製 ASCII 樹狀圖或鄰接表]

defer/async 使用率：N% script 用 defer，0% 用 async（或實際數字）
```

- [ ] **Step 3: Verify**

`grep -A 10 'Bundle 載入順序' report.md` 看到至少 5 行順序。

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(gui): JS load order + dependency graph for §3.1.1"
```

---

### Task A.4: CLI 命令 inventory (§3.2.1)

**Files:**
- Modify: `report.md` §3.2.1

- [ ] **Step 1: 列出每個入口的命令**

```bash
cd /home/harry/rd/illumio-ops
# CLI root
python -m src.cli.root --help 2>&1 || python illumio-ops.py --help 2>&1
# 三支獨立 CLI
python src/pce_cache_cli.py --help 2>&1
python src/rule_scheduler_cli.py --help 2>&1
python src/siem_cli.py --help 2>&1
# 互動 menu — 看程式碼結構
ls src/cli/menus/
grep -h 'def \|click.command\|argparse' src/cli/menus/*.py | head -50
```

捕捉每個指令的：name、verb、noun、flags、help 文字。

- [ ] **Step 2: 對每個命令補欄位**

對每個命令逐一檢查（讀程式碼）：
- 輸出格式預設（rich table / plain / json）
- 退出碼定義（grep `sys.exit\|exit(`）
- isatty 處理（grep `isatty`）
- `--json` flag 是否存在
- 互動 menu 是否也露出此命令

- [ ] **Step 3: 整理為 markdown 表格寫入 §3.2.1**

完整表格（schema 沿 design spec §3.2.1）：

```markdown
| 入口 | 命令 | verb | noun | flags | 輸出格式 | exit codes | isatty 處理 | --json | menu 也露出？ |
|---|---|---|---|---|---|---|---|---|---|
| root | rule list | list | rule | --filter, --json | rich table | 0/1 only | yes | yes | no |
| ... |
```

預估列數：10-30 個命令。

- [ ] **Step 4: Verify**

```bash
awk '/^#### §3.2.1/,/^#### §3.2.2/' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md | grep -c '^|'
```

Expected: ≥ 12 行（header + separator + ≥ 10 個命令）

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(cli): command inventory across 4 entry points for §3.2.1"
```

---

### Task A.5: TTY 旗標掃描 + Composability 掃描 (§3.2.2 + §3.2.3 起點)

**Files:**
- Modify: `report.md` §3.2.2

- [ ] **Step 1: 掃 isatty / NO_COLOR / stderr 用法**

```bash
cd /home/harry/rd/illumio-ops
{
  echo "=== isatty ==="; rg -n 'isatty\(\)' src/
  echo "=== NO_COLOR ==="; rg -n 'NO_COLOR' src/
  echo "=== TERM env ==="; rg -n "os.environ.*TERM" src/
  echo "=== stderr 用法 ==="; rg -n 'sys\.stderr|file=sys\.stderr' src/
  echo "=== sys.exit codes ==="; rg -n 'sys\.exit\([0-9]+\)|exit\([0-9]+\)' src/cli src/pce_cache_cli.py src/rule_scheduler_cli.py src/siem_cli.py
} | tee .superpowers/.../data/cli-tty-flags.txt
```

- [ ] **Step 2: 比對 §3.2.1 inventory，產出 consistency matrix**

對每個命令逐項標 ✓/✗：
- isatty 處理 ✓/✗
- stderr 訊息 ✓/✗
- exit code 自訂 ✓/✗ 還是只用 0/1
- `--json` ✓/✗
- `--quiet` / `--verbose` ✓/✗

把 §3.2.2 的 6 類 inconsistency 一一列出（沿 design spec schema）：
1. 旗標命名不一致清單
2. verb-noun 順序不一致清單
3. 輸出格式預設不一致清單
4. 退出碼定義 / 未定義清單
5. global flags 位置不一致
6. `ILLUMIO_OPS_*` 命中率（grep）

- [ ] **Step 3: Verify**

```bash
awk '/^#### §3.2.2/,/^#### §3.2.3/' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md | wc -l
```

Expected: ≥ 30 行（足以涵蓋 6 類 inconsistency）

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(cli): consistency matrix + TTY flags scan for §3.2.2"
```

---

### Task A.6: Report inventory (§3.3.1)

**Files:**
- Modify: `report.md` §3.3.1

- [ ] **Step 1: 量化每份 report**

```bash
cd /home/harry/rd/illumio-ops
{
  echo "=== generators ==="
  wc -l src/report/audit_generator.py src/report/policy_usage_generator.py src/report/ven_status_generator.py src/report/report_generator.py
  echo "=== exporters ==="
  wc -l src/report/exporters/*.py
  echo "=== i18n keys 估算 ==="
  python -c "import json; d=json.load(open('src/i18n_zh_TW.json')); print('total keys:', len(d))"
  python -c "import json; d=json.load(open('src/i18n_zh_TW.json')); audit=[k for k in d if 'audit' in k]; pol=[k for k in d if 'polic' in k]; ven=[k for k in d if 'ven' in k]; print(f'audit:{len(audit)} policy:{len(pol)} ven:{len(ven)}')"
} | tee .superpowers/.../data/report-inventory.txt
```

- [ ] **Step 2: 確認 `report_generator.py` + `html_exporter.py` 是否為 legacy**

```bash
git log --oneline -10 src/report/report_generator.py src/report/exporters/html_exporter.py
grep -l 'from .* import.*report_generator\|from .* import.*html_exporter' src/ -r
```

讀 file 頂部 docstring。判定：active / legacy / deprecated / 並存。

- [ ] **Step 3: 跑一次每個 report 的 sample 產生，量化平均輸出**

若可在 dev 環境跑：

```bash
# 在 dev venv 中
python illumio-ops.py report audit --output /tmp/audit.html 2>&1 | tail -10
python illumio-ops.py report policy_usage --output /tmp/pol.html 2>&1 | tail -10
python illumio-ops.py report ven_status --output /tmp/ven.html 2>&1 | tail -10
wc -c /tmp/*.html
```

若無法跑（缺資料），則跳過此 step，在 §3.3.1 註記「平均輸出大小：須 in-situ 觀察，本評估暫缺」。

- [ ] **Step 4: 整理 inventory table 寫入 §3.3.1**

```markdown
| Report | Generator | Exporters | i18n keys 數 | 平均輸出大小 | 主要 sections | 狀態 |
|---|---|---|---|---|---|---|
| audit | audit_generator.py (35.6KB) | audit_html, pdf, csv, xlsx | ~N | ~M KB | summary, findings, appendix | active |
| ... |
```

加註：legacy `report_generator.py` + `html_exporter.py` 是否確認退場？若是 → 列入 §9 Out-of-scope（已退場）；若否 → 列入待處理 finding。

- [ ] **Step 5: Verify + Commit**

```bash
grep -c '^|' <(awk '/^#### §3.3.1/,/^#### §3.3.2/' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md)
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(report): inventory across audit/policy/ven generators for §3.3.1"
```

Expected grep: ≥ 6 行表格

---

### Task A.7: Email template inventory (§3.4.1)

**Files:**
- Modify: `report.md` §3.4.1

- [ ] **Step 1: 確認模板引擎與變數契約**

```bash
cd /home/harry/rd/illumio-ops
ls -la src/alerts/templates/
cat src/alerts/templates/mail_wrapper.html.tmpl
cat src/alerts/templates/line_digest.txt.tmpl
cat src/alerts/templates/webhook_payload.json.tmpl
# 找渲染入口
rg -n 'mail_wrapper|line_digest|webhook_payload' src/alerts/
rg -n 'render_template\|str.format\|jinja\|Template\(' src/alerts/
```

- [ ] **Step 2: 列出每個模板的 placeholder / 變數**

對每個 .tmpl 檔，列出所有 `{var}` 或 `{{ var }}` 並回查 placeholder 來源（哪個 Python module 提供值）。

- [ ] **Step 3: 寫入 §3.4.1**

```markdown
| 模板 | 大小 | 引擎 | placeholder 數 | 來源 module | 用於通道 |
|---|---|---|---|---|---|
| mail_wrapper.html.tmpl | 2.5 KB | str.format / Jinja | N | src/alerts/plugins.py | mail |
| line_digest.txt.tmpl | ... | ... | N | ... | line |
| webhook_payload.json.tmpl | ... | ... | N | ... | webhook |

變數契約彙整：
- 共用變數：title, severity, message, ts_local
- 通道專屬：（列出）
```

- [ ] **Step 4: Verify + Commit**

```bash
grep -A 15 '^#### §3.4.1' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md | head -20
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(email): template inventory + variable contracts for §3.4.1"
```

---

## Phase B — Pre-conditions hand-off

### Task B.1: a6 HTTPS 破版驗證 dry-run + hand-off doc

**Files:**
- Modify: `report.md` §3.1.0 a6

- [ ] **Step 1: 跑 design spec 驗證步驟**

```bash
cd /home/harry/rd/illumio-ops
# 啟動 GUI（需在 dev venv）
# 兩種模式 curl 比對
curl -sk -I https://127.0.0.1:5001/ 2>&1 | head -20
curl -s -I http://127.0.0.1:5000/ 2>&1 | head -20
# 抓 secure_cookie 與 CSP 設定
rg -n 'secure_cookie|SECURE_COOKIE|Content-Security-Policy|CSP' src/gui/
```

若 GUI 沒在跑，至少把 secure_cookie / CSP 設定點抓出來。

- [ ] **Step 2: 整理 4 個成因假設的「驗證結果（如已有訊號）」**

對每個假設標：「待驗證 / 已確認 / 已排除」並附證據。

- [ ] **Step 3: 寫入 §3.1.0 a6 的 hand-off**

```markdown
##### a6 — HTTPS 啟用後 layout 破版

驗證日期：2026-05-04
本評估狀態：成因清單已給可靠性 sprint，本 spec 不修。

成因假設驗證表：
| 假設 | 狀態 | 證據 |
|---|---|---|
| 1. Mixed-content blocking | 待驗證 | DevTools 重現待你方執行 |
| 2. external resources 走 http:// | 已確認 / 已排除 | 與 a7 比對：a7 共 N 個外部資源中 M 個走 http:// |
| 3. CSP 配置缺失或過嚴 | 待驗證 | src/gui/__init__.py 中 CSP 設定為...（或：未設定 CSP） |
| 4. Cookie SameSite/Secure | 待驗證 | secure_cookie 設定點：src/gui/__init__.py:NN |

Hand-off owner：可靠性 sprint
建議優先處理：a2（與 a7 同源關係最強）
```

- [ ] **Step 4: Verify + Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(a6): HTTPS layout 破版 hand-off — 成因假設驗證 + owner"
```

---

### Task B.2: a7 vendor mapping plan 細化

**Files:**
- Modify: `report.md` §3.1.0 a7（補強 vendor 化建議）

- [ ] **Step 1: 把 A.1 的違規 URL 對應到 vendor 化具體 plan**

對每個違規 URL：
1. 找該檔案的 license（commercial / MIT / OFL / etc.）
2. 確認是否有 offline 友善的 vendor 來源（npm package / GitHub release）
3. 給具體 vendor 路徑與檔名

範例：
```
Google Fonts "Inter" → vendor/fonts/Inter/{Inter-Regular.woff2, Inter-Bold.woff2} + @font-face declaration in app.css
jsdelivr Chart.js 4.x → vendor/js/chart.umd.min.js + version pin
unpkg lucide-icons → vendor/icons/lucide.svg sprite (preferred over individual SVG)
```

- [ ] **Step 2: 寫入 §3.1.0 a7 的「Vendor 化執行 plan」附段**

```markdown
Vendor 化執行 plan（hand-off 給 implementation）：

| URL（原） | License | Vendor 路徑 | 取得方式 | size |
|---|---|---|---|---|
| https://fonts.googleapis.com/... | OFL | vendor/fonts/Inter/ | npm download or GitHub release | ~50KB |
| ... |

bundle 影響：vendor 增加 ~N KB；offline bundle 預估增量 ~M MB（如包進 wheels/）。
```

- [ ] **Step 3: Verify + Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(a7): vendor mapping plan with license + size impact"
```

---

## Phase C — UX rubric scoring

### Task C.1: GUI UX rubric (§3.1.2)

**Files:**
- Modify: `report.md` §3.1.2

- [ ] **Step 1: 對 GUI 跑 ui-ux-pro-max 10 類人工評分**

開啟 dev GUI（若可），對每類 0-3 分。每類至少捕捉一個證據（檔案:行 / DevTools snapshot / 描述）。

| 類別 | Score | Key Finding（≤ 2 行） | 觸及痛點 |
|---|---|---|---|
| §1 Accessibility (CRITICAL) | N | ... | a1 |
| §2 Touch & Interaction | N | ... | — |
| §3 Performance (CRITICAL) | N | ... | a1 |
| §4 Style Selection | N | ... | a2 |
| §5 Layout & Responsive | N | ... | a6 |
| §6 Typography & Color | N | ... | (cross-cutting visual) |
| §7 Animation | N | ... | — |
| §8 Forms & Feedback (CRITICAL) | N | ... | a2 |
| §9 Navigation Patterns | N | ... | a1 |
| §10 Charts & Data | N | ... | (Report side) |

CRITICAL 類任一 = 0 → 在末段標記「自動拉 P1 痛點：(列出)」

- [ ] **Step 2: 寫入 §3.1.2**

整段表格 + 簡短總結（3-5 行說 GUI 整體 UX 體質如何）。

- [ ] **Step 3: Verify + Commit**

```bash
awk '/^#### §3.1.2/,/^#### §3.1.3/' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md | grep -c '^|'
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(gui): UX rubric scoring 10 categories for §3.1.2"
```

Expected grep: ≥ 12 行（header + separator + 10 類）

---

### Task C.2: GUI Visual Identity 現況評估 (§3.1.3)

**Files:**
- Modify: `report.md` §3.1.3

- [ ] **Step 1: frontend-design 5 維度 + Distinctiveness 打分**

對 GUI 現況（含 redesign 後狀態）逐項評：

| 維度 | Score | Finding |
|---|---|---|
| Typography | N | 字體：system-ui / Inter / 其他；配對：是否有 heading vs body 差異？mono 字體？ |
| Color | N | 主色：（mem 訊號「綠色」）；accent 節制度；semantic token 化；light/dark dual？ |
| Motion | N | 現有動畫：（描述）；meaningful or decorative？ |
| Spatial Composition | N | 對稱 / 不對稱；密度層級；whitespace 比例 |
| Backgrounds & Details | N | 純 solid color / 漸層 / texture / 陰影 / pattern |
| **Distinctiveness** | N | 整體：「unforgettable thing」存在嗎？描述當前美學定位 |

**當前美學定位**：（以 1-2 句概括）generic admin / Bootstrap-default / 「綠色但無系統」/ ...

- [ ] **Step 2: Verify + Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(gui): Visual Identity 5-dim + Distinctiveness for §3.1.3"
```

---

### Task C.3: CLI rubric (§3.2.4)

**Files:**
- Modify: `report.md` §3.2.4

- [ ] **Step 1: ui-ux-pro-max 轉譯版 7 類**

對每類打 0-3：§1 / §3 / §5 / §7 / §8 / §9 / §10（依 design spec §3.2.4 列表）。

| 類別 | Score | Finding | 觸及痛點 |
|---|---|---|---|
| §1 Accessibility (CRITICAL) | N | NO_COLOR 支援？SR-friendly 輸出？ | b6 |
| §3 Performance | N | 啟動時間 / 首字延遲 | b3 |
| §5 Layout & Responsive | N | TTY 寬度自適應；CJK 對齊 | b3 |
| §7 Animation | N | spinner 用法 | b3 |
| §8 Forms & Feedback (CRITICAL) | N | error-clarity；確認 destructive | b4 |
| §9 Navigation Patterns | N | back-behavior；state-preservation | b1 |
| §10 Charts & Data | N | 表格顯示；large-dataset 分頁 | b3 |

- [ ] **Step 2: §2.5 CLI rubric 12 條**

逐條 0-3：

| # | 規則 | Score | Finding | 觸及痛點 |
|---|---|---|---|---|
| 1 | 命令文法一致性 | N | （引用 §3.2.2 inconsistency 數） | b2 |
| 2★ | 能力偵測 | N | isatty 命中 N/M；NO_COLOR 命中 N/M | b6 |
| 3★ | Composability | N | stderr/stdout 分流；--json 命中率 | b6 |
| 4★ | Exit codes | N | 自訂命中 N/M；標準 130 命中 ✓/✗ | b7 |
| 5 | Idempotency / dry-run | N | --dry-run / --force 命中清單 | (cross) |
| 6 | 配置層級 | N | ILLUMIO_OPS_* 命中 N | (cross) |
| 7 | 互動 vs 非互動雙模 | N | TTY/pipe 行為差異 | b6 |
| 8 | 長任務 | N | progress + ETA + interrupt | b3 |
| 9 | --help / man | N | 範例 / 子命令樹完整度 | b8 |
| 10 | Auto-completion | N | bash/zsh 提供？ | b8 |
| 11 | 雙入口整合 | N | 互動 menu vs 獨立 CLI 對等性 | b5 |
| 12 | Error actionability | N | did-you-mean 命中？ | b4 |

★ 三條基本盤任一 = 0 → 末段標「自動 P1：(列出)」。

- [ ] **Step 3: 寫入 §3.2.4 + 總結**

3-5 行總結：CLI 整體 UX 體質的關鍵 finding。

- [ ] **Step 4: Verify + Commit**

```bash
awk '/^#### §3.2.4/,/^#### §3.2.5/' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md | wc -l
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(cli): UX rubric (7 cats transl) + TTY rubric (12 rules) for §3.2.4"
```

Expected wc: ≥ 30 行

---

### Task C.4: Report content audit (§3.3.2)

**Files:**
- Modify: `report.md` §3.3.2

- [ ] **Step 1: 對每份 report sample 做 content audit**

若可取得 sample HTML / PDF 輸出（從 A.6 step 3）：

```bash
# 章節長度（用 pandoc / 簡單 grep）
for f in /tmp/audit.html /tmp/pol.html /tmp/ven.html; do
  echo "=== $f ==="
  rg -c '<h2|<h3' "$f" 2>/dev/null
  wc -c "$f"
done
```

對每份 report 評：

- 章節長度分布（中位數 / max 字數）
- 摘要密度：開頭 200 字能否 standalone 說完 What/Why/Action？
- Jargon 清單：grep 出 boundary / ringfence / ven / href / enforcement-mode 等出現次數，並列「i18n 是否有人話替代」

- [ ] **Step 2: Verdict 一致性檢查**

```bash
# 對同一 verdict 在 chart label / table cell / appendix 各處的用語比對
rg -n 'Allowed|Blocked|Potentially-Blocked|Potentially_blocked|allowed|blocked' src/report/ src/i18n_en.json src/i18n_zh_TW.json | head -50
```

列出不一致處（例：chart 用 `Allowed` / table 用 `已允許` / appendix 用 `OK`）。

- [ ] **Step 3: 跨報告連結 + 空資料 + i18n 一致性**

讀 generator 程式碼確認：
- 跨報告連結：是否有 `<a href="../audit_report.html">` 之類？
- 空資料 / 空章節：grep `if not data\|else:.*empty` 的處理 pattern
- i18n 一致性：列已修案例（Online/Offline → 在線/離線）+ 待修候選

- [ ] **Step 4: Illumio 術語留英策略**

依近期 commit（455f5f0、25d0926、c349f37）整理「留英 vs 譯中」原則：
- **留英**：Illumio 工程術語（Allowed/Blocked/Managed/Unmanaged/boundary/ringfence/ven/href/enforcement_mode）
- **譯中**：UI 動詞、狀態 pill（Online/Offline → 在線/離線）、操作按鈕

寫入 §3.3.2 末段（OQ-10 default 預設處理）。

- [ ] **Step 5: 整合進 §3.3.2 + Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(report): content audit — length/jargon/verdict/i18n for §3.3.2"
```

---

### Task C.5: Report Visual Identity 現況 (§3.3.3)

**Files:**
- Modify: `report.md` §3.3.3

- [ ] **Step 1: frontend-design 5 維度（document context，Typography 高權重）**

對 HTML 報告 + PDF 報告分別評：

| 維度 | HTML score | PDF score | Finding |
|---|---|---|---|
| Typography | N | N | 標題 / 正文字體；CJK fallback (PDF 已修)；tabular figures 使用 |
| Color | N | N | semantic palette；verdict 配色 colorblind-safe；light vs dark |
| Motion | N | N/A | HTML expand/collapse 動畫？ |
| Spatial | N | N | grid / 章節節奏 / 空白 / 圖表佔幅 |
| Backgrounds | N | N | cover / divider / 章節編號 / 頁眉頁腳 |
| Distinctiveness | N | N | 整體 |

- [ ] **Step 2: Verify + Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(report): Visual Identity 5-dim (HTML+PDF split) for §3.3.3"
```

---

### Task C.6: Email cross-client audit (§3.4.2)

**Files:**
- Modify: `report.md` §3.4.2

- [ ] **Step 1: 對 mail_wrapper.html.tmpl 做 known-issue checklist**

逐項檢查（不實測，只看 template 程式碼）：

| 檢查項 | 通過？ | 說明 |
|---|---|---|
| Table-based layout（vs div） | ✓/✗ | 看 mail_wrapper 用 `<table>` 還是 `<div>` |
| Inline CSS（vs `<style>`） | ✓/✗ | 看 CSS 是 inline 還是 `<style>` 區塊 |
| Img alt + width/height | ✓/✗ | 看 `<img>` 屬性完整度 |
| Webfont 不引用 | ✓/✗ | 看是否有 `@font-face` 或 Google Fonts |
| Position/flex/grid 不使用 | ✓/✗ | grep CSS |
| Bulletproof CTA (VML) | ✓/✗ | 看是否有 `<v:roundrect>` for Outlook |
| Dark mode 反轉處理 | ✓/✗ | 看是否有 `prefers-color-scheme` 或 `<meta name="color-scheme">` |
| 文字版 fallback | ✓/✗ | 看渲染端是否組 multipart/alternative |

每項加證據（檔:行）。

- [ ] **Step 2: 寫入 §3.4.2 + Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(email): cross-client compatibility checklist for §3.4.2"
```

---

### Task C.7: Email actionability audit (§3.4.4)

**Files:**
- Modify: `report.md` §3.4.4

- [ ] **Step 1: 看 mail_wrapper 與 plugins.py 確認**

逐項：
- Subject line pattern：grep render 處的 `subject=` / `Subject:`
- Preheader：HTML 開頭是否有 hidden 30-90 字符 preview text？（grep `display:none`）
- CTA：是否有按鈕 + deep link？deep link 直開 GUI 對應頁？
- Hierarchy：開信 5 秒內能說完 What-Why-Action？

對照範例：選一個近期 alert payload，逐項標通過 / 失敗。

- [ ] **Step 2: 寫入 §3.4.4 + Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(email): actionability audit (subject/preheader/CTA/hierarchy) for §3.4.4"
```

---

## Phase D — Visual Identity Direction

### Task D.1: §6.1 GUI direction 候選 4 個 spec sheet

**Files:**
- Modify: `report.md` §6.1

- [ ] **Step 1: 對 4 個候選（A 維持 / B industrial-editorial / C modern-saas / D dark-ops）逐項打 frontend-design 5 維度分**

| 候選 | Typography | Color | Motion | Spatial | Backgrounds | Distinct | 適用 P1/P2 |
|---|---|---|---|---|---|---|---|
| A. 維持 | （引 §3.1.3 分數） | | | | | | |
| B. industrial-editorial | 3 | 3 | 2 | 3 | 2 | 2 | 高 |
| C. modern-saas | 1 | 2 | 2 | 1 | 1 | 1 | 中 |
| D. dark-ops | 3 | 3 | 2 | 2 | 3 | 3 | P2 高 / P1 中 |

- [ ] **Step 2: 對每個候選給完整 spec sheet（≥ 9 欄）**

對 B / C / D 各填：
- 描述（1-2 行）
- 適用 persona
- Color palette（light：base / surface / accent / signal-success/warning/danger；dark 同）
- Typography：heading + body + mono 字體名 + 替代 fallback
- Iconset：Lucide / Heroicons / 其他
- Motion：duration token + easing
- Density level：dashboard 高 / settings 中 / empty 低
- Touch radius 估算
- Risk

- [ ] **Step 3: 推薦 + 理由**

依 §3.1.3 現況 + persona weight + offline 友善度，給推薦：B 或 D，附 3-5 行理由。

- [ ] **Step 4: Adopted Direction Spec Sheet**

把推薦選項擴展為「token 定義表」：

```css
:root {
  --color-base: ...;
  --color-surface: ...;
  --color-text-primary: ...;
  --color-accent: ...;
  --color-signal-success: ...;
  --color-signal-warning: ...;
  --color-signal-danger: ...;
  --color-signal-info: ...;
  --space-1: 4px; --space-2: 8px; ...
  --radius-sm: 2px; --radius-md: 4px; ...
  --shadow-sm: ...; --shadow-md: ...;
  --motion-fast: 150ms ease-out;
  --motion-slow: 300ms ease-out;
}
```

- [ ] **Step 5: Verify + Commit**

```bash
awk '/^### §6.1/,/^### §6.2/' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md | wc -l
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(visual): §6.1 GUI direction — 4 candidates + adopted spec sheet"
```

Expected wc: ≥ 80 行

---

### Task D.2: §6.2 Report+Email direction 候選 4 個 spec sheet

**Files:**
- Modify: `report.md` §6.2

- [ ] **Step 1: 對 4 個候選（A 維持 / B editorial-magazine / C data-journalism / D corporate-formal）打分**

權重：Typography 最高、Motion 最低。

| 候選 | Typography | Color | Spatial | Backgrounds | Distinct | 適用 P5 |
|---|---|---|---|---|---|---|
| A 維持 | （引 §3.3.3） | | | | | |
| B editorial-magazine | 3 | 3 | 3 | 2 | 2 | 高 |
| C data-journalism | 3 | 3 | 3 | 2 | 2 | 中 |
| D corporate-formal | 3 | 2 | 3 | 2 | 1 | 高（合規 audience） |

- [ ] **Step 2: 對 B / C / D 各填 spec sheet**

含：
- Type scale（含 print 段供 PDF）
- Cover page 設計
- 章節節奏（H1/H2/H3 上下空白）
- Tabular figures + 圖表配色
- Email 子集（刪 webfont、刪 grid、保留色票 primitive）

- [ ] **Step 3: 推薦 + 理由 + Adopted spec sheet**

預設推薦 B（依 design spec §6.2 default）。

- [ ] **Step 4: Verify + Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(visual): §6.2 Report+Email direction — 4 candidates + adopted"
```

---

### Task D.3: §6.3 共享 primitive decision

**Files:**
- Modify: `report.md` §6.3

- [ ] **Step 1: 確認 OQ-7 default**

預設：共享色票 primitive（`--color-base`、`--color-signal-*`）；分開 type-scale + spacing-scale。

- [ ] **Step 2: 寫入 §6.3 + 給共享色票表**

| Token | GUI value | Report/PDF value | Email value (subset) |
|---|---|---|---|
| --color-signal-success | #... | #... | #... |
| --color-signal-warning | #... | #... | #... |
| --color-signal-danger | #... | #... | #... |
| --color-signal-info | #... | #... | #... |
| --color-base | （各自） | （各自） | （各自） |

- [ ] **Step 3: Verify + Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(visual): §6.3 shared color primitives across GUI/Report/Email"
```

---

## Phase E — Pain card drafting (16 cards)

> 每張卡使用 design spec §4 開頭定義的統一格式。每張卡是一個「mini-task」，建議在同一個 commit 內完成同子系統內的 2-4 張卡（節省 commit 數量）。

### Task E.1: GUI cards (4.1 a1, 4.2 a2, 4.3 a6, 4.4 a7)

**Files:**
- Modify: `report.md` §4.1 / §4.2 / §4.3 / §4.4

- [ ] **Step 1: 4.3 a6 + 4.4 a7（pre-condition cards）**

兩張卡較簡：

```markdown
### 4.3 — a6 HTTPS 啟用後 layout 破版

| | |
|---|---|
| Subsystem | GUI |
| 觸及 persona | P1 P2 |
| Pre-condition | **是 → 詳情見 §3.1.0 a6** |
| Score | （不算 score，直接 P0） |
| 優先級 | **P0** |

本卡為 §3.1.0 a6 的 cross-reference shorthand。
完整成因清單、驗證步驟、hand-off owner 在 §3.1.0 a6。
```

4.4 a7 同款。

- [ ] **Step 2: 4.1 a1（GUI tab 載入體驗）**

完整 11 欄填入：
- 現況片段：bundle 大小（從 §3.1.1）+ 首頁 `<script>` 同步載入無 defer/async
- 影響：P1 每天進入時體感載入感
- UX rubric 觸及：§3 perf=0、§9 nav state=低
- Visual rubric 觸及：Motion=低（無 staggered reveal）
- 優化路線：加 defer/async + skeleton loading + lazy load 非首屏 JS
- 重構路線：拆 index.html monolith + token 化（Track A）+ 視需要 SSE backend（Track E conditional）
- 5 Gate 評估
- 推薦 + 驗收標準

- [ ] **Step 3: 4.2 a2（表格篩選/搜尋）**

完整 11 欄。優化路線：debounce + 視覺 loading state；重構路線：token 化篩選元件 + 跨表格共用 component。

- [ ] **Step 4: Verify + Commit**

```bash
awk '/^### 4\.1/,/^### 4\.5/' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md | grep -c '^### 4'
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(cards): GUI cards 4.1-4.4 (a1/a2/a6/a7)"
```

Expected grep: 4

---

### Task E.2: CLI cards 第 1 批 (4.5 b1, 4.6 b2, 4.7 b3, 4.8 b4)

**Files:**
- Modify: `report.md` §4.5 - §4.8

- [ ] **Step 1: 4.5 b1（互動 menu 層級）**

完整 11 欄。引 §3.2.3 interaction model audit 結果。

- [ ] **Step 2: 4.6 b2（命名/參數一致性）**

引 §3.2.2 consistency matrix。優化路線：補一致命名表 + deprecation alias；重構路線：Track C 統一入口。

- [ ] **Step 3: 4.7 b3（CLI 輸出格式）**

優化路線：Track B 共享輸出層；無重構路線（已是中度重構）。

- [ ] **Step 4: 4.8 b4（CLI 錯誤訊息）**

優化路線：增 error-clarity helper（cause + recovery）；重構路線：併入 Track B。

- [ ] **Step 5: Verify + Commit**

```bash
awk '/^### 4\.5/,/^### 4\.9/' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md | grep -c '^### 4'
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(cards): CLI cards 4.5-4.8 (b1/b2/b3/b4)"
```

Expected grep: 4

---

### Task E.3: CLI cards 第 2 批 (4.9 b5, 4.10 b6, 4.11 b7, 4.12 b8)

**Files:**
- Modify: `report.md` §4.9 - §4.12

- [ ] **Step 1: 4.9 b5（雙入口整合）**

完整 11 欄。重構路線指向 Track C。

- [ ] **Step 2: 4.10 b6（isatty / NO_COLOR / pipe）**

CRITICAL（§2.5 ★ 基本盤）。優化路線：補 isatty + NO_COLOR + stderr 分流（Track B 子集）。

- [ ] **Step 3: 4.11 b7（Exit codes）**

CRITICAL。優化路線：定義 domain-specific exit code map + 套用到所有命令。

- [ ] **Step 4: 4.12 b8（Auto-completion）**

優化路線：用 Click + click_completion 或 argcomplete 補；若採 Track L4 則一併解。

- [ ] **Step 5: Verify + Commit**

```bash
awk '/^### 4\.9/,/^### 4\.13/' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md | grep -c '^### 4'
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(cards): CLI cards 4.9-4.12 (b5/b6/b7/b8)"
```

Expected grep: 4

---

### Task E.4: Report cards (4.13 c1, 4.14 c3)

**Files:**
- Modify: `report.md` §4.13, §4.14

- [ ] **Step 1: 4.13 c1（Report 摘要 / 長度）**

引 §3.3.2 章節長度分布。優化路線：每份 report 加執行摘要（200 字 standalone）；重構路線：Track A token 化 + 章節結構模板化（OQ-2 reorg 配合）。

- [ ] **Step 2: 4.14 c3（圖表閱讀性）**

引 §3.3.3 + 近期 chart fix 進度。優化路線：補 colorblind-safe palette + tabular figures；重構路線：Track A 套用到 chart_renderer。

- [ ] **Step 3: Verify + Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(cards): Report cards 4.13-4.14 (c1/c3)"
```

---

### Task E.5: Email cards (4.15 d2, 4.16 d3)

**Files:**
- Modify: `report.md` §4.15, §4.16

- [ ] **Step 1: 4.15 d2（跨 client 顯示）**

引 §3.4.2 checklist。優化路線：補 inline CSS + dark-mode meta + multipart/alternative；重構路線：Track D MJML 預編譯。

- [ ] **Step 2: 4.16 d3（actionability）**

引 §3.4.4。優化路線：補 preheader + bulletproof CTA + subject line pattern；重構路線：Track D + 可選 i18n reorg（OQ-2）。

- [ ] **Step 3: Verify + Commit**

```bash
awk '/^### 4\.13/,/^## §5/' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md | grep -c '^### 4'
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(cards): Email cards 4.15-4.16 (d2/d3)"
```

Expected grep: 4（4.13 + 4.14 + 4.15 + 4.16）

---

## Phase F — Cross-cutting + Recommendations

### Task F.1: 每個子系統的「推薦組合」(§3.1.5 / §3.2.6 / §3.3.6 / §3.4.6)

**Files:**
- Modify: `report.md` §3.1.5, §3.2.6, §3.3.6, §3.4.6

- [ ] **Step 1: §3.1.5 GUI 推薦組合**

依 §3.1.4 候選評估 + §6.1 採用方向 + 5 Gate 評估，產出推薦：

```
推薦路徑：[優化-first 1-2 sprint → Track A token 化 → Track E conditional]

5 Gate 評估：
  Gate 1 Offline      : ✓ (vendor 化 a7 後)
  Gate 2 多痛點共因   : Track A 解 a1+a2+(c3+d2 視覺) 共 4-5 個
  Gate 3 Touch radius : 中（app.css + 跨 JS）
  Gate 4 Persona 衝擊 : 低（CSS-only token，不破功能）
  Gate 5 Reversibility: ✓ (token 可漸進 fallback)

執行順序：Phase 0 a6/a7 → Phase 1 quick wins → Phase 2 Track A
不推薦：C modern-saas（generic）；Vue 3（offline cost > 收益）
```

- [ ] **Step 2: §3.2.6 CLI 推薦組合**

預設推薦 L2 抽出共享輸出層（Track B）+ 視 Track C 進度評估。L4 完整重寫不推薦（OQ-6 default）。

- [ ] **Step 3: §3.3.6 Report 推薦組合**

預設推薦 §6.2 B editorial-magazine 套用 + Track A 共享 token + i18n reorg（OQ-2 配合）。

- [ ] **Step 4: §3.4.6 Email 推薦組合**

預設推薦 Track D MJML 預編譯（Phase 3）。Phase 1 先補 inline CSS / preheader / multipart 文字版。

- [ ] **Step 5: Verify + Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(reco): per-subsystem recommended combinations §3.x.5/6"
```

---

### Task F.2: §5.1 共因識別表

**Files:**
- Modify: `report.md` §5.1

- [ ] **Step 1: 攤平 16 張卡的「重構路線」**

從 E.1-E.5 寫的 16 張卡掃出每張卡的「重構路線」一行摘要 → 找共因。

- [ ] **Step 2: 寫入共因表**

```markdown
| 共用重構 | 解的痛點 | Touch radius | Offline 友善 | 註 |
|---|---|---|---|---|
| Token 化 app.css + design system | a1 a2 c3 d2 + visual 一致性 | 中 | ✅ | Track A |
| 共享 CLI 輸出層 | b3 b4 b6 b7 (+ b1 副作用) | 中 | ✅ | Track B |
| 統一 CLI 入口 | b1 b2 b5 b8 | 大 | ✅ | Track C |
| Email 模板系統化 (MJML) | d2 d3 | 中 | ✅ 編譯產物 | Track D |
| 拆 index.html monolith | a1 a2 (+ devx) | 大 | ✅ | Track A 子集 |
| Backend async + SSE | a1 残留 + c1 progress | 大 | ✅ FastAPI/Starlette | Track E conditional |
| Report exporter 整併 | c1 c3 + 維護性 | 大 | ✅ | 視 §3.3.1 legacy 確認 |
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(cross-cut): §5.1 root-cause grouping for 16 pain points"
```

---

### Task F.3: §5.2 5 條 Track + §5.3 推薦執行順序

**Files:**
- Modify: `report.md` §5.2, §5.3

- [ ] **Step 1: §5.2 Bundled Refactor Tracks（沿 design spec 結構，填入實際估算）**

```markdown
### Track A — Visual System
**解的痛點**：a1 a2 c3 d2 + cross-cutting 視覺一致性
**Touch radius**：中（app.css token 化 + 跨 JS 套用 + chart_renderer + Email subset）
**Offline 友善**：✅
**預估完成後 rubric 提升**：GUI §6 typography/color: N→3、Visual Identity: N→2

### Track B — CLI Output Layer
... (同樣展開)

### Track C — CLI Entry Unification
...

### Track D — Email System
...

### Track E (conditional) — Backend Async
**啟動條件**：Phase 1-3 完成後 a1 / c1 仍未達 rubric ≥ 2 → 啟動
```

- [ ] **Step 2: §5.3 推薦執行順序（含依賴圖）**

```markdown
Phase 0 (Pre-conditions, mandatory)
  - a6 HTTPS hand-off → 可靠性 sprint
  - a7 vendor 化 → 100% 清乾淨

Phase 1 (Quick wins)
  - 各痛點優化路線中的小改項目

Phase 2 (並行)
  - Track A Visual System
  - Track B CLI Output Layer

Phase 3
  - Track C CLI Entry Unification
  - Track D Email MJML

Phase 4 (conditional)
  - Track E Backend Async
```

依賴圖：

```
a6 (handoff) ─┬─→ Phase 1
a7 (vendor) ─┘
             │
Phase 1 ─→ Phase 2 (Track A | Track B)
             │
Phase 2 ─→ Phase 3 (Track C ← Track B; Track D 獨立)
             │
Phase 3 ─→ Phase 4 (Track E if a1/c1 still bad)
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(cross-cut): §5.2 5 tracks + §5.3 phased execution order"
```

---

## Phase G — Mockups

> 使用已啟動的 Visual Companion server：`http://localhost:54403`
> Mockup 檔案存於 `.superpowers/brainstorm/3034647-1777877764/content/`

### Task G.1: M1 GUI tab loading（before/after × light/dark = 4 個 mockup）

**Files:**
- Create: `.superpowers/.../content/m1-gui-loading-before-light.html`
- Create: `.superpowers/.../content/m1-gui-loading-before-dark.html`
- Create: `.superpowers/.../content/m1-gui-loading-after-light.html`
- Create: `.superpowers/.../content/m1-gui-loading-after-dark.html`
- Modify: `report.md` §7 M1

- [ ] **Step 1: M1 before light**

寫 HTML fragment 模擬現況 GUI tab 切換載入：空白主區 + 同步載入動作（無 skeleton），用 `mock-nav` `mock-sidebar` `mock-content` 等 Visual Companion 提供的 class。

- [ ] **Step 2: M1 before dark**

同上，dark 配色版本。

- [ ] **Step 3: M1 after light**

套用 §6.1 採用方向：skeleton（用 shimmer animation）+ staggered reveal + token 配色。

- [ ] **Step 4: M1 after dark**

同上 dark 版。

- [ ] **Step 5: 用瀏覽器逐一檢視（http://localhost:54403），截圖**

每個 mockup 用 Visual Companion 點擊預覽，必要時微調直到滿意。截圖（可用 Playwright tool）存到 `.superpowers/.../mockup-screenshots/m1-{before|after}-{light|dark}.png`。

- [ ] **Step 6: 把 mockup 連結 + screenshot 嵌入 report.md §7 M1**

```markdown
### M1 — GUI tab loading

| | Before | After |
|---|---|---|
| Light | ![](.superpowers/.../m1-...png) [HTML](.superpowers/.../content/m1-...html) | ![]() [HTML]() |
| Dark | ![]() [HTML]() | ![]() [HTML]() |

說明：
- Before：同步載入空白；首屏 TTI 估 N 秒
- After：skeleton + 200ms staggered reveal；perceived load 改善
- 套用 §6.1 採用 token：（列關鍵 token）
```

- [ ] **Step 7: Verify + Commit**

```bash
ls .superpowers/brainstorm/3034647-1777877764/content/m1-*.html | wc -l
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md .superpowers/brainstorm/3034647-1777877764/content/m1-*.html
git commit -m "assess(mockup): M1 GUI tab loading — before/after × light/dark"
```

Expected ls: 4

註：`.superpowers/` 已在 .gitignore，但本 plan 仍 add 該目錄下 mockup 檔（讓 reviewer 能 reproduce）。若 .gitignore 阻擋，改以 docs/assets/mockups/ 路徑放置（Step 1-4 改路徑）。

---

### Task G.2: M4 Report summary（before/after × light = 2 個 mockup）

**Files:**
- Create: `.superpowers/.../content/m4-report-summary-before.html`
- Create: `.superpowers/.../content/m4-report-summary-after.html`
- Modify: `report.md` §7 M4

- [ ] **Step 1: M4 before**

模擬現況 c1 痛點：長段落、無摘要區、jargon 密集。

- [ ] **Step 2: M4 after**

套用 §6.2 採用方向：執行摘要區（200 字 standalone）+ verdict 對照表 + chart 重畫 + 章節節奏。

- [ ] **Step 3: 截圖 + 嵌入 report.md §7 M4 + Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md .superpowers/brainstorm/3034647-1777877764/content/m4-*.html
git commit -m "assess(mockup): M4 Report summary — before/after light"
```

---

### Task G.3: M5 Email HTML（before/after × light/dark = 4 個 mockup）

**Files:**
- Create: `.superpowers/.../content/m5-email-before-light.html`
- Create: `.superpowers/.../content/m5-email-before-dark.html`
- Create: `.superpowers/.../content/m5-email-after-light.html`
- Create: `.superpowers/.../content/m5-email-after-dark.html`
- Modify: `report.md` §7 M5

- [ ] **Step 1: M5 before light + dark**

模擬現況 mail_wrapper：直送版型，無 preheader、無 bulletproof CTA、dark mode 反轉風險。

- [ ] **Step 2: M5 after light + dark**

套用 §6.2 子集：preheader（隱藏 30-90 字符）+ bulletproof CTA（VML for Outlook）+ dark-mode-safe color tokens。

- [ ] **Step 3: 截圖 + 嵌入 + Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md .superpowers/brainstorm/3034647-1777877764/content/m5-*.html
git commit -m "assess(mockup): M5 Email HTML — before/after × light/dark"
```

---

## Phase H — Resolve OQs + Final assembly

### Task H.1: 解未決的 Open Questions (§8)

**Files:**
- Modify: `report.md` §8

- [ ] **Step 1: 對 OQ-3 - OQ-10 逐一給最終答案**

OQ-3 Task 6 是否視為延伸 pre-condition？→ 預設「是」
OQ-4 Mockup 兩版策略？→ 已執行於 G.1-G.3
OQ-5 §3.4.2 渲染矩陣是否實測？→ 預設「不實測，已用 known-issue 形式記入 §3.4.2」；列為下游 implementation
OQ-6 CLI L4 是否上推薦？→ 預設「不推薦，列為候選但 Track C 為主路徑」
OQ-7 §6.1/§6.2 是否共享 primitive？→ 已執行於 D.3
OQ-8 §3.1.0 a7 強制掃描？→ 已執行於 A.1，hard-gate 狀態：（從 A.1 結果）
OQ-9 Track E 是否同步切 ASGI？→ 預設「是」
OQ-10 Illumio 術語留英策略？→ 已執行於 C.4

把 OQ 表格從「Open / Resolved」更新為全部 Resolved（除非有確實懸而未決的，標 Open + reason）。

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(oq): resolve OQ-3..10 with default decisions"
```

---

### Task H.2: Self-review (placeholder / 一致性 / 範圍 / 歧義)

**Files:**
- Modify: `report.md`（修任何發現的問題）

- [ ] **Step 1: Placeholder scan**

```bash
rg -n 'TBD|TODO|FIXME|placeholder|XXX|（待|尚未填' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
```

Expected: 無 match。若有則就地修。例外：design spec 設計上要保留 _TBD_ 的欄位（沒有的，全填）→ 全部清掉。

- [ ] **Step 2: 內部一致性**

- 16 張卡是否齊全？`grep -c '^### 4\.' report.md` → 16
- 每張卡是否引到正確 §3.x.y？逐張查 cross-ref
- 推薦組合的 5 Gate 評估是否一致（同一 Track 在不同章節說法相同）？
- §5.1 共因表的痛點 ID 是否在 §4 都存在？

- [ ] **Step 3: 範圍**

確認 16 痛點 + 4 子系統 + 5 軌道 + 2 視覺方向 + 3 mockup 全到齊。

- [ ] **Step 4: 歧義**

關鍵詞檢查：
- 「優化」與「重構」用語是否一致（不要「改進」「整理」交替混用）？
- 「Phase 0/1/2/3/4」是否與 §5.3 對應一致？
- Track A-E 是否在所有章節用同一名稱？

```bash
rg -n 'Track [A-E]|Phase [0-4]|優化|重構|改進|整理' docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md | wc -l
```

人工檢查列出的命中。

- [ ] **Step 5: 修正並 Commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(review): self-review fixes — placeholder/consistency/scope/ambiguity"
```

---

### Task H.3: Final assembly + status footer

**Files:**
- Modify: `report.md` frontmatter + 末尾

- [ ] **Step 1: 更新 frontmatter status**

```markdown
---
Title: UX / CLI / Report / Email 全域評估報告
Source spec: docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-design.md
Status: complete
Generated: 2026-05-04
Commit at: <git rev-parse HEAD 結果>
---
```

- [ ] **Step 2: 加末尾「下一步」段**

```markdown
## §12 下一步

本評估報告產出後，建議以下接續工作（不在本 plan 範圍）：

1. **Phase 0 啟動**（mandatory）：
   - a6 HTTPS hand-off → 可靠性 sprint owner
   - a7 vendor 化執行 → 開新 plan `2026-MM-DD-vendor-external-resources.md`

2. **Phase 1 quick wins**：依 §3.x.5/.6 推薦組合的「優化路線」項目，建議集中為一份 plan。

3. **Phase 2 並行**：Track A Visual System + Track B CLI Output Layer，建議各開獨立 plan。

4. **Phase 3**：Track C + Track D 獨立 plan。

5. **Phase 4 conditional**：Track E 是否啟動，依 Phase 1-3 完成後 a1/c1 rubric 重評結果。

每條 Track 開 plan 時，可引用本報告的對應 §3.x.5/.6 推薦組合 + §4 痛點卡作為 acceptance criteria。
```

- [ ] **Step 3: Final commit**

```bash
git add docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-report.md
git commit -m "assess(final): mark complete + add §12 next-step roadmap"
```

- [ ] **Step 4: 收尾 Visual Companion server（可選）**

```bash
/home/harry/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/brainstorming/scripts/stop-server.sh /home/harry/rd/illumio-ops/.superpowers/brainstorm/3034647-1777877764
```

---

## Self-review of this plan

**Spec coverage check：**
- §1 Scope & Assumptions：在 Task 0.1 skeleton 已包含；Methodology rubric 在 Phase C 全跑過
- §2 Methodology：rubric 在 Phase C 套用、5 Gate 在 Phase E/F 套用、Evidence 規範在 A.1-A.7
- §3.1 GUI：Phase A.1-A.3 + B.1-B.2 + C.1-C.2
- §3.2 CLI：Phase A.4-A.5 + C.3
- §3.3 Report：Phase A.6 + C.4-C.5
- §3.4 Email：Phase A.7 + C.6-C.7
- §4 16 張卡：Phase E.1-E.5
- §5 Cross-cutting：Phase F.1-F.3
- §6 Visual Identity：Phase D.1-D.3
- §7 Mockup：Phase G.1-G.3
- §8 Open Questions：Phase H.1
- §9 Out-of-scope：在 Task 0.1 skeleton 包含；H.1 視需要更新
- §10 Glossary：複製自 design spec
- §11 References：複製自 design spec

**Placeholder scan**：本 plan 內無「TBD/TODO/FIXME」遺留；所有「（從 X 章節）」是 cross-reference 而非待填。

**Type consistency**：Track A-E 名稱一致；Phase 0-4 一致；痛點 ID（a1/a2/a6/a7/b1-b8/c1/c3/d2/d3）一致；rubric 類別編號（§1-§10、TTY 12 條）與 design spec 一致。
