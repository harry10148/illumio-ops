# Integrations UI/UX 改版設計規格

**日期：** 2026-04-25
**範圍：** `src/static/js/integrations.js`、`src/static/css/app.css`（或 `integrations.css`）
**目標：** 消除新 Integrations tab 與既有介面的 6 項視覺落差，達到與 Rule Scheduler 等頁面一致的 design language

---

## 1. 背景與問題

Phase 17 新增了 Integrations tab（Overview / Cache / SIEM / DLQ），但因 CSS 未統一而存在以下落差：

| # | 問題 | 影響位置 |
|---|------|---------|
| 1 | Sub-tab 無 active 樣式 | 全部 sub-tab |
| 2 | 表單 label 缺 `form-group` wrapper（非 uppercase / `--dim` 色） | Cache、SIEM |
| 3 | SIEM / DLQ table 未套 `.rule-table` | SIEM、DLQ |
| 4 | Section `h3` 非 `var(--accent2)` 色 | Cache、SIEM |
| 5 | 未定義 CSS class（`.subtitle`、`.it-pane`、`.sub-tab`） | 全部 |
| 6 | Save 按鈕位置不一致 | Cache、SIEM Forwarder |

---

## 2. 設計原則

與既有介面（Rule Scheduler、Settings 頁）保持一致：

- **Sub-tab active**：`border-bottom: 3px solid var(--accent); color: var(--fg)`，底部 underline 樣式（同 Rule Scheduler `.rs-tab`）
- **Form label**：`display:block; color: var(--dim); font-size: .75–.78rem; text-transform: uppercase; letter-spacing: .06em; font-weight: 700`
- **Section h3**：`color: var(--accent2); font-size: .9–.95rem; font-weight: 700`
- **Table header**：`background: var(--bg3); color: var(--dim); font-size: .73rem; text-transform: uppercase`
- **Save 按鈕**：每個可編輯 section 的右下角，`btn-primary` 樣式

---

## 3. Overview Tab

### 3.1 四張統計 cards（2×2 → 4-column grid）

```
[ Cache Rows ] [ SIEM Destinations ] [ SIEM Queue ] [ DLQ Total ]
```

- **Cache Rows**：主值 = events 行數，次行 = `{events} events • {traffic_raw} traffic`
- **SIEM Destinations**：主值 = destinations 數量，次行 = `configured`
- **SIEM Queue**：主值改為三欄 mini-display（PENDING / SENT / FAILED），各有顏色（dim / success / success or danger）
- **DLQ Total**：主值 = DLQ 總筆數，次行 = `dead-letter entries`
- Card 左邊框顏色：queue 有 failed > 0 → `var(--danger)`；否則 `var(--success)`；未設定 → `var(--border)`

### 3.2 Recent Dispatch Events（mini-table）

取代原本的純文字列表，改為帶表頭的 mini-table：

| Destination | Pending | Sent | Failed | DLQ |
|-------------|---------|------|--------|-----|

- Destination 欄以 `<code>` 標籤包裹名稱
- Sent 數值：`color: var(--success)` 若 > 0
- 若無 SIEM 資料（未配置）：顯示 `—` 佔位

---

## 4. Cache Tab

### 4.1 狀態 cards（4-column）

```
[ 狀態 ] [ Events ] [ Traffic Raw ] [ Traffic Agg ]
```

- 狀態 card：enabled = `✓ Enabled`（`var(--success)`）；disabled = `✗ Disabled`（`var(--danger)`）

### 4.2 Toolbar

```
[ ⟳ Backfill ] [ ✂ Retention Now ]       Last sync: X min ago
```

按鈕在左，時間戳在右（`spacer` 推到右邊）

### 4.3 設定表單（分成 4 個 section）

**Basic**
- Enabled checkbox
- DB Path（全寬 input）

**Retention (days)**（2-column grid）
- Events / Traffic Raw / Traffic Agg（各 number input）

**Polling (seconds)**（2-column grid）
- Events Interval / Traffic Interval

**Traffic Filter**（2-column grid）
- Actions：checkbox group（blocked / potentially_blocked / allowed）
- Ports：text input，placeholder `22,443,8443`
- Exclude IPs：text input，placeholder `10.0.0.1,...`

### 4.4 Save 列

```
[restart banner（左，warn 色）]    [Save Settings（右，btn-primary）]
```

---

## 5. SIEM Tab

### 5.1 Forwarder section

2-column form-row：
- Dispatch Tick (sec)
- DLQ Max Per Dest

Enabled checkbox 獨立一行

Save 按鈕在 section 右下角（`btn-primary btn-sm`）

### 5.2 Destinations section

Section header 右側有 `+ Add` button

Table 套用 `.rule-table`（即既有 `.rule-table` CSS）：

| Name | Transport | Format | Endpoint | Status | Actions |
|------|-----------|--------|----------|--------|---------|

- Endpoint 欄 max-width 截斷（`.trunc`，`text-overflow: ellipsis`）
- **Status 欄**：CSS badge 取代 emoji dot
  - 已啟用且最後 test ok → `status-badge ok`（綠色 dot + "healthy"）
  - enabled=false → `status-badge warn`（橘色 dot + "disabled"）
  - 最後 test 有錯誤 → `status-badge err`（紅色 dot + "error"）
  - 未測試過 → plain `—`
- Actions：`[Test] [Edit] [Del]`（Del 套 `btn-danger`）

---

## 6. DLQ Tab

### 6.1 Filter + Bulk Action toolbar（合一列）

```
[Destination ▾] [Reason contains ___] [Search]    [Select All] [Replay] [Purge] [Export CSV]
```

