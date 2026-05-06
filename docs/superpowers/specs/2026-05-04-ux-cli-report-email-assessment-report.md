---
Title: UX / CLI / Report / Email 全域評估報告
Source spec: docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-design.md
Status: in-progress (Phase 0 complete, 後續 Phase A-H 填入)
Generated: 2026-05-04
---

# UX / CLI / Report / Email 全域評估報告

> 本檔依 design spec 結構鏡像產出。每個 §X.Y 對應 design spec 同編號章節的「填入結果」。
> 方法學 / rubric 定義皆引用 design spec，不在此重複。

---

## §1 Scope & Assumptions

### §1.0 文件定位（如何閱讀本 spec）

_（評估執行階段尚未填入）_

### §1.1 涵蓋

_（評估執行階段尚未填入）_

### §1.2 Persona 排序

_（評估執行階段尚未填入）_

### §1.3 硬約束

_（評估執行階段尚未填入）_

### §1.4 不在範圍

_（評估執行階段尚未填入）_

### §1.5 評估維度

_（評估執行階段尚未填入）_

---

## §2 Methodology

### §2.1 量化指標

_（評估執行階段尚未填入）_

### §2.2 痛點優先級評分公式

_（評估執行階段尚未填入）_

#### 門檻

_（評估執行階段尚未填入）_

### §2.3 GUI UX rubric（採 ui-ux-pro-max 10 類，0-3 分）

_（評估執行階段尚未填入）_

### §2.4 Visual Identity rubric（採 frontend-design 5 維度，0-3 分）

_（評估執行階段尚未填入）_

### §2.5 CLI-specific rubric（TTY 12 條，0-3 分）

_（評估執行階段尚未填入）_

### §2.6 重構 vs 優化判定 — 5 個 Gate

_（評估執行階段尚未填入）_

### §2.7 Evidence collection 規範

_（評估執行階段尚未填入）_

---

## §3 Subsystem Assessments（上半）

### §3.1 Frontend GUI

#### §3.1.0 Pre-conditions（先解再談優化）

##### a6 — HTTPS 啟用後 layout 破版

驗證日期：2026-05-04
本評估狀態：成因清單已給可靠性 sprint，本 spec 不修。

成因假設驗證表：
| 假設 | 狀態 | 證據 |
|---|---|---|
| 1. Mixed-content blocking | 待驗證 | DevTools 重現待你方執行；GUI 未運行，無法靜態確認 |
| 2. external resources 走 http:// | 已排除 | A.1 a7 共 7 個外部資源，2 個真正違反皆 https:// (Google Fonts)，0 個 http:// |
| 3. CSP 配置缺失或過嚴 | 已確認（過嚴） | `src/gui/__init__.py:251` font-src 僅允許 `'self'`，但 `src/templates/login.html:7-8` 仍載入 Google Fonts CDN (fonts.googleapis.com / fonts.gstatic.com)；啟用 HTTPS 後 Talisman 套用 CSP，外部字型被阻擋，造成 layout 破版 |
| 4. Cookie SameSite/Secure | 待驗證 | `src/gui/__init__.py:131,140` SESSION_COOKIE_SAMESITE=Strict、SESSION_COOKIE_SECURE=True（硬編碼）；Strict 模式在跨站重導向時可能丟失 session，但與 layout 破版關係間接，需實際瀏覽器測試確認 |

相關歷史變更：commit 24fe5ff 已移除 HTTP→HTTPS 自動重導向 server（5 files，41 deletions）。

Hand-off owner：可靠性 sprint
建議優先處理：a7 vendor 化（將 Google Fonts 本地化，同時解決 CSP font-src 阻擋與 mixed-content 風險，與假設 2、3 同源關係最強）

##### a7 — UI 依賴 external resources（違反 C1）

掃描日期：2026-05-04
總命中數：7（其中真正違反 C1 = 2；其餘 5 筆為 namespace 屬性、placeholder 文字、文件 URL、後端 API endpoint，非瀏覽器載入資源）

| 檔案 | 行 | URL | 資源類型 | 被 HTTPS 阻擋 | 替代本地 asset 建議 |
|---|---|---|---|---|---|
| src/templates/login.html | 7 | https://fonts.googleapis.com | font/CSS preconnect | ✓ | vendor/fonts/（self-host Montserrat woff2） |
| src/templates/login.html | 8 | https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap | CSS/webfont | ✓ | vendor/fonts/ + vendor/css/（@font-face 自建） |
| src/templates/login.html | 173 | http://www.w3.org/2000/svg | SVG namespace | N/A | （不載入 — XML namespace 屬性，無網路請求） |
| src/static/js/settings.js | 208 | https://pce.example.com:8443 | placeholder 文字 | N/A | （不載入 — UI input placeholder） |
| src/static/fonts/LICENSE-NotoSansCJK.txt | 5 | https://github.com/notofonts/noto-cjk | 文件 URL | N/A | （不載入 — license 文件說明） |
| src/alerts/plugins.py | 80 | https://api.line.me/v2/bot/message/push | 後端 API endpoint | N/A | （不載入 — 伺服器端 HTTP call，非瀏覽器資源） |
| src/alerts/metadata.py | 95 | https://hooks.example.com/events | placeholder 文字 | N/A | （不載入 — webhook URL 欄位 placeholder） |

Vendor 化目標位置（彙整）：
- vendor/fonts/ ← 2 個 webfont 資源（Montserrat woff2 各字重：400/500/600/700）
- vendor/css/ ← 1 個 CSS（@font-face 替代 Google Fonts stylesheet）

掃描範圍說明：`src/templates`、`src/static`、`src/alerts` 三個目錄均已掃描；binary 檔案（.otf、.pyc）grep 命中已排除。

P0 hard-gate 狀態：BLOCKED — login.html 第 7–8 行直接從 Google Fonts CDN 載入 Montserrat 字型，部署於強制 HTTPS 的離線環境將因混合內容或無法連外而失敗。須於 Task B.2 完成 vendor 化後方可解除。

#### §3.1.1 整體現況量化

##### 一、檔案大小表（降冪排序）

