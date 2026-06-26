# Illumio PCE Ops — UI/UX 改善計畫與排版重構提案

| 項目 | 內容 |
|---|---|
| 文件 | UI/UX 改善計畫 v1 |
| 立基 | 2026-05-14 UX Review（共 35+ 個發現、66 張截圖） |
| 範圍 | WebGUI + CLI + 報表 HTML |
| 配套文件 | [UX_Review.md](./UX_Review.md) |

> **核心立場**：目前 UI 不是「壞」，是「不一致」。問題不在缺功能，而在於設計決策散落、design token 沒抽出、i18n 機械式套用。這份改善計畫優先處理「導致用戶誤判」的問題，其次是「拖累專業度」的細節，最後才談「視覺重塑」。

---

## Part A — 改善計畫（分階段）

### Phase 0 — 即刻可做（總 1-3 個工作日）

零風險、無需設計討論、純 bug fix 與字串修正。

| # | 任務 | 動到的檔案 | 預估 |
|---|---|---|---|
| 0.1 | 修 `#bulk-bar` 在 `selected_count === 0` 時隱藏 | `src/static/js/dashboard.js` (or wherever bulk-bar lives) | 30 min |
| 0.2 | 報表 dialog `<select>` 「報表語言」預設讀 `config.language` 而非寫死 `en` | `src/static/js/reports.js`、`src/gui/routes/reports.py` | 1 h |
| 0.3 | 「截切」→「擷取」、「補抓」→「補抓取」、「廠商對齊格式」→ 重譯為「按警示樣板格式」 | `src/i18n/zh_tw.json`（grep `截切`/`補抓`/`廠商對齊`） | 30 min |
| 0.4 | 新增「確認新密碼」欄位 + 客端驗證 | `src/static/js/settings.js`（Web 安全設定區塊） | 1 h |
| 0.5 | 「Renew Now」/「Traffic Filters (optional)」/「Run a query to view real-time traffic anomalies.」 i18n 補譯 | `src/i18n/{en,zh_tw}.json` + 對應 JS | 1 h |
| 0.6 | CLI `--json` flag dispatcher bug：`_CLICK_SUBCOMMANDS` 加入 `--json`/`-q`/`-v`，讓 click 不要 fall back 到 argparse | `src/cli/root.py`（或 `illumio-ops.py` dispatch 邏輯） | 2 h |
| 0.7 | CLI bare-call menu「Manage PCE 快取」/「Manage SIEM 轉發器」→「管理 PCE 快取」/「管理 SIEM 轉發器」 | `src/cli/shell.py` 或對應 menu 模組 | 15 min |
| 0.8 | CLI `siem status` 與 WebUI 不一致 — 確認兩者讀同一份 config / DB | `src/cli/siem.py`（檢查 connection string） | 1 h debug |
| 0.9 | 「Renew Now」按鈕 i18n + Days Remaining 格式化（`>365 → 顯示年`） | `src/static/js/settings.js` (TLS section) | 30 min |
| 0.10 | Header「停止」按鈕 → 加 confirmation modal | `src/static/js/header.js`（或 admin.js） | 30 min |

**🎯 完成 Phase 0 即解決所有 🔴 P0 中可直接 fix 的部分。**

---

### Phase 1 — P0 結構修正（1-2 週）

需要設計取捨，但範圍局部。

#### 1.1 設定頁拆 sub-tab（最大痛點）

目前：1 個垂直 form ≈ 3500 px、7 個區塊
目標：4 個 sub-tab + 內部 anchor

```
[ PCE 連線 ]   [ 通知通道 ]   [ 介面 / 報表 ]   [ 安全 ]
   ↑             ↑              ↑                ↑
   API 狀態      LINE          時區/語言         密碼
   PCE 設定檔    Email         主題              IP 白名單
   API 連線      Webhook       報表輸出          TLS / HTTPS
                                                 CSR / 匯入
```

實作：在 `src/templates/index.html` 設定區段內加 sub-tab nav；route 不變（仍是 settings tab），只切換內部 panel。儲存按鈕仍維持 sticky 但加上 hint「儲存：PCE 連線 + 通知通道」（顯示影響範圍）。

