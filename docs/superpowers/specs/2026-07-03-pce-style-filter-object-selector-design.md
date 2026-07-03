# PCE 風格 Filter 物件選擇器 — 設計文件

日期：2026-07-03
狀態：已與使用者逐段核可（架構/後端、前端/CLI、資料流/相容性/錯誤處理/測試）

## 1. 目標

把專案所有 filter 從「純文字輸入（IP 或 `key=value`）」升級為 PCE 原生風格的物件選擇器：輸入時透過 API 搜尋可用物件、分類下拉顯示候選、選定成 pill；**同時保留原本的 IP/網段與自由文字輸入方式**。

範圍（使用者選定「真的全部」）：

- Web UI 8 個進入點：流量分析器進階 filter、即時報表、排程報表、Dashboard 儲存查詢、traffic/bandwidth 規則定義、workload 搜尋、事件檢視器（事件檢視器沿用其既有類別下拉，不強套 pill）。
- CLI 3 個落點：traffic/bandwidth 規則精靈、workload 列表互動模式、`pce_cache_cli` 的 traffic filter 編輯。
- 物件類型完整對齊 PCE：Labels、Label Groups、Workloads、IP Lists，加上手動 IP/CIDR 與自由 `key=value`。

非目標：FQDN 類別、PCE 的 App Groups 類別、報表 config（`ReportApiQuery`）的結構變更。

## 2. 已驗證的事實基礎（2026-07-03 以真實 PCE 實測）

### 2.1 Autocomplete API（全部可用）

| 物件 | 端點 | 部分比對參數 | 實測 |
|------|------|-------------|------|
| Labels | `GET /labels` | `value=`（子字串、大小寫不敏感）、`key=` | `value=ATA` 命中 `role=Database` |
| Workloads | `GET /workloads` | `name=`、`hostname=`（各自部分比對） | **必須兩參數都查再合併**：`name=SXi` 命中、`hostname=SXi` 0 筆 |
| IP Lists | `GET /sec_policy/active/ip_lists` | `name=` | OK |
| Services | `GET /sec_policy/active/services` | `name=` | OK |
| Label Groups | `GET /sec_policy/active/label_groups` | `name=` | API 正常（實測環境 0 筆物件） |

### 2.2 AND/OR 語意（async traffic query 實測）

`sources.include` 為二維陣列：**內層 = AND、外層 = OR**。實測（24h 窗）：

```
[[A]]     = 487 筆    [[B]]     = 18 筆
[[A,B]]   =   0 筆    [[A],[B]] = 505 筆（= 聯集）
```

- PCE 原生 UI 行為：**同 key 多 label = OR、跨 key = AND**（NotebookLM Illumio 筆記本引用官方文件證實）。
- **現行專案缺陷**：`_build_native_traffic_payload`（`src/api/traffic_query.py:285`）把所有 `src_labels` 放進同一個 inner group = AND，同 key 兩個 label 實測回 0 筆。client-side fallback（`traffic_query.py:692`）與 `df_filter._label_mask`（`src/report/df_filter.py:23`）同為 AND。三條路徑一致但語意錯誤，本案一併修正。
- `sources_destinations_query_op`（專案 `query_operator`）控制來源塊與目的塊之間的 AND/OR：實測 `and`=74、`or`=2386。
- 實測環境使用自訂 label 維度（`Net=`），**分類與同 key 分組不得寫死 app/env/loc/role**。

## 3. 架構

```
前端 FilterBar 元件（新）          CLI object_picker（新）
        │ GET /api/filter-objects/suggest │
        ▼                                 ▼
後端 Suggest 端點（新）──讀──> ApiClient TTLCache（既有）
        │                       └─即時─> PCE search_workloads（既有）
        ▼
pill 序列化 → 既有 filter 詞彙表（擴充 iplist/workload keys）
        ▼
traffic_query 三條消費路徑（native payload / client fallback / df_filter）
```

資料來源採**混合式**（使用者定案）：label、label_group、iplist 由 `ApiClient` 既有 TTLCache（`update_label_cache` 批次抓取）做子字串比對；workload 即時打 PCE（數量大、變動頻繁）。

## 4. 後端設計

### 4.1 Suggest 端點

`GET /api/filter-objects/suggest?q=<字串>&types=label,label_group,iplist,workload&limit=10`

- 新增於 GUI 藍圖，仿 `/api/labels`（`src/gui/routes/reports.py:525`）的模式與限流。
- 回傳依類別分組，每類別附 `truncated` 旗標：
  ```json
  {"label":    {"items": [{"name": "Net=Server-172.16.15", "key": "Net", "value": "...", "href": "..."}], "truncated": false},
   "iplist":   {"items": [{"name": "Prod-Subnets", "href": "...", "summary": "10.10.0.0/16, ..."}]},
   "workload": {"items": [{"name": "...", "hostname": "...", "ip": "...", "href": "..."}], "error": null}}
  ```
