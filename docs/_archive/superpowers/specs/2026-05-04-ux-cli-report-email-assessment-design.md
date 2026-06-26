---
Feature Name: UX / CLI / Report / Email 全域評估（Assessment Design）
Goal: 對 illumio-ops 的前端 UI/UX、CLI、Report 內容、Email/通知 4 個子系統做系統性評估，產出「優化路線 vs. 重構路線」雙路徑建議與優先級排序，供後續 implementation plan 引用。本 spec 定義評估的「結構、方法學、輸出模板」；實際 finding 採集與填入由下游 plan / implementation 階段完成。
Architecture:
  - 評估文件本身為靜態 markdown，產出於 docs/superpowers/specs/。
  - 評估執行時依本 spec 提供的 rubric 與工具指令掃描 src/templates、src/static、src/cli、src/report、src/alerts，產出量化資料、UX rubric 分數、Visual Identity 評分、痛點卡內容。
  - Mockup（M1 / M4 / M5）以 Visual Companion 產出 HTML 片段，附於 §7 Appendix。
Tech Stack:
  - 評估方法學：ui-ux-pro-max（10 priorities, 99 rules）+ frontend-design（5 維度 aesthetic + Distinctiveness）+ TTY-specific 12 條（自訂，採 GitHub CLI style guide / 12-factor / charmbracelet 為來源）。
  - 量化工具：radon、wc、ripgrep、stat、pylint duplicate-code。
  - Mockup：Visual Companion（位於 .superpowers/brainstorm/.../content/*.html）。
  - Persona 排序：P1 網管 > P2 SOC > P5 主管收件人。
  - Refactor cap：L4（含 backend swap、framework 換骨）。
  - Timeline：T3（純評估，不排程）。

---

# UX / CLI / Report / Email 全域評估

## §1 Scope & Assumptions

### §1.0 文件定位（如何閱讀本 spec）

本 spec 是「評估的設計文件」，不是「評估的成果」。三階段流程：

1. **本 spec（已完成）** — 定義評估的結構、方法學、輸出模板、痛點卡格式、Visual Identity 候選方向。
2. **下游 implementation plan** — 由 writing-plans skill 產出，列出「執行評估」需要的步驟（掃描、打分、填表、繪製 mockup）。
3. **評估執行階段** — 依 plan 跑工具、填入 spec 中所有標 _TBD_ 的表格、產出 mockup、給推薦結論。

文中所有「**評估執行階段填入**」的字樣都指第 3 步；本 spec 不在此處填入實際 finding。

### §1.1 涵蓋

4 個子系統 × 16 個錨點痛點：

- **GUI**：a1 tab 載入、a2 表格篩選/搜尋、a6 HTTPS 啟用後 layout 破版（pre-condition）、a7 UI 依賴 external resources（pre-condition）
- **CLI**：b1 互動 menu 層級、b2 命名/參數一致性、b3 輸出格式、b4 錯誤訊息、b5 三支獨立 CLI vs menu 雙入口整合、b6 isatty / NO_COLOR / pipe 友善度、b7 Exit codes、b8 Auto-completion
- **Report**：c1 報告長度/摘要、c3 圖表閱讀性
- **Email / 通知**：d2 跨 client 顯示、d3 主旨/摘要 actionability

### §1.2 Persona 排序

**P1 網管 > P2 SOC > P5 主管收件人**。

衝突解決：GUI/CLI 衝突優先 P1；Report/Email 衝突優先 P5。

### §1.3 硬約束

- **C1 Offline bundle 必須能跑** — 不可依賴 CDN、線上 npm install、線上 webfont。所有 vendor 化的檔案需進 `vendor/` 或 offline bundle 的 `wheels/` 對應位置。

C2-C5（Python 3.12、Flask、i18n keys、Report 介面）皆可挑戰，詳見 §8 Open Questions。

### §1.4 不在範圍

- 可靠性 bug（HTTP 503、mail/line 無回應、XLSX 在 GUI 不可見）→ §9 defer
- 安全議題本身的修復（HTTPS / CSP）→ §9 defer，但 §3.1.0 列出排查清單以協助 hand-off
- 效能 profiling（RUM / Lighthouse 實測）→ §9 defer
- 進行中工作（h5 blueprint split、h6 settings reorg、Integrations redesign Task 6）→ 本 spec 假設完成

### §1.5 評估維度

- **UX**（行為 / 流程） → ui-ux-pro-max 10 priorities
- **Visual Identity**（外觀 / 美學） → frontend-design 5 維度 + Distinctiveness
- **Refactor**（結構） → §2.6 五個 Gate

---

## §2 Methodology

### §2.1 量化指標

| 指標 | 工具 | 用途 |
|---|---|---|
| 檔案大小 | `wc -l`、`stat -c '%s'` | 大檔識別（>2k 行 yellow flag、>5k red flag） |
| 函式長度 / 圈複雜度 / MI | `radon cc src/`、`radon mi src/` | 結構性熱點 |
| 外部依賴 | `rg -n 'https?://' src/templates src/static src/alerts` | a7 違規清單與 vendor 化 |
| 重複度 | 目視 + `pylint --disable=all --enable=duplicate-code` | 跨檔重複 pattern |
| TTY 旗標命中 | `rg -E 'isatty\(\)|NO_COLOR|sys\.stderr'` | CLI rubric 取證 |
| Bundle / asset 大小 | `wc -c src/static/js/* src/static/css/*` | a1 客觀資料 |

### §2.2 痛點優先級評分公式

```
Priority Score = Impact × PersonaWeight × Frequency
```

- **Impact**：1（小煩惱）/ 2（影響任務完成）/ 3（阻斷任務）
- **PersonaWeight**：取此痛點觸及的最高 weight persona
  - P1 = 3 / P2 = 2 / P5 = 2 / 其他 persona = 1
- **Frequency**：1（月一次以下）/ 2（週）/ 3（每天 / 每次操作）

#### 門檻

- **P0** = Pre-condition（直接違反硬約束 / 阻斷其他評估）→ 不算 score，直接 P0
- **P1** = score ≥ 12，**或** 任一 CRITICAL rubric 類目（§2.3 §1 a11y、§2.3 §3 perf、§2.3 §8 error feedback、§2.5 三條基本盤）打 0 分
- **P2** = score 6–11
- **P3** = score < 6

### §2.3 GUI UX rubric（採 ui-ux-pro-max 10 類，0-3 分）

每類：**0 失敗 / 1 部分 / 2 大致 OK / 3 卓越**。CRITICAL 類任一為 0 自動拉到 P1 以上。

1. **Accessibility**（CRITICAL） — 焦點環、aria-label、color contrast 4.5:1、heading hierarchy、prefers-reduced-motion
2. **Touch & Interaction** — desktop-first，主要看 cursor / keyboard 替代物（hover-vs-tap fallback、tab-order、visible focus）
3. **Performance**（CRITICAL） — TTI、CLS、bundle size、lazy load、image optimization、reserve space for async content
4. **Style Selection** — 一致風格、no-emoji-icons、icon-set 一致、stroke 一致、filled vs outline 分層
5. **Layout & Responsive** — viewport、breakpoint、horizontal-scroll、container width、spacing scale
6. **Typography & Color** — type scale、line-height 1.5–1.75、tabular figures、semantic color tokens（不 hardcode hex）
7. **Animation** — duration 150-300ms、transform/opacity only、motion-meaning（不裝飾）、prefers-reduced-motion
8. **Forms & Feedback**（CRITICAL） — input-labels、error-placement、required-indicators、submit-feedback、error-clarity（cause + recovery）
9. **Navigation Patterns** — nav-state-active、back-behavior、persistent-nav、navigation-consistency、breadcrumb 3+ 層
10. **Charts & Data** — chart-type、tooltip、legend、empty-data-state、screen-reader-summary、colorblind-safe

### §2.4 Visual Identity rubric（採 frontend-design 5 維度，0-3 分）

5 維度逐項打分 + Distinctiveness 整體分。

- **Typography** — 字體選擇 + 配對（heading vs body vs mono），避免 generic（Inter/Roboto/Arial/system-ui）
- **Color** — 主導色 commit 程度、accent 節制、semantic token、light/dark dual
- **Motion** — meaningful 不裝飾、easing 一致、page-load orchestration
- **Spatial Composition** — asymmetry / overlap / grid-breaking、generous whitespace 或 controlled density
- **Backgrounds & Details** — gradient mesh / noise / 幾何 / 陰影 / 自訂 cursor / grain
- **Distinctiveness** — 「unforgettable thing」存在嗎？

**目標 Distinctiveness = 2**（清楚的工具感識別，不追求 art-piece 的 3；過度 distinctive 對 ops 工具會犧牲操作效率）。

### §2.5 CLI-specific rubric（TTY 12 條，0-3 分）

「★」為 **三條基本盤**，任一為 0 → 自動 P1 以上。

1. 命令文法一致性 — verb-noun 順序、flag 命名、長短旗標對應、global flags 位置
2. ★ 能力偵測 — `isatty()`、`TERM`、`NO_COLOR`、`COLORTERM`、Windows console
3. ★ Composability — stdout 走輸出、stderr 走訊息、`--json`/`--quiet`/`--verbose` 一致、可被 `grep`/`jq` 接管
4. ★ Exit codes — 0 成功 / 1 一般錯誤 / 2 用法錯誤 / 130 SIGINT + domain-specific 約定
5. Idempotency / dry-run — `--dry-run`、`--yes`、`--force`、可重入
6. 配置層級 — CLI flag > env var > config file > 預設；env 命名空間 `ILLUMIO_OPS_*`
7. 互動 vs 非互動雙模 — TTY 給 prompt、pipe 給合理預設或 fail-fast
8. 長任務 — progress + ETA、可中斷、resumable、log 路徑提示
9. `--help` / man — 範例、子命令樹、common pitfalls、相關連結
10. Auto-completion — bash / zsh / fish completion 是否提供
11. 雙入口整合 — 互動 menu 與三支獨立 CLI 命令對等性、deprecation 路徑
12. Error actionability — cause + recovery path、`did you mean ...?` 建議

### §2.6 重構 vs 優化判定 — 5 個 Gate

每個痛點都給雙路徑（R-yes），但「推薦哪一條」走以下五個 Gate：

1. **Offline 友善度** — 違反 C1 立刻刷掉
2. **多痛點共因** — 若同一改動解 ≥ 3 痛點 → 加重重構分數
3. **Touch radius** — 影響 < 5 檔偏優化、跨模組偏重構
4. **Persona 衝擊** — 重構期間是否有 P1 功能會壞？
5. **Reversibility** — 不能回滾偏優化

每張卡明示觸發了哪幾個 Gate。

### §2.7 Evidence collection 規範

每個 finding 必附：

- **代碼證據** — `file:line` 或 file glob
- **輸出證據（CLI）** — fenced code block 截短輸出
- **視覺證據（GUI / Report / Email）** — M1/M4/M5 用 Visual Companion，其餘用文字描述 + 必要時 ASCII 草圖
- **Mockup 規範** — M1 light + dark、M4 light only（PDF/HTML 報告以 light 為主）、M5 light + dark（dark mode 反轉是 Email 已知雷區）

---

## §3 Subsystem Assessments（上半）

### §3.1 Frontend GUI

#### §3.1.0 Pre-conditions（先解再談優化）

##### a6 — HTTPS 啟用後 layout 破版

成因假設清單（spec 寫作期不修，本 spec 提供 hand-off 給可靠性 sprint）：

1. **Mixed-content blocking** — http:// 資源在 https:// 頁面被擋
2. **External resources 走 http://** — 與 a7 同源；HTTPS 強制升級失敗
3. **CSP 配置缺失或過嚴** — `script-src` / `style-src` / `img-src` 限制
4. **Cookie SameSite/Secure 屬性** — SPA route 失敗

驗證步驟：

- 開 DevTools → Console，重現破版頁面
- 檢查 Network 中所有 mixed-content blocked 條目
- 比對 `curl -k https://127.0.0.1:5001/` 與 `curl http://127.0.0.1:5000/` 的 response headers
- 比對 `src/gui/__init__.py` 中的 secure_cookie 與 CSP 設定

標籤：**P0、blocking-eval、defer-fix-to-reliability**

##### a7 — UI 依賴 external resources（違反 C1）

掃描指令：

```bash
rg -n 'https?://' src/templates src/static src/alerts \
  | rg -v '^[^:]+:[0-9]+:\s*(#|//|/\*|\*)'
```

違規清單表（評估執行階段掃描填入）：

| 檔案 | 行 | URL | 資源類型（CSS/JS/font/img/icon） | 是否被 HTTPS 阻擋 | 替代本地 asset 建議 |
|---|---|---|---|---|---|
| _TBD by scan_ | | | | | |

Vendor 化目標位置：

- JS / CSS：`vendor/js/`、`vendor/css/`
- Webfont：`vendor/fonts/`（與既有 CJK font 同層）
- Icon set：`vendor/icons/`（Lucide 或 Heroicons SVG sprite）

標籤：**P0、violates-C1**

#### §3.1.1 整體現況量化

執行掃描後填入：

- 各 JS / CSS / template 檔案行數與大小（已知雛形：`index.html` 127.4 KB、`dashboard.js` 79.2 KB、`integrations.js` 54.2 KB、`rule-scheduler.js` 28.6 KB、`settings.js` 24.7 KB、`quarantine.js` 23.2 KB、`rules.js` 22.4 KB、`utils.js` 16.1 KB、`dashboard_v2.js` 15.4 KB、`app.css` 31.7 KB；總 JS ~370 KB）
- `index.html` 內 inline `<script>` / `<style>` 數量
- 全 GUI 模組依賴圖（`grep -l 'import\|require\|<script src='`）
- 套件依賴：vanilla JS（無 npm）；Flask + jinja2
- 進行中重構訊號：`dashboard.js` + `dashboard_v2.js` 共存、blueprint split (h5)、settings reorg (h6)
- 外部資源計數（從 §3.1.0 a7 表匯總）
- Bundle 載入順序：`index.html` 內 `<script>` 先後 + 是否 `defer` / `async`

#### §3.1.2 UX rubric 結果（10 類）

每類一段，格式：`Score N + Key Finding（1-2 行） + 觸及痛點卡編號`。

CRITICAL 類（§2.3 §1 / §3 / §8）任一為 0 自動拉到 P1 以上。

#### §3.1.3 Visual Identity 現況評估

frontend-design 5 維度逐項打分：Typography / Color / Motion / Spatial / Backgrounds & Details + Distinctiveness。

當前美學定位描述（評估執行階段填入）：generic admin / Bootstrap-default / 「綠色但無系統」（mem 訊號）/ 其他。

#### §3.1.4 可選方向

##### Aesthetic axis（視覺方向，沿用 §6.1）

| 候選 | 描述 | 適用 persona |
|---|---|---|
| A. 維持現狀 | （baseline） | — |
| B. industrial-editorial | 高密度、tabular figures、editorial 字體層級、克制配色 | P1 + P2 |
| C. modern-saas | Linear/Vercel 風、generic | (不推薦 — 過於 cookie-cutter) |
| D. dark-ops 終端感 | Bloomberg / 終端機暗色、monospace 為核 | P2 SOC |

每候選給 9 欄 spec sheet：色票（light/dark）、字體（heading/body/mono）、icon set、motion 原則、density、touch radius、risk。

##### Framework axis

| 候選 | offline 友善 | touch | risk | 推薦條件 |
|---|---|---|---|---|
| Stay Vanilla + Design System | ✅ | 中 | 低 | 默認推薦 |
| HTMX + Alpine.js | ✅（vendor 化） | 中 | 中 | 若需強化 server-rendered + 局部互動 |
| Vue 3 + Vite | ⚠ build pipeline 進 offline bundle | 大 | 高 | 若 a1 在前面 phase 仍解不掉 |
| Lit + Web Components | ✅ | 中 | 中 | 若需 component 化但避 framework lock-in |

##### Backend axis（OQ-1 resolved，在範圍內）

| 候選 | offline (wheels) | UX 直接收益 | 推薦條件 |
|---|---|---|---|
| Flask（現狀） | ✅ | 0 | 默認 |
| FastAPI + Uvicorn | ✅ | 中（async + SSE 釋放長任務） | 若需 SSE 進度推送 / async DB |
| Starlette | ✅ | 中 | 同上但更輕 |
| Litestar | ⚠ 需確認 wheel | 中 | 若需強型別 OpenAPI |

每個 framework / backend 候選跑 §2.6 五 Gate。

#### §3.1.5 推薦組合

格式：

```
推薦路徑：[優化-first] / [重構-first] / [混合：先 X 後 Y]

§2.6 Gate 評估：
  Gate 1 Offline      : ✓ / ✗ + 理由
  Gate 2 多痛點共因   : 共因識別到 N 個痛點 → 重構分 +X
  Gate 3 Touch radius : 小 / 中 / 大
  Gate 4 Persona 衝擊 : ...
  Gate 5 Reversibility: ...

執行順序：Phase 0 → Phase 1 → ...
不推薦的選項與原因：
```

---

### §3.2 CLI

#### §3.2.1 Command Inventory

攤平表（評估執行階段掃描填入），欄位：

| 入口 | 命令 | verb | noun | flags | 輸出格式 | exit codes | isatty 處理 | --json | menu 也露出？ |
|---|---|---|---|---|---|---|---|---|---|
| _TBD by scan_ | | | | | | | | | |

入口清單：

1. **互動 menu** — `src/cli/menus/`（alert / bandwidth / event / manage_rules / report_schedule / system_health / traffic / web_gui）
2. **`pce_cache_cli.py`**
3. **`rule_scheduler_cli.py`**
4. **`siem_cli.py`**
5. **CLI root** — `src/cli/_root.py` / `_runtime.py` / `report.py` / `rule.py` / `workload.py` / `siem.py` / `monitor.py` / `cache.py` / `config.py` / `status.py`

#### §3.2.2 Consistency Matrix

跨命令交叉比對（評估執行階段填入）：

- 旗標命名不一致清單（例：`--config-file` vs `--config`）
- verb-noun 順序不一致清單（例：`rule list` vs `list-rules`）
- 輸出格式預設不一致清單
- 退出碼定義 / 未定義清單
- global flags 位置（前置 vs 後置）
- 環境變數命名 (`ILLUMIO_OPS_*`) 命中率

#### §3.2.3 Interaction Model Audit（互動 menu 專屬）

- 層級樹 ASCII：`menu → submenu → action` 全圖（評估執行階段繪製）
- 返回邏輯一致性：每層 `back` 是回上一層還是回首頁？
- State preservation：中途離開後再進是否記得 selection？
- 長任務行為：`Ctrl-C` 是中斷還是回 menu？輸出去哪？
- Menu 文字 vs CLI 文字 wording 是否同一套？

#### §3.2.4 Rubric 打分

- ui-ux-pro-max 轉譯（§1 a11y / §3 perf / §5 layout / §7 anim / §8 forms / §9 nav / §10 tables）逐類打分
- §2.5 CLI rubric 12 條逐條打分
- 三條基本盤（能力偵測 / Composability / Exit codes）任一為 0 → 自動 P1

#### §3.2.5 可選方向

| 候選 | 描述 | offline | touch | risk |
|---|---|---|---|---|
| 維持現狀 + 補強 | 純文案 / 錯誤訊息修補 | ✅ | 小 | 低 |
| L2 抽出共享輸出層 | 顏色 / 表格 / spinner / exit code 共享 helper | ✅ | 中 | 低 |
| L3 統一入口 | 單一 `illumio-ops` 根命令含 3 支 CLI；menu 變 `shell` mode | ✅ | 大 | 中 |
| L4 Click + Rich + Typer 完整重寫 | 重新設計命令樹、bash/zsh/fish completion | ✅ | 最大 | 高 |

#### §3.2.6 推薦組合

格式同 §3.1.5。

---

### §3.3 Report

#### §3.3.1 Report Inventory

| Report | Generator | Exporters | i18n keys 數 | 平均輸出大小 | 主要 sections |
|---|---|---|---|---|---|
| audit | `audit_generator.py` | `audit_html_exporter.py` + pdf + csv + xlsx | _TBD_ | _TBD_ | _TBD_ |
| policy_usage | `policy_usage_generator.py` | `policy_usage_html_exporter.py` + pdf + csv + xlsx | | | |
| ven_status | `ven_status_generator.py` | `ven_html_exporter.py` + pdf + csv + xlsx | | | |
| dashboard_summaries | `dashboard_summaries.py` | (內嵌至其他報告) | | | |
| (legacy?) | `report_generator.py` (40.7 KB) | `html_exporter.py` (71.1 KB) ⚠ | | | |
| 共用 | — | `pdf_exporter.py`、`chart_renderer.py`、`table_renderer.py`、`code_highlighter.py`、`report_css.py` (37.6 KB)、`report_i18n.py` (68.8 KB) | | | |

確認 `report_generator.py` + `html_exporter.py` 是否為 legacy 待退場 → 評估執行階段釐清並填入。

#### §3.3.2 Content Audit

- **章節長度分布**：每個 report 的 section 字數中位數 / max
- **摘要密度**：是否有 TL;DR / 執行摘要？前 200 字能否 standalone？
- **Jargon 清單**：對 P5 主管不友善的術語（boundary、ringfence、ven、href、enforcement-mode、staged-readiness）— 列出每個術語在 i18n 是否有人話替代
- **Verdict 一致性**：`Allowed` / `Blocked` / `Potentially-Blocked` 等 verdict 在 chart label / table cell / appendix 三處用語一致性
- **跨報告連結**：audit ↔ policy_usage ↔ ven_status 之間是否有「相互 reference」
- **空資料 / 空章節呈現**：當某 section 無資料時是「省略」/「空白」/「說明」？
- **i18n 一致性**：`Online/Offline → 在線/離線`（mem 已修）作為先例；OQ-2 解決後可推 reorg：`verdict.allowed` / `severity.high_with_count.xxx` namespace 統一
- **Illumio 術語留英策略**：近期 commit 顯示 Illumio verdicts（Allowed/Blocked/Managed/Unmanaged）在 zh_TW 保留英文 — 此策略需在 spec 內明確定義「哪些術語保留英文、哪些譯」的判定原則

#### §3.3.3 Visual Identity 現況評估（document context）

frontend-design 5 維度（權重：Typography 高 / Color 高 / Spatial 高 / Motion 低 / Backgrounds 中）：

- **Typography** — 標題 / 正文字體、CJK fallback（PDF 已修 CJK font）、tabular figures
- **Color** — semantic palette、verdict 配色 colorblind-safe、light vs dark（PDF 偏 light）
- **Motion** — N/A 靜態文件，HTML 報告若有 expand/collapse 需評
- **Spatial** — 頁面 grid、章節節奏、空白比例、圖表佔幅
- **Backgrounds & Details** — cover page、divider、章節編號、頁眉頁腳、appendix 標記

#### §3.3.4 可選方向（沿用 §6.2）

| 候選 | 描述 | 適用 P5 主管 |
|---|---|---|
| A. 維持現狀 | （baseline） | — |
| B. editorial-magazine | Hoefler 風 / WSJ 工程感、優雅閱讀 | 高 |
| C. data-journalism | NYT / FT / Reuters Graphics 風，圖表敘事為主 | 中（取決於資料密度） |
| D. corporate-formal | McKinsey / 法務 deck / 合規風 | 高（若 audience 含合規） |

每候選給 spec sheet：色票、字體（標題 / 正文 / 圖表 / mono）、章節節奏、cover、appendix、空章節。

#### §3.3.5 痛點對應 finding

- **c1 摘要** — 從 §3.3.2 的章節長度 + 摘要密度 找根因
- **c3 圖表** — 從 §3.3.3 的 Color + Spatial + tabular figures 找根因；併同近期 chart fix（matplotlib `font.family`、pie autopct、i18n `title_key` / `label_key`、categorical slice label 翻譯）做延伸建議

#### §3.3.6 推薦組合

格式同 §3.1.5。

---

### §3.4 Email / Notification

#### §3.4.1 Template Inventory

- `src/alerts/templates/mail_wrapper.html.tmpl`（2.5 KB 單檔）
- `src/alerts/templates/line_digest.txt.tmpl`（純文字）
- `src/alerts/templates/webhook_payload.json.tmpl`（JSON schema）
- 模板引擎：評估執行階段確認（`str.format` / Jinja2 / 自寫）
- 變數契約：每個模板暴露的 placeholder 清單與來源（`src/alerts/__init__.py` + `metadata.py` + `plugins.py`）

#### §3.4.2 Cross-client Compatibility Audit

渲染矩陣（known-issue checklist；實測列入 OQ-5）：

| Client | 已知雷區 |
|---|---|
| Outlook (Win / Mac / 365) | VML for buttons、`<style>` quirks、`word-wrap`、不支援 flexbox/grid |
| Gmail (web / iOS / Android) | `<style>` 部分支援、可能移除 class、image proxy |
| Apple Mail | dark mode auto-invert |
| Thunderbird | CSS 限制 |

通用檢查項：

- table-based layout vs div-based（Outlook 仍偏好 table）
- inline CSS vs `<style>` 區塊
- dark mode 反轉處理
- `<img alt>` + width/height 防破版
- `position` / `flex` / `grid` 不可靠
- webfont 多數 client 阻擋
- Bulletproof CTA（VML for Outlook）
- 文字版 fallback（`multipart/alternative`）

#### §3.4.3 Visual Identity 評估（與 §3.3 共用 §6.2 子集）

Email 取 §6.2 縮減版：刪 webfont、刪 grid、保留色票 primitive（與 Report 一致）。

#### §3.4.4 Actionability Audit（命中 d3）

- **Subject line pattern** — 是否含 severity / count / time-window？
- **Preview text（preheader）** — 30-90 字符是否被刻意設計？
- **CTA** — 每封信是否有「下一步動作」？deep-link 能直開 GUI 對應頁？
- **Information hierarchy** — 開信 5 秒內能否說完 What / Why / Action？

#### §3.4.5 痛點對應 finding

- **d2** — 從 §3.4.2 渲染矩陣找根因
- **d3** — 從 §3.4.4 hierarchy 找根因

#### §3.4.6 推薦組合

| 候選 | 描述 | offline | touch | risk |
|---|---|---|---|---|
| 維持現狀 + 補強 | inline CSS + preheader + 文字版 fallback | ✅ | 小 | 低 |
| L3 模板系統化 | `templates/email/*.html.j2` + 共享 partials | ✅ | 中 | 中 |
| L4 MJML 預編譯 | MJML 寫 → cross-client safe HTML，產物進 vendor / 編譯產物 | ✅（編譯產物） | 中 | 中 |

格式同 §3.1.5。

---

## §4 Pain-point Cards（下半，16 張）

每張卡使用統一格式：

```markdown
### 4.X — <id> <短標題>

| | |
|---|---|
| Subsystem | GUI / CLI / Report / Email |
| 觸及 persona | P1 / P2 / P5 |
| Pre-condition | (若適用) → §3.1.0 |
| Score | Impact × PersonaWeight × Frequency = N |
| 優先級 | P0 / P1 / P2 / P3 |

**現況片段** — `file:line` 或指令輸出 / 量化證據

**影響** — 場景與頻率、persona 受衝擊程度

**UX rubric 觸及項** — §2.3 GUI rubric 與 §2.5 CLI rubric 命中類目

**Visual rubric 觸及項** — frontend-design 5 維度命中（如適用）

**優化路線（小改）** — 步驟 / Touch radius / 與 §5 cross-cutting 衝突？

**重構路線（大改）** — 步驟 / Touch radius / 與 §5 cross-cutting 同源？

**§2.6 五 Gate 評估**
- Gate 1 Offline       : ✓/✗
- Gate 2 多痛點共因    : 共因 N 個 → 重構分 +X
- Gate 3 Touch radius  : 小/中/大
- Gate 4 Persona 衝擊  : ...
- Gate 5 Reversibility : ✓/✗

**推薦** — 優化 / 重構 / 並行 + 理由

**驗收標準** — 採用後重跑 §2.3 / §2.5 rubric，預期該類分數從 N → M
```

16 張卡（評估執行階段逐一填入）：

- 4.1 a1 — GUI tab 載入體驗
- 4.2 a2 — 表格篩選 / 搜尋
- 4.3 a6 — HTTPS 啟用後 layout 破版（pre-condition → §3.1.0）
- 4.4 a7 — UI 依賴 external resources（pre-condition → §3.1.0）
- 4.5 b1 — CLI 互動 menu 層級
- 4.6 b2 — 命名 / 參數一致性
- 4.7 b3 — CLI 輸出格式
- 4.8 b4 — CLI 錯誤訊息
- 4.9 b5 — 三支獨立 CLI vs menu 雙入口整合
- 4.10 b6 — isatty / NO_COLOR / pipe 友善度
- 4.11 b7 — Exit codes 與 error actionability
- 4.12 b8 — Auto-completion 缺失
- 4.13 c1 — Report 摘要 / 長度
- 4.14 c3 — 圖表閱讀性
- 4.15 d2 — Email 跨 client 顯示
- 4.16 d3 — Email 主旨 / 摘要 actionability

a6 / a7 兩張卡標註「**See §3.1.0 — 列為 Pre-condition**」，卡內僅放掃描清單與 hand-off 細節，避免與 §3.1.0 重複。

---

## §5 Cross-cutting Recommendations

### §5.1 共因識別（Mining）

把 16 張卡的「重構路線」攤平，找出「同一個結構性改動同時解 N 個痛點」的群組（評估執行階段填入實際數據）：

| 共用重構 | 解的痛點 | Touch radius | Offline 友善 |
|---|---|---|---|
| Token 化 `app.css` + design system | a1 a2 c3 d2 + visual 一致性 | 中 | ✅ |
| 共享 CLI 輸出層 | b3 b4 b6 b7（+ b1 副作用） | 中 | ✅ |
| 統一 CLI 入口 | b1 b2 b5 b8 | 大 | ✅ |
| Email 模板系統化（MJML 預編譯） | d2 d3 | 中 | ✅ |
| 拆 `index.html` monolith | a1 a2（+ 開發體驗 spillover） | 大 | ✅ |
| Backend async + SSE（OQ-1 conditional） | a1 (loading via SSE)、c1 (long report progress) | 大 | ✅（FastAPI / Starlette） |
| Report exporter 整併（若 `html_exporter.py` 71 KB 是 legacy） | c1 c3 + 維護性 | 大 | ✅ |

### §5.2 Bundled Refactor Tracks

把 §5.1 合併成 ≤ 5 條軌道：

1. **Track A — Visual System**
   - token 化、design system、Iconset 統一（vendor 化 SVG sprite）
   - 解：GUI a1/a2 視覺、Report c3、Email d2 + 跨子系統視覺一致性
2. **Track B — CLI Output Layer**
   - 共享輸出層（顏色 / 表格 / spinner / exit code helpers）+ isatty + Composability
   - 解：b3 / b4 / b6 / b7
3. **Track C — CLI Entry Unification**
   - 單一 `illumio-ops` root 命令、子命令含 3 支獨立 CLI；menu 變 `shell` mode；bash/zsh completion
   - 解：b1 / b2 / b5 / b8
4. **Track D — Email System**
   - MJML 預編譯 + bulletproof CTA + dark-mode-safe colors + preheader 設計
   - 解：d2 / d3
5. **Track E (conditional) — Backend Async**
   - FastAPI / Starlette swap + Uvicorn + SSE 進度推送
   - 解：a1 殘留、c1 long report 進度
   - 啟動條件：Track A + 拆 monolith 完成後 a1 / c1 仍未達 rubric ≥ 2

### §5.3 推薦執行順序

```
Phase 0 (Pre-conditions, mandatory)
  - a6 HTTPS 修復（defer 給可靠性 sprint，但本 spec 提供 hand-off 清單）
  - a7 vendor 化所有 external resources（必須 100% 清乾淨）

Phase 1 (Quick wins, no structural change)
  - 各痛點「優化路線」中的小改項目
  - 文案 / 錯誤訊息 / preheader / inline CSS / focus ring 補回 / etc.

Phase 2 (並行：Track A + Track B)
  - Visual System token 化
  - CLI Output Layer 共享 helper

Phase 3 (Track C + Track D)
  - CLI Entry Unification
  - Email MJML 系統化

Phase 4 (conditional Track E)
  - 若 Phase 1-3 完成後 a1 / c1 仍未達 rubric ≥ 2 → 啟動 backend swap
```

依賴圖（dot）：

```
Track A → mockup 套用（§7）
Track B → Track C 是 prerequisite
Track D → 可獨立進行
Track E → 在 Track A 完成後才評估是否啟動
```

---

## §6 Visual Identity Direction

### §6.1 GUI direction

候選評估表（評估執行階段用 frontend-design 5 維度逐項打分）：

| 候選 | Typography | Color | Motion | Spatial | Backgrounds | Distinct | 適用 P1 / P2 |
|---|---|---|---|---|---|---|---|
| A. 維持現狀 | _TBD_ | | | | | | |
| B. industrial-editorial | | | | | | | |
| C. modern-saas | | | | | | | |
| D. dark-ops 終端感 | | | | | | | |

**推薦傾向**（評估執行階段依 §3.1.3 現況分數 + persona weight + offline 友善度 決定）：

- 默認傾向 **B (industrial-editorial)** 或 **D (dark-ops)** — security/operations 工具與 P1 網管 / P2 SOC 工作環境契合
- **C (modern-saas)** 不推薦 — 過於 cookie-cutter / generic，Distinctiveness 必然偏低
- **A (維持)** 視 §3.1.3 現況分數而定（預期 < 1 → 排除）

#### Adopted Direction Spec Sheet（採用後填入）

- **Token**：`--color-*` / `--space-*` / `--radius-*` / `--shadow-*` / `--motion-*`
- **Type scale**：12 / 14 / 16 / 18 / 24 / 32 / 48
- **Light + Dark 兩版色票**
- **Iconset**：Lucide 或 Heroicons（vendor 化 SVG sprite）
- **Motion**：duration token + easing token
- **Density tier**：dashboard 高 / settings 中 / empty 低
- **範例 component**：button / card / table-row / tab / form-field（皆給 token-only CSS）

### §6.2 Report + Email direction

候選評估表（Typography 權重最高、Motion 權重最低）：

| 候選 | Typography | Color | Spatial | Backgrounds | Distinct | 適用 P5 |
|---|---|---|---|---|---|---|
| A. 維持現狀 | _TBD_ | | | | | |
| B. editorial-magazine | | | | | | |
| C. data-journalism | | | | | | |
| D. corporate-formal | | | | | | |

**推薦傾向**：

- 默認傾向 **B (editorial-magazine)** — P5 主管的「閱讀體驗 + 商業報告專業感」契合
- **C (data-journalism)** 若報告以圖表為主則考慮
- **D (corporate-formal)** 若 audience 含合規 / 法務則考慮
- **A (維持)** 視現況分數而定

#### Adopted Direction Spec Sheet（採用後填入）

- **Type scale**（含 print 段供 PDF）
- **Cover page** 設計
- **章節節奏**（H1 / H2 / H3 上下空白比例）
- **Tabular figures** + 圖表配色
- **Email 子集**：刪 webfont、刪 grid、保留色票 primitive

### §6.3 跨兩套的共享 primitive（OQ-7 default）

- **共享**：色票 primitive（base / accent / signal-* semantic colors）
- **不共享**：type scale（GUI 螢幕 vs 文件 print 不同需求）、spacing scale（GUI 高密度 vs 文件呼吸感）

---

## §7 Mockup Appendix

每個 mockup 用 Visual Companion 產出 HTML 片段，spec 內附 screenshot + Visual Companion 連結。

### M1 — GUI tab loading

| | Before | After |
|---|---|---|
| 描述 | 現況同步載入空白 + a6 破版（若可重現） | 套用 §6.1 後 skeleton + staggered reveal + token 配色 |
| 版本 | light + dark | light + dark |
| 觸及痛點 | a1 + a2（部分）+ a6 visualization | — |

### M4 — Report summary section

| | Before | After |
|---|---|---|
| 描述 | c1「太長 / 摘要不夠」段落 | 套用 §6.2 後 執行摘要區 + verdict 對照表 + chart 重畫 |
| 版本 | light only（PDF/HTML 報告以 light 為主） | light only |
| 觸及痛點 | c1 + c3 | — |

### M5 — Email HTML

| | Before | After |
|---|---|---|
| 描述 | mail_wrapper 直送的版型 | 套用 §6.2 子集 preheader + bulletproof CTA + dark-mode-safe |
| 版本 | light + dark（dark mode 反轉是 Email 已知雷區，必雙版） | light + dark |
| 觸及痛點 | d2 + d3 | — |

---

## §8 Open Questions

| ID | 問題 | 狀態 | Default / 答案 |
|---|---|---|---|
| OQ-1 | 是否接受打破 Flask 換 FastAPI / Starlette / Litestar？ | **Resolved** | 可換，前提 = offline bundle 安裝（C1 仍硬） |
| OQ-2 | 是否接受打破既有 i18n keys 命名空間？ | **Resolved** | 可重組；deploy 期附 migration mapping |
| OQ-3 | GUI redesign Task 6 視覺驗證是否視為 §3.1.0 延伸 pre-condition？ | Open | Default：是，先收 Task 6 → 再啟動 GUI 實作 |
| OQ-4 | Mockup light/dark 兩版策略確認？ | Open | Default：M1 兩版 / M4 light only / M5 兩版 |
| OQ-5 | §3.4.2 Email 渲染矩陣是否需實測？ | Open | Default：spec 列 known-issue 矩陣，實測列為下游 implementation 任務 |
| OQ-6 | §3.2 CLI 的 L4「Click + Rich + Typer 完全重寫」是否上推薦清單？ | Open | Default：列出選項但默認不推薦，除非 Track C 過程經驗證需要 |
| OQ-7 | §6.1 GUI 與 §6.2 Report/Email 的兩套視覺方向是否共享 token primitive？ | Open | Default：共享色票 primitive；type-scale 與 spacing-scale 各自 |
| OQ-8 | spec 寫作期是否強制執行 §3.1.0 a7 掃描並填入違規清單？ | Open | Default：是，spec 不能空著 a7 表（這是唯一的 P0 hard-gate） |
| OQ-9 | 若推薦 Track E（Backend Async），是否同步切換到 ASGI server？ | Open | Default：是，FastAPI / Starlette + Uvicorn（offline wheel ready） |
| OQ-10 | Illumio 既有英文術語（Allowed/Blocked/Managed/Unmanaged/boundary 等）的留英 vs 譯中策略，是否要在本 spec 內定義「判定原則」？ | Open | Default：是，§3.3.2 內列「Illumio 工程術語留英、UI 動詞與狀態譯中」原則 |

---

## §9 Out-of-scope / Defer

### Reliability（不在 UX 評估範圍）

- mail / line 測試無回應 → 可靠性 sprint
- Integrations Overview HTTP 503 → 可靠性 sprint
- bug-1 XLSX 報告 GUI 不可見（gui/__init__.py 未傳 `traffic_report_profile` 是已知成因）→ bug fix sprint

### i18n 資料補齊（不是結構 / UX 議題；OQ-2 已開放重組空間）

- `gui_sched_*` / `daily_report` / `daily-audit-report` / `gui_time_minutes_ago` 等 missing key → i18n sprint
- `traffic_report_profile` 參數遺漏 → redesign Task 6 收尾

### 進行中工作（本 spec 假設完成）

- h5-gui-blueprint-split
- h6-settings-rename-reorg
- Integrations UI/UX redesign Task 6（OQ-3 預設視為延伸 pre-condition）

### 技術選型升級（值得獨立 spec）

- Vue / React 完整 SPA framework swap：本 spec 列為 §3.1.4 候選但不推薦做完整評估
- Click + Rich + Typer 完全重寫 CLI（OQ-6）

### 效能 profiling（不在 UX 評估範圍）

- 本 spec 給 a1 估算「TTI > 3s」是基於 bundle 大小推論（370 KB JS + 127 KB HTML）
- 實測 RUM / Lighthouse 屬獨立 implementation 任務

---

## §10 Glossary

- **Pre-condition** — 必須先解決才能進行其他評估的痛點（直接違反硬約束 / 阻斷其他 finding 採集）。本 spec 中為 a6 + a7。
- **Touch radius** — 一個改動會影響的程式碼範圍。小（< 5 檔）/ 中（單一模組）/ 大（跨模組）。
- **5 Gate** — §2.6 用以判定「優化 vs 重構」推薦的五個關卡：Offline / 多痛點共因 / Touch radius / Persona 衝擊 / Reversibility。
- **Track** — §5.2 的 bundled refactor unit，一條 Track 對應一個結構性改動，可解多個痛點。
- **Persona Weight** — §2.2 評分公式中的 persona 權重。P1=3 / P2=2 / P5=2 / 其他=1。
- **Distinctiveness** — frontend-design 中用以判定一個介面是否有「unforgettable thing」的整體分。本 spec 對 ops 工具的目標 = 2，不追求 art-piece 的 3。
- **TTY-specific 12 條** — §2.5 自訂的 CLI rubric，補 ui-ux-pro-max 不涵蓋的 CLI 議題。
- **R-yes** — 「每個痛點都列出『優化路線 + 重構路線』雙方案」的設計原則。
- **F4** — 評估產出形式：清單 + 量化證據 + mockup 全餐。

---

## §11 References

- ui-ux-pro-max skill（10 priorities, 99 UX rules, 161 color palettes, 50+ styles）
- frontend-design skill（aesthetic 5 維度 + Distinctiveness）
- GitHub CLI style guide — https://primer.style/cli
- 12-factor CLI（Heroku）— heroku 命令設計原則
- charmbracelet design language — gum / huh / vhs（CLI 互動體驗範式）
- Click / Typer / Rich 官方 patterns
- MJML — Mailjet Markup Language（Email 跨 client 預編譯）
- WCAG 2.1 / 2.2 — Web Content Accessibility Guidelines

### 相關專案 spec / plan

- `docs/superpowers/plans/2026-04-26-integrations-ui-ux-redesign.md`（OQ-3 引用）
- `docs/superpowers/plans/2026-04-25-report-r01-semantics-and-profiles.md`（c1 c3 對照）
- `docs/superpowers/plans/2026-04-25-report-r02-compression-and-appendix.md`
- `docs/superpowers/plans/2026-04-25-report-r03-new-analysis.md`
- `docs/superpowers/plans/2026-05-04-pdf-report-fixes.md`（c3 chart 近期修補）
- `docs/superpowers/plans/2026-05-02-h5-gui-blueprint-split.md`（§9 Out-of-scope 假設完成）
- `docs/superpowers/plans/2026-05-02-h6-settings-rename-reorg.md`（同上）
