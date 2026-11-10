# v6 報表內容計畫（6.6.0）：不需設定也讀得完、精簡、呈現

狀態：待核可。核可前不實作。
依據：2026-11-10 對 .106 上 15 份報表（zh_TW，id 120–156）逐頁評估，與原始碼盤點。
前置：`2026-11-10-v6-audit-corrections.md` 的 A 批（6.4.5）先做；本計畫排在 B 批（6.5.0）之後。

## 1. 規則

一份報表在沒有任何選用設定時，必須從標題讀到結尾都是算得出來的內容。選用設定只會多出內容。

三種「現在沒有」要分開處理，不可共用同一句話：

```
                 ┌─ 選用設定沒設（重要資產、管理群組）
 內容現在沒有 ──┼─ 還沒算出來／沒有資料（分析未跑、沒有保留流量）
                 └─ 這台 PCE 不支援

 三種的共同處理：
   標題句   不引用這個數字（換用不含它的句型）
   KPI      不產生這一格
   章節     不產生（目錄也沒有）
   表格欄   不產生這一欄
   資料品質 加一行：缺什麼、為什麼、補上後會多出什麼、去哪裡設（只有第一種有「去哪裡設」）

 與此不同：算過了，結果是 0
   標題句／KPI 照常顯示 0
   章節改成結尾「本期沒有內容的項目」清單裡的一行（見 §4.3）
```

不做的事：不猜重要資產、不猜管理群組。沒設就是沒有，不用「連入最多的主機」之類的替代值冒充。

## 2. 平台層改動（Task 1）

檔案：`illumio_ops/domain/conclusion.py`、`illumio_ops/domain/report.py`、`illumio_ops/services/reports/generate.py`、`render_html.py`／`render_xlsx.py`／`render_email.py`、`i18n/*.json`、`tests/services/reports/test_conclusion.py`。

1. **標題句多句型。** 現況：`CONCLUSION_KPIS` 每型一組 key，任一個 `value is None` 或不存在就整句變成 `rpt_conclusion_incomplete`（「…無法計算（…）」）。改為每型一個有序句型清單 `((keys, i18n_key), …)`，取第一個「keys 全部存在且有值」的句型。`rpt_conclusion_incomplete` 只留給沒有任何句型適用的情況（真的失敗）。
2. **資料品質提示行。** `ReportDocument.data_quality` 維持 `tuple[str, ...]`。新增一個小 helper（放 `services/reports/` 共用處）產生三類提示行，文案鍵 `rpt_hint_unset_*`、`rpt_hint_pending_*`、`rpt_hint_unsupported_*`，每個缺項一行，不重複。
3. **KPI 格數可變。** builder 不產生的 KPI 就不在 `doc.kpis` 裡。三個 renderer 確認 3–6 格都排得好（HTML 兩寬度、Email、XLSX 摘要頁）。
4. **「無上期資料」。** KPI 沒有上期值時不印字（現況每格都印「無上期資料」）；改在資料品質放一行「本報表沒有可比較的上一期」。
5. **守門測試（通用不變量，不逐型寫死）。** 對全部 15 型，用「選用設定全空＋分析結果不存在」的 fixture 產生 `ReportDocument`，斷言：
   - `conclusion()` 不等於 `rpt_conclusion_incomplete` 的輸出；
   - 沒有 `Kpi.value is None`；
   - 沒有任何 Section 的全部 block 都是空表／只有提示文字；
   - `data_quality` 內每個缺項恰好一行。
   先以現況跑一次確認會紅（lateral_posture、ransomware、security_risk 應該紅），再實作。

## 3. 逐型套用

盤點來源為原始碼。「位置」是現在會出現空殼或「無法計算」的地方。

| 報表 | 依賴 | 類別 | 現在的位置 | 改成 |
|---|---|---|---|---|
| lateral_posture | `lateral.critical_assets` | 未設定 | KPI `assets_reachable`=None → 標題「無法計算」；「重要資產與切斷點」整節；偵測表「涉及重要資產」欄 | 三處都不產生；標題句用不含資產的句型；提示行 |
| lateral_posture | `lateral.admin_groups` | 未設定／失效 | 偵測器狀態列一行 disabled | 狀態列不列這個偵測器；提示行（失效與未設定兩種文案） |
| lateral_posture | 暴露面分析結果 | 還沒算 | 多節變成單欄空表「尚未計算」 | 這些節不產生；提示行 |
| ransomware | 保留的流量 | 沒有資料 | 三張清單（優先修補／可直接封鎖／可疑）皆空；KPI priority、safe_to_block、suspicious 為 0；S01「44 個…無法判斷」 | 合成一張「未防護的服務」；KPI 改 `unprotected`；有流量才拆三張 |
| ransomware | 勒索分析／PCE 支援 | 還沒算／不支援 | 每張表都是 missing 文字 | 只剩標題、資料品質一行，其餘章節不產生 |
| security_risk | 勒索分析、暴露面分析 | 還沒算 | 區塊內文字「尚未計算」；KPI note | 區塊不產生；提示行 |
| security_risk | 使用者／程序欄位覆蓋率 | 沒有資料 | 「沒有使用者資料」「沒有程序資料」兩個區塊 | 區塊不產生；提示行合併成一行 |
| new_connections | 連線基準（`baseline_days`） | 沒有資料 | 期間早於基準保留範圍時數字偏低 | 維持現有品質行；確認標題句在基準為空時不出現 0 當結論 |
| rule_hit_count | PCE 開啟 RHC | 不支援／關閉 | 目錄已灰掉，產生時 `ReportFailed` | 不動（已符合） |
| app_summary | App label 篩選 | 必填 | 表單要求 | 不動；封面寫出選了哪個 App（評估發現沒寫） |
| ven_status | 相容性只在 Idle | 環境 | 「不檢查（非 Idle）」 | 文案統一為「不檢查」（評估發現同頁有「列為未知」） |
| 流量類全部 | 收集模式 | 環境 | 資料品質行 | 不動 |