| 檔案 | 路徑 | 行數 | 大小 | 旗標 |
|---|---|---:|---:|---|
| index.html | src/templates/ | 2,002 | 127.4 KB | 🔴 >20 KB |
| dashboard.js | src/static/js/ | 1,778 | 79.2 KB | 🔴 >20 KB |
| integrations.js | src/static/js/ | 1,232 | 54.2 KB | 🔴 >20 KB |
| app.css | src/static/css/ | 1,391 | 31.7 KB | 🔴 >20 KB |
| rule-scheduler.js | src/static/js/ | 666 | 28.6 KB | 🔴 >20 KB |
| settings.js | src/static/js/ | 488 | 24.7 KB | 🔴 >20 KB |
| quarantine.js | src/static/js/ | 571 | 23.2 KB | 🔴 >20 KB |
| rules.js | src/static/js/ | 510 | 22.4 KB | 🔴 >20 KB |
| utils.js | src/static/js/ | 432 | 16.1 KB | 🟡 >5 KB |
| dashboard_v2.js | src/static/js/ | 359 | 15.4 KB | 🟡 >5 KB |
| events.js | src/static/js/ | 287 | 10.4 KB | 🟡 >5 KB |
| actions.js | src/static/js/ | 101 | 4.7 KB | — |
| login.html | src/templates/ | 337 | 10.3 KB | 🟡 >5 KB |
| _event_dispatcher.js | src/static/js/ | 74 | 2.6 KB | — |
| module-log.js | src/static/js/ | 76 | 2.2 KB | — |
| tabs.js | src/static/js/ | 22 | 1.1 KB | — |

> 旗標標準：>5 KB → 🟡，>20 KB → 🔴（各頁面全量載入，無 code-splitting）

##### 二、總計

| 類別 | 總大小 | 說明 |
|---|---:|---|
| JS（13 檔） | ~285 KB | `wc -c` 合計 291,723 bytes |
| CSS（1 檔） | ~31.7 KB | app.css 32,430 bytes |
| Templates（2 檔） | ~137.7 KB | index.html 127.4 KB + login.html 10.3 KB |

注：無 npm 建置流程，所有 JS/CSS 均以原始碼直接 serve，未 minify / bundle。

##### 三、radon CC 高複雜度函式（CC > 10）

掃描範圍：`src/gui/`（Python），`src/gui/routes/`（sub-blueprint）。

| 函式 | 檔案 | CC 等級 |
|---|---|---|
| `_summarize_alert_channels` (line 317) | src/gui/_helpers.py | C (19) |
| `_generate_self_signed_cert` (line 598) | src/gui/_helpers.py | C (15) |

`src/gui/routes/` 全 9 個 blueprint factory：全部 A (1)，無高複雜度。

附注：`src/gui/__init__.py` 含 BOM 字元（U+FEFF），radon 解析錯誤，已排除於統計外；建議修正 encoding。

##### 四、radon MI 低分模組（MI < 20）

無。所有可解析模組均達 A 級：

| 模組 | MI 分數 |
|---|---|
| src/gui/_helpers.py | 21.24（A） |
| src/gui/settings_helpers.py | 100.00（A） |
| src/gui/routes/reports.py | 33.73（A） |
| src/gui/routes/dashboard.py | 35.04（A） |
| src/gui/routes/events.py | 35.63（A） |

最低分為 `_helpers.py`（21.24），仍在 A 級閾值（>20）之上；不觸發警告。

##### 五、dashboard.js vs dashboard_v2.js 共存觀察

| 項目 | dashboard.js | dashboard_v2.js |
|---|---|---|
| 大小 | 79.2 KB / 1,778 行 | 15.4 KB / 359 行 |
| 最後更新 | 2026-05-04（現行） | 2026-04-23（停更） |
| 引入時機 | 重構前主檔 | Apr 9 重構拆分嘗試 |
| 首個 commit | 早於 dashboard_v2.js | `4e4c3de`（Refactor vendor-aligned event engine） |

**結論**：`dashboard_v2.js` 開頭 6 個函式（`_dashboardCardTone`、`_dashboardSetCard`、`_pickValue`、`_buildAuditSummaryFieldset`、`ensureTrafficWorkloadLayout`、`ensureDashboardLayout`）在 `dashboard.js` 第 17–171 行均有同名定義。兩檔於 `index.html` 第 1990–1991 行依序載入，後者覆蓋前者（無 namespace 隔離）。`dashboard_v2.js` 為 Apr 9 重構過渡產物，目前已停更，屬**進行中拆分的遺留副本**，應在拆分完成後刪除。

##### 六、進行中重構訊號

- **H5 Blueprint split（完成）**：`src/gui/routes/` 下已完成 9 個 blueprint factory 分拆（`actions`、`admin`、`auth`、`config`、`dashboard`、`events`、`reports`、`rule_scheduler`、`rules`），最後步驟 commit `1fa8c61`（2026 年）。
- **H6 Settings reorg（完成）**：CLI settings 拆至 `src/cli/menus/`，共 10 步，最終 commit `31d4715` 退役 baseline scaffolding。兩項重構均已完成，但 `dashboard_v2.js` 殘留為尚未清理的過渡產物。

##### 七、外部資源計數（彙總自 §3.1.0 a7）

依 §3.1.0 a7 掃描結果：7 hits，**2 真正違反**（P0 hard-gate，詳見 §3.1.0）：
- `login.html` 第 7–8 行：Google Fonts CDN（Montserrat），違反 C1（外部依賴）
- 同上：CDN 載入在強制 HTTPS 離線環境下將因混合內容或無法連外失敗

##### Bundle 載入順序與依賴圖

**資料來源**：`src/templates/index.html` 全文掃描（13 個 `<script src=` 標籤）、`src/static/js/` 所有 .js 檔案符號分析。

---

**Bundle 載入順序**（依 index.html 出現順序）

1. `js/_event_dispatcher.js`（`<head>`，line 13）— CSP-friendly 事件委派層；立即執行 IIFE，無 global export，靠 `window[fnName]` 解析其他模組函式
2. *(inline script, line 17)* — 翻譯初始化（`window._INIT_TRANSLATIONS`），套用 `data-i18n` 屬性
3. `js/integrations.js`（body 中段，line 989）— 嵌入於 integrations panel HTML 之後，於其他功能模組**之前**載入
4. `js/utils.js`（body 末端，line 1988）— 核心 HTTP 工具（`api`/`post`/`put`/`del`）、CSRF、i18n（`_t`）、時區、`escapeHtml`；**所有功能模組的基礎依賴**
5. `js/tabs.js`（body 末端，line 1989）— `switchTab()` 全域函式
6. `js/dashboard.js`（body 末端，line 1990）— 主儀表板（1,778 行）
7. `js/dashboard_v2.js`（body 末端，line 1991）— 過渡副本（見五）；覆蓋 dashboard.js 中 6 個同名函式
8. `js/events.js`（body 末端，line 1992）— Event Viewer 模組
9. `js/rules.js`（body 末端，line 1993）— Alert Rules 模組；定義 `showSkeleton`/`showSpinner`/`hideSpinner` 等被多模組共用的 DOM 工具
10. `js/settings.js`（body 末端，line 1994）— Settings 模組
11. `js/actions.js`（body 末端，line 1995）— Alert Channel 動作
12. `js/quarantine.js`（body 末端，line 1996）— Quarantine 模組
13. `js/rule-scheduler.js`（body 末端，line 1997）— Rule Scheduler 模組
14. `js/module-log.js`（body 末端，line 1998）— Module Log 檢視器

