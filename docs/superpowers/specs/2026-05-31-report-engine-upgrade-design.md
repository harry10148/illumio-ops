# Design Spec — 報表引擎升級 (Report Engine Upgrade)

> 日期：2026-05-31 · 狀態：設計核可待 review
> 背景：UX 評估（`docs/ux-review-2026-05-30/assessment.md` §4）發現五份 HTML 報表的共通問題：缺「與前次比較」趨勢、甜甜圈在傾斜分布下零洞察、NetworkInventory 與 SecurityRisk 共用同一封面、Audit 的「需關注事件」卡片是最佳範本但未推廣、列印易破版。
> 結構事實：4 個 exporter 類（Traffic 一類產 SecurityRisk/NetworkInventory 兩變體，由 `self._profile` 決定）。共用件：`cover_page.build_cover_page`、`_exec_summary.render_exec_summary_html`、`table_renderer.render_df_table`、`report_css.build_css`。**`trend_store.py` 已實作 per-run delta 且 Traffic/Audit/Policy 已接（`compute_deltas`→`_trend_deltas`）。**

## 1. 目標與成功標準
- 五份報表都能呈現「與前次執行比較」的關鍵 KPI delta。
- 傾斜分布的甜甜圈改成可讀的長條。
- NetworkInventory 有自己的封面身分（不再與 SecurityRisk 撞臉）。
- Audit 的嚴重度卡片抽成共用件（Audit 先採用）。
- 列印 A4 橫向不再從中切斷卡片/表格/KPI。
- 成功標準：①VEN 報表出現 `_trend_deltas`；②目標甜甜圈改長條後 SVG/Plotly spec `type=="bar"`；③NetworkInventory 封面標題 ≠ SecurityRisk 且不顯示成熟度評級；④共用 `concern_card` helper 存在且 Audit 使用它；⑤新增的 `page-break-inside:avoid` 套用於 card/kpi/concern/maturity；⑥既有報表測試 + i18n parity/稽核全綠。

## 2. 已核可決策
| 項目 | 決策 |
|---|---|
| 統一卡片範圍 | **抽為共用件，Audit 先用**；其他報表（Traffic key_findings / Policy）資料形狀不同，之後要用再寫 adapter（YAGNI） |

## 3. 工作項目

### (a) 「與前次比較」delta — 補 VEN + 提升呈現
- **VEN**：`ven_status_generator.py` 目前完全沒接 trend_store。比照 `report_generator.py:447-456`：產出前 `prev = load_previous(output_dir, "ven")`，存 `save_snapshot(output_dir, "ven", build_kpi_dict_from_metadata(kpis))`，把 `compute_deltas(cur, prev)` 塞進 `result.module_results["_trend_deltas"]`，並在 `ven_html_exporter` 用既有 `_trend_deltas_section()` 模式渲染。
- **呈現**：四份報表都把 `_trend_deltas` chip 列上移到緊接執行摘要 KPI bar 之下（目前 Traffic/Audit 已有 `_trend_deltas_html()`，位置往上提；Policy 補同樣呼叫）。
- 來源：`trend_store.save_snapshot/load_previous/compute_deltas/build_kpi_dict_from_metadata`（已存在）。

### (b) 共用「需關注事件」卡片
- 新檔 `src/report/exporters/concern_card.py`：把 `AuditHtmlExporter._attention_section` + `_risk_badge` 抽成 `render_concern_cards(items, lang) -> str`，消費既有形狀 `{risk, event_type, count, summary, actors, targets, resources, src_ips, recommendation}`。
- CSS：把 `AUDIT_CSS` 的 `.audit-attn-*` / `.risk-*` 區塊（report_css.py:354-382）移到 `BASE_CSS`（改名 `.concern-*` 並保留舊 class 別名以免破壞），讓所有 exporter 都拿得到。
- Audit 改呼叫共用件（行為與輸出不變，僅來源集中）。Traffic/Policy 不動（之後要用再加 adapter）。

### (c) 甜甜圈 → 長條（傾斜分布）
- pie 與 bar 共用 `{"labels","values"}` 形狀，改 spec `type:"pie"→"bar"` 即可（`chart_renderer.py` bar 分支已存在於 :215）。
- 轉換目標（高度傾斜、圓餅零洞察）：政策決定分布 `mod01_traffic_overview.py:97`、VEN 狀態 `ven_html_exporter.py:114`、Audit 嚴重度分布（audit 報表的 severity 圖 spec）、Policy deny 有效性 `pu_mod04_deny_effectiveness.py:98`。
- 保留 pie 於分布相對均衡處（不一律改）。可選：bar 分支加 `orientation="h"`（水平長條，標籤更好讀）— 列為 spec 選項，預設垂直。

### (d) NetworkInventory 專屬封面
- `html_exporter.py:690` 目前兩變體都用 `t("rpt_cover_type_security")`。改成依 `self._profile` 分支：`network_inventory` → 新 i18n 鍵 `rpt_cover_type_inventory`（en「Network Inventory」/ zh「網路盤點」），且 **不傳** `maturity_grade/score`（成熟度評級是 SecurityRisk 的指標，盤點報表不該掛 D 分數）。
- `<title>`（html_exporter.py:705）同步依 profile 分支或維持中性。

### (e) 列印防破版
- `report_css.py`：在 `@media print` 區（或 BASE_CSS）為以下加 `page-break-inside: avoid; break-inside: avoid;`：`.card`（section wrapper）、`.kpi-card`、`.audit-attn-item`/新 `.concern-card`、`.pu-card`、`.score-hero`、`.mat-row`、`.report-table-panel`。
- 標題孤行：`h2, h3 { break-after: avoid; }`。
- 既有已保護的 `tr`/`.chart-container`/`.finding-card`（report_css.py:296/316/320）保留。

## 4. 測試策略
- **單元**：①VEN 產兩次 → 第二次 `result.module_results["_trend_deltas"]` 非空且方向正確；②`render_concern_cards` 給定 items → 輸出含 risk class + recommendation；③目標 chart spec 經轉換後 `type=="bar"`；④Traffic 以 `profile="network_inventory"` build → 封面含 `rpt_cover_type_inventory` 文案且不含成熟度評級 block。
- **回歸**：既有 report 測試（`test_report_*`、`test_ven_report_compact` 等）、i18n parity + 稽核（新增 `rpt_cover_type_inventory` 走 report_i18n.STRINGS / glossary 規範）。
- **視覺**：playwright file:// 渲染五份報表頂部 + 列印 emulate（`page.emulate_media(media="print")`）截圖，目視長條/封面/卡片/不破版。

## 5. 範圍邊界
- **做**：VEN delta + 全報表 delta 上移、共用 concern card（Audit 採用）、4 個傾斜甜甜圈改長條、NetworkInventory 封面、列印防破版。
- **不做**：強制把 Traffic/Policy 全改成統一卡片（YAGNI，之後 adapter）；不重寫 exec-summary/table renderer；不動報表產生的資料分析模組邏輯（只改圖型與封面分支）。

## 6. 實作待解（交由 writing-plans）
- Audit 嚴重度圖的確切 spec 位置（在 audit 分析模組或 exporter 內）。
- `concern_card` CSS 改名後對 Audit 既有 class 的相容別名清單。
- `rpt_cover_type_inventory` 放 `report_i18n.STRINGS` 還是 `i18n_*.json`（比照 `rpt_cover_type_security` 的位置）。
