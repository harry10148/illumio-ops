# 報表拆分與精簡設計：Traffic / Security 獨立 + 全報表瘦身

日期：2026-07-02
狀態：已與使用者逐段確認

## 背景與問題

現況 `report traffic` 預設即為 security_risk profile，與 `report security` 產出完全相同；
「traffic 報表」沒有獨立內容。使用者回饋：

1. traffic 與 security 應拆成兩份獨立報表。
2. 報表後段內容過多且難懂：大量標籤對標籤表格、Illumio 專有計算
   （微分段成熟度、Enforcement 就緒度、基礎架構評分、橫向移動圖論）。
3. 報表中的 `ams` 字眼應顯示為 `All Workloads`。
4. GUI 報表頁的 attack posture badge（`B/P/R/S/A` 計數）無必要，移除。

另由本次報表總體檢（實際產出全部報表逐一檢視）納入其他報表的精簡與 bug 修復。

技術背景：目前 `ReportGenerator._run_modules()` 不論 profile 都執行全部 15+ 個分析
模組（含圖論計算），profile 只影響匯出時的章節挑選（`section_guidance.profile_visibility`
+ `html_exporter._ordered_section_keys()`）與 mod12 KPI 組合。

## 已確認的決策

| 決策點 | 結論 |
|---|---|
| Traffic 報表定位 | 純流量事實報表（新 profile `traffic`），零評分、零安全分析 |
| Security 專有計算 | 全部保留計算，大幅簡化呈現 |
| Inventory 報表 | 保留並一併精簡，重新聚焦「資產與標籤治理」 |
| 實作架構 | Profile 感知模組執行（登錄表帶 profile 標記，按 profile 過濾執行） |
| CLI | `report traffic` 直接改產新報表；`--profile` deprecated 並導向 security/inventory |
| 裸 traffic 排程 | 直接改產新報表（CHANGELOG + 升級提示註明） |
| 新報表檔名 | `Illumio_Traffic_Report_*`（無 profile 後綴；與舊 `_SecurityRisk_`/`_NetworkInventory_` 可區分） |
| 其他報表改善 | Audit、Policy Usage、VEN、趨勢/Drift 全部納入本次範圍 |

## A. Traffic 流量報表（新 profile `traffic`）

定位：「網路上發生了什麼」，一般讀者可讀。只執行 6 個輕量模組：

| 章節 | 內容 | 來源模組 |
|---|---|---|
| 1. 執行摘要 | 流量數、連線數、來源/目的 IP、總資料量、觀測期間（無成熟度、無攻擊摘要） | mod12（新 KPI 組合） |
| 2. 流量總覽 | 基準統計 + 熱門 Ports / Protocols | mod01 |
| 3. Policy 判定摘要 | Allowed/Blocked/PB 占比一張表 + 圓餅圖（不含 App 流向明細 ×3、不含 port 覆蓋率大表） | mod02（僅 summary） |
| 4. 流量分布 | 依 App、依 Env 兩張表（無 role/loc、無矩陣） | mod09（精簡） |
| 5. 頻寬與傳輸量 | Top 傳輸量、Top 頻寬、異常流量（P95） | mod11 |
| 6. Unmanaged 流量概況 | 一張摘要表（unmanaged 占比 + Top 來源） | mod08（僅摘要） |

不執行：rules engine、drift、lateral（mod15）、infrastructure（mod14）、readiness
（mod13）、ransomware（mod04）、uncovered（mod03）、user/process（mod06）、
draft 分析、vuln、labels。不抓 workloads、不需 vuln CSV。

## B. Security 報表（計算保留，呈現大幅簡化）

1. 三層發現（關鍵發現 / 攻擊摘要五區塊 / 安全發現章）合併為單一「發現與行動」章：
   以行動矩陣為主軸，每個行動掛嚴重度、量化證據（N 條流量、主機/port 清單、
   對應規則編號）。原三章移除。
2. 攻擊摘要 posture item 依主體（workload/app）合併，文字必須量化，
   不得出現重複的制式句（如連續兩列「偵測到邊界控制弱點」）。
3. 橫向移動章 10 張表砍到 4 張：service 檢視、fan-out 來源、明確 allowed 的
   lateral 流量、攻擊路徑。其餘（IP top talkers、主機配對、橋接節點、可達節點、
   BFS App 鏈）下放 XLSX。
4. Policy 判定章依占比動態摺疊：占比 < 1% 的 decision 收成一行摘要。
5. 未覆蓋流量：port 缺口表與 services 表合併（4 表 → 3 表）。
6. 每個評分加一句白話說明（i18n）：成熟度、就緒度 5 因子、基礎架構評分各加
   「分數怎麼算、怎麼讀」。
7. 死碼清理：刪除 `mod05_remote_access.py`；確認 mod10 的 audit_flags 已由
   mod02 章呈現後，移除 mod10 模組。

## C. Inventory 盤點報表（聚焦資產與標籤治理）

1. 流量總覽、流量分布、頻寬三章移除（歸 Traffic 報表）。
2. 跨 Label 矩陣只留 ENV、APP 兩維；ROLE/LOC 下放 XLSX。
3. Unmanaged 6 張表合併為 3 張（來源排行、目標 App、暴露 port 合併版）。
4. 修「變更影響分析」首次產出的空章節（加 empty-state 文字）與
   流量總覽「日期範圍 N/A → N/A」問題。

## D. Profile 感知模組執行

- `src/report/analysis/__init__.py`：`TRAFFIC_MODULES` 登錄表每項帶 `profiles`
  集合標記；`ReportGenerator._run_modules()` 依 profile 過濾。
