---
title: Dashboard
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - src/gui/routes/dashboard.py
  - src/templates/index.html
  - src/static/js/dashboard.js
  - src/static/js/dashboard_v2.js
  - commit 519cf85
related_docs:
  - reports.md
  - alerts-and-quarantine.md
  - multi-pce.md
  - ../architecture/i18n-contract.md
---

> 🌐 **[English](dashboard.md)** | **[繁體中文](dashboard_zh.md)**
> 📍 [INDEX](../INDEX.md) › 使用者指引 › 儀表板
> 🔍 最後驗證 **2026-05-15** 對 commit `519cf85` — 詳見 frontmatter

# 儀表板

儀表板分頁（`#p-dashboard`）是連線 PCE 執行個體的主要即時檢視頁面。
包含即時 KPI 卡片、Plotly 圖表、流量報告快照面板，以及
流量分析器、工作負載搜尋、舊版查詢等子頁籤。

---

## 總覽

儀表板顯示 Illumio PCE Ops 所輪詢 PCE 的健康狀態與活動。
介面**不會**自動跳轉頁面；操作者停留在最後選取的分頁。

**自動更新：** Plotly 圖表每 60 秒透過 `setInterval(loadDashboardCharts, 60000)` 更新一次。
即時 KPI 卡片（`#d-rules`、`#d-health` 等）在頁面載入時以及
`/api/status` 或 `/api/dashboard/snapshot` 回傳新回應時更新。
KPI 列本身無頁面級輪詢迴圈；數值在初始載入及使用者明確操作時更新。

**語言切換：** UI 語言由 `window._uiLang` 決定，該值在 `dashboard.js` 中
從 API 回應的 `language` 欄位設定：

```js
window._uiLang = (d.language === 'zh_TW') ? 'zh_TW' : 'en';
```

所有 `data-i18n` 屬性在每次快照回應時由用戶端 `applyI18n()` 重新渲染。
帶有 `label_key` 的快照 KPI 標籤會在請求時於伺服器端重新翻譯
（詳見 `src/gui/routes/dashboard.py` 第 32–38 行與
[i18n 契約](../architecture/i18n-contract.md)中的重新翻譯模式說明）。

---

## KPI 卡片

`#p-dashboard` 內的主要 `.cards` 格線（`<div class="cards">`）包含六個 `.card` 元素。
每個卡片各有一個 `.label`（i18n 鍵）與一個 `.value`（由 JS 更新的 DOM id）。

| 標籤（i18n 鍵） | DOM id | 追蹤內容 |
|---|---|---|
| Rules（`gui_dashboard_rules`） | `d-rules` | 連線 PCE 中的有效規則數 |
| Health Rule（`gui_card_health_rule`） | `d-health` | PCE 健康檢查規則是否通過（`ON` / `WARN`） |
| Event Poll（`gui_card_event_poll`） | `d-event-poll` | 最後一次 PCE 事件輪詢的狀態（`OK` / `WARN` / `ERROR` / `UNKNOWN`） |
| Last Dispatch（`gui_card_last_dispatch`） | `d-dispatch` | 最後一次告警派送的時間戳記 |
| Unknown Types（`gui_card_unknown_types`） | `d-unknown` | 未對應至任何已知分類的事件類型數量 |
| Suppressed（`gui_card_suppressed`） | `d-suppressed` | 被過濾規則抑制的事件數量 |

第七張卡片 **Ransomware Exp**（`gui_card_ransomware_exp`，id `d-ransom`）存在於
範本中，但預設隱藏（`#card-ransom` 設有 `display:none`）。
僅當快照資料包含勒索軟體暴露資料時才會顯示。

KPI 卡片以 `.kpi-card` 統一元件實作（commit `88cdd5d`）。

---

## Mini-KPI 小卡

`#cd-field` 內的 `#cd-list` 容器（`<div id="cd-list" class="cards">`）
存放由 `dashboard_v2.js` 動態注入的 Mini-KPI 小卡。
此 fieldset 預設隱藏（`display:none`），當 `/api/dashboard/snapshot` 回應
包含快照層級 KPI 資料時才會填入。

快照 KPI 格線（`#snap-fieldset` 內的 `#snap-kpi-grid`）是獨立的 `.kpi-grid`，
由 `s.kpis`（`{label, value, label_key?}` 字典的列表）渲染：

```js
(s.kpis || []).forEach((k) => {
  card.className = 'kpi-card';
  labelEl.className = 'kpi-label';
  valueEl.className = 'kpi-value';
  // label_key 觸發伺服器端重新翻譯，透過 /api/dashboard/snapshot
});
```

`pd_*` i18n 鍵系列（`pd_1`、`pd_2`、`pd_3`、`pd_4`、`pd_allowed_*`、`pd_blocked_*`、
`pd_potentially_blocked_*`）描述流量分析器與工作負載搜尋子頁籤中使用的
**Policy Decision（政策決策）** 篩選選項。這些是篩選標籤，並非獨立的 Mini-KPI 小卡。

> [!TODO] @harry: 請確認 `#cd-list` 是否由不同程式碼路徑填入（有別於 `#snap-kpi-grid`）。
> 截至本次審查，兩者均存在於 `index.html`，但只有 `snap-kpi-grid` 在 `dashboard_v2.js`
> 中有明確的填入路徑。`cd-list` 可能為舊版遺留。

---

## 行動矩陣建議

行動矩陣建議面板位於產生報告的**執行摘要**區段
（`src/report/analysis/mod12_executive_summary.py`），並非直接放置於儀表板範本中。

在儀表板上，子頁籤 **Legacy**（`#q-panel-legacy`）內的 `#snap-fieldset`
顯示「最新流量報告摘要」快照，其中包含：