（共 13 個外部 `<script src=>`，另有 2 個 inline `<script nonce=>`；合計 15 個 `<script>` 區塊）

---

**JS 模組關聯（全域命名空間隱式依賴）**

無 ES module `import` / CommonJS `require`。所有模組均掛載於 `window.*`，透過 `_event_dispatcher.js` 的 `window[fnName]` 查找完成呼叫。依賴關係為**隱式**，由載入順序強制保證。

```
window._INIT_TRANSLATIONS (inline)
        │
_event_dispatcher.js  ──────────────────────────┐
        │ delegates clicks/change/input/keydown  │
        ▼                                        │
utils.js                                         │
  ├─ api / post / put / del (CSRF)               │
  ├─ _t (i18n)                                   │
  ├─ escapeHtml                                  │
  └─ _editIdx (shared modal state) ──────────────┼─► rules.js (openModal/closeModal)
        │                                        │
        ├──► tabs.js (switchTab)  ◄──────────────┘ (data-action="switchTab")
        │
        ├──► integrations.js  (api, post, put, del, _t, escapeHtml, switchTab)
        │       └─ 早於 utils.js 載入（line 989 < 1988）⚠  ← 載入順序缺陷
        │
        ├──► dashboard.js     (api, post, put, del, _t, escapeHtml, showSkeleton*)
        │       └─ showSkeleton / showSpinner / hideSpinner 定義於 rules.js
        │
        ├──► dashboard_v2.js  (同名覆蓋：_dashboardSetCard, _pickValue, ensureDashboardLayout 等)
        │       └─ 過渡副本，停更，應刪除
        │
        ├──► events.js        (api, post, del, _t, escapeHtml)
        ├──► rules.js         (api, post, put, del, _t, escapeHtml, _editIdx)
        │       └─ 定義 showSkeleton / showSpinner / hideSpinner（被 dashboard.js 使用）
        ├──► settings.js      (api, post, put, del, _t, escapeHtml)
        ├──► actions.js       (api, post, put, del, _t, escapeHtml)
        ├──► quarantine.js    (api, post, del, _t, escapeHtml, showSkeleton, switchTab)
        ├──► rule-scheduler.js(api, post, put, del, _t, escapeHtml, showSkeleton, switchTab)
        └──► module-log.js    (api, _t, escapeHtml)
```

> `*` showSkeleton/showSpinner/hideSpinner 定義在 rules.js（line 200–219），被 dashboard.js、quarantine.js、rule-scheduler.js 呼叫。這三個函式語義上屬 utils 層但位於 rules.js，為**隱性共用 DOM 工具跨模組散佈**的典型案例。

---

**defer / async 使用率**

| 統計項目 | 數值 |
|---|---:|
| 總 `<script src=>` 標籤數 | 13 |
| 含 `defer` 屬性 | 0 |
| 含 `async` 屬性 | 0 |
| defer/async 使用率 | **0%** |

所有腳本均為同步阻塞載入（render-blocking），其中 `_event_dispatcher.js` 位於 `<head>` 更是最早阻塞點。

---

**⚠ 關鍵觀察：integrations.js 載入時序缺陷**

`integrations.js`（line 989）在 `utils.js`（line 1988）之前載入，但大量使用 `api`、`post`、`_t`、`escapeHtml` 等 utils 符號。此時 utils.js 尚未執行，`integrations.js` 中的頂層立即呼叫（若有）將因符號未定義而失敗。目前程式碼依賴「頂層無立即呼叫，所有函式僅在使用者互動後觸發」的隱式慣例來迴避這個競態——脆弱且不可自驗。

#### §3.1.2 UX rubric 結果（10 類）

_（評估執行階段尚未填入）_

#### §3.1.3 Visual Identity 現況評估

_（評估執行階段尚未填入）_

#### §3.1.4 可選方向

##### Aesthetic axis（視覺方向）

| 候選 | 描述 | 適用 persona |
|---|---|---|
| A. 維持現狀 | （baseline） | — |
| B. industrial-editorial | 高密度、tabular figures、editorial 字體層級、克制配色 | P1 + P2 |
| C. modern-saas | Linear/Vercel 風、generic | (不推薦 — 過於 cookie-cutter) |
| D. dark-ops 終端感 | Bloomberg / 終端機暗色、monospace 為核 | P2 SOC |

_（每候選 9 欄 spec sheet 評估執行階段填入）_

##### Framework axis

| 候選 | offline 友善 | touch | risk | 推薦條件 |
|---|---|---|---|---|
| Stay Vanilla + Design System | ✅ | 中 | 低 | 默認推薦 |
| HTMX + Alpine.js | ✅（vendor 化） | 中 | 中 | 若需強化 server-rendered + 局部互動 |
| Vue 3 + Vite | ⚠ build pipeline 進 offline bundle | 大 | 高 | 若 a1 在前面 phase 仍解不掉 |
| Lit + Web Components | ✅ | 中 | 中 | 若需 component 化但避 framework lock-in |

_（每候選跑 §2.6 五 Gate 評估執行階段填入）_

##### Backend axis

| 候選 | offline (wheels) | UX 直接收益 | 推薦條件 |
|---|---|---|---|
| Flask（現狀） | ✅ | 0 | 默認 |
| FastAPI + Uvicorn | ✅ | 中（async + SSE 釋放長任務） | 若需 SSE 進度推送 / async DB |
| Starlette | ✅ | 中 | 同上但更輕 |
| Litestar | ⚠ 需確認 wheel | 中 | 若需強型別 OpenAPI |

_（每候選跑 §2.6 五 Gate 評估執行階段填入）_

#### §3.1.5 推薦組合

_（評估執行階段尚未填入）_

---

### §3.2 CLI