- workload 同時查 `name=` 與 `hostname=` 合併去重；PCE 離線時該類別回 `{"error": "pce_unreachable"}`，其他類別照常。
- label 的 key 以快取實際回傳值動態分組。

### 4.2 查詢層擴充

1. capability matrix（`traffic_query.py:37`）註冊：`src_iplist`/`dst_iplist`/`ex_src_iplist`/`ex_dst_iplist`（native actor `{"ip_list": {"href"}}`）、`src_workload`/`dst_workload`/`ex_*`（native actor `{"workload": {"href"}}`）、`any_iplist`/`any_workload`/`ex_any_*`（fallback，either-side）。
2. **同 key label OR 展開**：native builder 把同側同 key 多 label 依「同 key OR、跨 key AND」展開為多個 include group（笛卡兒積）；`_flow_matches_filters` 與 `df_filter._label_mask` 同步改為「同 key any、跨 key all」。三條路徑語意一致且對齊 PCE 原生。
3. iplist href 解析用既有 `_iplist_href_cache`；workload 以 href 直傳。
4. `query_operator` 既有支援，UI 直接暴露為「Source AND/OR Destination」切換（預設 and）。

## 5. 前端設計：`src/static/js/filter-bar.js`

可重複實例化元件：`createFilterBar(container, options)` → `{getFilters(), setFilters(dict), onChange(cb)}`。options 指定允許方向（來源/目的/任一）、允許類別、初始值。

互動（互動原型已由使用者體驗核可）：

- 方向分段按鈕（來源/目的/任一）決定新 pill 方向；pill 點擊開小選單改方向、切包含/排除、移除。
- 輸入 debounce 250ms 打 suggest（既有 `window.debounce` + `AbortController` 樣式，藍本 `rule-scheduler.js:134`）；分類下拉、鍵盤導航（↑↓/Enter/Esc）；空輸入 Backspace 刪最後 pill；無輸入時顯示類別捷徑可限定單一類別。
- IP/CIDR 直接輸入 → 置頂候選「加入 IP/CIDR」（保留原功能）；自由 `key=value` 亦可 Enter 成 pill。
- 同側同 key label pill 相鄰排列、間顯「or」小字；「任一」pill 用區別樣式並提示「含任一側條件，查詢較慢」。
- 降級：suggest 失敗 → 下拉顯示錯誤列、自由輸入照常（等於退回現行體驗）。
- 約束：CSP 無 inline script（用既有 `data-action` 分派器）；i18n 新鍵 `gui_fb_*` 雙語同步；樣式進 `app.css` 沿用既有 token；欄位過長內容以 pill 內 ellipsis 處理、pill 換行不截斷（遵守專案報表/欄位截斷規範）。

## 6. CLI 設計：`src/cli/object_picker.py`

- questionary 兩段式：先選類別（Label / Label Group / Workload / IP List / 手動 IP/CIDR / 手動 key=value），再 `questionary.autocomplete` 模糊搜尋；迴圈多選、完成顯示已選清單。
- 候選來源直接呼叫 `ApiClient`（cached 三類 + workload 即時），與 Web 同語意。
- PCE 離線 → 跳過候選載入、退回手動輸入並提示。
- 落點：`src/cli/menus/traffic.py:86`、`src/cli/menus/bandwidth.py:73`、workload 列表互動模式、`src/pce_cache_cli.py:91`（`workload_label_env`、`exclude_src_ips` 改用 picker）。

## 7. 資料流與相容性

```
輸入 → debounce → suggest → pill {cat, name, href, key?, dir, neg}
  → 序列化成 filter dict（src_label、dst_iplist、ex_src_workload、any_ip…）
  → build_traffic_query_spec → native / fallback / df_filter
```

- **舊資料零遷移**：儲存格式即既有詞彙表（僅新增 key）；`setFilters()` 把舊字串欄位解析回 pill；`=` 啟發式（`quarantine.js:270`、`dashboard.py:344`、`rules.py:150`）由結構化序列化取代，但讀取端保留解析能力。
- **語意變更一處**：同 key 多 label 由 AND（實測 0 筆）改 OR，屬缺陷修正，記錄於 CHANGELOG。
- 手動文字輸入永遠保留（需求 + 降級路徑）。

## 8. 錯誤處理