- rules engine、draft 分析、drift 注入、workloads 抓取、vuln CSV 依 profile 觸發。
- `section_guidance.profile_visibility` 與 `html_exporter._ordered_section_keys()`
  新增 `traffic` 章節順序。
- mod12 為 `traffic` 新增純流量 KPI 組合。

## E. CLI 與相容性

- `report traffic` → 新純流量報表。`--profile security_risk|network_inventory`
  印 deprecation 提示並委派給對應報表邏輯（行為不變）。
- `report security` / `report inventory` 入口不變。
- 排程任務帶 profile 者照舊；裸 `traffic` 排程改產新報表（CHANGELOG 註明）。
- 新報表檔名 `Illumio_Traffic_Report_<timestamp>`；趨勢/drift 快照按 profile
  分開存放，禁止跨 profile 比較。

## F. 顯示層修正

1. `ams` → 顯示 `All Workloads`：`resolve_actor_str` 顯示層對應
   （API payload 的 `actors: "ams"` 不動）。連帶修 actor 解析 fallback 直接
   印 raw dict（如 `{'ip_list': {...}}`）的問題，未解析 href 改顯示可讀名稱。
   影響 Policy Usage、Policy Resolver 的 Source/Destination 欄。
2. GUI 報表頁 attack posture badge（`Attack posture boundary 5 | pivot 2 | ...`
   與 `B/P/R/S/A` 計數）整組移除；HTML 報表內的攻擊摘要內容不受影響。
3. 補 `rpt_cat_draftpolicy_name` / `rpt_cat_draftpolicy_desc` i18n 翻譯。
4. 表格 port 欄不套千分位格式（`8,080` → `8080`）。

## I. Audit 報表精簡

1. 三模組各自的「近期事件（最多 50 筆）」→ HTML 只留 10 筆，完整清單留 CSV/XLSX。
2. 執行摘要 KPI 標籤中文化（Total Events 等改用 i18n）。
3. matplotlib SVG 內嵌去 metadata 瘦身。

## J. Policy Usage 報表精簡

1. 未使用 Rules 明細 HTML 上限 1000 → 50 列，完整清單走 CSV。
2. mod05 三張同構「高風險流量配對 Top 20」合併為一張表、加「風險類型」欄。

## K. VEN Status 報表

1. Bug 修復：`generate_ven_xlsx()` 的 online/offline 判定（active 且 <24h）與
   主 `_analyze`（1 小時心跳閾值）不一致 → XLSX 改用 `_analyze` 的分桶結果。
2. Online VEN 全列明細 → 改為計數 + 版本分布；明細表只列 offline / 失聯分桶。

## L. 趨勢與 Drift 可信度

1. trend/drift 快照記錄視窗長度、資料來源、profile；不一致時顯示警語或拒絕比較。
2. Drift「消失配對」過濾 ICMP、port 0、ephemeral 高 port；
   `(unlabeled)→(unlabeled)` 配對收合成一行統計。

## N. PDF 匯出與表格版面（全報表一致性）

1. 所有 HTML 報表都要有「列印 / PDF」按鈕：policy_diff、app_summary 兩個
   exporter 目前缺少（其餘報表已有 `print-btn` + `window.print()`）。
   之後新增的報表一律必須帶此按鈕（納入共用版型/檢查）。
2. 表格欄寬必須配合 PDF 版面：使用者不得需要水平拖拉才能看到內容。
   - 螢幕呈現：`.report-table-wrap` 不得依賴 `overflow: auto` 水平捲動
     呈現主要內容；欄位內容改為自動換行（`white-space: normal` +
     `word-break`），寬表以欄寬收斂與內容截斷（tooltip 顯示全文）處理。
   - 列印呈現：`@media print` 下表格必須完整落在 A4 版面內
     （`table-layout: fixed` + 換行），不得裁切欄位。
   - 各報表 HTML 表格欄數以列印可讀為上限原則（過寬的明細表改下放
     CSV/XLSX，與「HTML 給結論、明細給 XLSX」原則一致）。

## 不做的事（另案）

- 宣告式報表定義重構。
- XLSX 平行路徑（`generate_*_xlsx` ×3）架構重構——K1 只修 VEN 判定不一致。
- Policy Diff 擴充（IP list / service / label group 層 diff）。
- Enforcement 就緒度獨立成報表（產品方向，待使用回饋）。

## 測試策略

- `traffic` profile 管線測試：只執行預期模組、章節順序正確、無成熟度/posture 內容。
- Security/Inventory exporter 測試更新（章節增刪、合併表、動態摺疊）。
- `--profile` deprecation 路徑測試（行為等同 security/inventory）。
- `ams` 顯示、raw dict fallback、port 格式、i18n 鍵單元測試。
- VEN XLSX 與 HTML 分桶一致性測試。
- trend 快照不一致警語測試；drift 雜訊過濾測試。
- 全套 `pytest` 綠燈。

## 實作分期建議（供 writing-plans 參考）

1. Phase 1：Profile 感知模組執行 + 新 Traffic 報表 + CLI（A、D、E）。
2. Phase 2：Security 呈現簡化 + 死碼清理（B）。
3. Phase 3：Inventory 精簡（C）。
4. Phase 4：顯示層修正批次（F）+ PDF 匯出與表格版面一致性（N）。
5. Phase 5：Audit / Policy Usage / VEN 精簡（I、J、K）。
6. Phase 6：趨勢與 Drift 可信度（L）。

每期獨立可交付、可測試；Phase 1 是其餘各期的前置。