#### §3.2.1 Command Inventory

掃描 4 個入口（`src/cli/root.py` 的 Click 樹、`src/pce_cache_cli.py`、`src/rule_scheduler_cli.py`、`src/siem_cli.py`）並逐一讀取原始碼後填入：

| 入口 | 命令 | verb | noun | flags | 輸出格式 | exit codes | isatty 處理 | --json | menu 也露出？ |
|---|---|---|---|---|---|---|---|---|---|
| root | cache backfill | backfill | cache | --source (req), --since (req), --until | rich Console (plain text progress) | 0 / 1 | no | no | yes (pce_cache_cli 選單 5) |
| root | cache status | status | cache | — | rich Table | 0 only | no | no | yes (pce_cache_cli 選單 1) |
| root | cache retention | retention | cache | --run | rich Table | 0 / 1 | no | no | yes (pce_cache_cli 選單 6) |
| root | config show | show | config | --section | rich console_json (pretty JSON) | 0 only | no | no | no |
| root | config validate | validate | config | --file | rich Console (plain text) | 0 only | no | no | no |
| root | gui | launch | gui | --port, --host | 無（啟動 server） | 0 only | no | no | yes (main_menu 選單 5) |
| root | monitor | run | monitor | --interval | 無（daemon 模式） | 0 only | no | no | no |
| root | report traffic | generate | report | --source, --file, --format, --output-dir, --email, --profile | click.echo (file path list, plain text) | 0 / 1 (ClickException) | no | no | yes (report_generation_menu 選單 1) |
| root | report audit | generate | report | --start-date, --end-date, --format, --output-dir | click.echo (file path list, plain text) | 0 / 1 (ClickException) | no | no | yes (report_generation_menu 選單 2) |
| root | report ven-status | generate | report | --format, --output-dir | click.echo (file path list, plain text) | 0 / 1 (ClickException) | no | no | yes (report_generation_menu 選單 3) |
| root | report policy-usage | generate | report | --source, --file, --start-date, --end-date, --format, --output-dir | click.echo (file path list, plain text) | 0 / 1 (ClickException) | no | no | yes (report_generation_menu 選單 4) |
| root | rule list | list | rule | --type, --enabled-only | rich Table | 0 only | no | no | no |
| root | rule edit | edit | rule | RULE_ID (arg), --no-preview | rich Syntax (JSON diff) + questionary | 0 only | no | no | no |
| root | siem status | status | siem | — | rich Table | 0 / 1 | no | no | yes (siem_cli 選單 1) |
| root | siem test | test | siem | DESTINATION (arg) | rich Console (plain text) | 0 / 1 | no | no | yes (siem_cli 選單 7) |
| root | siem dlq | list | siem-dlq | --dest (req), --limit | rich Table | 0 / 1 | no | no | yes (siem_cli 選單 8a) |
| root | siem replay | replay | siem-dlq | --dest (req), --limit | rich Console (plain text) | 0 / 1 | no | no | yes (siem_cli 選單 8b) |
| root | siem purge | purge | siem-dlq | --dest (req), --older-than | rich Console (plain text) | 0 / 1 | no | no | yes (siem_cli 選單 8c/d) |
| root | status | status | daemon | — | rich Table | 0 only | no | no | no |
| root | version | version | app | — | click.echo (plain text) | 0 only | no | no | no |
| root | workload list | list | workload | --env, --limit, --enforcement, --managed-only | rich Table (with Progress spinner) | 0 only | no | no | no |
| pce_cache_cli | pce-cache view-status | view | cache | — (互動式) | plain print() | none | no | no | yes (main_menu 選單 7) |
| pce_cache_cli | pce-cache backfill | backfill | cache | 互動輸入 start/end | plain print() | none | no | no | yes (main_menu 選單 7) |
| rule_scheduler_cli | rule-scheduler manage | manage | rule-schedule | 互動選單 (a/e/d/r) | ANSI Colors + plain print() | none | no | no | yes (main_menu 選單 3) |

**觀察摘要（Summary Observations）**

1. **Verb 一致性差**：根 CLI 共使用 8 個動詞（backfill, status, retention, show, validate, launch, run, generate, list, edit, test, replay, purge, version），但 verb 語義並不統一——report 的子命令省略 verb 直接以 noun 分類（traffic/audit/ven-status/policy-usage），而 cache/siem/rule 則以動詞為子命令名稱，風格混雜。

2. **--json 支援率：0/24（0%）**：所有命令均無 `--json` 旗標，無法用於 pipeline 或機器消費。rich Table 輸出在 pipe 場景（isatty=false）仍會渲染 ANSI markup，造成 b3（輸出格式）和 b6（isatty/pipe 友善）的雙重缺失。

3. **isatty 切換輸出：0/24（0%）**：`_render.py` 的 `_stdout_is_tty()` 僅用於 Colors ANSI 和 safe_input 模式切換（questionary vs plain input()）；**不** 用於在 non-TTY 場合改為輸出 plain text 或 JSON，即 root CLI 的 rich Table 在被 pipe 時也照常渲染 box characters。

4. **exit codes 不完整**：root CLI 部分命令（cache, siem）使用 `sys.exit(1)` 或 `raise SystemExit(1)`，但 report 命令仰賴 `click.ClickException`（自動 exit 1），而互動 menu 入口（pce_cache_cli, rule_scheduler_cli, siem_cli）**完全無** exit code 語義，永遠回傳 0（b7 缺陷）。

5. **menu 雙重入口（b5 痛點）**：24 個命令中，14 個（58%）同時透過互動選單和 root CLI 公開，但兩個路徑的實作完全分離——menu 版本用 plain `print()`，root CLI 版本用 rich，行為不一致且無法共享。3 個純 menu 命令（pce_cache 的 edit-settings/traffic-filter/sampling 等）**僅** 在互動路徑存在，root CLI 無法觸達。

#### §3.2.2 Consistency Matrix

掃描基礎：`cli-tty-flags.txt`（Step 1）+ §3.2.1 inventory（24 commands）。

---

##### 1. 旗標命名不一致清單

同一概念在不同命令使用不同旗標名稱：