Task 2：lateral_posture。Task 3：ransomware（含 `domain/ransomware.py` 不動，只改報表組裝）。Task 4：security_risk 與表中其餘小項。每個 Task 的測試：同一份 fixture 分「未設定」「已設定」兩種，斷言章節 id 集合、KPI key 集合、欄位清單、提示行。

## 4. 精簡（Task 5）

1. **S01 與結尾「觸發的規則」重複。** security_risk、traffic、network_inventory、app_summary 四型：結尾 `outcomes_table` 只列 S01 沒出現的規則；全部都在 S01 時不產生這張表。
2. **跨報表重複的大表。** policy_usage 的「尚未 Provision」表與 rule_hit_count 相同：留在 policy_usage，rule_hit_count 改成一句數字加報表名稱。security_risk 重述其他報表的部分各縮成一張 5 列摘要。
3. **算過是 0 的章節。** 不再佔一整個面板；結尾一節「本期沒有內容的項目」逐行列出（章節名稱＋原本的空表文字）。policy_diff 6 節有 4 節空、ransomware 2 節空都會因此縮短。
4. **「已移除的主機 …」。** 排行榜裡合併成一列「已移除的主機（N 台）」，放在排行之後。
5. **明細上限。** ransomware 逐服務表 200 列全 0.0% 時只列貢獻大於 0 的列，其餘一句帶過；unmanaged_endpoints「全部」與「公網」兩張 200 列表只留分類後的表；new_connections 的逐條 finding 改成依服務彙總。完整明細仍在 XLSX／CSV，HTML 註明。
6. **lateral_posture 明細。** 113 列表的兩個全空欄不產生（欄位整欄皆空時不輸出，做成 `TableBlock` 組裝時的通用處理）。

## 5. 呈現（Task 6）

1. 佔比欄加比例條（HTML；Email 與 XLSX 維持數字）。
2. security_risk 成熟度由文字改成各面向分數條。
3. 窄表（寬度不到版面一半）兩張並排，760px 以下回到單欄。
4. traffic 加每日連線數趨勢（現有資料算得出來；全期只有一天時不產生）。
5. 「行動」欄：同一張表每列文字相同時，移到表格上方寫一次。
6. readiness 11 欄表拆成「判定」與「依據」兩張。
7. 「未知」判定：表頭下方一行寫出判成未知的條件與筆數。

## 6. 移到 6.4.5 的缺陷（不在本計畫實作）

核可後併入更正計畫 A 批：
- ven_status 竄改統計單位不一致（`n_7d` 數時間點、`unexplained_7d` 數讀數，出現 18 > 3）。
- unmanaged_endpoints S01 排序出現「中、中、高」。
- rule_hit_count 規則名稱漏出排程標記字串。
- lateral_posture S01 漏出 workload href。
- 原始 PCE 值未翻譯（`rule_sets`/`create`、`applied`/`syncing`、`sporadic`、`selective`、`success`、事件類型、OS 代碼）與內部用語（「沿用自 5.x」、規則代碼、`num_connections`、`tedt: 309`）。
- policy_resolver 產出 0 列但沒寫原因（`rules_no_address: 2`）；先查成因。
- 100.95.x 標成「私有」（CGNAT 段的分類）。
- audit 使用者欄與 policy_diff「最後修改者」全是「—」；先查是資料沒有還是沒讀。

## 7. 驗收（Task 7）

1. 閘門：CI workflow 內每一項（不只 pytest），逐項跑。
2. .106 上 15 型 × 2 語系重產，兩種狀態各一次：現況設定；`critical_assets`、`admin_groups` 清空（測完還原）。.135 重產一次（輕量模式、沒有保留流量，驗 ransomware 單一清單）。
3. Playwright 以 1280 與 760 兩寬度逐頁看：標題句、KPI 列、目錄與章節對應、資料品質行。
4. 截斷與溢出檢查（專案規則）：每型記錄頁面水平溢出、表格是否在容器內捲動、超過上限的表是否寫明上限；結果附在回報。
5. 比較改動前後每型 HTML 高度與章節數，列表回報。

## 8. 順序與執行方式

```
Task 1 平台層＋守門測試（紅）
   ├─ Task 2 lateral_posture
   ├─ Task 3 ransomware
   └─ Task 4 security_risk＋小項      → 守門測試全綠
Task 5 精簡
Task 6 呈現
Task 7 驗收、版本 6.6.0、部署 .106／.135
```

建議單一 agent 依序做：Task 2–6 都改同幾支 renderer 與同一份 i18n JSON，平行會互撞。

## 9. 我代為決定的事

1. 「還沒算出來」「PCE 不支援」與「沒設定」用同一套處理（章節不產生＋一行說明），不只處理設定。
2. 提示行放資料品質，不放 S01、不放封面。
3. 算過是 0 的章節收進結尾清單，而不是完全消失（讀者看得到「查過了、沒有」）。
4. 「無上期資料」從每格 KPI 拿掉。
5. HTML 明細縮短，完整資料留在 XLSX／CSV。
6. 新報表類型不在 6.6.0，之後另議。
7. §6 的缺陷歸 6.4.5，不等 6.6.0。