| 任務 | 預估 |
|---|---|
| 設計 sub-tab navigation 與動畫 | 1 d |
| 重新組織 HTML，每個 sub-section 加 `id` anchor | 1 d |
| sticky save button + 「未儲存變更」指示 | 1 d |
| 拆 i18n keys（每個 sub-tab 一組） | 0.5 d |

#### 1.2 Dashboard mini KPI 全面在地化稽核

12 個小卡片 + 5 列建議的中文翻譯，至少 30 個 string 需要找 PM/在地化負責人重審。

| 任務 | 預估 |
|---|---|
| 把所有可疑翻譯列表（建議自動掃 `_zh_tw.json` 與英文 key 比對） | 0.5 d |
| 對照 Illumio 官方術語表（Anomaly Score / Visibility / Enforcement / Boundary） | 0.5 d |
| 重譯 + review | 1-2 d |

#### 1.3 顏色語意 token 系統

```css
:root {
  /* Brand */
  --color-brand:      #FF5500;   /* Illumio Orange — primary actions */
  --color-brand-h:    #E54D00;
  /* Semantic — status */
  --color-success:    #16A34A;
  --color-success-bg: #DCFCE7;
  --color-warning:    #F59E0B;
  --color-warning-bg: #FEF3C7;
  --color-danger:     #BE122F;
  --color-danger-bg:  #FEE2E2;
  --color-info:       #2563EB;
  --color-info-bg:    #DBEAFE;
  /* Neutral */
  --color-text:       #313638;
  --color-muted:      #6F7274;
  --color-border:     #D6D7D7;
  --color-bg-page:    #F7F4EE;
  --color-bg-card:    #FFFFFF;
}
```

**重新著色清單**：
- KPI cards「健康摘要: 0」→ 綠 (`--color-success`)
- KPI cards「事件查詢: OK」→ 綠
- SIEM 「失敗」 column 頂線 → 紅 (`--color-danger`)
- 報表「52.4/100 (D)」 → 評分 D 用紅色 (`--color-danger`)，A/B 用綠，C 用橘
- 報表 Modal CTA「產生」按鈕 → 改回品牌橘色

| 任務 | 預估 |
|---|---|
| 定義 token CSS variable 並全站套用 | 1 d |
| 重著色（grep 所有 inline color） | 1 d |
| 一頁 visual diff 截圖比對 | 0.5 d |

#### 1.4 Header bar 重設計

目前：
```
[Logo] [https://pce.lab.local:8443] 規則數: 17 排程數: 3 載入時間: 現在 | 佈景 ▼ 密度 ▼ [模組日誌] [停止]
```

提案：
```
[Logo Illumio PCE Ops]              [● pce.lab.local | 規則 17 · 排程 3 · 30s前]      [⚙️ 佈景] [☰ 操作 ▼]
                                                                                              ├── 模組日誌
                                                                                              ├── 變更密度
                                                                                              └── 停止 daemon (危險)
```

- URL → 改為小 chip 樣式（不像 address bar）
- 統計數字壓縮為一行
- 「停止」收進 menu 並加紅色警告
- 佈景/密度 改為單一 settings menu

---

### Phase 2 — Design System 基礎（2-4 週）

不解決單點，而是建立可長期維護的基礎。

#### 2.1 Spacing / Typography token

```css
:root {
  /* Space — 4px grid */
  --space-1: 4px;   --space-2: 8px;   --space-3: 12px;
  --space-4: 16px;  --space-5: 20px;  --space-6: 24px;
  --space-8: 32px;  --space-10: 40px; --space-12: 48px;

  /* Type scale */
  --text-xs:   12px / 16px;
  --text-sm:   13px / 20px;
  --text-base: 14px / 22px;
  --text-md:   16px / 24px;
  --text-lg:   18px / 28px;
  --text-xl:   22px / 32px;
  --text-2xl:  28px / 36px;

  /* Radii */
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;

  /* Shadows */
  --shadow-1: 0 1px 2px rgba(0,0,0,.05);
  --shadow-2: 0 4px 12px rgba(0,0,0,.08);
  --shadow-3: 0 8px 24px rgba(0,0,0,.12);
}
```