| 概念 | 命令 A | 旗標 A | 命令 B | 旗標 B | 備註 |
|---|---|---|---|---|---|
| 時間範圍起點 | `cache backfill` | `--since` | `report audit`, `report policy-usage` | `--start-date` | 相同語義（YYYY-MM-DD），旗標名不同 |
| 時間範圍終點 | `cache backfill` | `--until` | `report audit`, `report policy-usage` | `--end-date` | 相同語義，旗標名不同 |
| 資料來源 | `cache backfill` | `--source` (Choice: events\|traffic) | `report traffic`, `report policy-usage` | `--source` (Choice: api\|csv) | **同名異義**：旗標名相同但語義完全不同 |
| SIEM 目標名稱 | `siem test` | positional `DESTINATION` (arg) | `siem replay`, `siem dlq`, `siem purge` | `--dest` (option, required) | 同一概念分別用 positional arg 和具名 option |
| 資料筆數限制 | `siem dlq` | `--limit` (default 50) | `siem replay` | `--limit` (default 100) | 旗標同名但 default 值不一致（50 vs 100） |

**小結**：5 個不一致點，其中 `--source` 同名異義最嚴重（影響自動補全與文件）；`DESTINATION` vs `--dest` 混用 positional/option 破壞 pipeline 脚本相容性。

---

##### 2. verb-noun 順序不一致清單

root CLI 整體採 `noun verb` 風格（group → subcommand），但內部存在風格裂縫：

| 命令路徑 | 實際排列 | 風格 | 備註 |
|---|---|---|---|
| `illumio-ops rule list` | noun → verb | noun-first ✓ | `rule` = noun group, `list` = verb |
| `illumio-ops cache backfill` | noun → verb | noun-first ✓ | |
| `illumio-ops report traffic` | noun → noun-as-type | **無 verb** | `traffic` 是報告類型，非動詞；`generate` 隱含在函式名 `generate_traffic_report` |
| `illumio-ops report audit` | noun → noun-as-type | **無 verb** | 同上；report 子命令全部以 noun 為名（traffic/audit/ven-status/policy-usage） |
| `illumio-ops siem status` | noun → verb | noun-first ✓ | |
| `illumio-ops siem test` | noun → verb | noun-first ✓ | `test` 既是 noun 也是 verb，語義模糊 |
| `pce_cache_cli` (menu) | 互動選單，無 CLI 命令名稱 | — | 無命令樹，僅數字選單 |
| `rule_scheduler_cli` (menu) | 互動選單，無 CLI 命令名稱 | — | 無命令樹，僅字母選單 |

**小結**：root CLI 共 8 個 group/command 中，`report` 子命令（4 個）違背 verb-subcommand 慣例，以類型 noun 取代動詞，與 `rule list`、`cache backfill` 等風格不一致。3 個純 menu 入口完全無命令結構。

---

##### 3. 輸出格式預設不一致清單

| 命令 | 輸出方式 | 是否 TTY-aware | pipe 下行為 |
|---|---|---|---|
| `cache backfill` | `rich.Console` (進度文字) | no | ANSI markup 直接輸出 |
| `cache status` | `rich.Table` | no | box characters 直接輸出 |
| `cache retention` | `rich.Table` | no | box characters 直接輸出 |
| `config show` | `rich.Console.print_json` | no | JSON-formatted, ANSI 上色 |
| `config validate` | `rich.Console` (plain text) | no | ANSI 上色 |
| `rule list` | `rich.Table` | no | box characters 直接輸出 |
| `rule edit` | `rich.Syntax` (JSON diff) | no | ANSI syntax highlight |
| `siem status` | `rich.Table` | no | box characters 直接輸出 |
| `siem test` | `rich.Console` (plain text) | no | ANSI 上色 |
| `siem dlq` | `rich.Table` | no | box characters 直接輸出 |
| `siem replay` | `rich.Console` (plain text) | no | ANSI 上色 |
| `siem purge` | `rich.Console` (plain text) | no | ANSI 上色 |
| `status` | `rich.Table` | no | box characters 直接輸出 |
| `workload list` | `rich.Table` + Progress spinner | no | box characters + spinner 殘留 |
| `report traffic` | `click.echo` (plain file path) | no | plain text ✓ |
| `report audit` | `click.echo` (plain file path) | no | plain text ✓ |
| `report ven-status` | `click.echo` (plain file path) | no | plain text ✓ |
| `report policy-usage` | `click.echo` (plain file path) | no | plain text ✓ |
| `version` | `click.echo` (plain text) | no | plain text ✓ |
| `gui` | 無（啟動 server） | no | — |
| `monitor` | 無（daemon 模式） | no | — |
| `pce_cache_cli` view-status | plain `print()` | no | plain text（無 rich） |
| `pce_cache_cli` backfill | plain `print()` | no | plain text（無 rich） |
| `rule_scheduler_cli` manage | `print()` + ANSI Colors 類 | no | ANSI escape codes 殘留 |

**量化**：21 個有輸出命令中，rich 輸出 13 個（62%），click.echo 5 個（24%），plain print 3 個（14%）。**0/21 會在 non-TTY 情境自動切換格式**（`_stdout_is_tty()` 存在於 `_render.py` 但不連接至任何 rich Console 或 Table 的條件渲染）。

---

##### 4. 退出碼定義 / 未定義清單

| 命令 / 入口 | 退出碼實作方式 | 碼值 | 問題 |
|---|---|---|---|
| `cache backfill/status/retention` | `sys.exit(1)` 明確呼叫（6 處） | 0 / 1 | ✓ 有定義，但無文件 |
| `siem test/status/replay/purge/dlq` | `raise SystemExit(1)`（7 處） | 0 / 1 | ✓ 有定義；**風格異於** cache 的 `sys.exit(1)` |
| `report *` (4 個子命令) | `raise click.ClickException(...)` | 0 / 1 (Click 自動) | ✓ 有定義，靠 Click 機制；不明確 |
| `_runtime.py` (daemon/gui 啟動) | `sys.exit(1)`（2 處） | 0 / 1 | ✓ |
| `main.py` (頂層 dispatcher) | `sys.exit(exc.exit_code)` | 自訂（唯一處） | `exit_code` 值未見文件 |
| `rule list`, `rule edit` | 無 explicit exit；依賴 Click default | 0 only | ⚠ 錯誤時仍回傳 0 |
| `config show`, `config validate` | 無 explicit exit | 0 only | ⚠ |
| `workload list` | 無 explicit exit | 0 only | ⚠ |
| `status`, `version`, `gui`, `monitor` | 無 explicit exit | 0 only | ⚠ |
| `pce_cache_cli`（menu 入口） | 無任何 sys.exit；while True loop | none | ✗ 錯誤與成功均無差異 |
| `rule_scheduler_cli`（menu 入口） | 無任何 sys.exit | none | ✗ 同上 |
| `siem_cli`（menu 入口） | 無任何 sys.exit | none | ✗ 同上 |

