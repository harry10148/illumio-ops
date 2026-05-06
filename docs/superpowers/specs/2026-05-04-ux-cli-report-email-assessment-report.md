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