#### 2.2 元件抽象化

從目前散落的 inline class 抽出元件層：

| Component | 目前狀態 | 抽出 |
|---|---|---|
| KPI Card | 散落 12+ 處 inline | `<div class="kpi-card">` with consistent label/value/trend slots |
| Status Pill | inline color | `<span class="status-pill" data-status="success/warning/danger">` |
| Filter Bar | 每頁自己寫 | `<form class="filter-bar">` 配 token spacing |
| Empty State | 各種文案 | `<div class="empty-state">` icon + title + description + action |
| Section Card | 設定頁每段 | `<section class="settings-card">` header / body / footer slots |
| Toast | 已有 | 統一 z-index、enter/exit 動畫、最大 3 個堆疊 |

#### 2.3 表格元件統一

目前 events / rules / workload / reports 各自有表格 style。建議：
```html
<table class="data-table" data-density="compact|comfortable">
  <thead>
    <tr><th class="sortable" data-sort="name">名稱 ↕</th>...</tr>
  </thead>
  <tbody>...</tbody>
</table>
```

加上：
- `data-density` 屬性連動 header「密度」切換
- 統一 row hover background
- column header sort icon affordance
- truncated cell 有 hover tooltip

---

### Phase 3 — IA / 排版重構（4-8 週）

#### 3.1 Dashboard 重設計

目前的 dashboard 是「資訊密度高、缺乏層級」。建議改為「故事化 dashboard」：

```
┌───────────────────────────────────────────────────────────────────┐
│ Hero（一句話結論）                                                 │
│ 「過去 24 小時偵測到 17 條規則命中，2 件高風險，建議優先處理 X。」  │
│                                                              [檢視] │
└───────────────────────────────────────────────────────────────────┘

┌──── 健康狀態 ──────┐ ┌──── 流量摘要 ───────┐ ┌──── 重要事件 ──────┐
│ ✅ PCE: 連線正常   │ │ 8.6K 流量 ▲ 12%    │ │ 🔴 2 高風險發現    │
│ ✅ Workloads: 33/33│ │ 21M 連線            │ │ 🟠 4 中風險        │
│ ⚠️ DLQ: 0          │ │ 2,460 唯一目的 IP   │ │ ⓘ 96 異常流量      │
└────────────────────┘ └─────────────────────┘ └─────────────────────┘

┌─────── Microsegmentation 成熟度 ─────────────────────┐
│ Visibility:    ████████████████████  96.1%            │
│ Enforcement:   █░░░░░░░░░░░░░░░░░░  0.1%             │
│ ...                                                    │
└────────────────────────────────────────────────────────┘

┌── Top 行動建議 ────────────────────────────────────┐
│ 1. [HIGH] 偵測到 504 筆流量使用勒索...   [檢視 →]   │
│ 2. [HIGH] 96 筆 高風險東西/橫向移動...   [檢視 →]   │
│ 3. [MED]  4% 流量被 enforce, 96% 仍 visibility 模式 │
└─────────────────────────────────────────────────────┘
```

對比目前：12 個小卡 + 5 列建議散落、無 hero。

#### 3.2 設定頁的三種佈局選項

詳見 Part B「排版重構提案」一節。

#### 3.3 報表 HTML 重設計

目前 4 種報表都有 KPI 重複問題（Executive Summary + 又一個 Key Metrics 段，數字完全一樣）。重構：

```
┌───── Cover ─────────────────────────────────────────┐
│  Illumio Traffic Flow Report — Security Risk         │
│  2026-05-14 13:31 (UTC+8)   範圍：2026-05-07 → 14    │
├──────────────────────────────────────────────────────┤
│  ┌── Microsegmentation Maturity ──┐ ┌── Key Stats ─┐│
│  │ Score: 52.4/100 (D) 🔴          │ │ 8,666 流量    ││
│  │ ▓▓▓░░░░░░░ 0.1% Enforce         │ │ 21M 連線      ││
│  │ ▓▓▓▓▓▓▓▓▓▓ 96.1% Visibility    │ │ 131 唯一來源  ││
│  │ ...                              │ │ 2,460 唯一目的││
│  └──────────────────────────────────┘ └───────────────┘│
└───────────────────────────────────────────────────────┘

(以下章節僅在當區段有資料時顯示，不再有 "Key Metrics" 重複段)
```