**小結**：3 個 menu 入口完全無退出碼語義（永遠 0）；root CLI 有退出碼的命令（cache, siem, report）風格不統一（`sys.exit` vs `SystemExit` vs `ClickException`）；`exc.exit_code` 自訂值僅出現一處且無文件。

---

##### 5. global flags 位置不一致

| 旗標 | 是否存在 | 位置 | 有此旗標的命令 | 備註 |
|---|---|---|---|---|
| `--json` | **不存在** | — | 0/24 | 無任何命令支援機器可讀輸出 |
| `--quiet` | **不存在** | — | 0/24 | 無靜默模式 |
| `--verbose` | **不存在** | — | 0/24 | 無詳細輸出模式 |
| `--config` / `--config-file` | 部分存在 | per-command | `config validate` 有 `--file`；其餘命令無法指定 config 路徑 | 不在 root group 層級 |
| `--output-dir` | 部分存在 | per-command | 4 個 report 子命令各自定義 | 未提升至 `report` group 層級 |
| `--format` | 部分存在 | per-command | 4 個 report 子命令各自定義 | 未提升至 `report` group 層級 |
| `-i` / `--interval` | 僅 monitor | per-command | `monitor` 命令 | 有短旗標 |
| `-p` / `--port`, `-h` / `--host` | 僅 gui | per-command | `gui` 命令 | 有短旗標；-h 與 Click 預設 --help 衝突（被 context_settings 排除） |

**小結**：root CLI 群組層級（`cli` group）**零個** global flag。`--output-dir` 和 `--format` 在 4 個 report 子命令重複定義，應提升至 `report` group；`--json`/`--quiet`/`--verbose` 完全缺席（composability 基本盤全失）。短旗標僅 monitor（`-i`）和 gui（`-p`,`-h`）有，其餘命令無短旗標。

---

##### 6. `ILLUMIO_OPS_*` 命中率

掃描結果（`grep -rnE 'ILLUMIO_OPS_' src/`）：

| 環境變數 | 定義位置 | 用途 | 文件化？ |
|---|---|---|---|
| `ILLUMIO_OPS_I18N_STRICT` | `src/report/exporters/report_i18n.py:9` | i18n key 找不到時是否拋出例外 | 無（隱藏旗標） |

**命中率：1/∞**（僅 1 個 `ILLUMIO_OPS_*` 環境變數存在於整個 src/ 目錄）。

**問題**：
- **極低發現率**：只有 1 個 env var，且僅控制 i18n strict mode，屬於開發除錯旗標，非操作旗標。
- **完全無文件**：`ILLUMIO_OPS_I18N_STRICT` 未出現於任何 README、help text 或 --help 輸出。
- **覆蓋率空白**：常見需求（config path override、log level、API timeout、offline mode）均無對應 `ILLUMIO_OPS_*` 環境變數，用戶必須修改 `config.json`，無法透過環境變數控制（影響 CI/CD 場景）。
- 對照同類工具（如 `kubectl`、`gh`）通常有 5–15 個 `<APP>_*` env var 作為旗標補充；此專案接近零。

---

**§3.2.2 總結**：所有 6 類不一致均為系統性問題，非個案。0/24 isatty 處理、0/24 `--json` 支援、0 global flags、3 個 menu 入口無 exit code，構成 composability 三項基本盤全部缺失。

#### §3.2.3 Interaction Model Audit（互動 menu 專屬）

_（評估執行階段尚未填入）_

#### §3.2.4 Rubric 打分

_（評估執行階段尚未填入）_

#### §3.2.5 可選方向

| 候選 | 描述 | offline | touch | risk |
|---|---|---|---|---|
| 維持現狀 + 補強 | 純文案 / 錯誤訊息修補 | ✅ | 小 | 低 |
| L2 抽出共享輸出層 | 顏色 / 表格 / spinner / exit code 共享 helper | ✅ | 中 | 低 |
| L3 統一入口 | 單一 `illumio-ops` 根命令含 3 支 CLI；menu 變 `shell` mode | ✅ | 大 | 中 |
| L4 Click + Rich + Typer 完整重寫 | 重新設計命令樹、bash/zsh/fish completion | ✅ | 最大 | 高 |

_（評估執行階段填入推薦結果）_

#### §3.2.6 推薦組合

_（評估執行階段尚未填入）_

---

### §3.3 Report

#### §3.3.1 Report Inventory

| Report | Generator | Exporters | i18n keys 數（EN） | 平均輸出大小 | 主要 sections | 狀態 |
|---|---|---|---|---|---|---|
| audit | `audit_generator.py` (878 行) | `audit_html_exporter.py` (519L) + pdf + csv + xlsx | 48 (`rpt_au_*`) | 須 in-situ 觀察（本評估暫缺） | Executive summary, Health, Users, Policy changes, Correlations | active |
| policy_usage | `policy_usage_generator.py` (656 行) | `policy_usage_html_exporter.py` (532L) + pdf + csv + xlsx | 39 (`rpt_pu_*`) | 須 in-situ 觀察 | Executive summary, Rule overview, Hit detail, Unused rules, Deny effectiveness, Draft PD | active |
| ven_status | `ven_status_generator.py` (368 行) | `ven_html_exporter.py` (209L) + pdf + csv + xlsx | 13 (`rpt_ven_*`) | 須 in-situ 觀察 | Summary, Online inventory, Offline, Lost heartbeat today, Lost heartbeat yesterday | active |
| traffic（主報告） | `report_generator.py` (857 行) | `html_exporter.py` (1337L) + pdf + csv + xlsx | 322 (`rpt_*` 共用) | 須 in-situ 觀察 | mod01–mod15 + ringfence + change_impact（17 個 _mod HTML 方法） | active — 統一入口 |
| dashboard_summaries | `dashboard_summaries.py` (154 行) | 內嵌輸出 JSON（無獨立檔案） | 10 (`*dashboard*`) | n/a（Web UI 用） | audit 摘要, policy_usage 摘要 | active |

**Report Generator / Exporter Legacy 判定：**

`report_generator.py` 與 `html_exporter.py` **均為 active，非 legacy**。