- **關鍵發現**表格（嚴重程度 / 發現 / 行動 欄位）
- **政策分析**欄與**熱門連接埠**欄

行動矩陣建議文字原本以 Python tuple 硬編碼，夾雜品質低落的中文字串。
自 commit `f970d39` 起，這 4 組建議對（共 8 個）已遷移至 `rpt_actmtx_*` i18n 鍵，
讓 `mod12` 透過標準 i18n 管線呼叫 `_t(key).format(...)`。
`f970d39` 之後產生的快照，儀表板快照面板中將顯示正確翻譯的建議文字。

---

## 操作選單（頁首）

頁面頁首右上角的**操作**按鈕（`#hdr-menu-btn`，i18n 鍵 `gui_hdr_operations`）
可開啟下拉面板（`#hdr-menu-panel`，class `.hdr-menu`）。

此選單於 commit `f679f3a`（「Operations dropdown menu collects Theme/Density/Logs/Stop」）中加入，
包含四個控制項：

| 控制項 | i18n 鍵 | 行為 |
|---|---|---|
| Theme（佈景） | `gui_theme` | `<select id="ui-theme-mode">` — Auto / Dark / Light |
| Density（密度） | `gui_density` | `<select id="ui-density">` — Compact / Comfortable |
| Logs（日誌） | `gui_ml_logs_btn` | 開啟維護日誌 modal（`data-action="mlOpen"`） |
| Stop（停止） | `gui_stop` | 呼叫 `stopGui()`，顯示 `confirm()` 確認對話框後停止伺服器 |

選單支援鍵盤存取：在外部點擊或按 <kbd>Esc</kbd> 時關閉。點擊 Logs 或 Stop 也會自動關閉選單。
按鈕使用 `aria-expanded` / `aria-haspopup="menu"` 無障礙屬性。

```html
<button id="hdr-menu-btn" type="button" class="btn btn-secondary btn-sm"
        data-action="hdrMenuToggle" aria-haspopup="menu" aria-expanded="false">
```

---

## 狀態片籤與健康指示

頁首中的 `#hdr-chip` 元素（class `.pce-chip`，role `status`）是
commit `753b753`（「merge URL+stats into single status chip with health dot」）引入的統一狀態片籤，
取代了原本分離的兩個 div（`hdr-meta` 顯示 URL，`hdr-stats` 顯示 3 個 KPI span）。

片籤包含：

| 元素 | id / class | 顯示內容 |
|---|---|---|
| 健康指示點 | `#hdr-chip-dot`（`.status-dot`） | 以顏色表示 PCE 事件輪詢狀態：`ok`（綠）、`warn`（琥珀）、`err`（紅）、`unknown`（灰） |
| PCE 主機 | `#hdr-chip-host`（`.pce-host`） | 來自 `pce_url` 的壓縮 PCE 主機名稱 |
| Rules | `.chip-kpi` | 有效規則數（伺服器渲染後由 JS 更新） |
| Schedules | `.chip-kpi` | 有效排程數 |
| Loaded | `.chip-kpi` | 設定載入時間（人類可讀格式，例如「3 分鐘前」） |

指示點狀態從快照回應的 `pce_stats.event_poll_status` 衍生：

```js
// dashboard.js ~第 1178 行
const polled = String((d.pce_stats || {}).event_poll_status || 'unknown').toLowerCase();
if (polled === 'ok') status = 'ok';
else if (polled === 'warn' || polled === 'degraded') status = 'warn';
else if (polled && polled !== 'unknown') status = 'err';
```

片籤的 `aria-label` 由 Jinja2 伺服器端渲染，`title` 屬性由 JS 更新以包含 PCE 版本（`| v{d.version}`）。

---

## 多 PCE 切換

目前的 `index.html` 範本中**不存在** PCE 切換器 UI。
搜尋 `pce_switcher`、`pce-profile`、`switchPce` 等選擇器均無結果。

多 PCE 設定檔管理在舊版使用者手冊（§6）中記錄為 Settings → PCE Profiles 工作流程
（新增、編輯、刪除、啟用），但該 UI 位於設定分頁而非儀表板頁首。

多 PCE 架構的說明文件，請參見 [Multi-PCE](multi-pce.md)。

---

## 語言切換

儀表板支援在不重新載入頁面的情況下即時切換 EN ↔ zh_TW。

**運作方式：**

1. 每次 `/api/status` 或 `/api/dashboard/snapshot` 回應時，`language` 欄位設定 `window._uiLang`。
2. `applyI18n()` 遍歷所有 `[data-i18n]`、`[data-i18n-placeholder]`、`[data-i18n-title]` 元素，
   使用 `/api/ui_translations` 提供的翻譯包替換其文字/屬性。
3. 帶有 `label_key` 的快照 KPI 標籤在**請求時由伺服器重新翻譯**：
   `dashboard.py` 在回傳 JSON 前以 `_t(label_key, lang=lang)` 覆寫 `label`。
   這表示舊快照中的 KPI 標籤會反映*目前* UI 語言，而非快照產生時的語言。

不含 `label_key` 的舊版快照標籤保留其原始語言（見 `src/gui/routes/dashboard.py` 第 38 行）。

i18n 鍵、重新翻譯及 zh_TW 核准翻譯回歸閘門的完整契約，
請參見 [i18n 契約](../architecture/i18n-contract.md)。

---

## 相關文件

- [Reports](reports.md) — 從儀表板資料匯出與排程報告
- [Alerts & Quarantine](alerts-and-quarantine.md) — 驅動告警的 KPI
- [Multi-PCE](multi-pce.md) — 在多個 PCE 之間切換
- [i18n 契約](../architecture/i18n-contract.md) — 語言切換時標籤重新渲染的原因