主要工作：
- 移除重複 Executive Summary block
- 大數字 human-readable（6,062,571,061 → `6.06 GB`）
- 評分顏色語意化（D = 紅色）
- TOC sidebar 標題對比修正

---

### Phase 4 — 持續優化

- A11y audit（鍵盤導航、screen reader）
- Performance：載入時資產體積
- 行動裝置：目前未測試 < 1024px viewport
- Print-friendly：報表 HTML print CSS 優化（使用者用瀏覽器列印成 PDF；無獨立 PDF exporter）
- 國際化：加入 Japanese / Korean（亞太市場常見需求）

---

## Part B — 排版重構提案（更好的可能）

### B.1 整體 IA 兩種候選

#### 候選 1：**保守演進**（推薦先做）

維持目前 8 tab top navigation，但加上：
- Header 重塑（見 1.4）
- 設定頁 sub-tab（見 1.1）
- Dashboard 故事化（見 3.1）

**優點**：用戶習慣不變、學習成本 0、可漸進交付
**缺點**：天花板低、頁面間導航仍是「平面式」

#### 候選 2：**Sidebar + Content** 經典 admin layout

```
┌─────────┬─────────────────────────────────────────┐
│ Logo    │  Breadcrumb · 報表 / 流量分析            │
│         │ ────────────────────────────────────────│
│ 🏠 總覽 │                                          │
│ 📊 流量 │     (主內容)                              │
│ ⚙ 規則  │                                          │
│ 📅 排程 │                                          │
│ 📑 報表 │                                          │
│ 🔌 整合 │                                          │
│ 🛠 設定 │                                          │
│         │                                          │
│ ─────── │                                          │
│ ⚙ user  │                                          │
└─────────┴─────────────────────────────────────────┘
```

**優點**：
- 適合「功能型 admin」工具
- 可放更多次級導航
- breadcrumb 取代多層 sub-tab
- 主內容區寬度更穩定

**缺點**：
- 行動裝置需 hamburger menu
- 與現有 css 改動大（~1 週重構）
- 用戶要重新學習（短期 friction）

> **建議**：先做候選 1（4-6 週）；觀察 6 個月後若功能再擴增（例：加 5 個新 tab），再考慮候選 2。

---

### B.2 Dashboard 三種重設計選項

#### 選項 A：保守 — 收緊現有元素

維持 12 mini KPI + 5 行動 + 表格，但：
- 整理為 4×3 一致 grid
- 修翻譯、補單位、人類友善大數字
- 加 Hero 一句話結論在最上方

> 工作量：~1 週

#### 選項 B：故事化（推薦）

```
┌─────── HERO ───────────────────────────────────┐
│ 過去 24h：環境健康 7.8/10，2 件高風險待處理。   │
│ ▶ 立即檢視高風險                                │
└─────────────────────────────────────────────────┘

┌── 健康(綠) ──┐ ┌── 流量(藍) ──┐ ┌── 風險(橘) ──┐
│ ✅ 全部 OK   │ │ 8.6K ▲ 12%   │ │ 🟠 2 待處理  │
└──────────────┘ └──────────────┘ └──────────────┘

┌─ Microsegmentation 成熟度（雷達圖 / bar） ─────┐
│  [視覺化]                                       │
└──────────────────────────────────────────────────┘

┌─ Top 3 行動建議（卡片）──────┐
│  ...                          │
└───────────────────────────────┘

(可摺疊) ▼ 詳細指標 (12 KPI)
```

**核心 idea**：把「12 個指標」變成「3 群、1 個 hero、1 個雷達」，平日掃一眼即可，要 deep dive 才展開 12 個。

> 工作量：~3 週

#### 選項 C：可組合 dashboard

讓用戶自選顯示哪些 widgets（已有 `/api/dashboard/queries` route — 用戶儲存自訂 query）。

**優點**：高階用戶最愛
**缺點**：設計+工程量大，需要 widget library

