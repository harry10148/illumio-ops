# Report Print Layout Redesign — Design Spec

## Goal

全面改善 4 種報告（Traffic/Security、Audit、Policy Usage、VEN Status）的列印版面，達成：

1. **列印品質**：長表格不截斷、每頁表頭重複、圖表不被切割
2. **螢幕 + 列印都更好看**：重新安排表格/圖表排列，資訊更清晰
3. **資訊密度**：縮減空白、專業封面、每頁頁碼

適用語言：英文、繁體中文（同一套 CSS，i18n key 控制文字）。

---

## 架構

所有變更透過以下兩層實作，不改動分析模組（mod01–mod15）：

1. **CSS 層**（`report_css.py`）：`@media print` 規則、版型 class、封面樣式、頁尾 counter
2. **HTML 結構層**（各 exporter）：封面頁 HTML、section 套上正確版型 class、頁尾元素

```
report_css.py          ← @media print 規則、.layout-b、.layout-c、.report-cover、@page footer
html_exporter.py       ← Traffic/Security 封面 + section layout class
audit_html_exporter.py ← Audit 封面 + section layout class
policy_usage_html_exporter.py ← Policy Usage 封面 + section layout class
ven_status_generator.py      ← VEN Status 封面 + section layout class
i18n_en.json / i18n_zh_TW.json ← 封面頁 i18n keys
report_config (schema) ← 新增 org_name 欄位
```

---

## Section 版型規則

### 版型 B（主要）— 說明+圖表並排，表格全寬

套用條件：有圖表 **且** 表格欄位 ≥ 4 欄

```
┌─────────────────────────────────────────────┐
│ Section 標題                                 │
├──────────────────────┬──────────────────────┤
│ 說明文字             │  📊 圖表（¼ 頁高）    │
│ (flex: 1)            │  (flex: 1)            │
├──────────────────────┴──────────────────────┤
│ 表格（全寬，可跨頁，每頁表頭重複）           │
└─────────────────────────────────────────────┘
```

CSS class：`<section class="layout-b">`

適用：mod02（Policy Decisions + pie）、mod10 以外有圖表的 section

### 版型 C — 表格+圖表並排

套用條件：有圖表 **且** 表格欄位 ≤ 3 欄

```
┌─────────────────────────────────────────────┐
│ Section 標題                                 │
│ 說明文字（全寬）                             │
├──────────────────────┬──────────────────────┤
│ 表格（flex: 1）      │ 📊 圖表（flex: 1）   │
│ 可跨頁，表頭重複     │ 不跨頁，整塊保留      │
└──────────────────────┴──────────────────────┘
```

CSS class：`<section class="layout-c">`

適用：mod10（Port/Connections 2 欄 + bar chart）、Policy Usage mod01（hit rate pie）

### 版型 A（預設）— 直排

套用條件：無圖表的 section

表格可跨頁，表頭每頁重複，無特殊 class。

---

## 表格列印修正（全部版型）

```css
@media print {
  /* 移除：.card { page-break-inside: avoid } — 長表格不再被整塊推到下頁 */

  /* 表頭每頁重複 */
  thead { display: table-header-group; }

  /* 不在行中間截斷 */
  tr { page-break-inside: avoid; }

  /* 寬表格（5+ 欄）縮小字體 */
  .report-table-wide { font-size: 8pt; }

  /* 圖表列印高度上限（¼ A4 頁 ≈ 185px at 96dpi） */
  .chart-container { max-height: 185px !important; page-break-inside: avoid; }
}
```

`.report-table-wide` class 由 exporter 在欄位數 ≥ 5 時自動加上。

---

## 封面頁

**風格**：深色品牌漸層（Teal `#1a3f4b → #2a5b6b`），橘色分隔線，白字。

**位置**：HTML 最前方，`<section class="report-cover">`，CSS `page-break-after: always`。

**欄位**：

| 欄位 | 資料來源 | i18n key |
|------|---------|----------|
| 報告標題 | 各 generator 硬編 | `rpt_cover_title_*` |
| 報告類型 | profile / generator 類型 | `rpt_cover_type_*` |
| 資料時間範圍 | `df` timestamp 欄 min/max，或 `report_config['date_range']` | `rpt_cover_date_range` |
| PCE 位址 | `report_config['pce_url']` | `rpt_cover_pce` |
| 組織名稱 | `report_config.get('org_name', '')` | `rpt_cover_org` |
| 生成時間 | `datetime.now()` | `rpt_cover_generated` |

**新增 report_config 欄位**：`org_name`（str，預設 `""`）。現有 YAML config schema 加此選填欄位，GUI settings 頁加對應輸入框（另立任務）。

---

## 頁尾（每頁）

使用 CSS Paged Media（Chrome/Edge 列印原生支援）：

```css
@page {
  margin-bottom: 20mm;
  @bottom-center {
    content: attr(data-report-title) " — " counter(page) " / " counter(pages);
    font-size: 8pt;
    color: #888;
  }
}
```

`data-report-title` attribute 設在 `<html>` 或 `<body>` 元素上，由 exporter 注入。

> **降級**：若瀏覽器不支援 `@page @bottom-center`（Firefox），頁尾不顯示但不影響內容。不需 JS polyfill。

---

## 影響的檔案

| 檔案 | 變更內容 |
|------|---------|
| `src/report/exporters/report_css.py` | 重寫 `@media print`、加 `.layout-b`、`.layout-c`、`.report-cover`、`@page` footer、`.report-table-wide` |
| `src/report/exporters/html_exporter.py` | 封面頁、section class、`data-report-title`、寬表格 class |
| `src/report/exporters/audit_html_exporter.py` | 同上 |
| `src/report/exporters/policy_usage_html_exporter.py` | 同上 |
| `src/report/ven_status_generator.py` | 封面頁、section class |
| `src/i18n_en.json` | 新增封面頁 keys（`rpt_cover_*`） |
| `src/i18n_zh_TW.json` | 同上 |
| `src/report/report_generator.py` | 傳遞 `org_name` 至 exporter |
| `src/report/audit_generator.py` | 同上 |
| `src/report/policy_usage_generator.py` | 同上 |

---

## 不在此次範圍

- GUI settings 頁加 `org_name` 輸入框（封面頁可顯示空白）
- 分析模組（mod01–mod15）的資料或邏輯變更
- 非列印的互動功能調整
