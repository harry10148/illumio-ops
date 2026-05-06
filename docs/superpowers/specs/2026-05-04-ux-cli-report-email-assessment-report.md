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

###### Vendor 化執行 plan（hand-off 給 implementation）

| URL（原） | License | Vendor 路徑 | 取得方式 | size |
|---|---|---|---|---|
| https://fonts.googleapis.com (preconnect) | n/a | （移除標籤） | 改成本地 link | 0 |
| https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap | OFL | vendor/fonts/Montserrat/{Regular,Medium,SemiBold,Bold}.woff2 + vendor/css/montserrat.css | npm `@fontsource/montserrat` 或 GitHub release `JulietaUla/Montserrat` | ~150 KB (4 woff2) + ~1 KB CSS |

實作步驟：
1. `npm download @fontsource/montserrat`（或從 GitHub release `JulietaUla/Montserrat` 下載 woff2）→ 4 個 .woff2 檔
2. 放入 `vendor/fonts/Montserrat/`（檔名：Montserrat-Regular.woff2、Montserrat-Medium.woff2、Montserrat-SemiBold.woff2、Montserrat-Bold.woff2）
3. 建 `vendor/css/montserrat.css` with @font-face declarations（4 個字重，各指向本地 woff2）
4. `src/templates/login.html` 移除第 7–8 行 Google Fonts CDN，改 `<link rel="stylesheet" href="{{ url_for('static', filename='vendor/css/montserrat.css') }}">`（或對應 vendor 靜態路由）
5. 確認 CSP `font-src` 包含 `'self'`（已是 — src/gui/__init__.py:251）→ 自動 unblock
6. 跑 offline bundle build 確認新增資源被打包

bundle 影響：
- vendor/ 增加 ~151 KB（fonts 150 + css 1）
- offline bundle (.tar.gz) 增量 ~50–100 KB（壓縮後）
- 解除 a6 + a7 雙痛點，無新依賴

聯合修復收益：
- 移除 CDN 依賴 → 滿足 C1 offline 硬約束
- 解除 CSP font-src 阻擋 → 修復 a6 layout 破版（B.1 根因：CSP `font-src 'self'` 阻擋 Google Fonts）
- 字型載入時間：CDN ~200–400 ms (cold) → local ~10 ms (always)

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