> 工作量：~6 週

---

### B.3 設定頁佈局：三種候選

#### 設定 A：Sub-tab（最小變動，推薦）

```
[ PCE 連線 ] [ 通知通道 ] [ 介面 / 報表 ] [ 安全 ]
─────────────────────────────────────────────────────
                                              [儲存所有]
  PCE 設定檔
  ┌─────────────────────────────────┐
  │ lab    pce.lab.local   1    [編輯] [刪除] │
  └─────────────────────────────────┘
  + 新增 PCE

  API 連線
  ┌─────────────────────────────────┐
  │ URL: [https://...]      Org: [1] │
  │ API Key: [....]    Secret: [.] ↻│
  │ □ 驗證 SSL                       │
  └─────────────────────────────────┘
  [測試連線]
```

> 工作量：1-2 週

#### 設定 B：Master-Detail（左側清單 + 右側編輯）

```
┌──── 設定 ────────────┬─────────────────────────────┐
│ PCE 連線              │  (右側展示選中項目的詳細)    │
│ ▸ API 連線    ✅ OK   │                              │
│ ▸ 證書 (TLS)  ⚠ 1804d │                              │
│ ─────────────────────│                              │
│ 通知通道              │                              │
│ ▸ LINE        ✅ ON   │                              │
│ ▸ Email       ✅ ON   │                              │
│ ▸ Webhook     ◯ OFF  │                              │
│ ─────────────────────│                              │
│ 系統                  │                              │
│ ▸ 語言/主題           │                              │
│ ▸ 報表輸出            │                              │
│ ▸ 排程                │                              │
│ ─────────────────────│                              │
│ 安全                  │                              │
│ ▸ 帳號密碼            │                              │
│ ▸ IP 白名單           │                              │
│ ▸ 憑證 (CSR)          │                              │
└──────────────────────┴──────────────────────────────┘
```

**優點**：
- 視覺上像「真的設定」（VS Code / macOS System Settings 同模式）
- 一眼看狀態（✅ / ⚠ / ◯）
- 不同 section 獨立儲存（避免「儲存所有」風險）

**缺點**：
- 1280px 以下 layout 緊
- 重構量大

> 工作量：3-4 週

#### 設定 C：嚮導式（首次設定）+ 進階模式

新使用者跑 wizard，老使用者直接進階模式。

**優點**：onboarding 友善（README 提到首次登入要改密碼，再加上 PCE 連線 + 至少一個通知通道）
**缺點**：兩套 UI 維護成本

> 工作量：4-6 週

---

### B.4 字體與視覺層級

目前用了 3 個字體（Montserrat / Space Grotesk / Inter）— **過多**。建議：

| 用途 | 字體 | 字重 | 範例 |
|---|---|---|---|
| 主要 UI 文字 | Inter | 400 / 500 | 內容、表格、表單 |
| 標題 / KPI 大數字 | Space Grotesk | 600 / 700 | 大數字、tab、區段標題 |
| Monospace（程式碼、log） | JetBrains Mono / Fira Code | 400 | log box、JSON viewer |

移除 Montserrat（目前只用在登入頁的副標）。減少 3 個 woff2 載入 → 加快首頁 200ms+。

---

### B.5 配色擴充提案

目前 token：橘 / 米色背景 / 灰文字 / 紅 danger。**缺乏中間漸層**。

加：
```
--orange-50:  #FFF7F2
--orange-100: #FFE5D6
--orange-500: #FF5500  (brand)
--orange-600: #E54D00
--orange-700: #B53D00

--slate-50:  #F8FAFC
--slate-100: #F1F5F9
--slate-200: #E2E8F0
--slate-500: #64748B
--slate-700: #334155
--slate-900: #0F172A

--green-100 / -500 / -700
--amber-100 / -500 / -700
--red-100 / -500 / -700
--blue-100 / -500 / -700
```

每色 3-5 階；目前只有 brand 與 danger 各一階，所以 toast / pill / chart axis 用色失準。

---

### B.6 動效原則

目前幾乎無動效（tab 切換瞬切）。建議加入：