- `report_generator.py` 是系統統一入口：`src/main.py`、`src/cli/report.py`、`src/gui/routes/reports.py`、`src/report_scheduler.py` 四處均直接 `import ReportGenerator`。最後修改涵蓋至最新 commit（`clip_to_cache`、i18n 強化等功能持續在此演進）。
- `html_exporter.py` 是 Traffic 報告的 HTML 輸出核心（17 個 section renderer），同時作為共用基礎設施被三個專屬 HTML exporter（`audit_html_exporter.py`、`policy_usage_html_exporter.py`、`ven_html_exporter.py`）繼承其 `render_section_guidance()`、`_trend_deltas_section()` 等工具函數。
- **建議：保留，不刪除。** 若日後抽出 Traffic 報告為獨立模組，再考慮重命名為 `traffic_html_exporter.py`。

**共用基礎設施（Shared Infra）：**

| 元件 | 路徑 | 行數 | 職責 |
|---|---|---|---|
| `pdf_exporter.py` | `src/report/exporters/` | 280 | ReportLab 純 Python PDF，支援 CJK |
| `chart_renderer.py` | `src/report/exporters/` | 378 | Plotly HTML chart 嵌入 |
| `table_renderer.py` | `src/report/exporters/` | 104 | DataFrame → HTML table，統一樣式 |
| `code_highlighter.py` | `src/report/exporters/` | 22 | syntax highlight CSS 生成 |
| `report_css.py` | `src/report/exporters/` | 653 | 全域 CSS（含 dark mode、CJK 字型） |
| `report_i18n.py` | `src/report/exporters/` | 1057 | 報告層 EN/zh-TW 字串（STRINGS dict + lang toggle HTML） |
| `csv_exporter.py` | `src/report/exporters/` | 81 | CSV 輸出（Traffic 用） |
| `xlsx_exporter.py` | `src/report/exporters/` | 99 | XLSX 輸出（多 sheet） |

#### §3.3.2 Content Audit

_（評估執行階段尚未填入）_

#### §3.3.3 Visual Identity 現況評估（document context）

_（評估執行階段尚未填入）_

#### §3.3.4 可選方向

| 候選 | 描述 | 適用 P5 主管 |
|---|---|---|
| A. 維持現狀 | （baseline） | — |
| B. editorial-magazine | Hoefler 風 / WSJ 工程感、優雅閱讀 | 高 |
| C. data-journalism | NYT / FT / Reuters Graphics 風，圖表敘事為主 | 中（取決於資料密度） |
| D. corporate-formal | McKinsey / 法務 deck / 合規風 | 高（若 audience 含合規） |

_（每候選 spec sheet 評估執行階段填入）_

#### §3.3.5 痛點對應 finding

_（評估執行階段尚未填入）_

#### §3.3.6 推薦組合

_（評估執行階段尚未填入）_

---

### §3.4 Email / Notification

#### §3.4.1 Template Inventory

**引擎**：Python `string.Template`（`safe_substitute`），實作於 `src/alerts/template_utils.py`。
`alert_tpl_*` 前綴的 placeholder 由 `render_alert_template()` 自動從 i18n 層（`src/i18n.py`）注入，呼叫端無需手動傳入。

| 模板 | 大小 | 引擎 | caller-side placeholder 數 | i18n auto-merged 數 | 來源 module | 用於通道 |
|---|---|---|---|---|---|---|
| `mail_wrapper.html.tmpl` | 2.5 KB | `string.Template` | 7 | 8（`alert_tpl_*`） | `src/reporter.py` `_build_mail_html()` | mail |
| `line_digest.txt.tmpl` | 393 B | `string.Template` | 11 | 9（`alert_tpl_*`） | `src/reporter.py` `_build_line_message()` | line |
| `webhook_payload.json.tmpl` | 317 B | `string.Template` | 8 | 0 | `src/reporter.py` `_build_webhook_payload()` | webhook |

**Caller-side placeholder 明細：**

`mail_wrapper.html.tmpl`（7 個，由 `_build_mail_html()` 傳入）：
- `$subject_html` — HTML-escaped 郵件主旨，來自呼叫方 `subj` 參數
- `$generated_at_html` — HTML-escaped 時間戳記，`self._now_str()`
- `$summary_html` — 四個告警類別統計卡片（pre-built HTML 字串）
- `$health_section_html` — 健康告警 HTML 表格（若無告警則為空字串）
- `$event_section_html` — 安全事件 HTML 表格
- `$traffic_section_html` — 流量告警 HTML 表格
- `$metric_section_html` — 指標告警 HTML 表格

`mail_wrapper.html.tmpl` auto-merged i18n（8 個，由 `render_alert_template()` 自動解析）：
`$alert_tpl_official_notice`、`$alert_tpl_summary`、`$alert_tpl_aggregated_blurb`、`$alert_tpl_generated_at`、`$alert_tpl_scope`、`$alert_tpl_categories`、`$alert_tpl_auto_generated`、`$alert_tpl_act_per_runbook`

`line_digest.txt.tmpl`（11 個，由 `_build_line_message()` 傳入）：
- `$subject` — compact 郵件主旨
- `$generated_at` — 時間戳記
- `$total_issues` — 所有告警總計數
- `$health_count`、`$event_count`、`$traffic_count`、`$metric_count` — 各類別計數
- `$health_section`、`$event_section`、`$traffic_section`、`$metric_section` — 各類別文字摘要區塊

`line_digest.txt.tmpl` auto-merged i18n（9 個）：
`$alert_tpl_line_title`、`$alert_tpl_subject`、`$alert_tpl_generated_at`、`$alert_tpl_total_issues`、`$alert_tpl_health_alert`、`$alert_tpl_security_events`、`$alert_tpl_traffic_alert`、`$alert_tpl_metric_alert`、`$alert_tpl_see_web_for_details`

`webhook_payload.json.tmpl`（8 個，由 `_build_webhook_payload()` 傳入，均為 JSON-serialized）：
- `$subject_json` — `json.dumps(subj)`
- `$content_model_json` — 固定值 `"vendor_pretty_cool_events_baseline"`
- `$health_alerts_json` — `self.health_alerts` list
- `$event_alerts_json` — `self.event_alerts` list
- `$event_alert_payloads_json` — `self._build_all_event_alert_payloads()` 結果
- `$traffic_alerts_json` — `self.traffic_alerts` list
- `$metric_alerts_json` — `self.metric_alerts` list
- `$timestamp_json` — UTC ISO-8601 時間戳記

**變數契約彙整：**

共用概念（跨通道語意相同，但呈現形式不同）：
- `subject` / `subject_html` / `subject_json` — 告警主旨
- `generated_at` / `generated_at_html` / `timestamp_json` — 產生時間
- `health_*` / `event_*` / `traffic_*` / `metric_*` — 四類告警資料