| 情境 | 行為 |
|------|------|
| PCE 離線 / workload 查詢逾時 | workload 群組顯示警告，cached 類別照常，手動輸入不受影響 |
| suggest 5xx / 網路錯 | 下拉顯示錯誤列，退回自由輸入 |
| pill 引用物件已刪（href 失效） | 沿用既有 `_record_unresolved` 降級 fallback 並記 diagnostics |
| 非法 CIDR | 不出現「加入 IP/CIDR」候選，Enter 無作用 |

## 9. 測試

1. `tests/test_gui_filter_suggest.py`：mock ApiClient；分組、部分比對、大小寫、limit/truncated、離線降級、限流。
2. 序列化雙向 round-trip，含舊格式讀入。
3. 查詢層：同 key OR 展開的 payload 結構斷言（以 2.2 實測為基準）、iplist/workload actor、`ex_*`；fallback 與 df_filter 的同 key any 語意。
4. 模板/CSP：`test_csp_compliance.py`、`test_component_filter_bar.py` 擴充。
5. Playwright E2E：打字出候選 → 選 pill → 切排除 → 送查詢。
6. CLI：mock questionary 精靈流程。
7. i18n 稽核：新鍵雙語齊全。

## 10. 實作分期

0. 隔離安全與截斷提示（獨立 batch，與第 1 期檔案零重疊，可先做或平行做；見 §11）
1. 查詢層擴充 + 同 key OR 修正（純後端，先修語意缺陷）
2. Suggest 端點
3. FilterBar 元件 + 流量分析器落地（打樣）
4. 其餘 Web 進入點分批（即時報表、排程報表、儲存查詢、規則、workload 搜尋；即時報表後端補收 `any_*` 的既有落差一併修）
5. CLI picker 與三個 CLI 落點

## 11. 第 0 期：隔離安全與截斷提示（2026-07-03 併入，使用者核可）

功能盤點（流量分析器 / Top 10 / workload）發現的三個安全與正確性缺口，使用者決定併入本計畫：

### 11.1 隔離審計 log + 二次確認

- `apply`、`bulk_apply` 與新增的 `lift` 皆寫審計 log：沿用 accelerate 的 `ModuleLog.get("actions").info(...)` best-effort 樣式（`src/gui/routes/actions.py:303-310`），內容含操作者（flask_login `current_user`，取不到記 `?`）、目標 href（bulk 記數量與清單）、severity、成功/失敗結果。審計失敗不阻斷主操作。
- 前端套用隔離前加 `confirm()`（顯示目標數量與 severity），與刪除儲存查詢的既有樣式一致。

### 11.2 解除隔離

- 新端點 `POST /api/quarantine/lift`，吃 `hrefs` 清單（單筆多筆同一支）。實作依據：隔離是「附加」Quarantine 標籤、原標籤未動（`actions.py:219-222`），故解除＝移除 `check_and_create_quarantine_labels()` 三個 href、保留其餘標籤。無需原標籤還原機制。
- 回應統計 `{success, failed, skipped_invalid, not_quarantined}`；身上沒有 Q 標籤的目標不打 update、計入 `not_quarantined`。
- UI：workload 列表已隔離機器的靜態 `gui_isolated` 標籤（`quarantine.js:607`）改為「解除隔離」按鈕，confirm + 審計 log 同 11.1。

### 11.3 500 筆截斷提示

- `Analyzer.query_flows` 截斷前記錄 `self.last_query_stats = {"total_matches": N, "cap": 500, "truncated": N > 500}`（仿 `ApiClient.last_traffic_query_diagnostics` 樣式；回傳型別不變，既有呼叫者零影響）。魔術數字 500 抽成模組常數。
- `/api/quarantine/search` 回應加 `total_matches`/`truncated`；流量分析器顯示「顯示前 {cap} 筆（共 {total} 筆符合），請縮小條件」。
- Dashboard top10 route 回傳 `truncated`，卡片顯示「排名基於前 {cap} 筆」警示 badge。

### 11.4 不做的（YAGNI）

- 不改 500 上限本身；不做 type-to-confirm；不做隔離原因欄位；lift 不處理隔離期間的標籤合併衝突（直接移除 Q 標籤保留其餘）。

## 附錄：需求決策紀錄

| 決策點 | 選擇 |
|--------|------|
| 範圍 | 真的全部（Web + CLI + pce_cache_cli） |
| 物件類型 | 完整對齊 PCE（Labels、Label Groups、Workloads、IP Lists）+ 手動 IP/CIDR |
| UI 呈現 | 完整 PCE 風格單一搜尋列（pill + 方向 + include/exclude） |
| CLI | questionary 逐欄 autocomplete |
| 資料來源 | 混合式（cached 三類 + workload 即時） |
| 多 label 語意 | 對齊 PCE：同 key OR、跨 key AND |
| 互動原型 | https://claude.ai/code/artifact/2a5fd799-b3f9-4950-b6d5-4112e3c80e30 |