| 場景 | 動效 |
|---|---|
| Tab / sub-tab 切換 | 200ms ease-out fade + tiny x-axis slide |
| Modal 開啟 | 150ms ease-out scale 0.96 → 1.0 + opacity 0 → 1 |
| Toast | enter 200ms slide-in-up, exit 200ms slide-out-down |
| Skeleton loader | 報表生成 / table 載入時用 shimmer |
| Hover | row hover 100ms background fade |

不需要 framer-motion 級別；CSS transition 即可。

---

## Part C — 美化的「可能性」評估

> 老實回答：值得做，但要先建 design system。

### 「美化」可達到的水位

以同類產品為比較：

| 產品 | 視覺檔次 | 我們現在 | 我們可達 |
|---|---|---|---|
| Splunk Cloud / Datadog | 商業 SaaS dashboard 頂尖 | 60% | 85%（建 design system 後）|
| Grafana / Kibana | 開源企業級 | 75% | 95% |
| Linux 套件管理 GUI（cockpit）| 中等 | ≈ | ≈ |
| Illumio PCE 本體 console | 嚴肅企業風 | 80% | 100%（同 family）|

**現實**：以 lab / 內部工具來看，目前已經算上段班。要打 Datadog 等級需要 6-9 個月持續設計投入 + 1 名專職 designer。但**達到 Grafana 等級**只需要 Phase 0-2（約 6 週工程）+ 1 週 design review。

### 加分但可以暫緩的

- Dark mode 完整支援（目前有 toggle，但很多元件硬寫色彩）— 1 週
- 自訂 dashboard widget（B.2 選項 C）— 6 週
- Onboarding wizard（B.3 選項 C）— 4-6 週
- 動態圖表互動（drilldown）— 3 週

### 不要做的

- ❌ **不要追隨 brutalism / glassmorphism**：security ops 工具用花俏視覺破壞權威感
- ❌ **不要 dense UI 學 Bloomberg**：用戶不是專業 trader、密度太高更難讀
- ❌ **不要在報表 HTML 加炫圖**：產出是給管理層列印成 PDF 閱讀，sparkline / 圓環 chart 已足

---

## Part D — 建議的 6 週 Sprint 切片

```
Week 1 — Phase 0 全套（quick wins 10 項）
Week 2 — 1.3 顏色 token + 重著色
Week 3 — 1.1 設定頁 sub-tab
Week 4 — 1.4 Header 重設計 + 1.2 dashboard i18n 稽核
Week 5 — 2.1 spacing/typography token + 2.2 元件抽象（KPI、Pill、Filter）
Week 6 — 3.1 dashboard 故事化（選項 B）+ 報表 HTML KPI 重構
```

**里程碑**：
- Week 1 結束：P0 全清
- Week 3 結束：設定頁不再痛苦
- Week 6 結束：可以對外宣稱「Major UI Refresh」

---

## Part E — 風險與決策點

| 決策點 | 選項 | 推薦 |
|---|---|---|
| Sidebar vs Top-nav | 候選 1（保守）/ 候選 2（sidebar） | 1（先）|
| Dashboard 重設 | A（保守）/ B（故事化）/ C（可組）| B |
| 設定頁佈局 | A（sub-tab）/ B（master-detail）/ C（wizard）| A → 6 個月後評估升級到 B |
| 設計師參與 | 工程內部 / 外包 / 招聘 | 工程 + 1 次外部 design audit |
| Token 系統 | 純 CSS variable / Tailwind / CSS-in-JS | 純 CSS variable（已有基礎、零依賴）|

---

## 附錄 — 相關進行中的工作對齊

根據目前 branch 與 mem0 記錄，以下工作已在進行，這份計畫與其相容：
- **SIEM destination 拆 host/port**：屬於 Phase 1.3 token 化 + 通知通道 sub-tab 重組，順道完成
- **「Accelerate Workloads」→「Increase Traffic Update Rate」改名**：在 Phase 0.7 順手做掉
- **CSR 工作流 UI 調查**：本計畫 1.1 設定頁拆 sub-tab 時，TLS / 憑證 整段會重新組織

如有衝突或新方向，請優先在開始 Phase 1 前同步。
