# 拆分 Traffic 報表為兩份獨立報表(Security & Risk / Network Inventory)

- **日期**: 2026-06-03
- **狀態**: 設計（待 spec review → 實作計畫）
- **背景**: 目前 Traffic 報表是單一 `ReportGenerator` + `HtmlExporter`,以 `traffic_report_profile`（`security_risk` / `network_inventory`）參數切換,兩種輸出共用大量 section、有重複內容,且難以各自獨立演進。

## 1. 目標

把現行的兩個 traffic profile 拆成**兩個一級報表型別**(比照 VEN report 的獨立型別模式):各有獨立的 exporter、CLI 動詞、排程型別與檔名前綴;**流量分析引擎共用**(同一份 flow 資料、同一組 mod01–16 分析,不重複計算)。同時做 section 去重與歸位。

非目標(獨立後續,不在本 spec):橫向移動 / 安全發現的列數瘦身、`nan` 來源工作負載清理、screen 端 auto-fit(PDF 已驗證正常)。

## 2. 兩份報表的身分

| | 報表 A | 報表 B |
|---|---|---|
| 名稱 | **Security & Risk Report**(資安與風險) | **Network & Traffic Inventory Report**(網路流量盤點) |
| 受眾 | 資安 / SOC | 網路 / 維運 |
| report_type | `security_risk` | `network_inventory` |
| CLI 動詞 | `report security` | `report inventory` |
| 檔名前綴 | `Illumio_Security_Risk_Report_…` | `Illumio_Network_Inventory_Report_…` |

## 3. Section 歸位（已與使用者定案）

**共同保留**（不去重,基礎/決策性):執行摘要(各報表自動產生)、**流量總覽 (mod01)**、**Policy 判定 (mod02)**。

**報表 A 專屬**:微分段成熟度(maturity hero)、勒索曝險 (mod04)、使用者與程序 (mod06)、Allowed 流量 (mod10)、基礎架構評分 (mod14)、橫向移動 (mod15)、Enforcement 就緒度 (mod13)、安全發現 (findings)。

**報表 B 專屬**:跨 Label 矩陣 (mod07)、Unmanaged 主機 (mod08)、流量分佈 (mod09)、頻寬與傳輸量 (mod11)、應用程式 Ringfence (mod_ringfence)、變更影響 (mod_change_impact)。

**去重結果**:相對現況,報表 B **移除**「微分段成熟度 + Enforcement 就緒度」(改為報表 A 專屬);其餘 profile-unique section 維持原樣。

> 完整 section→module 對照見附錄 A。

## 4. 架構

### 4.1 共用分析引擎（不重複)

- `ReportGenerator`(`src/report/report_generator.py`)維持為**共用的 traffic-flow 分析引擎**:`generate_from_api()` / `generate_from_csv()` 跑 mod01–16 並回傳 `ReportResult`(所有 module 結果)。兩個報表型別都呼叫它取得同一份分析結果。
- 移除 `generate_*` / `export` 上的 `traffic_report_profile` 參數對「分析」的影響(分析本來就跑全部 module);profile 僅決定「渲染哪些 section」,該責任移到 exporter。
- 純分析函式(mod01–16、exec summary、maturity/posture、policy decisions、readiness)已在 `src/report/analysis/`,本來就是共用的純函式 — 不需搬動。

### 4.2 兩個 exporter（取代單一 profile-branching `HtmlExporter`)

現行 `src/report/exporters/html_exporter.py:HtmlExporter` 以 `self._profile` 在 `nav_links`(:561/:576)與 body 組裝(:609-694)分支。改為:

- **`_TrafficReportBase`**(新增,或就放在 html_exporter):持有共用基礎設施與**共用 section 渲染**(`_section`、`_nav_link`、exec summary、流量總覽 `_mod01_html`、Policy 判定 `_mod02_html`,以及所有 `_modNN_html` cell renderers)。每個 `_modNN_html` 已存在,保留為共用方法。
- **`SecurityRiskHtmlExporter(_TrafficReportBase)`**:`export()` 組裝報表 A 的 nav + body(§3 A 的 section 集合)。
- **`NetworkInventoryHtmlExporter(_TrafficReportBase)`**:組裝報表 B。
- 各自的 `profile_label` / 檔名前綴(取代 :417 的三元判斷)。
- 刪除 `HtmlExporter` 內所有 `if profile == …` 分支(邏輯移進各子類的 body 組裝)。