- Filter 區：`background: var(--bg3); border: 1px solid var(--border)`
- Bulk action 在右側（`spacer` 隔開）
- Purge 套 `btn-warn`

### 6.2 Table（`.rule-table`）

| ☐ | Destination | Source ID | Reason | Failed At | Retries | Actions |
|---|-------------|-----------|--------|-----------|---------|---------|

- Reason 欄：`max-width: 180px; text-overflow: ellipsis; white-space: nowrap`；完整文字放 `title` attribute
- Failed At：格式 `Apr 25 22:41`（不顯示秒數）
- Actions：`[View] [Replay]`（per-row）

### 6.3 分頁列

```
2 entries    [‹]  Page 1  [›]
```

---

## 7. CSS 變更

### 7.1 在 `app.css`（或新增 `integrations.css`）中定義：

```css
/* Sub-tab active underline */
.it-subtab-bar { display:flex; gap:0; border-bottom:2px solid var(--border); padding-bottom:0; }
.it-subtab-bar button {
  background:transparent; border:none; border-bottom:3px solid transparent;
  padding:8px 16px 10px; color:var(--dim); cursor:pointer;
  font-size:.85rem; font-weight:600; margin-bottom:-2px; transition:.15s;
}
.it-subtab-bar button.active { border-bottom-color:var(--accent); color:var(--fg); }

/* Status badge */
.status-badge { font-size:.73rem; padding:2px 8px; border-radius:99px; font-weight:600; }
.status-badge.ok   { background:rgba(41,155,101,.15); color:var(--success); border:1px solid rgba(41,155,101,.3); }
.status-badge.warn { background:rgba(230,167,0,.12);  color:var(--warn);    border:1px solid rgba(230,167,0,.3); }
.status-badge.err  { background:rgba(244,63,81,.15);  color:var(--danger);  border:1px solid rgba(244,63,81,.3); }

/* Dot indicator */
.dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:4px; }
.dot.ok   { background:var(--success); }
.dot.warn { background:var(--warn); }
.dot.err  { background:var(--danger); }

/* Text truncation */
.trunc { max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; display:inline-block; vertical-align:bottom; }

/* Filter bar */
.it-filter-bar {
  display:flex; gap:10px; align-items:flex-end;
  background:var(--bg3); border:1px solid var(--border);
  border-radius:var(--radius); padding:10px 14px;
  margin-bottom:10px; flex-wrap:wrap;
}

/* 2-column form grid */
.form-row2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
```

### 7.2 刪除（或停止使用）

- `.it-pane`（未定義）→ 改用 `.section`（現有 class）
- `.sub-tab`（未定義）→ 改用 `.it-subtab-bar button`
- `.subtitle`（未定義）→ 改用 `<p style="color:var(--dim);font-size:.85rem;">`

---

## 8. JS 變更（integrations.js）

### 8.1 Sub-tab 切換

將現有的 sub-tab active toggle 從操作 `background` 改為 toggle `active` class，配合新 CSS：

```javascript
// 舊：el.classList.add/remove 或 style.background
// 新：統一 toggle 'active' class
```

### 8.2 Overview renderOverview()

- 建構 4-card HTML：Cache Rows card、SIEM Destinations card、SIEM Queue card（3 mini-columns）、DLQ card
- 建構 Recent Dispatch Events mini-table（以 `<ul>` 或 `<table>` 呈現，不影響現有 fetch 邏輯）
- 無資料時顯示 `—` 而非錯誤

### 8.3 Cache renderCache()

- 加入 4-card 狀態列（從 `/api/cache/status` 取值）
- 設定區改用 `section` + `form-group` 包裝
- 按鈕改到 toolbar；Save 按鈕在底部右側

### 8.4 SIEM renderSiem()

- Forwarder section 套 form-group + 2-col grid
- Destinations table 套 `.rule-table`
- Status 欄：從 SIEM status API 對應 last_test 結果渲染 badge HTML
- 取消現有 inline style 的表格樣式

### 8.5 DLQ renderDlq()

- Filter + Bulk action 整合為 `.it-filter-bar`
- Table 套 `.rule-table`
- Reason 欄加 `title` attribute（完整文字）
- Failed At 改為短格式（`Apr DD HH:MM`）

---

## 9. i18n

所有新增的 UI 文字需加入 i18n key（中英文）：

- `integrations.overview.cache_rows`
- `integrations.overview.siem_destinations`
- `integrations.overview.siem_queue`
- `integrations.overview.dlq_total`
- `integrations.overview.recent_dispatch`
- `integrations.siem.status_healthy`
- `integrations.siem.status_disabled`
- `integrations.siem.status_error`
- `integrations.dlq.failed_at`（欄位標頭）

（若前一版已有對應 key，沿用舊 key，不重複新增）

---

## 10. 不在此次範圍內

- DLQ "Replay Selected" per-ID 功能（後端未實作，另立 issue）
- Cache Retention Now 的實際 API（placeholder button 保持原樣）
- 任何功能性變更

---

## 11. 測試計畫

1. `python3 scripts/audit_i18n_usage.py` → 0 findings
2. `python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py` → pass
3. 瀏覽器手動測試 `?tab=integrations`：
   - Sub-tab 點擊後有 orange underline active
   - Cache 表單 label 為 uppercase + dim 色
   - SIEM destinations table 有統一表頭樣式
   - DLQ Reason 欄有 ellipsis + title tooltip
   - Overview 顯示正確 4 cards 與 mini-table
4. `python3 -m pytest tests/` → 全部通過