| 類別 | Score | Key Finding（≤2 行） | 觸及痛點 |
|---|---|---|---|
| §1 Accessibility (CRITICAL) | 2 | tablist/role=tab/aria-selected/aria-modal/aria-live(toast)/skip-link 完整；但 13 個 modal 缺 aria-labelledby，無 focus-trap，鍵盤使用者無法在 modal 內 Tab 循環。 | a1 |
| §2 Touch & Interaction | 1 | btn-pad-y 預設 8px → 按鈕高度約 32px < WCAG 44px；comfortable 模式僅升至 ~36px；無手勢支援（拖拉/swipe）。 | — |
| §3 Performance (CRITICAL) | 0 | 13 個 `<script>` 全部無 defer/async（其中 dashboard.js 81 KB、integrations.js 55 KB），0 個 preload；整包 JS 291 KB 阻塞首次渲染；integrations.js (line 989) 在 utils.js (line 1988) 之前載入（a3 時序缺陷）。 | a2 |
| §4 Style Selection | 2 | 47 個 CSS custom property（Illumio 品牌色彩 token：--accent #FF5500、dark/light 雙主題）；token 系統一致但無字體大小 token（硬編碼 px/rem 混用）。 | a2 |
| §5 Layout & Responsive | 2 | 5 個 @media 斷點（1080/960/780/640px + prefers-reduced-motion）；CSS Grid 用於 dashboard；但行動裝置（<640px）側邊欄摺疊行為未見完整設計。 | a6 |
| §6 Typography & Color | 2 | Montserrat 自託管 woff2（font-display: swap）；type scale 存在（2rem/1.6rem/.95rem/.86rem/.82rem）；dark/light 雙配色完整；但 --dim (#989A9B on #1A2C32) 對比率約 3.5:1，低於 WCAG AA 4.5:1。 | — |
| §7 Animation | 2 | 5 個 @keyframes（fadeIn/pulseDot/fadeInModal/loading/spin），30 處 transition；prefers-reduced-motion 正確覆寫所有 animation/transition；modal fadeInModal 有意義而非純裝飾。 | — |
| §8 Forms & Feedback (CRITICAL) | 1 | toast (role=status/aria-live=polite) 提供全域回饋；login.html 有 required/autocomplete；但主 app 162 個 input 無 aria-invalid/aria-describedby，無 inline 欄位級錯誤訊息，modal dialog 缺 aria-labelledby。 | a2 |
| §9 Navigation Patterns | 2 | role=tablist + role=tab + aria-selected 完整；skip-link 存在；Escape 鍵關閉 modal（rules.js:157）；但無 breadcrumb，深層頁面無回上層的 UI 語意。 | a1 |
| §10 Charts & Data | 1 | Plotly（server-render JSON + Plotly.react，responsive:true）；60 秒自動刷新；但 4 個 chart div 無 aria-label/role="img"，無文字替代內容，資料無障礙訪問完全缺失。 | — |

**總分：15/30（平均 1.5/3）**

GUI UX 體質總結：token 設計系統與 ARIA 語意結構顯示有基礎意識，但效能面完全未優化——0% defer/async 造成 291 KB JS 同步阻塞首次渲染，為最嚴重痛點。Accessibility 次佳（score 2）但存在系統性缺口：13 個 modal 無 aria-labelledby 且缺 focus-trap，鍵盤使用者無法安全操作；表單回饋依賴全域 toast 而非欄位級 aria-invalid，Forms 類得分僅 1。觸控裝置支援薄弱（按鈕高度 ~32px）。Plotly 圖表無任何 aria 替代，對 P1 使用螢幕閱讀器的邊緣場景完全不可用。

**自動拉 P1 痛點：**
- §3 Performance (score 0) → 觸及 **a2**（bundle 與載入時序問題）
- §8 Forms & Feedback (score 1 < threshold) → 觸及 **a2**（主 app 表單缺 aria-invalid inline 回饋）

#### §3.1.3 Visual Identity 現況評估

| 維度 | Score | Finding |
|---|---|---|
| Typography | 2 | Montserrat 自託管 woff2（`/static/fonts/`），`--header-font` / `--body-font` 均指向同一字族，無 heading/body 對比；`--mono-font` 有 Cascadia Code / Fira Code 明確 fallback chain；type scale 約 7 級（0.8rem–2rem）；無 tabular figures、無 CJK fallback、無 editorial 字重對比。 |
| Color | 3 | Illumio 品牌 palette 全部具名並以 CSS token 落地：System Cyan 背景層（`--bg/bg2/bg3`）、Illumio Orange（`--accent: #FF5500`）、Circuit Gold（`--accent2`）、Safeguard Green（`--success`）、Risk Red（`--danger`）；176 處均使用 `var()`，無散裸 hex；雙主題由 `[data-theme="light"]` 切換 + `color-scheme: dark light`；密度 token 另有 `[data-density="comfortable"]` 覆蓋層。調色板克制且語義明確。 |
| Motion | 2 | 5 個 `@keyframes`（fadeIn / fadeInModal / pulseDot / loading / spin）+ 11 條 transition；easing 以 ease/ease-out 為主，toast 用 `cubic-bezier(0.175,0.885,0.32,1.275)` 彈性進場；所有動畫均有功能語義（載入態、模態進入、狀態指示、微互動）；無頁面載入 orchestration 或 stagger 序列。 |
| Spatial Composition | 2 | 140 處 flex/grid/gap/padding/margin；spacing 以 7 個 token 層級覆蓋（header / panel / card / fieldset / row-cell / btn / tab），可由 density 模式整體切換；版面全為直角 grid/flex 結構，無 grid-breaking 或非對稱設計語言；密度控制良好但構圖語言傳統。 |
| Backgrounds & Details | 2 | backdrop-filter blur 三處（4px / 12px / 2px）；login 頁 radial-gradient 背景圓；brand 標題 linear-gradient text-clip；active tab 左邊框 `rgba(accent,0.08)` 漸層；`--shadow` token 一致；8px 圓角 + 999px pill 變體；無 mesh gradient、noise texture 或幾何圖樣。細節完整但無記憶點。 |
| **Distinctiveness** | **1** | Illumio 品牌 token 系統完整且紀律良好，但 Montserrat 兼任標題與正文導致無字體個性對比；深色主題的 cyan-teal 底色給予輕微辨識感，整體氣質仍屬「稱職的 ops admin dashboard」而非有明確視覺語言的工具；缺乏任何單一令人印象深刻的視覺元素。 |

**VI 總分：12 / 18**

**當前美學定位：** Illumio 品牌色 token（Illumio Orange + System Cyan 深色底）落地徹底、palette 紀律嚴整，但 Montserrat 單字族系統缺乏 heading/body 對比、構圖語言傳統直角 grid，整體定位為有品牌感的 generic security ops admin dashboard，視覺語言尚未形成可識別的工具個性。

與 §3.1.2 UX rubric 結果的相互印證：UX 維度中 Color 達到滿分、Space token 系統完整，與 VI 評估的 Color 3 分、Spatial 2 分一致；然而 Typography 在 UX 層面的字體可讀性尚可，在 VI 層面卻因 heading/body 同字族而失去editorial 對比感，直接壓低了 Distinctiveness。這個結構性落差呼應 §6.1 GUI 方向中 B（industrial-editorial）和 D（dark-ops）兩個選項的存在理由——兩者均以「字體對比系統 + 構圖突破」為核心差異化槓桿，而非改色。Track A Visual System 若僅做 token 整理而不引入字族對比，Distinctiveness 難以從 1 提升至目標 2。

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

##### ui-ux-pro-max 轉譯 7 類（CLI 適用子集）

評分基礎：§3.2.1 inventory（24 commands）+ §3.2.2 consistency matrix（6 類不一致）+ `src/cli/_render.py` 直接讀取。

| 類別 | Score | Finding（≤2 行） | 觸及痛點 |
|---|---|---|---|
| §1 Accessibility (CRITICAL) | 1 | `--help` 存在（Click 預設）但無使用範例、無 common pitfalls、無相關連結；`-h` 短旗標因 `context_settings` 限制僅部分命令支援；無 man page；無 screen reader 適配文件。 | b1 |
| §3 Performance | 1 | `Spinner`（rich.status）+ `progress_bar`（inline bar）存在但均無 ETA；backfill 長任務（可達數分鐘）無進度百分比估算；daemon loop 的 APScheduler 無任務剩餘時間提示。 | b4 |
| §5 Layout & Responsive | 2 | `get_terminal_width()` 存在；box-char fallback（Unicode → ASCII）在非 UTF-8 terminal 正確退化；`pad_string` 處理 CJK 全形寬度；rich Table 在窄 terminal 無強制折行保護。 | — |
| §7 Animation | 1 | `Spinner`（rich dots）有語義（表示等待）；`progress_bar` 有 `\r` 原地更新；但兩者均未檢查 `NO_COLOR`/`TERM=dumb` 是否應停用動畫；`prefers-reduced-motion` CLI 等效（`NO_COLOR`）完全未處理。 | b6 |
| §8 Forms & Feedback (CRITICAL) | 1 | `safe_input` 有型別驗證 + range check + 帶 help_text；錯誤僅顯示「Value out of range」，無 recovery path 建議（例如「有效值：1-30，請重新輸入」）；CLI 命令錯誤訊息一律 `[red]...[/red]`，無結構化 cause + fix。 | b2 |
| §9 Navigation Patterns | 2 | Click 命令樹（group → subgroup → command）結構清晰；`-h`/`--help` 雙入口於 root group；`0=back`/`-1=cancel` 互動選單導航一致；但 4 個純 menu 命令（edit-settings 等）在 CLI 樹中不可達，無 deprecation 路徑。 | b5 |
| §10 Charts & Data | 0 | 0/24 命令支援 `--json`；rich Table 在 pipe 模式（isatty=false）仍輸出 box characters + ANSI markup，完全無法被 `grep`/`jq`/`awk` 消費；無任何 machine-readable 輸出格式。 | b3 |

**UX 7 類總分：8/21（平均 1.1/3）**

---

##### CLI rubric 12 條（§2.5 TTY 規範）

| # | 規則 | Score | Finding（≤2 行） | 觸及痛點 |
|---|---|---|---|---|
| 1 | 命令文法一致性 | 1 | 6 類不一致（§3.2.2）：`--since`/`--start-date` 同義異名；`--source` 同名異義；`DESTINATION` positional vs `--dest` option；report 子命令以 noun 取代 verb；flag default 值不一致（`--limit` 50 vs 100）；0 global flag at root。 | b2 |
| 2★ | 能力偵測 | 1 | `_stdout_is_tty()` 存在（`_render.py:67`）且用於 Colors ANSI 停用；`safe_input` 的 questionary 路徑亦偵測 stdin+stdout isatty（`_render.py:237-240`）；但 **NO_COLOR=0**（整個 src/ 無任何讀取）、**TERM=0**、**COLORTERM=0**；rich Console 未透過 isatty 切換 box-char → plain 模式。 | b6 |
| 3★ | Composability | 0 | 0/24 `--json`；0/24 `--quiet`；rich Table/Console 輸出全走 stdout，錯誤訊息（`[red]...[/red]`）**同走 stdout 非 stderr**（`cache.py:55` console.print → stdout）；pipe 場景完全不可用（box characters + ANSI + 訊息混入 stdout）。**自動 P1。** | b3 |
| 4★ | Exit codes | 1 | 0（成功）/ 1（錯誤）有使用；但 **exit 2（用法錯誤）完全缺席**（無 `sys.exit(2)` 或 `UsageError`，日期格式錯誤也是 exit 1）；**exit 130（SIGINT）**：`_runtime.py` 捕捉 SIGINT 後 graceful shutdown 但回傳 0 而非 130；3 個 menu 入口（pce_cache_cli / rule_scheduler_cli / siem_cli）永遠 exit 0。 | b7 |
| 5 | Idempotency / dry-run | 1 | `cache retention --run`（flag 才執行，預設 dry）是良好模式；`rule edit --no-preview` 存在；但**無 `--dry-run` 通用旗標**，`cache backfill` 無冪等保護（重複執行會重複插入，靠應用層去重），`siem purge` 無 dry-run 預覽。 | — |
| 6 | 配置層級 | 1 | 配置層級：flag > config file > 預設（三層）；但 **env var 層完全缺席**：僅 1 個 `ILLUMIO_OPS_*` 變數存在（`ILLUMIO_OPS_I18N_STRICT`，隱藏開發旗標）；無 `ILLUMIO_OPS_CONFIG`、`ILLUMIO_OPS_LOG_LEVEL` 等操作旗標；Click 的 `auto_envvar_prefix` 未啟用。 | b8 |
| 7 | 互動 vs 非互動雙模 | 1 | `safe_input` 在非 TTY 正確 fallback 至 `input()`（`_render.py:237-240`）；但 rich Table 在 pipe 不降級（box char 直輸）；menu 入口無 `--non-interactive` / `--ci` flag；pipe 輸入無法驅動互動選單（無合理 fail-fast 或預設值自動選取）。 | b6 |
| 8 | 長任務 | 1 | `Spinner`（rich.status dots）+ `progress_bar`（inline `█░` bar）存在（`_render.py:475-527`）；workload list 使用 `rich.progress.Progress + SpinnerColumn`（`workload.py:36`）；但**無 ETA**；SIGINT 捕捉存在（`_runtime.py:29`）但 graceful shutdown 僅對 daemon，backfill 長任務中斷後無 resume 路徑、無 log 路徑提示。 | b4 |
| 9 | --help / man | 1 | Click 自動生成 `--help`（`-h`/`--help` 雙入口於 root）；各 group/command 有一行說明；但**無使用範例**（無 `Examples:` section）、無 common pitfalls、無相關連結；3 個 menu 入口（argparse path）的 `--help` 完全未整合至 root CLI 樹。 | b1 |
| 10 | Auto-completion | 2 | `scripts/illumio-ops-completion.bash` + `scripts/completions/illumio-ops.bash` 存在；使用 Click 的 `_ILLUMIO_OPS_COMPLETE=bash_source` 機制動態生成；但**僅 bash**，無 zsh / fish completion；無自動安裝機制（需手動 source）。 | — |
| 11 | 雙入口整合 | 1 | 14/24 命令（58%）同時存在於互動 menu 與 root CLI，但**實作完全分離**（menu 用 `print()`，CLI 用 rich）；3 個純 menu 命令在 CLI 不可達；無 deprecation 路徑；menu 選單無法透過 `illumio-ops` 根命令的子命令直接替代。 | b5 |
| 12 | Error actionability | 0 | **0** 處 `difflib`/`get_close_matches`/`did you mean`；錯誤訊息格式為 `[red]<exception message>[/red]`（直接暴露 Python exception 文字）；無 cause + recovery path 結構；錯誤走 stdout 非 stderr（rule 3 同源缺陷）；`siem test` 對不存在的 destination 僅回 "not found or disabled"，無可用名稱建議。**自動 P1。** | b2 |

**CLI 12 條總分：11/36（平均 0.9/3）**

---

**合計：UX 7 = 8/21，CLI 12 = 11/36；總計 19/57（33%）**

**CLI 整體 UX 體質總結：**

CLI 的核心體質問題集中於 composability 完全缺失——0/24 `--json`、錯誤訊息混入 stdout、rich markup 無 TTY-aware 降級，使整個工具在 pipe/script/CI 場景完全不可用。能力偵測（rule 2★）雖有 `isatty()` 基礎，但 `NO_COLOR`/`TERM` 未讀取，導致 daemon/service 模式下仍輸出 ANSI 序列。Exit code 語義（rule 4★）缺少 exit 2（用法錯誤）和 exit 130（SIGINT），且 menu 路徑永遠 exit 0，破壞 shell script 錯誤偵測。正向亮點：terminal width 自適應、box-char Unicode fallback、bash completion 腳本均已存在，顯示有 TTY 意識的工程基礎，但未延伸至 composability 層。

**自動 P1 痛點：**
- **rule 3★ Composability = 0** → **b3**（stdout/stderr 混用 + 無 --json）
- **rule 12 Error actionability = 0** → **b2**（無 cause+recovery，錯誤走 stdout）
- **§10 Charts & Data = 0**（CLI 側）→ 同 b3（machine-readable 輸出完全缺失）

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

> 注意：樣本 HTML 輸出不可用（Task A.6 已跳過實際產出量測）。以下審計基於原始碼閱讀，非執行期 render 輸出。

##### 各報告章節結構

| 報告 | 章節數 | 有執行摘要？ | 空資料處理 | 跨報告連結 |
|---|---|---|---|---|
| audit（`audit_html_exporter.py`） | 5（summary + health + users + policy + correlation） | 有（mod00 executive：attention items + 摘要 pills） | `rpt_no_data` key 統一顯示說明文字；policy / correlation 章節依 `visible_in()` 條件省略 | 無 |
| policy_usage（`policy_usage_html_exporter.py`） | 6（summary + overview + hit-rules + unused-rules + deny-rules + draft-pd） | 有（mod00 executive：execution stats + attention items） | `rpt_no_data` / `rpt_no_records` + `rpt_pu_draft_pd_empty` 個別覆蓋；unused / deny 章節依 profile 條件省略 | 無 |
| ven_status（`ven_html_exporter.py`） | 5（summary + online + offline + lost-today + lost-yest） | 有（summary section：KPI cards + summary pills） | `rpt_ven_no_data` 於 generator 層提前攔截；`rpt_no_records` 於 exporter 層填空表 | 無 |
| traffic（`html_exporter.py`，主力報告） | 16（overview / policy / uncovered / ransomware / unmanaged / distribution / allowed / bandwidth / readiness / infrastructure / lateral / ringfence / change_impact + matrix 等） | 有（mod12 executive summary：KPI、key findings、attack summary、maturity score） | `.empty` 檢查 + 條件 `visible_in()` + `rpt_no_data`；mod07 cross-label matrix 空資料提前 return | 無 |

**跨報告連結**：所有報告均無跨報告 `<a href>` 連結（確認：`grep -rn 'cross-report\|cross_report\|link_to' src/report/` 無結果）。此為 §3.3.6 推薦機會。

##### Jargon 分析

`src/i18n_zh_TW.json` 中 Illumio 術語命中數：**134 筆**（`boundary|ringfence|enforcement|Allowed|Blocked|Managed|Unmanaged|VEN|href` 合計）。

**留英**（近期 commit 455f5f0/25d0926/c349f37/c70ba52 確立的先例）：
- `Allowed`、`Blocked`、`Potentially Blocked`、`Potentially-Blocked`
- `Managed`、`Unmanaged`（nav / section title 保留英文；見 `rpt_tr_nav_unmanaged = "Unmanaged 主機"`）
- `VEN`、`boundary`、`ringfence`、`href`、`enforcement_mode`、`enforcement_boundary`
- `scope`、`label`（作為 Illumio 物件欄位）
- `Policy`（Illumio policy 引擎物件）

**已譯中**：
- Online → 在線（`rpt_pill_online`）、Offline → 離線（`rpt_pill_offline`）
- 狀態 pills 文字（在線 / 離線）、錯誤分類、告警動詞（離線 / 離線檢查）
- 系統訊息：`gui_status_online = "在線"`、`gui_status_offline = "離線"`

**待議邊界案例**：
- `rpt_chart_managed_vs_unmanaged` 的 zh_TW 譯為「受管 vs 未受管流量」— 圖表標題例外翻譯，與 nav / section 保留英文 Managed/Unmanaged 不一致（見下方 Verdict 一致性）
- `mod12_kpi_blocked_flows` zh_TW 為「Blocked 流量」（混合）vs `rpt_pill_offline` 為純中文「離線」— 相同語意結構（KPI 標籤）處理不統一

##### Verdict 一致性

| 場域 | 用詞 | zh_TW |
|---|---|---|
| 流量圖表圖例（`html_exporter.py` L773-775） | `ALLOWED` / `BLOCKED` / `POTENTIAL`（全大寫，hardcoded） | 英文（hardcoded，非 i18n） |
| 表格欄位 / 摘要列（`report_i18n.py` L906-908） | `Allowed` / `Blocked` / `Potentially Blocked`（title case） | 英文保留 |
| 章節標題（`rpt_tr_sec_allowed`） | Allowed Traffic | **已允許流量**（中文） |
| Nav 連結（`rpt_tr_nav_allowed`） | Allowed Traffic | **Allowed 流量**（混合） |
| 圖表標題（`rpt_chart_managed_vs_unmanaged`） | Managed vs Unmanaged Flows | **受管 vs 未受管流量**（中文） |
| Nav / 章節（`rpt_tr_nav_unmanaged` / `rpt_tr_sec_unmanaged`） | Unmanaged Hosts | **Unmanaged 主機**（混合） |
| VEN 餅圖標籤（`ven_html_exporter.py` L107） | `"Online"` / `"Offline"` / `"Lost <24h"`（hardcoded） | 英文（hardcoded，非 i18n） |
| VEN 摘要 pills（`report_i18n.py` L52-53） | Online / Offline | **在線 / 離線**（中文） |

**不一致清單（4 項）**：
1. **Same-section nav vs heading split**：`rpt_tr_nav_allowed` = "Allowed 流量" vs `rpt_tr_sec_allowed` = "已允許流量"——同一章節兩個進入點用語不同。
2. **Managed 圖表 vs nav/section**：`rpt_chart_managed_vs_unmanaged` 譯為「受管 vs 未受管」，但 nav / section 用 "Unmanaged 主機"——同術語在不同位置兩種處理。
3. **Verdict 大小寫**：圖表圖例用全大寫 `ALLOWED`/`BLOCKED`/`POTENTIAL`，其他位置用 title case——視覺層次可接受，但 i18n bypass 是潛在維護風險。
4. **VEN chart labels i18n bypass**：`ven_html_exporter.py` L107 hardcoded `["Online", "Offline", "Lost <24h", "Lost 24-48h"]`，無法跟隨 zh_TW 在線/離線翻譯。

##### 跨報告連結

**不存在**。所有報告為獨立 HTML 文件，報告之間無相互引用連結（audit / policy_usage / ven_status 均未引用彼此）。

機會：§3.3.6 可推薦在 audit summary 加入「→ 查看 Policy Usage 報告」、在 ven_status 加入「→ 查看 Audit 報告（VEN 相關事件）」等跨報告導覽連結。

##### 空資料 / 空章節處理

三份報告均有明確的空資料處理，模式一致：
- **Generator 層**：`df.empty` / `not data` 提前攔截，不傳給 exporter（`ven_status_generator.py` 有 `rpt_ven_no_data` 提前輸出）
- **Exporter 層**：`_df_to_html()` 統一支援 `no_data_key` 參數，預設 `rpt_no_data`（audit / policy_usage）或 `rpt_no_records`（ven_status）
- **章節省略**：`visible_in()` 條件控制章節是否渲染（非空白章節，而是直接省略）
- **個別空態訊息**：`rpt_pu_draft_pd_empty`（policy_usage draft-pd 章節獨立 key）

zh_TW 空態文字：`rpt_ven_no_data = "沒有 VEN 資料"` / `report_no_data = "這份報表沒有可用資料"`——措辭自然，無工程味。

##### i18n 一致性

- **鍵值數量**：`src/i18n_en.json` 與 `src/i18n_zh_TW.json` 均為 2,197 行——無遺漏 key（對稱）。
- **report_i18n.py**：獨立管理 440 個報告專用 i18n 條目（雙語 `_entry(en, zh_TW)` 格式），與主 i18n 分層管理。
- **已修先例**：Online/Offline → 在線/離線（commit 455f5f0/25d0926/c349f37/c70ba52）
- **待修候選**：
  - `rpt_tr_sec_allowed` vs `rpt_tr_nav_allowed` 統一（建議 nav 跟進改為「已允許流量」或兩者均用「Allowed 流量」）
  - `rpt_chart_managed_vs_unmanaged` 的 "受管 vs 未受管" 改回 "Managed vs Unmanaged"（或反向，統一 nav/section 也改中文）
  - `ven_html_exporter.py` L107 chart labels 改用 `_s("rpt_pill_online")` 等 i18n key
- **stale 翻譯**：無明確 stale key（en/zh_TW 行數一致，且近期 commit 持續維護）

##### Illumio 術語留英策略（OQ-10 default）

**留英**（Illumio 工程術語不譯，避免歧義）：`Allowed`、`Blocked`、`Potentially-Blocked`、`Managed`、`Unmanaged`、`boundary`、`ringfence`、`ven`、`href`、`enforcement_mode`、`scope`、`label`、`Policy`、`VEN`、`PCE`

**譯中**（UI 體驗一致）：動詞（新增 / 刪除 / 匯出 / 查看）、狀態 pill（Online → 在線，Offline → 離線）、操作按鈕、錯誤訊息分類、系統訊息、空態說明文字

**判定原則**：Illumio 物件 / verdict / API 欄位 → 留英；通用 UI 詞彙 → 譯中。邊界案例參考近期 commit 455f5f0 / 25d0926 / c349f37 / c70ba52。圖表標籤與 nav / section title 應保持一致（目前 Managed/Unmanaged 有分歧，為已知待修項）。

#### §3.3.3 Visual Identity 現況評估（document context）

**評分來源**：`src/report/exporters/report_css.py`、`src/report/exporters/pdf_exporter.py`、`src/report/exporters/chart_renderer.py`。HTML 滿分 18（6 維度 × 3），PDF 滿分 15（Motion = N/A，5 維度 × 3）。

| 維度 | HTML | PDF | 關鍵證據 |
|---|:---:|:---:|---|
| Typography | 2 | 2 | HTML：Montserrat 主字 + JetBrains Mono 等寬、h1–h4 四層層次、`font-variant-numeric: tabular-nums` 廣泛用於數值欄位；無 `@font-face` 本地嵌入（依 CDN）。PDF：MSung-Light CID 字體 fallback 已修（commit 4cca064）；`_make_cell_style` 依欄位數動態 8/7px；單一字體無字重差異。 |
| Color | 2 | 1 | HTML：完整 CSS token（`--cyan-120/110/100/90`、`--orange`、`--gold`、`--green`、`--red`、`--tan`）；CRITICAL/HIGH/MEDIUM/LOW badge 四色語意一致；`prefers-color-scheme: dark` 僅覆蓋 `.section-guidance`（局部）。PDF：表頭 `colors.white` 背景，無 verdict badge 色彩移植，資料列全灰白。 |
| Motion | 1 | N/A | HTML：table row hover `transition: background .12s`、sort indicator `transition: opacity .12s`；無 expand/collapse `@keyframes`，互動微弱。PDF：靜態輸出，不適用。 |
| Spatial | 3 | 2 | HTML：固定 210px 側欄 + `main` content area；`dual-grid`（2 × 1fr）、`tri-grid`（2fr+1fr+1fr）響應式 grid；`@media` + CSS Container Query 雙層斷點；`chart-container` max-width 860px 控幅；card `margin-bottom: 24px` 節奏一致。PDF：Landscape A4、12mm 四邊 margin；`KeepTogether` 防孤兒標題；8mm Spacer 章節間距；表格等寬欄、圖表 160×90mm；無 page-break-before 章節控制。 |
| Backgrounds & Details | 2 | 0 | HTML：`.report-hero` 雙層漸層 cover card（radial + linear）；table panel `linear-gradient`；shadow token 三層（card/panel/panel-strong）；`footer` 極簡存在。PDF：無 cover page、無 header/footer、無頁碼、無章節分隔線；`SimpleDocTemplate` 純白預設，無任何品牌背景處理。 |
| Distinctiveness | 2 | 1 | HTML：深青（`#1A2C32`）+ 橙（`#FF5500`）品牌色一致貫穿；chart `_PALETTE` 首色 `#FF5500/#FFA22F` 沿用；整體偏「整潔儀表板」而非 editorial 個性。PDF：ReportLab 預設外觀，無 Illumio 品牌色應用，無視覺差異化。 |
| **合計** | **12/18** | **6/15** | |

**主要 gap**：

- **PDF Backgrounds（0/3）**：缺 cover page、頁眉/頁腳、頁碼是最大單點缺口；`SimpleDocTemplate` 需加 `onFirstPage`/`onLaterPages` callback 才能植入品牌頁首。
- **PDF Color（1/3）**：HTML 的四色 severity badge 語意未移植到 PDF；`_dataframe_to_table` 的 `TableStyle` 無條件著色邏輯。
- **HTML Motion（1/3）**：缺少 expand/collapse 動畫（findings card 可摺疊）與 section fade-in；目前僅有 hover/sort transition。
- **HTML Color dark mode（局部）**：`prefers-color-scheme: dark` 僅覆蓋 `.section-guidance`，其餘元素（nav、card、badge）在深色系統下對比度未驗證。

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

##### Known-issue checklist（mail_wrapper.html.tmpl 靜態審查）

| 檢查項 | 通過? | 說明 |
|---|---|---|
| Table-based layout（vs div） | ✗ | 整個骨架全為 `<div>` 巢狀；line 3–37 無 `<table>` 存在。Outlook 不支援 div-based 佈局，欄寬將跑版。 |
| Inline CSS（vs `<style>` block） | ✓ | 無 `<style>` block；所有樣式均以 `style="..."` 行內撰寫（plugins.py:32 只注入 HTML body）。Gmail / Outlook 的 `<style>` strip 問題在此不適用。 |
| Img alt + width/height | ✓ | 模板中無 `<img>` 標籤，無圖片引用，此項風險不存在。 |
| Webfont 不引用 | ✗ | line 2：`font-family:'Montserrat',Arial,sans-serif`。未引用 @font-face / googleapis（無外部請求），但 Montserrat 在多數 email client 中不可用；Arial fallback 可接受，但 font-stack 宣告仍構成視覺落差。 |
| Position / flex / grid 不使用 | ✗ | line 6：`display:flex; align-items:center; gap:14px`；line 13：`display:flex; flex-wrap:wrap; gap:18px`。Outlook 2007–2019 完全不支援 flexbox，header 與 meta 欄位將塌陷成垂直堆疊。 |
| Bulletproof CTA（VML） | ✗ | 無 `<v:roundrect>` 或任何 `<!--[if mso]>` 條件注釋。若未來加入按鈕，Outlook 將顯示純文字連結而非樣式化按鈕。 |
| Dark mode 反轉處理 | ✗ | 無 `<meta name="color-scheme">` 及 `prefers-color-scheme` media query。Apple Mail / Outlook iOS 在 dark mode 會自動反轉背景（`#F3F0E9` → 深色），橘色 logo badge（`#FF5500`）與文字對比可能失效。 |
| 文字版 fallback | ✗ | `plugins.py:28`：`MIMEMultipart()` 預設為 `mixed`，非 `alternative`；`plugins.py:32` 只 attach `MIMEText(body, "html")`，無 `text/plain` part。`reporter.py:1373–1377` 同樣問題。`line_digest.txt.tmpl` 雖存在但從未被 attach 至 email。 |

**審查結果：2 / 8 通過（inline CSS ✓、無圖片 ✓）；6 項不通過。**

##### Client 風險矩陣

| Client | 已知雷區 | 對 mail_wrapper 影響 |
|---|---|---|
| Outlook（Win / Mac / 365） | 不支援 flexbox/grid、VML for buttons、`<style>` quirks | **高風險**：header（line 6）與 meta 欄（line 13）的 flex 佈局塌陷；無 VML CTA；整體 layout 以 div 為根，Outlook 可能完全錯位 |
| Gmail（web / iOS / Android） | `<style>` 部分支援、可能移除 class、image proxy | **中風險**：inline CSS 可躲過 `<style>` strip；無外部圖片（image proxy 不觸發）；但 flex gap 在舊版 Gmail App 不支援 |
| Apple Mail | dark mode 自動反轉 | **中風險**：無 color-scheme meta，dark mode 下橘色 badge 與淺色背景可能遭反轉，品牌識別受損 |
| Thunderbird | CSS 限制、flex 支援不穩 | **低-中風險**：inline CSS 通過；flex 視版本而定；整體比 Outlook 容忍度高 |

##### 總結

2 / 8 通過，**3 個高風險或中風險 client**（Outlook 高風險、Gmail 中風險、Apple Mail 中風險）。

主要建議（優先序）：
1. **換用 table-based layout**（最高優先）— 解決 Outlook / 舊版 email client 根本不相容問題
2. **加入 `text/plain` MIME part**（plugins.py + reporter.py）— `MIMEMultipart('alternative')` + attach text 版本；`line_digest.txt.tmpl` 已備妥，只缺 attach 邏輯
3. **加入 `<meta name="color-scheme" content="light">` + forced-light CSS**（Apple Mail dark mode）
4. **移除 Montserrat 從 font-stack 或改用系統字型**（視覺落差低優先）

#### §3.4.3 Visual Identity 評估

_（評估執行階段尚未填入）_

#### §3.4.4 Actionability Audit（命中 d3）

##### Subject line audit

| Pattern | 通過? | 證據 |
|---|---|---|
| 含關鍵資訊（severity / source / object） | ✗ | `i18n_en.json:1300` `"Illumio PCE Ops Alert ({count} issue(s))"` — 只有 count，無 severity / 受影響物件 |
| 長度合理（50–78 chars） | ✗ | 最長 35 chars（`count=99`）；未充分利用 subject 空間傳遞資訊 |
| 避免模糊詞（Alert / Notification 開頭） | ✗ | 模板以 `Alert` 結尾且無具體脈絡；`mail_subject_test` 為 `"… Alert — Test"`，同樣模糊 |

> **實際值**（`src/reporter.py:542` → `src/i18n_en.json:1300`）：  
> `"Illumio PCE Ops Alert ({count} issue(s))"` → 範例：`Illumio PCE Ops Alert (3 issue(s))`

##### Preheader audit

| 項目 | 結果 | 說明 |
|---|---|---|
| Hidden preheader 存在 | ✗ | `mail_wrapper.html.tmpl` 全文無 `display:none` / `preheader` / `preview` — grep exit 1，表示完全缺席 |
| 長度 30–90 chars | ✗ | 無 preheader，無從評估；email 預覽列將直接抓到 `<body>` 第一段文字（「Official Alert Notification」） |
| Standalone summary（離開 subject 可讀） | ✗ | 無法判斷，因不存在 |

##### CTA + deep link

| 項目 | 結果 | 說明 |
|---|---|---|
| Button styled CTA | △ 條件性 | `reporter.py:806-807`：event 區段若 `pce_link` 存在則渲染 `"View on PCE"` 深色按鈕；wrapper footer、health / traffic / metric 區段均無 CTA |
| Deep link to GUI page | △ 條件性 | `reporter.py:148-161` `_event_console_link()` 根據 event `href` 欄位拼出 `{base}/#/{path}`；但此 link 僅在 event 資料有 `href` 時才呈現 |
| Deep link 正確帶參數 | △ 部分 | 連結格式 `{pce_base}/#/{org_path}` 可讓瀏覽器跳至 PCE console，但無 UTM / 查詢篩選參數；health / traffic / metric 告警完全無對應 deep link |

##### Hierarchy（5 秒 What-Why-Action）

- **What（發生什麼）**：✓ — header 有 `{count} issue(s)` 計數 + 四區段 summary 卡片（health / event / traffic / metric 各別數字）
- **Why（為何觸發）**：✗ — 無 severity 等級、無觸發閾值說明；`alert_tpl_aggregated_blurb` 僅為通用說明文字，非當次告警原因
- **Action（應採取什麼行動）**：✗ — footer 僅有 `"Confirm and act per your alert runbook."` 靜態文字，無具體操作連結、無 runbook URL、無 escalation 路徑

##### 痛點 d3 命中總結

1. **Subject 無差異化**：固定格式 `"Alert (N issue(s))"` 讓所有告警 subject 幾乎相同；無 severity 前綴（如 `[CRIT]`）導致 inbox 無法排序優先級。
2. **Preheader 完全缺席**：主流 email client（Gmail / Outlook / Apple Mail）會擷取 body 首段文字作為 preview — 目前顯示 `"Official Alert Notification"`，毫無資訊價值。
3. **CTA 覆蓋率低**：僅 event 類別有條件性 "View on PCE" 按鈕；health / traffic / metric 告警收件者讀完後無任何可點行動。
4. **Why 層完全缺失**：收件者無法從 email 本身判斷告警嚴重程度或觸發原因，必須另行登入 PCE 才能確認，增加 MTTR。
5. **Action 層為靜態佔位**：`"Confirm and act per your alert runbook."` 無 runbook 連結，實際上無法驅動操作；manager persona（P5）閱讀後無任何可執行下一步。

**改善建議**：① Subject 加 `[CRIT/WARN/INFO]` 前綴 + 最高嚴重性告警名稱（50–70 chars）；② 加入 30–90 chars hidden preheader div（`display:none;max-height:0`）；③ wrapper footer 加統一 "Open PCE Dashboard" CTA 按鈕（帶 `{pce_base}/` deep link）；④ 每個告警區段標示觸發閾值（Why）。

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

GUI 四張卡（4.1–4.4）已填入（Task E.1，2026-05-06）。CLI / Report / Email 卡（4.5–4.16）待後續 Task 填入。

---

### 4.1 — a1 GUI tab 載入體驗

| | |
|---|---|
| Subsystem | GUI |
| 觸及 persona | P1 P2 |
| Pre-condition | 無獨立 pre-condition；與 a6/a7 同源但可獨立優化 |
| Score | Impact 3 × PersonaWeight 3 (P1+P2) × Frequency 3 (每次開啟 GUI) = **27** |
| 優先級 | **P1** |

**現況片段** — `src/templates/index.html`：13 個 `<script>` 標籤全部無 `defer`/`async`（`§3.1.1 A.2`）；總 JS 285 KB 阻塞首次渲染。`integrations.js`（line 989）在 `utils.js`（line 1988）之前載入，存在符號未定義競態視窗（`§3.1.1` 關鍵觀察）。`dashboard_v2.js` 未被任何 template 引用（孤兒檔）。0 個 `<link rel="preload">`，0 個 skeleton placeholder。

**影響** — P1 每次登入後 cold-load 時整頁白屏至 JS 全部解析完畢；SOC P2 在告警高峰期（高壓場景）尤其敏感於「進去就白屏」的感知延遲。`integrations.js` 競態若頂層有立即呼叫，會在特定瀏覽器 / 快取狀態下靜默失敗，頻率難預測。

**UX rubric 觸及項** — §3 Performance = 0（CRITICAL）：0% defer/async，阻塞渲染；§9 Navigation = 2（state preservation 中等，無 skeleton）。

**Visual rubric 觸及項** — Motion = 2：無頁面載入 orchestration 或 stagger 序列，tab 切換無過渡暗示載入狀態。

**優化路線（小改）**
1. 所有 `<script src="…">` 加 `defer`（30 min）→ 首次渲染非阻塞
2. 在 `</head>` 前加 `<link rel="preload" as="script">` 給 dashboard.js + utils.js（15 min）
3. 以 CSS skeleton（灰色閃爍條）作為 tab content 初始 placeholder（1 day）
4. 移除或標記 `dashboard_v2.js` 孤兒（30 min）
- Touch radius：小（index.html template + 4 script 標籤）
- 與 §5 cross-cutting 衝突？無衝突，為 §5.1「拆 `index.html` monolith」重構的前置安全網

**重構路線（大改）**
1. Track A：設計 token 系統 + `index.html` monolith 拆分（component-per-tab）
2. Track E（OQ-1 conditional）：長時操作改 SSE 串流，tab 切換後台非同步
3. 引入 ES modules（`type="module"`），解決 integrations.js 載入次序問題
- Touch radius：大（templates + static/js 全部 + 後端路由）
- 與 §5 cross-cutting 同源：§5.2 Track A + Track E

**§2.6 五 Gate 評估**
- Gate 1 Offline       : ✓（defer/skeleton 完全不依賴外部服務）
- Gate 2 多痛點共因    : 共因 3 個（a1 bundle 阻塞 / a2 filter 等待 / a6 CSP layout） → 重構分 +1
- Gate 3 Touch radius  : 優化小；重構大
- Gate 4 Persona 衝擊  : P1 每次使用必觸；P2 高壓告警場景敏感度高 → 高衝擊
- Gate 5 Reversibility : ✓（defer 可 1 行回退；skeleton 獨立 CSS class）

**推薦** — 優化先行（2 day）+ 重構排隊 Track A；優化路線即可將 §3 Performance 從 0 → 2，不需等重構。

**驗收標準** — 採用優化路線後重跑 §2.3 rubric：
- §3 Performance: 0 → 2（defer 覆蓋率 100%，存在 preload）
- Cold-load（DevTools Throttle: Fast 3G）主要內容可見時間 < 2 s
- integrations.js 競態視窗消除（defer 保證執行次序）
- `dashboard_v2.js` 孤兒狀態解除

---

### 4.2 — a2 表格篩選 / 搜尋體驗

| | |
|---|---|
| Subsystem | GUI |
| 觸及 persona | P1 P2 |
| Pre-condition | 無獨立 pre-condition |
| Score | Impact 3 × PersonaWeight 3 (P1+P2) × Frequency 3 (P1 高密度表單操作為核心工作流) = **27** |
| 優先級 | **P1** |

**現況片段** — `§3.1.2 UX rubric §8 Forms & Feedback = 1`：主 app 162 個 `<input>` 無 `aria-invalid` / `aria-describedby`；無 inline 欄位級錯誤訊息（僅全域 toast）。Filter / search 輸入框未見 `debounce`（待動態確認，靜態掃描未發現 setTimeout/debounce wrapper）。`§3.1.2 §4 Style = 2`：token 系統存在但無字體大小 token（px/rem 混用）。`§3.1.3 Spatial Composition = 2`：spacing token 完整，但無 loading overlay。

**影響** — P1 網管的核心工作流為高密度表單與規則列表操作；每次篩選若無 debounce，打字後即觸發請求，體感「打字→等待→跳動」循環，在 rules / integrations 大資料集尤為明顯。無 inline 錯誤訊息導致 P1 填錯表單後只能依賴 toast，需視線移動至畫面角落辨認錯誤，提高認知負擔。P2 在批次告警處理中使用篩選快速定位，延遲直接影響響應時間。

**UX rubric 觸及項** — §8 Forms & Feedback = 1（CRITICAL）：inline validation 缺失；§4 Style = 2：token 系統存在但不完整；§10 Charts & Data = 1：與資料表格體驗連動（aria 缺失）。

**Visual rubric 觸及項** — Spatial Composition = 2：filter 輸入框無 loading overlay / spinner 視覺狀態，使用者無回饋感。

**優化路線（小改）**
1. 所有 filter/search input 加 debounce wrapper（300ms）（1 day）
2. 搜尋進行中加 spinner overlay 或 input disabled + 游標變更（半天）
3. 162 個 input 加 `aria-invalid="false"` 初始值，驗證失敗時切換為 `"true"` 並加 `aria-describedby` 指向 inline error element（3 day）
4. 新增 inline error `<span>` template（1 day）
- Touch radius：小（static/js 篩選邏輯 + template input 標籤）
- 與 §5 cross-cutting 衝突？無衝突；可為 Track A 共用 filter-component 鋪路

**重構路線（大改）**
1. Track A：抽取共用 `filter-component` primitive，內建 debounce + aria-invalid 生命週期
2. 加 `aria-live` region 報告搜尋結果筆數（「找到 N 筆規則」）
3. 字體大小改用 design token（消除 px/rem 混用）
- Touch radius：中（共用 component 影響所有含 filter 的 tab）
- 與 §5 cross-cutting 同源：§5.1「Token 化 `app.css`」+ §5.2 Track A

**§2.6 五 Gate 評估**
- Gate 1 Offline       : ✓（debounce / aria-invalid 純前端，無網路依賴）
- Gate 2 多痛點共因    : 共因 2 個（a1 bundle 阻塞共用 index.html / a6 layout 破版 CSS token 同源） → 重構分 +1
- Gate 3 Touch radius  : 優化小；重構中
- Gate 4 Persona 衝擊  : P1 核心工作流高頻觸及；P2 告警響應路徑觸及 → 高衝擊
- Gate 5 Reversibility : ✓（debounce 可 flag 回退；aria 屬性純增量，無破壞性）

**推薦** — 優化路線足夠解決核心體感問題；重構放回 Track A 排程，與 filter-component primitive 統一設計。

**驗收標準** — 採用優化路線後重跑 §2.3 rubric：
- §8 Forms & Feedback: 1 → 2（aria-invalid 覆蓋率 > 80%，inline error 存在）
- Filter debounce 300ms 生效（DevTools Network 確認：打字停頓 < 300ms 不觸發請求）
- Spinner overlay 出現於搜尋進行中
- （選項）`aria-live` region 報告結果筆數

---

### 4.3 — a6 HTTPS 啟用後 layout 破版

| | |
|---|---|
| Subsystem | GUI |
| 觸及 persona | P1 P2 |
| Pre-condition | **是 → 詳情見 §3.1.0 a6** |
| Score | （不算 score，直接 P0） |
| 優先級 | **P0** |

本卡為 §3.1.0 a6 的 cross-reference shorthand。完整成因清單、驗證步驟、hand-off owner、CSP 確認（B.1）在 §3.1.0 a6。

根本原因已確認：`src/gui/__init__.py:251` CSP `font-src 'self'` 過嚴，阻擋 `src/templates/login.html:7-8` 載入的 Google Fonts CDN（fonts.googleapis.com / fonts.gstatic.com）；啟用 HTTPS 後 Talisman 套用 CSP，字型被阻擋，造成 layout 破版。

聯合修復路徑：與 a7 vendor 化（4.4）一石二鳥——將 Google Fonts 本地化後，CSP `font-src 'self'` 自動合法，不需放寬 CSP 規則。

Hand-off：可靠性 sprint（詳見 §3.1.0 a6）。

---

### 4.4 — a7 UI 依賴 external resources（違反 C1）

| | |
|---|---|
| Subsystem | GUI |
| 觸及 persona | P1 P2 |
| Pre-condition | **是 → 詳情見 §3.1.0 a7** |
| Score | （不算 score，直接 P0 BLOCKED） |
| 優先級 | **P0 BLOCKED** |

本卡為 §3.1.0 a7 的 cross-reference shorthand。完整掃描表（7 hits，2 真正違反）、vendor 計畫、hand-off owner 在 §3.1.0 a7。

2 真正違反（均為 Google Fonts，`login.html:7-8`）在離線環境（C1 constraint）下會阻斷字型載入，疊加 a6 CSP 問題造成 layout 完全破版。

Vendor 計畫：Montserrat woff2 subset 下載至 `vendor/fonts/`，`@font-face` 自建於 `vendor/css/`，login.html 改用本地路徑。執行後 a6 CSP `font-src 'self'` 自動合法，不需修改 CSP 規則（Task B.2）。

Hand-off：可靠性 sprint（詳見 §3.1.0 a7）。

---

### 4.5 — b1 CLI 互動 menu 層級

| | |
|---|---|
| Subsystem | CLI |
| 觸及 persona | P1 |
| Pre-condition | 無獨立 pre-condition；menu 重複問題可獨立修復 |
| Score | Impact 2 × PersonaWeight 3 (P1) × Frequency 3 (每次 CLI 互動) = **18** |
| 優先級 | **P2** |

**現況片段** — `§3.2.3 interaction model audit`：24 個 commands 中 14 個（58%）在互動式 menu 與直接子命令兩處皆出現，形成入口重複。menu 選單無 breadcrumb 顯示當前層級，無 `back` / ESC 提示。按 Ctrl-C 離開 submenu 後整個 CLI 程序終止，不回父 menu。無任何 state preservation 機制（進入 submenu 前的選擇不保留）。

**影響** — P1 網管進入巢狀 menu 後路徑不明，`back` 行為不一致，誤按 Ctrl-C 中斷整個工作流。14/24 重複入口造成認知混亂：不確定該走 menu 路徑還是直接子命令路徑，help-grep cycle 增加。

**UX rubric 觸及項** — §9 Navigation = 2（中等）：有 menu 層級但無 breadcrumb / back hint；§1 Accessibility = 1：鍵盤逃脫路徑不明。

**優化路線（小改）**
1. 統一在每個 submenu 頂部印出 `[parent > current]` breadcrumb（1 day）
2. 所有 menu prompt 底部加 `[b]ack / Ctrl-C exits` 提示行（半天）
3. 以 `questionary` / `InquirerPy` 替換裸 `input()` call，統一 ESC = back 行為（2 day）
- Touch radius：小（CLI menu 顯示邏輯，不觸及業務邏輯）
- 與 §5 cross-cutting 衝突？優化可獨立執行；Track C 統一入口重構後本卡自動合併解決

**重構路線（大改）**
1. Track C：統一 CLI 入口設計——消除 menu / 子命令重複，單一命令樹
2. 引入 `typer` 或 `click` group hierarchy，breadcrumb 由框架自動生成
3. 實作 state preservation（session-level context dict 傳遞）
- Touch radius：大（影響全部 24 個 commands 的入口定義）
- 與 §5 cross-cutting 同源：§5.2 Track C

**§2.6 五 Gate 評估**
- Gate 1 Offline       : ✓（breadcrumb / back hint 純 terminal 輸出，無網路依賴）
- Gate 2 多痛點共因    : 共因 3 個（b1 menu / b2 命名 / b5 entry duplication）→ 重構分 +1
- Gate 3 Touch radius  : 優化小；重構大
- Gate 4 Persona 衝擊  : P1 每次 CLI 操作必觸；頻率 3 → 衝擊實際高於 score 呈現
- Gate 5 Reversibility : ✓（breadcrumb 純增量 print；questionary 替換可 flag 回退）

**推薦** — Track C 已涵蓋此問題；在 Track C 排程前，優化路線（breadcrumb + back hint）可即時降低 P1 迷路頻率，1 sprint 內可完成。

**驗收標準** — 採用優化路線後：
- 所有 submenu 頂部出現 `[parent > child]` breadcrumb
- menu prompt 底部顯示 `[b]ack / Ctrl-C exits` 提示
- ESC / b 鍵回父 menu（不終止程序）
- §9 Navigation: 2 → 3

---

### 4.6 — b2 CLI 命名 / 參數一致性

| | |
|---|---|
| Subsystem | CLI |
| 觸及 persona | P1 |
| Pre-condition | 無獨立 pre-condition |
| Score | Impact 3 × PersonaWeight 3 (P1) × Frequency 2 (命名問題在新功能 / 新用戶首遇) = **18** |
| 優先級 | **P2** |

**現況片段** — `§3.2.4 A.5 六類不一致`：
1. `--source` 同名異義：在 `cache` 系列命令中指「快取來源路徑」，在 `report` 系列命令中指「資料來源類型」，語義完全不同但 option 名稱相同。
2. verb-noun 衝突：5 處命令使用名詞優先（`siem-test`）而其他命令使用動詞優先（`run-report`、`send-email`），風格不一致。
3. positional vs. `--dest` 混用：`siem test` 接受 positional argument，而 `siem replay` / `dlq purge` 使用 `--dest`，同族命令參數風格分裂。
4. 無 `did-you-mean` 機制：輸入錯誤命令名稱直接噴 `No such command`，無相近命令建議。

**影響** — P1 網管誤用 `--source` 傳入錯誤語義值，導致靜默錯誤或 unexpected behavior。verb-noun 不一致增加 help-grep cycle（必須記憶每個命令的命名風格）。`did-you-mean` 缺失造成 typo 後需重翻 help，P1 自助修復路徑延長。

**UX rubric 觸及項** — §1 Accuracy & Alignment = 1：命令語義與名稱不對齊；CLI 命名一致性規則 = 0（未達任何統一風格）。

**優化路線（小改）**
1. 建立命名一致性表（verb-noun 正規化清單），為 `--source` 語義衝突引入 alias（`--cache-source` / `--report-source`），保留 `--source` 作 deprecation alias 並在 help 顯示 `[deprecated, use --cache-source]`（2 day）
2. 引入 `difflib.get_close_matches` 於頂層 command dispatcher，輸入錯誤命令時顯示 `Did you mean: siem-test?`（1 day）
3. alias 保留 4 個版本 compat 週期，不立即 breaking（0 extra cost）
- Touch radius：小（CLI option 定義層 + dispatcher，不觸及業務邏輯）
- 與 §5 cross-cutting 衝突？優化可獨立執行；Track C 重新設計命令樹時正式廢除 deprecated alias

**重構路線（大改）**
1. Track C：重新設計統一命令樹，強制 verb-noun 規範（`<verb>-<noun>` 或 `<noun> <verb>`，選一）
2. 全面稽核 positional / named option 使用規則，以 ADR 記錄
3. 產出 CLI naming guide，作為 lint rule 的 spec 基礎
- Touch radius：大（全部 24 commands option 定義重命名）
- 與 §5 cross-cutting 同源：§5.2 Track C

**§2.6 五 Gate 評估**
- Gate 1 Offline       : ✓（命名 / alias / difflib 純 CLI 邏輯，無網路依賴）
- Gate 2 多痛點共因    : 共因 3 個（b1 menu / b2 命名 / b5 entry 共用同一 Track C）→ 重構分 +1
- Gate 3 Touch radius  : 優化小；重構大
- Gate 4 Persona 衝擊  : P1 新功能 / 首次使用時高頻觸及；誤用後靜默失敗影響嚴重性高
- Gate 5 Reversibility : ✓（alias 保留 compat 4 版本；did-you-mean 純增量）

**推薦** — 優化路線先行（3 day）補 `did-you-mean` + deprecation alias，Track C 排入重構排程正式統一命名規範。

**驗收標準** — 採用優化路線後：
- `--source` 語義歧義解除（alias 覆蓋原有用法，help 顯示 deprecated 提示）
- 輸入錯誤命令名稱顯示 `Did you mean: <closest-match>?`
- verb-noun 正規化清單寫入 `docs/cli-naming-guide.md`
- §1 Accuracy: 1 → 2

---

### 4.7 — b3 CLI 輸出格式

| | |
|---|---|
| Subsystem | CLI |
| 觸及 persona | P1 P3 |
| Pre-condition | 無獨立 pre-condition |
| Score | Impact 3 × PersonaWeight 3 (P1+P3) × Frequency 3 (每次 CLI 執行) = **27** |
| 優先級 | **P1** |

**現況片段** — `§3.2.2 A.4 / A.5`：輸出層分裂為三條路徑——`rich.console` 13 個命令（62%）、`click.echo` 5 個（24%）、裸 `print()` 3 個（14%）。0/24 命令支援 `--json` flag，0/24 命令使用 `sys.stdout.isatty()` 條件渲染，導致 pipe 下直接輸出 ANSI escape codes（`\x1b[32m` 等），污染下游 `jq` / `grep` pipeline。無 `--quiet` 壓制非必要輸出，無 `--verbose` 展開 debug 資訊。`NO_COLOR` env var 未被偵測。

**影響** — CI/CD pipeline 中 CLI 輸出含 ANSI 導致 log aggregator（如 Elastic/Splunk）解析失敗；`jq` pipeline 完全不可能（無 `--json` 模式）；自動化腳本必須用 `sed` 剝除 ANSI 作 workaround，增加維護負擔。P3 自動化腳本作者（運維自動化場景）完全無法將 CLI 納入 composable pipeline。

**UX rubric 觸及項** — §3 Performance = 1（ANSI 輸出拖慢 log 處理）；§10 Charts & Data = 0（CRITICAL）：structured output 完全缺失；CLI composability 規則 3★ = 0（`--json` / `isatty` / `NO_COLOR` 三項全缺）。P1 escalation：Composability = 0 觸發 CRITICAL。

**優化路線（小改，並行 Track B 前置）**
1. 在所有 `print()` call 點加 `isatty()` guard（TTY → 保留 ANSI；非 TTY → 剝除 ANSI）（1 day）
2. 偵測 `NO_COLOR` env var，存在時強制無色輸出（半天）
3. 為最高頻使用的 5 個命令增加 `--json` flag，輸出標準 JSON 結構（2 day）
- Touch radius：小（各命令輸出點，不觸及業務邏輯）
- 與 §5 cross-cutting 衝突？為 Track B 共用輸出層的安全前置，不衝突

**重構路線（Track B 共用輸出層）**
1. Track B：設計共享 `OutputManager` 類別（Console + isatty 條件 + `--json` / `--quiet` / `--verbose` 統一旗標）
2. 所有 24 個命令改用 `OutputManager.print()` 替換現有三條輸出路徑
3. `--json` flag 注入 Click group，所有子命令自動繼承
4. 整合 `rich.Console(no_color=True)` 作為非 TTY fallback
- Touch radius：中（輸出層統一，業務邏輯不動）
- 與 §5 cross-cutting 同源：§5.1「共享 CLI 輸出層」

**§2.6 五 Gate 評估**
- Gate 1 Offline       : ✓（isatty / NO_COLOR / --json 純 CLI 邏輯，無網路依賴）
- Gate 2 多痛點共因    : 共因 4 個（b3 輸出 / b4 錯誤訊息 / b6 log 污染 / b7 CI pipe 失敗）→ 重構分 +2
- Gate 3 Touch radius  : 優化小；重構中
- Gate 4 Persona 衝擊  : P1 每次 CLI 執行必觸；P3 自動化場景完全 blocked → 衝擊最高
- Gate 5 Reversibility : ✓（isatty guard 可 flag 回退；OutputManager 採漸進式替換）

**推薦** — 並行策略：優化先補 isatty / NO_COLOR（1 day），同步啟動 Track B 共用輸出層開發（1 week）。Track B 完成後優化路線的臨時 patch 自動被取代。

**驗收標準** — Track B 完成後：
- `--json` 覆蓋率 24/24 命令
- isatty 條件渲染覆蓋率 24/24 命令
- `NO_COLOR` env var 偵測覆蓋率 24/24 命令
- CI/CD pipe 全綠（無 ANSI 污染，`jq` pipeline 可正常運作）
- §10 Charts & Data: 0 → 2；CLI composability 規則 3★: 0 → 3

---

### 4.8 — b4 CLI 錯誤訊息

| | |
|---|---|
| Subsystem | CLI |
| 觸及 persona | P1 |
| Pre-condition | 無獨立 pre-condition |
| Score | Impact 3 × PersonaWeight 3 (P1) × Frequency 2 (錯誤發生頻率中等，但影響嚴重) = **18** |
| 優先級 | **P1**（§8 Forms & Feedback CRITICAL = 0 觸發升級） |

**現況片段** — `§3.2.5 A.5`：CLI 無 `difflib.get_close_matches` 整合，命令輸入錯誤時直接顯示 Click 框架的裸 `Error: No such command 'xxx'.`，無相近命令建議。業務邏輯錯誤（如 API 連線失敗、設定檔格式錯誤）直接噴 Python traceback（`Traceback (most recent call last): ...`），無 cause + recovery 結構。無統一頂層 `try/except` 攔截未預期 exception，錯誤訊息格式隨 exception 類型而異（KeyError / ConnectionError / FileNotFoundError 各有不同輸出）。exit code 有三種風格（0/1/-1 混用），CI/CD 腳本無法統一依賴 exit code 判斷成功失敗。

**影響** — P1 網管遇到錯誤後無法自助修復：缺乏 cause（為什麼出錯）+ recovery（如何修復）結構，只能 Google traceback 或提 support ticket。裸 Python traceback 暴露內部堆疊，增加安全性 surface area（路徑資訊、模組結構可見）。exit code 不穩定導致 CI/CD 誤判（-1 在某些 shell 被解讀為 255，破壞 `$?` 判斷邏輯）。support load 上升。

**UX rubric 觸及項** — §8 Forms & Feedback = 1（CRITICAL）：無結構化錯誤訊息，無 inline recovery 提示；CLI rule 12（錯誤明確性）= 0。P1 escalation：Error actionability = 0 觸發 CRITICAL → P1。

**優化路線（小改）**
1. 頂層 CLI entry point 加統一 `try/except Exception as e` wrapper，攔截未預期 exception，轉換為 `[ERROR] <cause>\n[FIX] <recovery hint>` 格式輸出，exit code 統一為 1（1 day）
2. 建立 `error_helper.py`：`format_error(cause, recovery, suggestion=None)` → 輸出統一格式；常見 exception 類型（`ConnectionError` / `FileNotFoundError` / `PermissionError`）預設 recovery hint 表（2 day）
3. 在 command dispatcher 層加 `difflib.get_close_matches` 建議（與 4.6 b2 共用實作，1 day）
4. exit code 正規化：成功 = 0，user error = 1，system error = 2（半天）
- Touch radius：小（頂層 entry + error_helper 新模組，業務邏輯不動）
- 與 §5 cross-cutting 衝突？`error_helper` 設計與 Track B OutputManager 協同，不衝突

**重構路線（併入 Track B）**
1. Track B：`OutputManager` 統一 error 輸出路徑，`error_helper` 成為 OutputManager 的 error channel
2. 所有 business error 改用 `OutputManager.error(cause, recovery)` 呼叫，廢除裸 `print()` / `click.echo()` 錯誤輸出
3. 整合 `--json` 模式下的結構化 error payload（`{"error": {"cause": "...", "recovery": "..."}, "exit_code": 1}`）
- Touch radius：中（錯誤路徑統一，含 --json 結構化輸出）
- 與 §5 cross-cutting 同源：§5.1「共享 CLI 輸出層」Track B

**§2.6 五 Gate 評估**
- Gate 1 Offline       : ✓（error_helper / top-level try-except 純 CLI 邏輯，無網路依賴）
- Gate 2 多痛點共因    : 共因 3 個（b4 錯誤訊息 / b3 輸出格式 / b2 did-you-mean 共用 difflib）→ 重構分 +1
- Gate 3 Touch radius  : 優化小；重構中
- Gate 4 Persona 衝擊  : P1 每次遇錯必觸；裸 traceback 阻斷自助修復，support load 上升 → 高衝擊
- Gate 5 Reversibility : ✓（top-level try/except 可 flag 回退；error_helper 純增量模組）

**推薦** — 優化路線優先（3 day）；Track B 完成時，`error_helper` 自動接入 OutputManager error channel，無需重寫。

**驗收標準** — 採用優化路線後：
- 所有 CLI 錯誤輸出為 `[ERROR] <cause>\n[FIX] <recovery>` 格式（無裸 traceback）
- exit code 正規化：成功 0，user error 1，system error 2（CI/CD `$?` 判斷穩定）
- `difflib.get_close_matches` 建議覆蓋命令層輸入錯誤
- 結構化錯誤 payload 可在 `--json` 模式下輸出
- §8 Forms & Feedback: 1 → 2；CLI rule 12: 0 → 2

---

### 4.9 — b5 三支獨立 CLI vs menu 雙入口整合

| | |
|---|---|
| Subsystem | CLI |
| 觸及 persona | P1 |
| Pre-condition | 無獨立 pre-condition；可先建命令對等表再決定整合節奏 |
| Score | Impact 3 × PersonaWeight 3 (P1) × Frequency 2 (日常操作遇雙入口) = **18** |
| 優先級 | **P1**（§9 Navigation = 2；CLI rule 11 雙入口整合 = 1，低於閾值觸發升級） |

**現況片段** — `§3.2.4 A.4`：專案同時維護 3 支獨立 CLI 腳本（`pce_cache_cli.py`、`rule_scheduler_cli.py`、`siem_cli.py`）以及 `src/cli/menus/` 互動式選單。24 個命令中 14 個（58%）在兩處皆有入口，且各自持有獨立實作（非共用底層函式）。選單以裸 `print()` 輸出（佔 62%），獨立 CLI 改用 `rich`（佔 24%），其餘 14% 為 Click 原生輸出，三套渲染路徑並存，行為一致性無保障。

**影響** — P1 網管須學習雙套命令路徑，認知負擔翻倍。14 份重複實作維護量加倍，任一修改需同步兩處，漂移風險高。輸出格式不統一使 CI/CD 腳本對接困難（grep/parse 結果依呼叫路徑而異）。

**UX rubric 觸及項** — §9 Navigation = 2：有層級但無單一入口；CLI rule 11（雙入口整合）= 1（CRITICAL 閾值 = 2，未達觸發升級）；P1 escalation：學習雙倍命令路徑 + 維護重複 → 實際頻率 2 × Impact 3 → P1。

**優化路線（小改）**
1. 建立 menu / standalone 命令對等表文件（`docs/cli-command-map.md`），明確標示兩路徑的功能等價性（1 day）
2. 將重複命令的業務邏輯提煉為共用底層函式（`src/cli/core/`），menu 與 standalone 皆呼叫同一函式，消除實作漂移（3-5 day）
3. 在 standalone CLI `--help` 末尾加入 `see also: interactive menu` 提示，反之亦然（半天）
- Touch radius：中（業務邏輯提煉，不動 CLI 結構與入口定義）
- 與 §5 cross-cutting 衝突？共用底層函式為 Track C 統一入口的前置工作，不衝突

**重構路線（大改）**
1. Track C：統一 CLI 入口 `illumio-ops`——移除三支獨立腳本，以 Click group 子命令取代
2. 以 `shell` / `--interactive` 模式取代互動式選單，底層仍為同一命令樹
3. Deprecation alias 保留舊腳本名稱指向新入口（6 個月過渡期）
- Touch radius：大（影響全部入口定義，含 shebang / PATH 設定）
- 與 §5 cross-cutting 同源：§5.2 Track C 統一 CLI 入口

**§2.6 五 Gate 評估**
- Gate 1 Offline       : ✓（CLI 結構調整純本地，無網路依賴）
- Gate 2 多痛點共因    : 共因 3 個（b1 menu / b2 命名一致性 / b5 雙入口）→ 重構分 +1
- Gate 3 Touch radius  : 優化中；重構大
- Gate 4 Persona 衝擊  : P1 每次操作必須選擇路徑；14/24 重複命令覆蓋率高 → 高衝擊
- Gate 5 Reversibility : ✓（deprecation alias 保留舊路徑；共用底層函式可漸進替換）

**推薦** — 重構路線（Track C）為最終解；優化路線（共用底層函式）是必要前置步驟，可獨立 sprint 先行，降低漂移風險，同時為 Track C 鋪路。

**驗收標準** — 採用優化路線後：
- 14 個重複命令皆呼叫共用底層函式（diff: 無同功能重複實作）
- 輸出渲染路徑統一（rich / plain 由同一開關控制，不依呼叫路徑而異）
- `docs/cli-command-map.md` 完整列出 24 命令的入口對等關係
- §9 Navigation: 2 → 3；CLI rule 11: 1 → 2

---

### 4.10 — b6 isatty / NO_COLOR / pipe 友善度

| | |
|---|---|
| Subsystem | CLI |
| 觸及 persona | P1、CI/CD pipeline 操作者 |
| Pre-condition | 無獨立 pre-condition；可獨立修復，與其他卡無強依賴 |
| Score | Impact 3 × PersonaWeight 3 (P1) × Frequency 3 (每次 pipe/CI 觸發) = **27** |
| 優先級 | **P1**（§1 Accessibility CRITICAL = 1；CLI rule 2★ 能力偵測 = 1；CLI rule 7 雙模 = 1，三項同時低於閾值） |

**現況片段** — `§3.2.5 A.5`：codebase 有 `isatty()` 呼叫共 4 處，但均未用於條件性渲染——即使偵測到非 TTY，仍照常輸出 `rich` ANSI markup 與 `rich.box` 表格框線。`NO_COLOR` 環境變數未被讀取（`os.environ.get('NO_COLOR')` 全檔案無此查詢）。`rich.Console()` 初始化未傳入 `force_terminal=False` / `no_color` 參數。結果：在 CI 日誌、`| jq`、`> file.txt` 等非互動場景下，ANSI escape sequence 直接污染輸出流。

**影響** — CI/CD pipeline 日誌充斥 ANSI 噪音，log parser 與 grep 失效。`jq` pipeline 無法直接消費 CLI 輸出（需額外 `sed` 清除 escape code）。`NO_COLOR=1` 標準（https://no-color.org）未實作，違反 POSIX-friendly 工具期望。P1 在自動化腳本中呼叫 CLI 須額外處理輸出，增加 glue code 負擔。

**UX rubric 觸及項** — §1 Accessibility CRITICAL = 1（pipe 場景輸出不可用）；CLI rule 2★（能力偵測）= 1；CLI rule 7（雙模輸出：人類可讀 / 機器可讀）= 1。三項 CRITICAL baseline rule ★ 同時為 1 → P1 強制升級。

**優化路線（小改）**
1. 加 `NO_COLOR` 讀取：CLI entry point 啟動時讀取 `os.environ.get('NO_COLOR')`，為非空字串則強制純文字模式（半天）
2. `isatty()` 條件渲染：將現有 4 處 `isatty()` 偵測結果傳入 `rich.Console(force_terminal=sys.stdout.isatty(), no_color=...)` 初始化，確保非 TTY 場景降級（1 day）
3. 所有 CLI entry points 套用上述 Console 設定（含 3 支獨立 CLI，1 day）
4. `rich.box` 表格在非 TTY 時改用 `box=None`（純文字 tab-separated）（半天）
- Touch radius：小→中（Console 初始化集中，業務邏輯不動）
- 與 §5 cross-cutting 衝突？優化可獨立；Track B 統一輸出層接管後此設定集中一處

**重構路線（併入 Track B）**
1. Track B `OutputManager` 統一管理 Console 實例，`isatty` / `NO_COLOR` 偵測邏輯集中在 `OutputManager.__init__`
2. 所有 CLI 輸出路徑改呼叫 `OutputManager.print()` / `.table()` / `.error()`，移除散落的裸 `rich.Console()` 初始化
3. `--json` flag 強制機器可讀模式（獨立於 isatty 偵測）
- Touch radius：中（輸出路徑統一，業務邏輯不動）
- 與 §5 cross-cutting 同源：§5.1「共享 CLI 輸出層」Track B

**§2.6 五 Gate 評估**
- Gate 1 Offline       : ✓（isatty / NO_COLOR 純本地環境變數與 fd 偵測，無網路依賴）
- Gate 2 多痛點共因    : 共因 4 個（b3 輸出格式 / b4 error 格式 / b6 pipe 友善 / b7 exit codes）→ 重構分 +1
- Gate 3 Touch radius  : 優化小→中；重構中
- Gate 4 Persona 衝擊  : CI/CD 場景每次觸發；P1 自動化腳本需額外 glue code → 高衝擊
- Gate 5 Reversibility : ✓（Console 初始化參數可 flag 回退；NO_COLOR 讀取純增量）

**推薦** — 優化路線優先（1-2 day patch，可立即解除 CI 噪音）；Track B 完成後，Console 管理自動集中至 OutputManager，優化代碼可直接遷移。

**驗收標準** — 採用優化路線後：
- `CLI_OUTPUT=pipe | grep` 或 `| jq` 場景：零 ANSI escape code 出現在 stdout
- `NO_COLOR=1 <command>` 強制純文字（覆蓋所有 4 entry points + 3 standalone CLIs）
- CI 日誌可直接 grep 命令輸出，無需前置 `sed` 清除
- §1 Accessibility CRITICAL: 1 → 2；CLI rule 2★: 1 → 2；CLI rule 7: 1 → 2

---

### 4.11 — b7 Exit codes 與 error actionability

| | |
|---|---|
| Subsystem | CLI |
| 觸及 persona | P1、CI/CD pipeline 操作者 |
| Pre-condition | 無獨立 pre-condition；與 b4 error 訊息優化可協同進行 |
| Score | Impact 2 × PersonaWeight 3 (P1) × Frequency 2 (自動化腳本 / CI 觸發) = **12** |
| 優先級 | **P2**（CLI rule 4★ exit codes = 1，CRITICAL 閾值未達；若 shell pipeline 強依賴場景確認為 P1 use case 則升為 P1） |

**現況片段** — `§3.2.5 A.5`：CLI 使用三種不同的 exit code 風格——`sys.exit(code)`、`raise SystemExit(code)`、`raise click.ClickException(msg)`（ClickException 預設 exit code = 1，但 msg 格式不統一）。3 支獨立 CLI（`pce_cache_cli.py` 等）在所有執行路徑（含錯誤）均回傳 exit code 0。全專案 0 個命令實作標準 SIGINT → exit 130（`signal.signal(SIGINTM signal.SIG_DFL)` 未設定）。`CLI rule 4★`（exit code 語義）baseline score = 1；CLI rule 12（error actionability）= 0。

**影響** — Shell pipeline 的 `command || handle_error` 邏輯失效（因錯誤仍回傳 0）。CI gate 無法依 exit code 路由至正確的 failure handler（retry / alert / skip）。Ctrl-C 中斷後 exit code 非 130，破壞呼叫腳本的 trap 邏輯。錯誤類別不可區分（user error vs system error vs network error），CI/CD log 分析困難。

**UX rubric 觸及項** — CLI rule 4★（exit codes）= 1（CRITICAL，標準未實作）；CLI rule 12（error actionability）= 0（無結構化錯誤分類）。與 4.8 b4 共因：exit code 正規化與 error 訊息結構化為同一 root fix。

**優化路線（小改）**
1. 定義 domain exit code map（參照 `sysexits.h`）：0 成功 / 1 user error / 2 system error / 64 用法錯誤 / 65 資料錯誤 / 69 服務不可用 / 75 暫時性失敗（1 day 設計 + 文件化）
2. 套用至所有 24 個命令與 3 支獨立 CLI：每個錯誤路徑明確傳入對應 code（2-3 day）
3. 加 `signal.signal(signal.SIGINT, signal.SIG_DFL)` 確保 Ctrl-C → exit 130；`SIGTERM` → exit 143（半天）
4. 統一以 `sys.exit(code)` 取代混用的 SystemExit / ClickException exit path（1 day）
- Touch radius：中（每個命令的 error path 須逐一標注，但業務邏輯不動）
- 與 §5 cross-cutting 衝突？與 4.8 b4 error_helper 協同：`format_error(cause, recovery, exit_code=1)` 可同步攜帶 exit code

**重構路線（併入 Track B）**
1. Track B `OutputManager.error(cause, recovery, exit_code)` 統一 exit code 發出點
2. 所有錯誤路徑改呼叫 `OutputManager.error()`，自動套用 exit code map
3. `--json` 模式下 error payload 包含 `{"exit_code": N, "cause": "...", "recovery": "..."}`
- Touch radius：中（錯誤路徑統一，exit code 由 OutputManager 集中管理）
- 與 §5 cross-cutting 同源：§5.1「共享 CLI 輸出層」Track B

**§2.6 五 Gate 評估**
- Gate 1 Offline       : ✓（exit code 語義純本地 process 行為，無網路依賴）
- Gate 2 多痛點共因    : 共因 4 個（b3 輸出 / b4 error 訊息 / b6 pipe 友善 / b7 exit codes）→ 重構分 +1
- Gate 3 Touch radius  : 優化中；重構中
- Gate 4 Persona 衝擊  : CI/CD 自動化場景直接依賴；shell pipeline `||` 失效場景對 P1 高影響
- Gate 5 Reversibility : ✓（exit code map 以常數表定義，可 flag 回退至舊行為；signal handler 增量設定）

**推薦** — 優化路線（1 week）與 4.8 b4 協同進行效率最高；Track B 接管後 exit code map 自動集中至 OutputManager，無需重寫。若確認 shell pipeline 為 P1 核心 use case，升級至 P1 處理。

**驗收標準** — 採用優化路線後：
- `command_that_fails; echo $?` 回傳非 0（3 支獨立 CLI 覆蓋）
- Ctrl-C 中斷任意命令 → `$?` = 130
- exit code map 文件化（`docs/cli-exit-codes.md`），24 命令各自對應 code 標注
- CI pipeline `command || handle` 邏輯可正確路由（整合測試驗證）
- CLI rule 4★: 1 → 3；CLI rule 12: 0 → 2

---

### 4.12 — b8 Auto-completion 缺失

| | |
|---|---|
| Subsystem | CLI |
| 觸及 persona | P1 |
| Pre-condition | 需確認 `scripts/completions/` 現有 bash completion 的安裝路徑與文件狀態 |
| Score | Impact 1 × PersonaWeight 3 (P1) × Frequency 1 (一次性設定，非每次操作) = **3** |
| 優先級 | **P3**（CLI rule 10 completion = 2，bash 已部分實作；缺 zsh/fish；score 低不升級） |

**現況片段** — `§3.2.5 A.5`：`scripts/completions/` 目錄下存在 bash completion 腳本（CLI rule 10 baseline = 2，已部分實作）。zsh 與 fish shell completion 不存在。`click_completion` 套件與 `argcomplete` 均未整合至 `pyproject.toml` / `setup.cfg` 依賴清單。bash completion 的安裝路徑（`/etc/bash_completion.d/` vs `~/.bash_completion`）與啟用方式未在 `README` 或 `docs/` 中文件化。`--help` 未提及 completion 設定方式（CLI rule 9 `--help` = 1）。

**影響** — P1 在快速操作（type-fast cycle）時無 Tab 補全，依賴記憶命令名稱與參數，錯字率上升。zsh（macOS 預設 shell）用戶完全無 completion 支援。completion 存在但未文件化，等同對新成員不存在。

**UX rubric 觸及項** — CLI rule 10（auto-completion）= 2（bash 已存在，zsh/fish 缺失）；CLI rule 9（`--help` 完整度）= 1（未提及 completion 設定）。score 3 → P3，不觸發升級。

**優化路線（小改）**
1. 加 zsh completion 腳本（`scripts/completions/illumio-ops.zsh`）：參照現有 bash 腳本結構，使用 `#compdef` 框架（1 day）
2. 加 fish completion 腳本（`scripts/completions/illumio-ops.fish`）（半天）
3. 加 `docs/cli-completion-setup.md`：記錄 bash / zsh / fish 各 shell 的安裝指令與驗證步驟（半天）
4. 在 `illumio-ops --help` 末尾加入 `Tip: Run 'illumio-ops --install-completion' to enable tab completion` 提示（半天）
- Touch radius：小（新增腳本與文件，不動現有 CLI 實作）
- 與 §5 cross-cutting 衝突？獨立執行，不與其他 Track 衝突

**重構路線（Track L4 — 不推薦現階段）**
1. 遷移至 `typer`（基於 Click，但原生支援 `--install-completion` / `--show-completion`，自動生成所有主流 shell completion）
2. 遷移後 `scripts/completions/` 手工腳本可移除，改由 typer 運行期動態生成
- Touch radius：大（需重寫所有命令定義）
- 與 §5 cross-cutting 同源：Track C 統一 CLI 入口若選用 typer，completion 問題自動解決

**§2.6 五 Gate 評估**
- Gate 1 Offline       : ✓（shell completion 腳本純本地，無網路依賴）
- Gate 2 多痛點共因    : 共因 1 個（b8 completion 獨立，與 b1/b2/b5 間接關聯）→ 重構分不加
- Gate 3 Touch radius  : 優化小；重構大
- Gate 4 Persona 衝擊  : P1 type-fast cycle 受益；但非每次操作觸發（一次性設定）→ 衝擊低
- Gate 5 Reversibility : ✓（新增腳本可直接移除；文件化無副作用）

**推薦** — 優化路線（low-hanging fruit，2 day）；若 Track C 選用 typer，completion 問題自動解決，無需單獨重構。不推薦現階段為此單獨啟動大型重構。

**驗收標準** — 採用優化路線後：
- `Tab` 補全在 bash / zsh / fish 三種 shell 下均可用
- `docs/cli-completion-setup.md` 提供逐步安裝指引（含驗證指令）
- `illumio-ops --help` 末尾出現 completion 設定提示
- CLI rule 10: 2 → 3；CLI rule 9 `--help`: 1 → 2

---

### 4.13 — c1 Report 摘要 / 長度

| | |
|---|---|
| Subsystem | Report |
| 觸及 persona | P5 |
| Pre-condition | 無獨立 pre-condition；與 c3（圖表可讀性）及 b5（CLI 雙入口）有共因，可獨立優化 |
| Score | Impact 2 × PersonaWeight 3 (P5) × Frequency 2 (每週產報告) = **12** |
| 優先級 | **P2** |

**現況片段** — `§3.4.2 A.6`：5 份生成器（`audit_report.py` 878 L；`policy_usage_report.py` 656 L；`ven_status_report.py` 368 L；`traffic_report.py` 16-section；`dashboard_summaries.py`）；exporter infra 共 5272 行。`mod00` exec summary 區塊已存在於各報告，但 standalone 執行摘要能力（無需閱讀全文即可抓重點）待驗。`§3.4.4 C.4`：跨報告連結數量 = 0；在 audit ↔ policy 之間切換時使用者需完全重新 navigate。Traffic 報告含 16 個 section，無章節進度指示。Audit 報告 `mod00` 含 5 個執行摘要子模組；policy_usage 含 6 個 mod00 exec + execution stats；ven_status 含 5 個 KPI card。

**影響** — P5 主管開啟報告後，200 字以內無法 standalone 抓到關鍵訊息，需要向下捲動閱讀才能判斷狀態。跨報告無連結導致 audit ↔ policy 切換時重新 navigate，認知摩擦高。Traffic 16 section 無章節節奏指示，閱讀路徑不明確。exec summary 若只能作為「前言」而非可獨立查閱的摘要，則在行動裝置或快速掃描情境下使用率趨零。

**UX rubric 觸及項** — §3.3.2 length distribution = 1（exec summary 存在但 standalone density 未驗證）；summary density 是 Report 核心評分項。§3.3.1 overall structure = 2（章節架構存在，但 traffic 16-section 無節奏分組）。

**Visual rubric 觸及項** — 章節節奏（D.2 已規範 H1/H2/H3 上下空白與 Source Serif 4 字體）；exec summary block 的視覺權重（需與 body 段落有足夠區隔）；sidebar nav 的版面容納性（D.2 @page first 封面 + footer 頁碼已確立，sidebar 需與此兼容）。

**優化路線（小改）**
1. 每份報告加 200 字 standalone executive summary 區塊（統一放 mod00 開頭，格式：3 個 KPI bullet + 1 句 next action）：audit / policy_usage / ven_status 各 1 day，共 3 day
2. Traffic 報告加章節進度 TOC sidebar（HTML：sticky `<nav>`；PDF：頁眉節名）：1 day
3. 各報告末尾加跨報告 sidebar nav（HTML: `<aside>` 連結其他 3 份報告；PDF: footer 連結文字）：1 day
- Touch radius：中（各 report 生成器 mod00 + HTML/PDF exporter template；不動 exporter infra 核心）
- 與 §5 cross-cutting 衝突？與 Track A token 化配合：sidebar nav 樣式可先硬碼，重構時改接 design token

**重構路線（Track A — 排隊）**
1. Track A：Report exporter infra token 化（`report_css.py` + `html_exporter.py`）+ 章節結構模板化（Section dataclass → jinja2 partial）
2. 與 OQ-2 i18n reorg 配合：exec summary 語言版本切換時自動套用對應翻譯的摘要模板
3. 建立 cross-report nav component（共享 `_nav_sidebar.html.j2`），在所有 5 份報告複用
- Touch radius：大（5272 行 exporter infra + 各 report 生成器）
- 與 §5 cross-cutting 同源：§5.1「Report exporter 整併」

**§2.6 五 Gate 評估**
- Gate 1 Offline       : ✓（exec summary 與 sidebar nav 均為靜態 HTML/PDF，無外部依賴）
- Gate 2 多痛點共因    : 共因 3 個（c1 摘要結構 + c3 圖表可讀性 + d3 Email 摘要一致性） → 重構分 +1
- Gate 3 Touch radius  : 優化中（4 生成器 mod00 + 2 exporter template）；重構大
- Gate 4 Persona 衝擊  : P5 主管每週必看報告，standalone 摘要缺失直接影響決策效率 → 高衝擊
- Gate 5 Reversibility : ✓（exec summary block 可獨立移除；sidebar nav 為新增 HTML 元素，可 feature-flag）

**推薦** — 優化先行（4 day patch：3 份報告 exec summary × 1 day + TOC sidebar 1 day）+ 重構排隊 Track A。優化路線可將 §3.3.2 summary density 從未驗證 → 明確 pass，不需等重構。

**驗收標準** — 採用優化路線後：
- audit / policy_usage / ven_status 三份報告各含 ≤ 200 字 standalone executive summary（KPI bullet × 3 + next action × 1）
- Cross-report sidebar nav 存在於每份報告（HTML sidebar + PDF footer link）
- Traffic 報告含章節 TOC sidebar，可直接跳至任一 section
- §3.3.2 length distribution: 1 → 2；§3.3.1 overall structure: 2 → 3

---

### 4.14 — c3 圖表閱讀性

| | |
|---|---|
| Subsystem | Report |
| 觸及 persona | P5 |
| Pre-condition | 需確認 `chart_renderer.py` 調色板實作位置與 `report_css.py` token 共用狀態；D.3 signal hex 已確立 |
| Score | Impact 2 × PersonaWeight 3 (P5) × Frequency 3 (每份報告必有圖表) = **18** |
| 優先級 | **P2** |

**現況片段** — `§3.4.4 C.4`：VEN 餅圖 label 硬編碼英文（繞過 i18n 管線）；4 處 verdict 字面不一致（`Allowed` / `已允許` / `OK`）；`rpt_tr_sec_allowed` 中文 key 存在但 nav 顯示英文。`§3.4.5 C.5`：HTML chart Plotly responsive（Spatial 3/3），但無 `aria-label` 屬性；PDF chart 為靜態圖片，color verdict 未統一遷移（PDF Color 1/3，Backgrounds 0/3）。完整 chart 調色板實作分散於 `chart_renderer.py` 與 `report_css.py`。`§3.4.4 C.4` i18n_zh_TW：134 jinja2 key，共 4 處不一致；跨報告連結 = 0。

**影響** — P5 讀圖時 verdict 字面不一致（Allowed vs 已允許 vs OK）造成認知摩擦，無法快速判斷「允許 = 已允許 = OK」是否為同一狀態。VEN 餅圖英文 label 在全中文介面中突兀，繁體用戶信任度下降。螢幕閱讀器（SR）使用者因 HTML chart 無 `aria-label`，圖表資訊完全無障礙。PDF chart 缺 colorblind-safe palette，報告列印後（黑白或 deuteranopia）圖例失效。

**UX rubric 觸及項** — §10 charts = 1（Plotly responsive，但無 accessibility；PDF 靜態無互動）；§3.1.2 Accessibility = 1（chart aria-label 缺失為關鍵缺口）；§10 = 1 為 cross-cutting visual 核心評分項。

**Visual rubric 觸及項** — Color（semantic palette + colorblind-safe）：D.3 已給定 4 個 signal hex（綠/黃/紅/灰）；當前 PDF chart color 未統一採用 D.3 signal；`chart_renderer.py` 調色板與 `report_css.py` CSS token 是否共享待確認。

**優化路線（小改）**
1. VEN 餅圖 label 改接 i18n key（`ven_status_report.py`，定位 hardcoded string → 替換為 `t('ven_status_label_managed')` 等）：2 hours
2. 補 colorblind-safe palette：`chart_renderer.py` 採用 D.3 signal hex（綠 `#2E7D32` / 黃 `#F9A825` / 紅 `#C62828` / 灰 `#757575`），確保 PDF 與 HTML 一致：1 day
3. 補 `font-feature-settings: "tnum"` tabular figures 至 chart axis label CSS（`report_css.py`）：半天
4. 補 HTML chart `aria-label` + `<table>` fallback（Plotly `config.toImageButtonOptions` 旁加 `aria` attribute + `<noscript>` 等價表格）：3 days
- Touch radius：中（`chart_renderer.py` + `report_css.py` + `ven_status_report.py`；不動 exporter infra 核心）
- 與 §5 cross-cutting 衝突？可並行；與 c1 patch 共用 exporter template 改動窗口，建議同 sprint

**重構路線（Track A — 排隊）**
1. Track A：統一 `chart_renderer.py` + `report_css.py` signal color token（D.3 共享 palette dataclass）
2. 建立 chart accessibility wrapper（HTML `<figure>` + `<figcaption>` + `<table>` template，供所有報告複用）
3. PDF chart 遷移至 SVG 矢量輸出（替代靜態 PNG），支援 colorblind filter 後仍可讀
- Touch radius：大（chart_renderer.py 全改 + 5 份報告生成器 chart 呼叫點）
- 與 §5 cross-cutting 同源：§5.1「Report exporter 整併」+ §5.1「Token 化 design system」

**§2.6 五 Gate 評估**
- Gate 1 Offline       : ✓（調色板 hex、aria-label、tabular figures 均為純本地靜態改動，無外部依賴）
- Gate 2 多痛點共因    : 共因 3 個（c3 圖表 + c1 報告摘要結構 + d2 Email 視覺設計）→ 重構分 +1
- Gate 3 Touch radius  : 優化中（3 個檔案 + 4 點修補）；重構大
- Gate 4 Persona 衝擊  : P5 每份報告必有圖表，verdict 不一致與無障礙缺口影響中至高；SR users 完全 inaccessible → 衝擊中-高
- Gate 5 Reversibility : ✓（palette 可 feature-flag；aria-label 為純新增屬性，不破壞現有渲染）

**推薦** — 並行優化（4 點補丁，1 week 並行，建議與 c1 patch 同 sprint）+ Track A 接手長線重構。優化路線可將 §10 charts: 1 → 2，§3.1.2 Accessibility: 1 → 2，不需等重構。

**驗收標準** — 採用優化路線後：
- VEN 餅圖 label 在 zh_TW 介面下顯示繁體中文（不再硬編碼英文）
- HTML chart `aria-label` 覆蓋率 100%；每個 Plotly 圖表含對應 `<table>` fallback
- PDF chart 調色板採用 D.3 signal hex（colorblind-safe 驗證：Coblis deuteranopia filter 後仍可區分）
- chart axis label 採用 tabular figures（`font-feature-settings: "tnum"`）
- §10 charts: 1 → 2；§3.1.2 Accessibility: 1 → 2

---

### 4.15 — d2 Email 跨 client 顯示

| | |
|---|---|
| Subsystem | Email |
| 觸及 persona | P5 |
| Pre-condition | A.7 已確認 3 個模板（mail_wrapper.html.tmpl 2.5 KB、line_digest.txt.tmpl 393 B、webhook_payload.json.tmpl 317 B）；D.2 決策選 B（`<table role="presentation">` + bulletproof CTA + bgcolor + Georgia,...,serif fallback，無 `@font-face`）；D.3 signal hex 已確立 |
| Score | Impact 3 × PersonaWeight 3 (P5) × Frequency 2 (高 severity 事件觸發) = **18** |
| 優先級 | **P1** |

**現況片段** — `§3.4.2 C.6`：2/8 pass；`mail_wrapper.html.tmpl` 使用 `<div>` + `display:flex` 佈局（Outlook flex 塌陷）；引用 Montserrat font-stack（webmail 載入失敗時視覺落差）；無 `<meta name="color-scheme">` dark-mode meta；無 `multipart/alternative`（`line_digest.txt.tmpl` 存在但未作為 plaintext part attach）。完整 8 項 known-issues 清單見 `§3.4.2 C.6`。

**影響** — P5 主管使用 Outlook 365 → flex 塌陷，版面破損無法閱讀；Apple Mail dark mode 自動反色 → 文字與背景對比失效，無法讀取內容；純文字 client（Thunderbird 無 HTML mode）無 plaintext fallback，顯示空白或原始 HTML tag；Montserrat font-stack 在無 Google Fonts 環境（離線部署）退回 sans-serif，與 Report/GUI 字型視覺落差。

**UX rubric 觸及項** — `§3.4.2 C.6` 8 項 known-issues 全數失敗（2/8 pass）；`§1 Acc`：dark-mode 反色為 Accessibility 中等缺口。

**Visual rubric 觸及項** — Color（D.3 signal token：success `#2D9B5E` / warning `#C47A00` / danger `#D93025` / info `#0077CC`，需雙軌 inline CSS + bgcolor 雙寫，不依賴 `@font-face` 或 CSS variable）；Typography（D.2 Email subset 限制：系統 serif `Georgia, "Times New Roman", Times, serif`，禁用 webfont 引用）。

**優化路線（小改）**
1. 將 `<div>` + `display:flex` 改為 `<table role="presentation">` 表格佈局（依 D.2 決策 B）：1 day
2. Inline CSS + bgcolor 雙軌：所有背景色以 `bgcolor` attribute + `background-color` inline 雙寫（D.3 hex 直接引用）：1 day
3. 加 `<meta name="color-scheme" content="light dark">` + `<meta name="supported-color-schemes" content="light dark">`（`mail_wrapper.html.tmpl` `<head>` 段）：1 hour
4. 加 `multipart/alternative`：`src/reporter.py` email builder 附加 `line_digest.txt.tmpl` 渲染結果為 `text/plain` part：1 day
5. 移除 Montserrat font-stack 引用，改為 `Georgia, "Times New Roman", Times, serif`（D.2 Email subset）：15 min
- Touch radius：中（`mail_wrapper.html.tmpl` 全面改表格 + `src/reporter.py` builder 加 multipart）
- 與 §5 cross-cutting 衝突？與 d3 patch 共用同一 template 改動窗口，建議同 sprint

**重構路線（Track D — 中期）**
1. Track D：引入 MJML 預編譯管線（`mail_wrapper.mjml` → cross-client safe HTML），取代手工維護 `<table>` 嵌套
2. Build pipeline 加 `mjml` compile step（CI：`npx mjml src/email/*.mjml -o dist/email/`）
3. MJML component 封裝 preheader、signal color block、bulletproof CTA primitive（與 d3 改動共享）
- Touch radius：大（新增 MJML build step + 所有現有 `.tmpl` 遷移至 `.mjml`）
- 與 §5 cross-cutting 同源：§5.1「Email renderer 整併」

**§2.6 五 Gate 評估**
- Gate 1 Offline       : ✓（table 佈局、inline bgcolor、meta tag、multipart 均為純本地靜態改動；MJML compile-time 亦離線可執行）
- Gate 2 多痛點共因    : 共因 3 個（d2 跨 client + d3 actionability + a7 external resource → Email 系統統一）→ 重構分 +1
- Gate 3 Touch radius  : 優化中（`mail_wrapper.html.tmpl` + `src/reporter.py`）；重構大
- Gate 4 Persona 衝擊  : P5 Outlook 365 flex 塌陷為高衝擊（主要閱讀管道破損）；dark-mode 與純文字 client 為中衝擊
- Gate 5 Reversibility : ✓（table 佈局為純增量替換；multipart 為新增 part，不移除現有 HTML part；均可 feature-flag）

**推薦** — 並行：優化路線 5 點（1 week，清補 7/8 items）+ Track D MJML（mid-term，系統化解跨 client 相容）。優化路線可將 `§3.4.2 C.6` 2/8 → 7/8，不需等重構。

**驗收標準** — 採用優化路線後：
- Outlook 365 渲染正確（無 flex 塌陷；`<table>` 佈局驗證）
- Gmail / Apple Mail / Thunderbird 渲染正確（`§3.4.2 C.6` 8/8 checklist 全綠）
- Apple Mail dark mode 下文字對比可讀（`color-scheme` meta 生效）
- 純文字 client 收到可讀 plaintext（`multipart/alternative` 含 `line_digest.txt` 渲染結果）
- Font-stack 為 `Georgia,...,serif`（無 Montserrat 引用）

---

### 4.16 — d3 Email 主旨 / 摘要 actionability

| | |
|---|---|
| Subsystem | Email |
| 觸及 persona | P5 |
| Pre-condition | C.7 已確認 0/4 pass；D.2 決策 B 已確立 Email subset spec；D.3 signal hex 已確立；`src/reporter.py` email builder 可取得 severity / object 欄位 |
| Score | Impact 3 × PersonaWeight 3 (P5) × Frequency 3 (每封告警郵件必觸及) = **27** |
| 優先級 | **P1** |

**現況片段** — `§3.4.3 C.7`：0/4 pass；Subject 固定為 `"Illumio PCE Ops Alert ({count} issue(s))"` 無 severity / object；preheader 缺席（inbox preview 顯示 `"Official Alert Notification"`）；CTA 按鈕僅出現在 event 區段，其他區段無 CTA；Why 層（severity badge + threshold + trigger context）缺席；Action 層 runbook 文字存在但為純文字，無可點 link。完整 4 項 actionability checklist 見 `§3.4.3 C.7`。

**影響** — P5 主管 inbox 排序失效（無 severity 無法快速識別 CRITICAL vs INFO）；email preview 行顯示無資訊的 `"Official Alert Notification"`，需開信才能判斷是否需立即處理；CTA 覆蓋率不足 → 主管需自行切換到 GUI 找對應入口，MTTR 上升；Why 層缺席 → 無法在不開 GUI 的情況下 self-route 判斷是否需要升級；Action 層 runbook 無 link → 無法在行動裝置直接開啟。

**UX rubric 觸及項** — `§3.4.3 C.7` 4 項 actionability 全數失敗（0/4 pass）。

**Visual rubric 觸及項** — Hierarchy（sky-eye 5 秒 What-Why-Action 三層結構：Subject 為 What，preheader 為 Why 前導，CTA 為 Action 入口）；Color（D.3 signal token 應用於 severity badge：success `#2D9B5E` / warning `#C47A00` / danger `#D93025` / info `#0077CC`）。

**優化路線（小改）**
1. Subject pattern 改為 `[<severity>] <object>: <action>`（例：`[CRITICAL] PCE 192.168.1.1: VEN offline > 30min`）：`src/reporter.py` email builder 取 severity + object 欄位組裝：1 day
2. 加 hidden preheader 50–90 chars（`<div style="display:none;max-height:0;overflow:hidden;">` 段）至 `mail_wrapper.html.tmpl`，內容為獨立摘要（不重複 subject）：2 hours
3. 補 CTA 至所有區段（event / policy / workload / VEN）+ deep link 帶參數（例：`<gui-base>/dashboard?alert_id=<id>&severity=<sev>`）：`src/reporter.py` builder + `mail_wrapper.html.tmpl` 各區段模板：2 days
4. Why 區補 severity badge + threshold + trigger context（`mail_wrapper.html.tmpl` Why section；badge 採 D.3 signal hex inline bgcolor）：1 day
5. Action 區補 inline runbook link（`mail_wrapper.html.tmpl` Action section；`src/reporter.py` 取 runbook_url 欄位）：4 hours
- Touch radius：中（`src/reporter.py` builder 欄位取用 + `mail_wrapper.html.tmpl` 結構新增）
- 與 §5 cross-cutting 衝突？與 d2 patch 共用同一 template 改動窗口，建議同 sprint

**重構路線（Track D — 中期）**
1. Track D MJML 包含 preheader / CTA primitive 封裝（與 d2 MJML 共享 component library）
2. 配合 OQ-2 i18n reorg：subject pattern key 抽為 `alert_subject_critical` / `alert_subject_warning` 等，preheader key 為 `alert_preheader_*`（`i18n_zh_TW.py`）
3. CTA deep link URL 規則抽為 `email_cta_url_builder`（集中管理 `gui-base` + 參數結構）
- Touch radius：大（i18n key 重組 + MJML component + URL builder 抽象層）
- 與 §5 cross-cutting 同源：§5.1「Email renderer 整併」+ OQ-2 i18n

**§2.6 五 Gate 評估**
- Gate 1 Offline       : ✓（Subject 組裝、preheader div、CTA link、Why/Action template 均為純本地靜態改動）
- Gate 2 多痛點共因    : 共因 2 個（d3 actionability + d2 跨 client → Track D Email 系統統一）→ 重構分 +1
- Gate 3 Touch radius  : 優化中（`src/reporter.py` + `mail_wrapper.html.tmpl`）；重構大
- Gate 4 Persona 衝擊  : P5 每封告警郵件必觸及；Subject 無 severity 為高衝擊（inbox 排序失效）；CTA 缺失為高衝擊（MTTR 上升）
- Gate 5 Reversibility : ✓（Subject pattern 可 feature-flag；preheader 為純新增 div；CTA link 為新增元素，不移除現有內容）

**推薦** — 並行：優化全 5 點（1 week，其中項目 2/5 為簡單 2–4 hours 改動，可先行）+ Track D 統一（mid-term，含 i18n reorg + MJML）。

**驗收標準** — 採用優化路線後：
- `§3.4.3 C.7` 4/4 actionability checklist 全綠
- Subject 格式符合 `[<severity>] <object>: <action>` pattern；inbox 排序可依 `[CRITICAL]` / `[WARNING]` 等前綴區分
- Preheader 在 Gmail / Apple Mail 預覽行顯示獨立 standalone summary（50–90 chars，非 subject 重複）
- CTA 覆蓋率 100%（所有區段均有 CTA；deep link 帶 `alert_id` + `severity` 參數）
- Why 區含 severity badge（D.3 signal hex bgcolor）+ threshold + trigger context
- Action 區含可點 inline runbook link

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

#### Step 1 — 4 候選評分（5+1 維度，0-3 分）

評分依據：§3.1.3 現況為基線（Distinctiveness=1，Typography=2，Color=3，Motion=2，Spatial=2，Backgrounds=2），各候選相對現狀評估可達成分數，並考量 P1 網管 / P2 SOC 工作場景與 C1 offline 硬約束。

| 候選 | Typography | Color | Motion | Spatial | Backgrounds | Distinct | 適用 P1 | 適用 P2 | **合計** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| A. 維持現狀 | 2 | 3 | 2 | 2 | 2 | 1 | 中（引 §3.1.3 = 12/18，"稱職 ops admin"） | 高 | **14** |
| B. industrial-editorial | 3 | 3 | 2 | 3 | 2 | 2 | **高** | 中 | **15** |
| C. modern-saas | 1 | 2 | 2 | 1 | 1 | 1 | 中 | 中 | **8** |
| D. dark-ops 終端感 | 3 | 3 | 2 | 2 | 3 | 3 | 中 | **高** | **16** |

評分說明：
- **A. 維持現狀**：現況數據直接引用 §3.1.3，Distinctiveness=1 為結構缺陷（Montserrat 兼任標題/正文導致無字族對比），Color 3 為唯一亮點。適用 P2 SOC「高」是因為現有深色主題 cyan-teal 已有終端感基礎，但未深化。
- **B. industrial-editorial**：引入 display 字族（如 Space Grotesk）對比 body（Inter），tabular figures 強化數據可讀性；Typography 升至 3；Spatial 升至 3（因 editorial grid 強調資訊層級構圖）；Distinct 升至 2（有明確 editorial 工具個性但非顛覆）。對 P1 網管的表單/列表密集場景最契合，P2 SOC 次之（無強烈終端感）。
- **C. modern-saas**：Linear/Vercel 美學，字族與 Montserrat 差異小，排版個性不足；配色因走更亮的 SaaS 風格而與 Illumio 深色品牌稍偏離；Spatial 偏向大留白低密度，與 P1 高密度操作場景衝突；整體 Distinctiveness 不高於現狀。
- **D. dark-ops 終端感**：引入 monospace 為核心字族（JetBrains Mono 標題 / 數值），深色底（#0A0F14）+ 窄邊框 grid；Backgrounds=3（noise texture / scanline overlay / grid lines 等細節）；Distinct=3（獨特視覺語言，不易被誤認）；P2 SOC 高度契合；P1 網管「中」因高密度 mono 字型在長時間表單操作時略增視覺負擔。

---

#### Step 2 — B / C / D 候選完整 Spec Sheet

##### 候選 B — industrial-editorial

| 欄位 | 內容 |
|---|---|
| **描述** | 高密度 editorial 工具感：display 字族 × body 字族雙層對比，tabular figures 對齊數據欄位，克制配色保留 Illumio 品牌，grid 構圖強調資訊層級。類比：GitLab Data Viz、IBM Carbon、Oxide Console。 |
| **適用 persona** | P1 網管（主）— 表單/規則/設定高密度操作；P2 SOC（次）— 事件列表 tabular 閱讀；P5 主管（弱）— dashboard 摘要可讀性尚可 |
| **Color palette light** | base `#F8F9FA`（近白灰）／surface `#FFFFFF`／accent `#FF5500`（Illumio Orange）／success `#2D9B5E`（Safeguard Green 調亮）／warning `#C47A00`（Circuit Gold 調暗）／danger `#D93025`（Risk Red） |
| **Color palette dark** | base `#0D1117`（近黑）／surface `#161B22`／accent `#FF6B35`（Orange 微調亮）／success `#3AB86F`／warning `#E8A020`／danger `#EF4444` |
| **Typography** | heading：Space Grotesk Bold/SemiBold（offline self-host woff2，OFL），fallback `'Segoe UI', system-ui`；body：Inter Regular/Medium（offline self-host woff2，OFL），fallback `system-ui, -apple-system`；mono：JetBrains Mono（code blocks / log 輸出，offline self-host），fallback `'Cascadia Code', 'Fira Code', monospace` |
| **Iconset** | Lucide（vendor 化 SVG sprite，MIT license，offline 友善，~400 icon subset） |
| **Motion** | `--motion-fast: 120ms ease-out`（hover / focus 狀態切換）；`--motion-base: 200ms ease-out`（panel slide / tab switch）；`--motion-slow: 350ms cubic-bezier(0.4,0,0.2,1)`（modal / overlay enter）；無裝飾性動畫 |
| **Density level** | dashboard 高（row-height 36px，gap 8px）／settings 中（row-height 44px，gap 12px）／empty state 低（center layout，gap 24px） |
| **Touch radius** | 最小 tap target 40×40px（settings / form field）；table row 點擊區 36px height，側邊操作 icon 32px + 4px padding；符合 WCAG 2.5.5 |
| **Risk** | 低-中。Space Grotesk + Inter 均為主流 OFL 字型，woff2 subset 可控制在 100 KB 以內；SVG sprite 無 CDN 依賴；最大實作風險為現有 Montserrat heading 替換後的 line-height / letter-spacing 微調，影響範圍約 30–40 個 heading selector。 |

##### 候選 C — modern-saas

| 欄位 | 內容 |
|---|---|
| **描述** | Linear / Vercel / Notion 美學：大留白、低密度、圓角卡片、柔和陰影、sans-serif 單字族。Generic SaaS 工具感，缺乏 security/ops 工具個性。 |
| **適用 persona** | P5 主管（次）— 低資訊密度符合偶發瀏覽；P1 網管（弱）— 低密度與高頻操作需求衝突；P2 SOC（弱）— 缺乏終端感/緊張感不符事件分析情境 |
| **Color palette light** | base `#FFFFFF`／surface `#F5F5F5`／accent `#6366F1`（Indigo，偏離 Illumio 品牌）／success `#22C55E`／warning `#F59E0B`／danger `#EF4444` |
| **Color palette dark** | base `#09090B`／surface `#18181B`／accent `#818CF8`／success `#4ADE80`／warning `#FCD34D`／danger `#F87171` |
| **Typography** | heading + body：Inter（單字族，無 display 對比），fallback `system-ui`；mono：`monospace`（無具名 offline 字型） |
| **Iconset** | Heroicons（MIT，offline 友善 SVG sprite） |
| **Motion** | `--motion-fast: 150ms ease`；`--motion-base: 250ms ease-out`；含大量裝飾性 hover 動畫（scale / shadow lift），與操作工具場景略顯浮誇 |
| **Density level** | dashboard 低（row-height 48px，gap 16px）／settings 低-中（row-height 48px，gap 16px）／empty 低（插圖型） |
| **Touch radius** | 44×44px（充足）；`--radius-lg: 12px`（大圓角，與 Illumio 現有 8px 有落差） |
| **Risk** | 低（實作簡單），但**設計風險高**：Distinctiveness 1，與現狀無提升；且偏離 Illumio 品牌色 (Indigo 非品牌色)；若強行保留 Illumio Orange 則美學自相矛盾。不推薦。 |

##### 候選 D — dark-ops 終端感

| 欄位 | 內容 |
|---|---|
| **描述** | Bloomberg Terminal / 終端機 UI 美學：monospace 字型貫穿介面，深色底（近黑 navy）+ 細邊框 grid，數據欄位等寬對齊，scanline / noise texture 強化終端質感。系統管理員 "power tool" 個性強烈。 |
| **適用 persona** | P2 SOC（主）— 事件分析、log 審查，終端感契合工作情境；P1 網管（中）— 熟悉 CLI/終端環境，接受度高，但長時間表單操作略增視覺負擔；P5 主管（弱）— 視覺複雜度高，不適合偶發摘要閱讀 |
| **Color palette light** | （此候選以深色為主版；light 版為有限支援）base `#F0F2F5`／surface `#FFFFFF`／accent `#00C8C8`（System Cyan 調亮）／success `#1A7A4A`／warning `#B86A00`／danger `#CC2222` |
| **Color palette dark** | base `#0A0F14`（near-black navy）／surface `#111820`／accent `#00E5E5`（System Cyan 亮化）／success `#00B060`／warning `#E8A020`（Circuit Gold）／danger `#FF4040`（Risk Red 亮化）；另有 grid-line `rgba(0,200,200,0.08)` + noise overlay `url(noise.svg) opacity 0.03` |
| **Typography** | heading + 數值：JetBrains Mono Bold/Regular（offline self-host，OFL）—等寬對齊數據欄、monospace 個性強；body prose（說明段落）：Inter Regular，fallback `system-ui`；mono（log/code）：JetBrains Mono，與 heading 共用，fallback `'Cascadia Code', monospace` |
| **Iconset** | Phosphor Icons（MIT，offline SVG sprite，含 Terminal / Shield / Network 等 ops 語境 icon，風格細線與 mono 字型契合） |
| **Motion** | `--motion-fast: 100ms linear`（光標閃爍感，刻意快速）；`--motion-base: 180ms ease-out`；`--motion-slow: 300ms ease-out`；可加 `scanline-flicker` CSS animation（選用，`prefers-reduced-motion: reduce` 時關閉） |
| **Density level** | dashboard 高（row-height 32px，gap 4px，monospace 字元對齊）／settings 中（row-height 40px）／empty 低（ASCII-art 型 placeholder） |
| **Touch radius** | 最小 tap target 36px（桌面 ops tool，鍵盤優先操作情境）；需注意 WCAG 2.5.5 在觸控設備上的合規性，若有行動端需求須補 44px override |
| **Risk** | 中。JetBrains Mono 作為 UI heading 字型需驗證多語言（中文 label 仍需 CJK fallback：`'Noto Sans CJK TC', sans-serif`）；noise.svg / scanline overlay 需實測不同 DPI 螢幕渲染品質；P1 長時間 mono 閱讀疲勞需 A/B 驗證；整體 CSS 改動幅度大於 B（影響 150+ selector）。 |

---

#### Step 3 — 推薦方向

**推薦：B (industrial-editorial)**

理由：

1. **槓桿點對齊**：§3.1.3 明確指出 Distinctiveness=1 的根因是「Montserrat 兼任標題/正文，無字族對比」，B 方向以 Space Grotesk（display）× Inter（body）雙字族直接攻克此結構缺陷，Distinctiveness 可升至 2，Typography 升至 3，總分可達 15/18，突破「稱職 ops admin」定位。

2. **Persona weight P1 優先**：P1 網管為最高優先人群，其核心場景為高密度表單、規則列表、設定操作（呼應 §3.1.2 UX rubric a2 forms 弱點）。B 方向 editorial grid + tabular figures 直接強化此場景可讀性；D 方向的 monospace heading 在長時間表單場景增加視覺負擔，P1 適用性降為「中」。

3. **C1 offline 友善**：Space Grotesk + Inter + JetBrains Mono 均有 OFL 授權，woff2 subset 可 vendor 化於 `vendor/fonts/`，與 §3.1.0 a7 Vendor 化執行 plan 完全一致，不引入新 CDN 依賴。

4. **實作風險最低**：B 方向影響約 30–40 個 heading selector，CSS token 改動範圍可控；D 方向影響 150+ selector 且需驗證 CJK fallback 與多 DPI 渲染，實作複雜度顯著更高。

**保留 D 作為「SOC 深色 variant」選項**：若 P2 SOC 使用者回饋要求更強的終端感，可在 B 方向的 dark mode 中疊加 scanline overlay 與 Phosphor icon，作為 opt-in 密度層，不需全面重寫。

---

#### Step 4 — Adopted Direction Spec Sheet（B: industrial-editorial）

```css
/* ============================================================
   Illumio Ops — Industrial-Editorial Design System
   Direction: B (industrial-editorial)
   Offline strategy: all fonts self-hosted via vendor/fonts/
   Fonts: Space Grotesk (OFL), Inter (OFL), JetBrains Mono (OFL)
   Icons: Lucide SVG sprite (MIT), vendor/icons/lucide-sprite.svg
   ============================================================ */

:root {
  /* --- Color (Light) --- */
  --color-base:             #F8F9FA;   /* page background */
  --color-surface:          #FFFFFF;   /* card / panel */
  --color-surface-raised:   #F1F3F5;   /* table header / sidebar */
  --color-border:           #DEE2E6;
  --color-border-subtle:    #E9ECEF;
  --color-text-primary:     #0D1117;
  --color-text-secondary:   #495057;
  --color-text-muted:       #868E96;
  --color-accent:           #FF5500;   /* Illumio Orange */
  --color-accent-hover:     #E64D00;
  --color-accent-subtle:    rgba(255, 85, 0, 0.08);
  --color-cyan:             #00B4C8;   /* System Cyan (toned for light bg) */
  --color-signal-success:   #2D9B5E;   /* Safeguard Green */
  --color-signal-warning:   #C47A00;   /* Circuit Gold (darkened) */
  --color-signal-danger:    #D93025;   /* Risk Red */
  --color-signal-info:      #0077CC;

  /* --- Spacing --- */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;
  --space-12: 48px;

  /* --- Radius --- */
  --radius-sm: 2px;
  --radius-md: 4px;
  --radius-lg: 8px;
  --radius-pill: 9999px;

  /* --- Shadow --- */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.04);
  --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.07), 0 2px 4px rgba(0, 0, 0, 0.06);
  --shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.08), 0 4px 6px rgba(0, 0, 0, 0.05);

  /* --- Motion --- */
  --motion-fast: 120ms ease-out;   /* hover / focus state */
  --motion-base: 200ms ease-out;   /* tab switch / panel slide */
  --motion-slow: 350ms cubic-bezier(0.4, 0, 0.2, 1); /* modal / overlay */

  /* --- Typography --- */
  /* Space Grotesk: vendor/fonts/SpaceGrotesk/{Regular,Medium,SemiBold,Bold}.woff2 */
  --font-heading: 'Space Grotesk', 'Segoe UI', system-ui, -apple-system, sans-serif;
  /* Inter: vendor/fonts/Inter/{Regular,Medium,SemiBold}.woff2 */
  --font-body: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
  /* JetBrains Mono: vendor/fonts/JetBrainsMono/{Regular,Medium}.woff2 */
  --font-mono: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', monospace;

  /* Type scale (rem) */
  --text-xs:   0.75rem;   /* 12px — label / badge */
  --text-sm:   0.875rem;  /* 14px — table cell / secondary */
  --text-base: 1rem;      /* 16px — body default */
  --text-lg:   1.125rem;  /* 18px — section intro */
  --text-xl:   1.5rem;    /* 24px — card heading */
  --text-2xl:  2rem;      /* 32px — page title */
  --text-3xl:  3rem;      /* 48px — dashboard KPI (display use) */

  /* Tabular figures for numeric columns */
  --font-feature-tabular: "tnum" 1, "ss01" 1;

  /* --- Density: Dashboard (高) --- */
  --density-row-height: 36px;
  --density-gap: var(--space-2);
  --density-padding-y: var(--space-2);
  --density-padding-x: var(--space-3);

  /* --- Iconset --- */
  /* Lucide SVG sprite: vendor/icons/lucide-sprite.svg (MIT, ~400 icon subset) */
}

/* --- Dark theme overrides --- */
[data-theme="dark"] {
  --color-base:             #0D1117;
  --color-surface:          #161B22;
  --color-surface-raised:   #1C2128;
  --color-border:           #30363D;
  --color-border-subtle:    #21262D;
  --color-text-primary:     #E6EDF3;
  --color-text-secondary:   #8B949E;
  --color-text-muted:       #6E7681;
  --color-accent:           #FF6B35;   /* Orange 微調亮，深色底適讀 */
  --color-accent-hover:     #FF8555;
  --color-accent-subtle:    rgba(255, 107, 53, 0.12);
  --color-cyan:             #00C8DC;   /* System Cyan 亮化 */
  --color-signal-success:   #3AB86F;
  --color-signal-warning:   #E8A020;   /* Circuit Gold */
  --color-signal-danger:    #EF4444;
  --color-signal-info:      #3B82F6;
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.30);
  --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.35);
  --shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.40);
}

/* --- Density modifier: settings (中) --- */
[data-density="comfortable"] {
  --density-row-height: 44px;
  --density-gap: var(--space-3);
  --density-padding-y: var(--space-3);
  --density-padding-x: var(--space-4);
}

/* --- Offline font self-host @font-face stubs (填入 vendor 化後補完) ---
   vendor/fonts/SpaceGrotesk/SpaceGrotesk-{Regular,Medium,SemiBold,Bold}.woff2
   vendor/fonts/Inter/Inter-{Regular,Medium,SemiBold}.woff2
   vendor/fonts/JetBrainsMono/JetBrainsMono-{Regular,Medium}.woff2
   vendor/css/fonts.css  ← 統一 @font-face 宣告，login.html / index.html 引入此檔
   CJK fallback: 'Noto Sans CJK TC' 或系統 font-stack，不自帶（體積過大）
   --- */
```

**Token table 補充說明：**

| Token 群 | 說明 | 注意事項 |
|---|---|---|
| `--color-accent` | Illumio Orange `#FF5500` (light) / `#FF6B35` (dark) | 保留品牌色，深色版微調亮以確保對比 ≥ 4.5:1 |
| `--color-cyan` | System Cyan，用於 active tab / focus ring / badge | 非 accent 主色，作為品牌輔助色使用 |
| `--font-heading` | Space Grotesk — editorial 個性字族 | woff2 subset 約 60 KB；取代現有 Montserrat heading 用途 |
| `--font-body` | Inter — 螢幕可讀性最優之 sans | woff2 subset 約 50 KB；取代 Montserrat body 用途 |
| `--font-mono` | JetBrains Mono — log / code / KPI 數值 | 已於現有 Montserrat mono fallback chain，升為具名首選 |
| `--font-feature-tabular` | `tnum` — tabular figures | 數值欄位（dashboard KPI / table cell）開啟等寬數字 |
| `--density-*` | 三級密度：高（dashboard）/ 中（settings）/ 低（empty） | 現有 `[data-density="comfortable"]` 機制可直接擴充 |
| `--motion-fast/base/slow` | 120 / 200 / 350 ms | 無裝飾性動畫；`prefers-reduced-motion` 需全數歸零 |

**Offline self-host 執行計畫（簡表）：**

| 字型 | License | 來源 | vendor 路徑 | 估算大小 |
|---|---|---|---|---|
| Space Grotesk | OFL | `@fontsource/space-grotesk` 或 GitHub fontsource | `vendor/fonts/SpaceGrotesk/` | ~80 KB（4 字重 woff2） |
| Inter | OFL | `@fontsource/inter` | `vendor/fonts/Inter/` | ~70 KB（3 字重 woff2 subset） |
| JetBrains Mono | OFL | `@fontsource/jetbrains-mono` 或 JetBrains GitHub | `vendor/fonts/JetBrainsMono/` | ~50 KB（2 字重 woff2） |
| Lucide sprite | MIT | `lucide` npm，build SVG sprite | `vendor/icons/lucide-sprite.svg` | ~200 KB（400 icon subset） |
| **合計** | | | | **~400 KB（解壓縮）；壓縮後 ~130 KB** |

### §6.2 Report + Email direction

#### Step 1 — 4 候選評分（Typography 高權重 / Motion 最低）

評分依據：C.5 現況基線 HTML=12/18、PDF=6/15（PDF Backgrounds 0/3 為 critical gap）；C.6 Email 跨 client 2/8 fail。各候選評估可達成分數，并考量 P5 主管收件人為 Report/Email 衝突優先 persona（§1.2）、C1 offline 硬約束（無 CDN webfont 於 Email）。

維度滿分各 3，Motion 對 Report/Email 不適用故填 N/A（最低權重 = 不計分）。

| 候選 | Typography | Color | Spatial | Backgrounds | Distinct | 適用 P5 | **合計** |
|---|:---:|:---:|:---:|:---:|:---:|---|:---:|
| A. 維持現狀 | 2 | 2 | 3 | 0(PDF) | 1 | 低（引 §3.3.3；PDF Backgrounds 0/3 結構缺陷） | **8** |
| B. editorial-magazine | 3 | 3 | 3 | 2 | 2 | **高**（商業報告閱讀體驗 + 主管閱讀節奏） | **13** |
| C. data-journalism | 3 | 3 | 3 | 2 | 2 | 中（圖表密度高，主管須花時間解讀） | **13** |
| D. corporate-formal | 3 | 2 | 3 | 2 | 1 | 高（合規/法務閱讀清單，低 Distinctiveness） | **11** |

評分說明：
- **A. 維持現狀**：PDF Backgrounds 0/3（封面/分隔頁/頁首頁尾均無印刷背景色），與 §3.3.3 評估一致；Typography 2 沿用現有 sans 無 display 對比；Distinct 1 報告毫無個性，等同系統預設 HTML 輸出。
- **B. editorial-magazine**：Source Serif 4（印刷款 Serif，heading）× Inter（body）形成強烈字族對比，帶來商業報告「出版物感」；Color 3 沿用 signal 語義色票；Backgrounds 2（cover band + section divider 可有色彩背景，PDF 印刷友善）；Distinct 2（有明確 editorial 工具個性而不過度裝飾）；適用 P5 高——執行層閱讀節奏在 editorial 排版下最自然。
- **C. data-journalism**：與 B 同分（13/15），差異在 P5 適用評為「中」：圖表即首要載體，非圖表區文字仍是 editorial，但主管須投入更多解讀每張圖的認知成本；若報告以圖表為主（KPI dashboard export）則 C 可反超 B。
- **D. corporate-formal**：Typography 3（serif）；Backgrounds 2（可有色封面）；但 Color 2（全色票走低飽和灰藍，signal 色變淡，verdicts 鮮明度下滑）；Distinct 1（套公司模板感，與 A 接近，無個性提升）。合規場景適用，但非最佳選擇。

---

#### Step 2 — B / C / D 候選完整 Spec Sheet

##### 候選 B — editorial-magazine

| 欄位 | 內容 |
|---|---|
| **描述** | 商業出版物排版：Serif display 字族 × sans body 雙層對比，寬版心 + 呼吸感留白，cover page 色帶呈現 verdict，章節間 section divider 有輕量色塊背景。類比：Economist / McKinsey report / IPCC chapter。 |
| **適用 persona** | P5 主管（主）— 執行摘要快速掃描；P2 SOC（次）— 技術細節章節仍 sans-serif body 閱讀舒適；合規（次）— editorial restraint 符合正式文件期望 |
| **Print type scale (PDF)** | Title 36pt / Subtitle 20pt / H1 28pt / H2 22pt / H3 18pt / body 11pt / table 10pt / caption 9pt / @page header/footer 8pt |
| **Print fonts** | heading：Source Serif 4 SemiBold/Regular（OFL，`vendor/fonts/SourceSerif4/`，woff2 + 嵌入 PDF）；body：Inter Regular/Medium（共用 GUI vendor，`vendor/fonts/Inter/`）；table figures：JetBrains Mono Regular，`font-feature-settings: "tnum" 1`（等寬對齊數值欄）；fallback（無 embed）：`Georgia, 'Times New Roman', serif` |
| **Cover page 設計** | Title (36pt, Source Serif 4 Bold, white) / Subtitle (20pt, white 80% opacity) / Date + Org (13pt, white 60% opacity, tabular date format) 置於左上三分之二；右下 Verdict summary band (10px padding, signal 色依結論填色：#2D9B5E=Pass / #C47A00=Warning / #D93025=Fail)，band 內 verdict label (12pt Inter SemiBold, uppercase, white)；封面底色 `#0D1117`（與 GUI dark base 一致），非全白封面 |
| **章節節奏** | H1 前 48pt / 後 24pt；H2 前 32pt / 後 16pt；H3 前 24pt / 後 12pt；paragraph spacing 14pt；section divider：4px top border `--color-accent` (#FF5500) + 12pt 空白後接 H2 |
| **Tabular figures** | `font-feature-settings: "tnum" 1, "ss01" 1`；數值欄 text-align: right；column header text-align: right when numeric；JetBrains Mono 用於 table body 數值，Inter 用於 table 欄位名稱 |
| **圖表配色** | 語義色票 (signal): success `#2D9B5E` / warning `#C47A00` / danger `#D93025` / info `#0077CC`；中性序列（非語義）：5-step `#DEE2E6→#868E96→#495057→#212529→#0D1117`；Colorblind-safe 驗證：所有 signal 色通過 Deuteranopia + Protanopia 模擬（signal 不依賴 hue 唯一性，以明度差距 ≥ 40% 補強）；PDF 印刷：CMYK 近似注記於 spec |
| **@page 規則（CSS/PDF）** | `@page { margin: 25mm 20mm 30mm 20mm; }` 含 header（章節名 8pt Inter，left）+ footer（頁碼 8pt Inter，right；`content: counter(page) " / " counter(pages)`）；封面頁 `@page :first { margin: 0; }` 全出血 |
| **Email 子集處理** | **刪除**：`@font-face`（webfont）、`display: grid`、`display: flex`、`position: absolute/fixed`、`background: linear-gradient`、`border-radius > 4px`（部分 client 不支援）；**保留**：色票 primitive `--color-signal-*`（轉 inline style `color: #2D9B5E` 等）、table-based layout（`<table role="presentation">`）、inline CSS `font-family: Georgia, 'Times New Roman', serif`（email serif fallback）、signal verdict badge 以 `<td>` + inline bgcolor 實現 |
| **Email HTML 結構** | `<table>` wrapper (max-width 680px) → preheader (display:none, 100 char) → header band (bgcolor=#0D1117, white logo) → body table → verdict band (bgcolor per signal) → CTA button (bulletproof: `<a>` + inline border + bgcolor) → footer (muted, 8px font, unsubscribe) |
| **Risk** | 低-中。Source Serif 4 為 Google Fonts OFL，woff2 subset 含 Latin + 基礎數字約 80 KB；PDF 內嵌字型 subset 可由 WeasyPrint / Puppeteer 自動完成；Email subset 無 webfont 依賴，Outlook 2016–2023 + Apple Mail + Gmail Web 均可安全渲染 |

##### 候選 C — data-journalism

| 欄位 | 內容 |
|---|---|
| **描述** | 圖表為第一公民：寬幅圖表佔版面 60%+，文字為圖表注解而非主體；帶狀背景色區塊分隔章節；condensed sans 字族強調資訊密度。類比：The Guardian Data / FiveThirtyEight / Our World in Data 報告頁。 |
| **適用 persona** | P5 主管（中）— 快速掃描 chart，閱讀 takeaway caption；技術人員（次）— 認可圖表細節；合規（弱）— 高圖表密度不符合規文件期望 |
| **Print type scale (PDF)** | Title 34pt / H1 26pt / H2 20pt / H3 16pt / body 10.5pt / caption 9pt（caption 比 body 小以示輔助角色）/ table 9.5pt |
| **Print fonts** | heading：DM Sans SemiBold/Bold（OFL，condensed感，`vendor/fonts/DMSans/`）；body + caption：Inter Regular（共用）；chart label：Inter Medium 8–9pt；table figures：JetBrains Mono，`"tnum" 1` |
| **Cover page 設計** | 全版大型圖表（summary spider/bar chart）置封面右側 65% 寬；左側標題區 Title (30pt, DM Sans Bold, dark) / Date / Org；verdict band 橫跨底部全寬（高 40px），依 signal 色填色 |
| **章節節奏** | 章節以色帶背景分隔（`background: #F1F3F5` 淺灰 section card）；H1 前 40pt / 後 20pt；圖表與文字交替排列，圖前 20pt / 圖後 16pt / caption 後 8pt；paragraph spacing 12pt |
| **Tabular figures** | 同 B（`"tnum" 1` + JetBrains Mono for table figures）；chart tick label 另用 Inter 9pt tabular |
| **圖表配色** | 同 B signal 色票（語義一致性）；另有 category 色板：7-step accessible（Tableau 10 subset，無紅綠相鄰）；圖表背景 `#F8F9FA`，grid line `#DEE2E6`；Print 去 grid line 改 tick only |
| **@page 規則（CSS/PDF）** | 同 B margin；圖表允許跨頁（`page-break-inside: avoid` 僅對 caption + figure 組合）；每章首頁可有 section color band |
| **Email 子集處理** | **刪除**：同 B（webfont, flex/grid, gradient）；**注意**：全版大圖 Email 無法 render，改以 verdict table（文字版）替代圖表；保留 signal badge inline style；CTA bulletproof 同 B |
| **Email HTML 結構** | 同 B wrapper；圖表位置改為 verdict summary table（3 欄：指標 / 得分 / 狀態 badge）；无圖表 fallback `<img>` alt text 完整 |
| **Risk** | 中。圖表主導版面需圖表函式庫（如 Vega-Lite / matplotlib）支援 PDF 輸出格式；Email 圖表完全降級為 table，須維護兩套渲染路徑；DM Sans 需額外 vendor 化 |

##### 候選 D — corporate-formal

| 欄位 | 內容 |
|---|---|
| **描述** | 傳統企業/合規報告格式：serif 標題、內縮段落、保守配色、全頁 logo watermark、嚴格的 header/footer 規範。類比：PwC 合規報告 / Big4 風險報告格式。 |
| **適用 persona** | 合規/法務（主）— 符合傳統文件格式期望；P5 主管（次）— 熟悉但無驚喜；技術人員（弱）— 格式過重，資訊密度不足 |
| **Print type scale (PDF)** | Title 32pt / H1 24pt / H2 20pt / H3 16pt / body 11pt / table 10pt / caption 9pt（保守，與 Word 預設接近）|
| **Print fonts** | heading：Garamond / Source Serif 4（合規場景偏 Garamond，若 vendor 化難度高則降回 Source Serif 4）；body：Inter Regular；table：Inter Regular 10pt（不用 mono，合規文件偏向全 sans-serif 數字）|
| **Cover page 設計** | 上方公司 logo 置中；Title 居中 (32pt serif)；版本/機密等級 label（10pt，灰色）；Date + 委託機構底部居中；底部細線 (`1px #DEE2E6`) 分隔頁尾；封面底色全白；無 verdict band（verdict 移至 Executive Summary 第一段）|
| **章節節奏** | H1 前 36pt / 後 18pt；H2 前 24pt / 後 12pt；首段不縮排，後續段落首行縮排 1em；paragraph spacing 14pt；頁眉頁腳格式嚴格：左頁眉 = 章節名，右頁眉 = 文件編號，左頁腳 = 機密等級，右頁腳 = 頁碼 |
| **Tabular figures** | `"tnum" 1`，但不使用 JetBrains Mono（合規文件避免 monospace 數字），保持 serif/sans tabular figures |
| **圖表配色** | 低飽和度版本：success `#4A9E6B`（調淡）/ warning `#B8860B`（深金）/ danger `#C0392B`（暗紅）/ info `#2980B9`（暗藍）；避免鮮豔色票，符合傳統印刷期望 |
| **@page 規則（CSS/PDF）** | `@page { margin: 30mm 25mm 30mm 25mm; }`（更大邊距，合規文件標準）；header 左 = 章節 / 右 = 文件號；footer 左 = 機密等級 / 右 = 頁碼 |
| **Email 子集處理** | **刪除**：同 B；**保留**：保守 inline styles，signal 色用調淡版本；CTA button 改為純文字連結（合規 email 偏向低 HTML 複雜度）|
| **Email HTML 結構** | 純文字優先 multipart；HTML 部分為保守 `<table>` layout，max-width 600px，無色帶背景，verdict 以粗體文字 + 方括號標示 [PASS] / [WARNING] / [FAIL] |
| **Risk** | 低（實作簡單，保守設計）；但**設計風險高**：Distinct 1，與 A 現況無差異感；signal 色調淡後 accessibility contrast 需重新驗證（danger `#C0392B` 在白底 contrast ratio 約 5.8:1，勉強通過 WCAG AA）|

---

#### Step 3 — 推薦方向

**推薦：B (editorial-magazine)**

理由：

1. **直接修復 C.5 PDF Backgrounds 0/3 critical gap**：B 方向的 cover page 設計帶有深色底色塊（`#0D1117`）+ verdict signal band，section divider 有 accent border，@page header/footer 完整定義；這三處直接對應 PDF Backgrounds 三個失分點，可將 Backgrounds 分數從 0/3 拉至 2/3（滿分需測試印刷出血）。

2. **P5 主管閱讀節奏最契合**：editorial-magazine 排版（Serif heading × sans body 雙字族、呼吸感留白、chapter rhythm）是商業出版物的成熟 UX pattern，P5 主管的閱讀習慣（Executive Summary → verdict → 關鍵圖表）可在 B 方向獲得最流暢的視覺引導；C 方向圖表密度高但非所有主管願意解讀每圖，D 方向無 Distinctiveness 提升。

3. **與 D.1 GUI 方向 B (industrial-editorial) 和諧**：GUI 選 B（Space Grotesk display × Inter body）；Report 選 editorial-magazine（Source Serif 4 heading × Inter body）；兩套均以 Inter 為 body，signal 色票完全共享（§6.3），且均走「克制 editorial + 資訊密度」路線，視覺語言一致而不相同（GUI 用 sans display，Report 用 serif heading，媒介適配正確）。

4. **C1 offline 約束最友善**：Source Serif 4 + Inter + JetBrains Mono 均 OFL，woff2 subset 已在 GUI vendor 計畫中（Inter + JetBrains Mono 共用）；Email subset 完全無 webfont 依賴，不增加 C1 風險。

5. **Email cross-client 修復 C.6 2/8 fail**：B 的 Email subset 明確刪除 flex/grid/webfont/gradient，改採 `<table role="presentation">` layout + inline style，bulletproof CTA button，直接攻克 Outlook 2016/2019 渲染失敗的根因。

---

#### Step 4 — Adopted Direction Spec Sheet（B: editorial-magazine）

```css
/* ============================================================
   Illumio Ops — Report + Email Design System
   Direction: B (editorial-magazine)
   Scope: HTML report / PDF @print / Email HTML subset
   Offline strategy: all fonts self-hosted via vendor/fonts/
   Fonts: Source Serif 4 (OFL), Inter (OFL, shared w/ GUI),
          JetBrains Mono (OFL, shared w/ GUI)
   ============================================================ */

/* ── Print / PDF 專用 type scale ─────────────────────────── */
/* 注意：pt 單位用於 @media print 與 @page 規則；
   HTML preview 以 rem 對應（1pt ≈ 1.333px）               */

:root {
  /* --- Print fonts --- */
  /* Source Serif 4: vendor/fonts/SourceSerif4/{Regular,SemiBold,Bold}.woff2 */
  --report-font-heading: 'Source Serif 4', Georgia, 'Times New Roman', serif;
  /* Inter: shared with GUI, vendor/fonts/Inter/{Regular,Medium,SemiBold}.woff2 */
  --report-font-body: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
  /* JetBrains Mono: shared with GUI, vendor/fonts/JetBrainsMono/{Regular,Medium}.woff2 */
  --report-font-mono: 'JetBrains Mono', 'Cascadia Code', 'Courier New', monospace;

  /* --- Signal color tokens (shared primitives with GUI §6.1) --- */
  --report-color-signal-success:  #2D9B5E;   /* Safeguard Green */
  --report-color-signal-warning:  #C47A00;   /* Circuit Gold (darkened) */
  --report-color-signal-danger:   #D93025;   /* Risk Red */
  --report-color-signal-info:     #0077CC;
  --report-color-accent:          #FF5500;   /* Illumio Orange */
  --report-color-base:            #F8F9FA;
  --report-color-surface:         #FFFFFF;
  --report-color-text-primary:    #0D1117;
  --report-color-text-secondary:  #495057;
  --report-color-text-muted:      #868E96;
  --report-color-border:          #DEE2E6;
  --report-color-cover-bg:        #0D1117;   /* cover page dark background */

  /* --- Tabular figures --- */
  --report-font-feature-tabular: "tnum" 1, "ss01" 1;
}

/* ── @page rules (PDF / WeasyPrint / Puppeteer) ─────────── */
@page {
  size: A4;
  margin: 25mm 20mm 30mm 20mm;

  @top-left {
    content: string(chapter-title);
    font-family: var(--report-font-body);
    font-size: 8pt;
    color: #868E96;
  }
  @top-right {
    content: "ILLUMIO OPS ASSESSMENT";
    font-family: var(--report-font-body);
    font-size: 8pt;
    color: #868E96;
    letter-spacing: 0.05em;
  }
  @bottom-right {
    content: counter(page) " / " counter(pages);
    font-family: var(--report-font-body);
    font-size: 8pt;
    color: #868E96;
    font-feature-settings: "tnum" 1;
  }
}

/* Cover page: full-bleed, no header/footer */
@page :first {
  margin: 0;
  @top-left { content: none; }
  @top-right { content: none; }
  @bottom-right { content: none; }
}

/* ── Cover page layout ──────────────────────────────────── */
.report-cover {
  background: var(--report-color-cover-bg);   /* #0D1117 */
  min-height: 100vh;                           /* full A4 page */
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 60pt 50pt 0 50pt;
  color: #FFFFFF;
}

.report-cover__title {
  font-family: var(--report-font-heading);
  font-size: 36pt;
  font-weight: 700;
  line-height: 1.15;
  color: #FFFFFF;
  margin: 0 0 16pt 0;
  max-width: 70%;
}

.report-cover__subtitle {
  font-family: var(--report-font-heading);
  font-size: 20pt;
  font-weight: 400;
  color: rgba(255,255,255,0.80);
  margin: 0 0 32pt 0;
}

.report-cover__meta {
  font-family: var(--report-font-body);
  font-size: 13pt;
  color: rgba(255,255,255,0.60);
  font-feature-settings: "tnum" 1;
  margin: 0;
  /* format: "2026-05-06 · Illumio Inc." */
}

/* Verdict band — bottom of cover page */
.report-cover__verdict-band {
  margin-top: auto;
  padding: 14pt 50pt;
  /* bgcolor set inline per verdict: success/warning/danger */
  display: flex;
  align-items: center;
  gap: 12pt;
}

.report-cover__verdict-band--pass    { background: #2D9B5E; }
.report-cover__verdict-band--warning { background: #C47A00; }
.report-cover__verdict-band--fail    { background: #D93025; }

.report-cover__verdict-label {
  font-family: var(--report-font-body);
  font-size: 12pt;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #FFFFFF;
}

/* ── Type scale — body / sections ───────────────────────── */
/* Print pt sizes; HTML preview uses rem approximation */

.report-body h1 {        /* 28pt */
  font-family: var(--report-font-heading);
  font-size: 2.333rem;   /* ≈28pt */
  font-weight: 600;
  margin: 48pt 0 24pt 0;
  border-top: 4px solid var(--report-color-accent);
  padding-top: 12pt;
  string-set: chapter-title content();   /* for @page header */
  page-break-after: avoid;
}

.report-body h2 {        /* 22pt */
  font-family: var(--report-font-heading);
  font-size: 1.833rem;   /* ≈22pt */
  font-weight: 600;
  margin: 32pt 0 16pt 0;
  page-break-after: avoid;
}

.report-body h3 {        /* 18pt */
  font-family: var(--report-font-heading);
  font-size: 1.5rem;     /* ≈18pt */
  font-weight: 400;      /* regular weight for H3 */
  margin: 24pt 0 12pt 0;
  page-break-after: avoid;
}

.report-body p {
  font-family: var(--report-font-body);
  font-size: 0.917rem;   /* ≈11pt */
  line-height: 1.65;
  color: var(--report-color-text-primary);
  margin: 0 0 14pt 0;
}

/* ── Table styles ────────────────────────────────────────── */
.report-table {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--report-font-body);
  font-size: 0.833rem;    /* ≈10pt */
  page-break-inside: avoid;
}

.report-table th {
  font-family: var(--report-font-body);
  font-size: 0.833rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: var(--report-color-cover-bg);
  color: #FFFFFF;
  padding: 8pt 10pt;
  border: none;
}

.report-table td {
  padding: 7pt 10pt;
  border-bottom: 1px solid var(--report-color-border);
  vertical-align: top;
}

/* Numeric columns: tabular figures, right-align */
.report-table td.num,
.report-table th.num {
  font-family: var(--report-font-mono);
  font-feature-settings: "tnum" 1;
  text-align: right;
}

/* Verdict badge in table */
.verdict-badge {
  display: inline-block;
  padding: 2pt 6pt;
  border-radius: 2px;
  font-family: var(--report-font-body);
  font-size: 0.75rem;    /* ≈9pt */
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #FFFFFF;
}
.verdict-badge--pass    { background: var(--report-color-signal-success); }
.verdict-badge--warning { background: var(--report-color-signal-warning); }
.verdict-badge--fail    { background: var(--report-color-signal-danger);  }

/* Caption */
.report-caption {
  font-family: var(--report-font-body);
  font-size: 0.75rem;    /* ≈9pt */
  color: var(--report-color-text-muted);
  margin: 6pt 0 0 0;
  font-style: italic;
}

/* ── Email subset CSS (inline only, no @font-face) ────────── */
/*
  Rules for Email HTML generation:
  1. Convert all above tokens to inline style attributes.
  2. REMOVE: @font-face, display:flex, display:grid,
             position:absolute/fixed, linear-gradient,
             border-radius > 4px, CSS custom properties.
  3. KEEP:   Table-based layout, inline bgcolor, inline color,
             signal color hex values (#2D9B5E / #C47A00 / #D93025),
             font-family stack ending in serif/sans-serif.
  4. Email font-family: Georgia,'Times New Roman',serif (heading)
                        Arial,Helvetica,sans-serif (body)
  5. Max-width wrapper: <table width="680" role="presentation">
  6. Verdict band: <td bgcolor="#2D9B5E"> (bulletproof bgcolor attr)
  7. CTA button:
       <a href="{url}"
          style="display:inline-block;padding:10px 24px;
                 background:#FF5500;color:#ffffff;
                 font-family:Arial,sans-serif;font-size:14px;
                 font-weight:600;text-decoration:none;
                 border:2px solid #FF5500;border-radius:4px;">
         View Full Report
       </a>

  Email HTML structure:
  <table width="680" role="presentation" cellpadding="0" cellspacing="0" border="0">
    <tr><td><!-- preheader (display:none, max 100 chars) --></td></tr>
    <tr><td bgcolor="#0D1117"><!-- header: logo --></td></tr>
    <tr><td><!-- body: verdict summary table --></td></tr>
    <tr><td bgcolor="{signal_color}"><!-- verdict band --></td></tr>
    <tr><td><!-- CTA button row --></td></tr>
    <tr><td><!-- footer: muted, 12px, unsubscribe --></td></tr>
  </table>

  Tested clients per C.6 fix target:
  - Outlook 2016/2019 (Windows): bgcolor attr + table layout = safe
  - Gmail Web: inline style = safe
  - Apple Mail: safe
  - Mobile Gmail/iOS Mail: safe
*/
```

**Adopted Spec Sheet 補充說明：**

| 項目 | 說明 | 與 GUI B 方向關係 |
|---|---|---|
| `--report-font-heading` | Source Serif 4（印刷 Serif）| GUI 用 Space Grotesk（screen display sans）；媒介適配差異，**intentional** |
| `--report-font-body` | Inter（共用）| **共用** GUI `--font-body`，vendor 路徑相同 |
| `--report-font-mono` | JetBrains Mono（共用）| **共用** GUI `--font-mono`，vendor 路徑相同 |
| `--report-color-signal-*` | 四色 signal 語義色票 | **完全共用** GUI signal tokens（#2D9B5E / #C47A00 / #D93025 / #0077CC）→ §6.3 共享 primitive |
| `--report-color-cover-bg` | `#0D1117`（Cover 深底色）| 與 GUI dark mode base 相同值，視覺語言延伸 |
| @page header/footer | 8pt Inter，頁碼 tnum | PDF only，GUI 無對應 |
| Cover verdict band | 依 signal 色 inline bgcolor | Email 以 `bgcolor` attr 實現 bulletproof |
| Email font stack | `Georgia,...,serif` / `Arial,...,sans-serif` | 無 @font-face，offline + cross-client safe |

**Offline vendor 計畫（Report 新增部分）：**

| 字型 | License | 來源 | vendor 路徑 | 估算大小 |
|---|---|---|---|---|
| Source Serif 4 | OFL | Google Fonts / `@fontsource/source-serif-4` | `vendor/fonts/SourceSerif4/` | ~90 KB（3 字重 woff2 Latin subset） |
| Inter | OFL | 共用 GUI plan | `vendor/fonts/Inter/`（已列）| — (已計) |
| JetBrains Mono | OFL | 共用 GUI plan | `vendor/fonts/JetBrainsMono/`（已列）| — (已計) |
| **Report 新增合計** | | | | **~90 KB** |

### §6.3 跨兩套的共享 primitive（OQ-7 default）

##### Decision (OQ-7 default)

**共享**：色票 signal primitives（`--color-signal-success/warning/danger/info`）— 跨 surface 認知一致性
**分開**：type-scale（字體大小階梯）+ spacing-scale（間距階梯）— 媒介物理特性差異

**理由：**
判定色（Allowed/Blocked/Potentially-Blocked）在 GUI badge、Report verdict cell、Email status pill 三處必須眼睛識別一致——Safeguard Green 就是「允許」，Risk Red 就是「封鎖」，不允許任何 surface 自行詮釋。共享 signal primitive 是零成本的認知一致性保證，也消除了未來「GUI 綠 ≠ Report 綠」的 QA 問題。

type-scale 各自有其需求：GUI 以 4px grid、螢幕 pixel density 驅動（14–36px），Report 以 CSS `@page` print pt 單位驅動（10–36pt），Email 無法依賴 webfont 因此退回 system stack 並固定 px；三套 scale 若強制共享反而需要大量 `@media print` 覆蓋，維護成本升高。spacing-scale 同理：GUI 高密度 4px baseline grid，Report editorial 8px baseline grid，Email table-cell padding 在各 client 渲染不一，各自定義才能精確控制。

##### 共享色票表（GUI / Report+PDF / Email）

| Token | GUI value | Report+PDF value | Email value (inline) |
|---|---|---|---|
| `--color-signal-success` | `#2D9B5E` (Safeguard Green) | `#2D9B5E` (same) | `style="background:#2D9B5E"` + `bgcolor="#2D9B5E"` |
| `--color-signal-warning` | `#C47A00` (Circuit Gold) | `#C47A00` (same) | `style="background:#C47A00"` + `bgcolor="#C47A00"` |
| `--color-signal-danger` | `#D93025` (Risk Red) | `#D93025` (same) | `style="background:#D93025"` + `bgcolor="#D93025"` |
| `--color-signal-info` | `#0077CC` (System Blue) | `#0077CC` (same) | `style="background:#0077CC"` + `bgcolor="#0077CC"` |
| `--color-base` | `#F8F9FA` | `#F8F9FA` | `bgcolor="#F8F9FA"` |
| `--color-surface` | `#FFFFFF` | `#FFFFFF` | `bgcolor="#FFFFFF"` |
| `--color-text-primary` | `#0D1117` | `#0D1117` | `style="color:#0D1117"` |

> **注**：Report CSS 前綴為 `--report-color-signal-*`，值與 GUI `--color-signal-*` 完全相同；Email 無 CSS custom property，一律 inline hex。

##### 用途映射範例

| Verdict / state | `--signal-*` token | 例：GUI badge | 例：Report verdict cell | 例：Email status pill |
|---|---|---|---|---|
| Allowed | `success` (`#2D9B5E`) | green badge + ✓ icon | green cell + ✓ icon + text "Allowed" | `bgcolor="#2D9B5E"` pill，白字 "Allowed" |
| Blocked | `danger` (`#D93025`) | red badge + ✗ icon | red cell + ✗ icon + text "Blocked" | `bgcolor="#D93025"` pill，白字 "Blocked" |
| Potentially-Blocked | `warning` (`#C47A00`) | amber badge + ⚠ icon | amber cell + text "Potentially Blocked" | `bgcolor="#C47A00"` pill，白字 "Potentially Blocked" |
| Info / metadata | `info` (`#0077CC`) | blue badge + ℹ icon | blue cell + text | `bgcolor="#0077CC"` pill，白字 |

##### Token 命名 contract

```
GUI:         CSS custom property  --color-signal-{success|warning|danger|info}
Report HTML: CSS custom property  --report-color-signal-{success|warning|danger|info}  (值 = GUI 值)
Report PDF:  同 Report HTML（WeasyPrint / Puppeteer 讀 CSS）
Email:       inline style="background:<hex>"  AND  bgcolor="<hex>"  attribute（Outlook fallback）
```

**Email 雙軌原則**：inline CSS 供現代 client（Gmail web, Apple Mail, Outlook 2019+），`bgcolor` attr 供 Outlook 2007-2016（Word HTML engine 忽略 inline `background-color` 但讀 `bgcolor`）。兩者 hex 必須一致，不得差異。

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