### 4.3 入口(generator facade per type)

比照 VEN(`VenStatusGenerator.generate()/export()`),提供兩個薄 facade(**採此方案** — 貼近既有 VEN 模式、可測性佳、CLI/scheduler 共用同一入口):

- `src/report/security_risk_report.py` → `SecurityRiskReport`(包 `ReportGenerator` + `SecurityRiskHtmlExporter`)
- `src/report/network_inventory_report.py` → `NetworkInventoryReport`(包 `ReportGenerator` + `NetworkInventoryHtmlExporter`)

### 4.4 CLI（`src/cli/report.py`)

- 新增 `report security` 與 `report inventory` 兩個 command(比照現有 `report ven-status`)。
- 保留 `report traffic --profile {security_risk|network_inventory}` 為**deprecated 相容別名**:內部 dispatch 到對應新型別,印 deprecation 提示。`generate-traffic` 別名同樣保留。
- 對應 `generate_security_report()` / `generate_inventory_report()` helper(比照 `generate_traffic_report`)。

### 4.5 排程(`src/report_scheduler.py`)

- `_generate_report()`(:247)新增 `report_type == "security_risk"` 與 `"network_inventory"` 分支。
- 保留 `report_type == "traffic"`(+ 既有 schedule 的 profile 欄位)為**長期相容路徑**,dispatch 到新型別(profile→type 對應),讓既有 `config/config.json` 的 `report_schedules` **不需遷移**。**採此方案** — 不強制改使用者既有設定。

## 5. 邊界 / 相容性

- **既有排程與 CLI 不可破壞**:`report traffic --profile` 與 `report_type:"traffic"` 必須持續運作(deprecated 相容路徑)。
- **i18n**:新增報表標題 / CLI 說明 key(`rpt_security_report_title`、`rpt_inventory_report_title`、CLI help…),en + zh_TW 雙語。
- **XLSX / CSV 匯出**(`generate_traffic_xlsx` 等):**本 spec 範圍只拆 HTML 兩型別**;XLSX/CSV 維持現行 profile 參數不動(避免擴大範圍)。XLSX 拆分如有需要,列為獨立後續。

## 6. 測試策略

- 共用分析:`ReportGenerator` 既有測試不動。
- 兩個 exporter:各一組渲染測試 — 斷言「該出現的 section 出現、該去重的不出現」(例:報表 B 不含 maturity/readiness;兩者皆含 overview/policy)。仿 `tests/test_mod16_report.py` 已刪、改用 section-id 斷言。
- CLI:`report security` / `report inventory` 產出對應檔名;`report traffic --profile` 相容別名仍可用(印 deprecation)。
- 排程:`report_type` 新值 + `traffic` 相容路徑各一測試。
- 全套迴歸:`python3 -m pytest tests/`(基線 1579 passed)。

## 7. 附錄 A — section → module 對照

| Section | module | A | B |
|---|---|:--:|:--:|
| 執行摘要 | mod00/exec | ✓(自) | ✓(自) |
| 流量總覽 | mod01 | ✓ | ✓ |
| Policy 判定 | mod02 | ✓ | ✓ |
| 微分段成熟度 | maturity/posture | ✓ | — |
| 未覆蓋流量 | mod03 | ✓ | — |
| 勒索曝險 | mod04 | ✓ | — |
| 使用者與程序 | mod06 | ✓ | — |
| 跨 Label 矩陣 | mod07 | — | ✓ |
| Unmanaged 主機 | mod08 | — | ✓ |
| 流量分佈 | mod09 | — | ✓ |
| Allowed 流量 | mod10 | ✓ | — |
| 頻寬與傳輸量 | mod11 | — | ✓ |
| Enforcement 就緒度 | mod13 | ✓ | — |
| 基礎架構評分 | mod14 | ✓ | — |
| 橫向移動 | mod15 | ✓ | — |
| 應用程式 Ringfence | mod_ringfence | — | ✓ |
| 變更影響 | mod_change_impact | — | ✓ |
| 安全發現 | findings | ✓ | — |

> 註:現況「未覆蓋流量 (mod03)」在 security_risk profile 顯示;歸入報表 A。