通道專屬差異：
- **mail**：section HTML 由 Python 動態組裝後注入（7 個 caller vars）；i18n 標籤由 `render_alert_template()` 自動注入（8 個）
- **line**：純文字段落（`*_section` 已是拼接後的純文字字串）；計數欄位獨立（`*_count`）；i18n 自動注入（9 個）
- **webhook**：全部為 JSON 序列化物件，無 i18n；`content_model_json` 為唯一靜態欄位；資料結構直接使用 reporter 內部 list 物件

#### §3.4.2 Cross-client Compatibility Audit

渲染矩陣（known-issue checklist）：

| Client | 已知雷區 |
|---|---|
| Outlook (Win / Mac / 365) | VML for buttons、`<style>` quirks、`word-wrap`、不支援 flexbox/grid |
| Gmail (web / iOS / Android) | `<style>` 部分支援、可能移除 class、image proxy |
| Apple Mail | dark mode auto-invert |
| Thunderbird | CSS 限制 |

_（實測結果評估執行階段填入）_

#### §3.4.3 Visual Identity 評估

_（評估執行階段尚未填入）_

#### §3.4.4 Actionability Audit（命中 d3）

_（評估執行階段尚未填入）_

#### §3.4.5 痛點對應 finding

_（評估執行階段尚未填入）_

#### §3.4.6 推薦組合

| 候選 | 描述 | offline | touch | risk |
|---|---|---|---|---|
| 維持現狀 + 補強 | inline CSS + preheader + 文字版 fallback | ✅ | 小 | 低 |
| L3 模板系統化 | `templates/email/*.html.j2` + 共享 partials | ✅ | 中 | 中 |
| L4 MJML 預編譯 | MJML 寫 → cross-client safe HTML，產物進 vendor / 編譯產物 | ✅（編譯產物） | 中 | 中 |

_（評估執行階段填入推薦結果）_

---

## §4 Pain-point Cards（下半，16 張）

> Cards filled in Phase E（評估執行階段逐一填入）。
>
> 16 張卡：4.1 a1 / 4.2 a2 / 4.3 a6 / 4.4 a7 / 4.5 b1 / 4.6 b2 / 4.7 b3 / 4.8 b4 / 4.9 b5 / 4.10 b6 / 4.11 b7 / 4.12 b8 / 4.13 c1 / 4.14 c3 / 4.15 d2 / 4.16 d3

_（評估執行階段尚未填入）_

---

## §5 Cross-cutting Recommendations

### §5.1 共因識別（Mining）

| 共用重構 | 解的痛點 | Touch radius | Offline 友善 |
|---|---|---|---|
| Token 化 `app.css` + design system | a1 a2 c3 d2 + visual 一致性 | 中 | ✅ |
| 共享 CLI 輸出層 | b3 b4 b6 b7（+ b1 副作用） | 中 | ✅ |
| 統一 CLI 入口 | b1 b2 b5 b8 | 大 | ✅ |
| Email 模板系統化（MJML 預編譯） | d2 d3 | 中 | ✅ |
| 拆 `index.html` monolith | a1 a2（+ 開發體驗 spillover） | 大 | ✅ |
| Backend async + SSE（OQ-1 conditional） | a1 (loading via SSE)、c1 (long report progress) | 大 | ✅（FastAPI / Starlette） |
| Report exporter 整併（若 `html_exporter.py` 71 KB 是 legacy） | c1 c3 + 維護性 | 大 | ✅ |

_（評估執行階段依掃描結果驗證與更新）_

### §5.2 Bundled Refactor Tracks

_（評估執行階段尚未填入）_

### §5.3 推薦執行順序

_（評估執行階段尚未填入）_

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

#### Adopted Direction Spec Sheet

_（採用後評估執行階段填入）_

### §6.2 Report + Email direction

候選評估表（Typography 權重最高、Motion 權重最低）：

| 候選 | Typography | Color | Spatial | Backgrounds | Distinct | 適用 P5 |
|---|---|---|---|---|---|---|
| A. 維持現狀 | _TBD_ | | | | | |
| B. editorial-magazine | | | | | | |
| C. data-journalism | | | | | | |
| D. corporate-formal | | | | | | |

#### Adopted Direction Spec Sheet

_（採用後評估執行階段填入）_

### §6.3 跨兩套的共享 primitive（OQ-7 default）

_（評估執行階段尚未填入）_

---

## §7 Mockup Appendix

> Mockup 由 Visual Companion 產出 HTML 片段，評估執行階段填入 screenshot + 連結。

### M1 — GUI tab loading

| | Before | After |
|---|---|---|
| 描述 | 現況同步載入空白 + a6 破版（若可重現） | 套用 §6.1 後 skeleton + staggered reveal + token 配色 |
| 版本 | light + dark | light + dark |
| 觸及痛點 | a1 + a2（部分）+ a6 visualization | — |

_（評估執行階段尚未填入）_

### M4 — Report summary section

| | Before | After |
|---|---|---|
| 描述 | c1「太長 / 摘要不夠」段落 | 套用 §6.2 後 執行摘要區 + verdict 對照表 + chart 重畫 |
| 版本 | light only | light only |
| 觸及痛點 | c1 + c3 | — |

_（評估執行階段尚未填入）_

### M5 — Email HTML

| | Before | After |
|---|---|---|
| 描述 | mail_wrapper 直送的版型 | 套用 §6.2 子集 preheader + bulletproof CTA + dark-mode-safe |
| 版本 | light + dark | light + dark |
| 觸及痛點 | d2 + d3 | — |

_（評估執行階段尚未填入）_

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

_（評估執行階段逐一解決 Open 項目並更新狀態）_

---

## §9 Out-of-scope / Defer

### Reliability（不在 UX 評估範圍）

_（評估執行階段尚未填入）_

### i18n 資料補齊

_（評估執行階段尚未填入）_

### 進行中工作（本 spec 假設完成）

_（評估執行階段尚未填入）_

### 技術選型升級（值得獨立 spec）

_（評估執行階段尚未填入）_

### 效能 profiling（不在 UX 評估範圍）

_（評估執行階段尚未填入）_

---

## §10 Glossary

_（評估執行階段尚未填入）_

---

## §11 References

_（評估執行階段尚未填入）_

### 相關專案 spec / plan

_（評估執行階段尚未填入）_
