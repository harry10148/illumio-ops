# Port/Service Filter 與物件瀏覽 — 設計文件

日期：2026-07-10
狀態：已與使用者逐段核可（架構/後端、前端/CLI、資料流/相容性/錯誤處理/測試）

## 1. 目標

在既有 PCE 風格 filter 物件選擇器（2026-07-03 設計、Phase 0-5 已完成）之上做兩件事：

1. **Port/Service 過濾進 FilterBar**：新增「服務」類別——可從 PCE 選 service 物件成 pill，也可直接輸入 port 語法（`80`、`443/tcp`、`1000-2000/tcp`）成 pill；支援包含/排除。
2. **物件瀏覽（案 C 混合式）**：解決「不知道要找什麼就無從下手、候選一次只顯示 10 筆」的痛點——空輸入下拉即可分類分組瀏覽（快查），下拉底部可開 modal 物件庫（分頁、多選、深挖）。所有物件類別受惠，不只服務。

另確認：**手動 IP/CIDR 輸入已完整支援**（GUI 置頂候選、CLI 手動類別、查詢層 native actor、cache 路徑 CIDR containment），本案不需改動，僅在交付驗證時一併實測。

非目標：workload 全量瀏覽（維持打字搜尋）、per-label workload 使用數（PCE labels API 不提供、逐 label 查成本過高）、CLI 的 modal 瀏覽（autocomplete 已可瀏覽全部候選）、改動 500 筆查詢上限。

## 2. 已確認的技術前提

- PCE traffic query 的 `services.include/exclude` **不吃 service href**，只吃 `{"port", "proto"}`、`{"port", "to_port", "proto"}`、`{"process_name"}`、`{"windows_service_name"}` 條目（`_build_native_traffic_payload`，`src/api/traffic_query.py:418-479` 組裝邏輯既存）。選 service 物件必然在本專案側展開，PCE 原生 UI 亦同。
- service 物件已有記憶體快取：`LabelResolver.update_label_cache`（`src/api/labels.py:200`）從 `/orgs/{org}/sec_policy/draft/services?max_results=10000` 抓取，建 `service_ports_cache`（href → raw port/proto dicts）。**但現況只收 `service_ports`（port/proto/to_port）**：`windows_services` 條目（windows_service_name/process_name）與純 proto（無 port）條目被跳過，完全沒有 port 的 service 不會進快取（`labels.py:251-272`，`if port_defs:` 守門）。本案需擴充快取建構（見 §4.3）。
- Services autocomplete API `GET /sec_policy/active/services?name=` 已於 2026-07-03 真實 PCE 實測可用（見前案設計 §2.1）。
- 查詢層既有 port 能力完整：`port`/`proto`/`ex_port`/`port_range`/`port_ranges`/`ex_port_range(s)`/`process_name`/`windows_service_name` 全部 native（capability matrix `traffic_query.py:53-63`）。缺的只是選擇介面。
- 目前 GUI 的 port 入口僅流量分析器一個純文字欄位（`qt-port`，`src/static/js/quarantine.js:278`）；FilterBar 類別無 service；suggest 端點 `_ALL_TYPES` 無 service（`src/gui/routes/filter_objects.py:11-12`）。
- `labels._parse_port_range_entry`（`labels.py:102-132`）接受 `80-90`、`80-90/tcp`，**不接受單一 port**（需含 `-`），需擴充。
- cache 讀取路徑 `df_filter`（`src/report/df_filter.py:158-169`）目前只有單 port int 與 proto alias 比對，無 range。

## 3. 架構

```
FilterBar（＋服務類別、＋空輸入瀏覽、＋modal 物件庫）   CLI object_picker（＋服務/Port 類別）
        │ GET /api/filter-objects/suggest（既有，＋service）      │
        │ GET /api/filter-objects/browse（新：分組列表＋分頁）     │
        ▼                                                       ▼
filter_object_cache（＋service 快取，TTL 300s＋stale-serving）── ApiClient
        ▼
pill 序列化 → 扁平 filter 詞彙表（新增 services/ex_services、ports/ex_ports）
        ▼
traffic_query 查詢時展開：service href ─(service_ports_cache)→ port/proto 條目
        ├→ native payload services.include/exclude（結構既存）
        └→ cache 路徑：組裝層先展開，df_filter 比對（擴充 range/proto）
```

## 4. 後端設計

### 4.1 Suggest 端點擴充

- `filter_objects.py` 的 `_CACHED_TYPES`/`_ALL_TYPES` 加 `service`，走既有 module 快取模式。
- service 候選項：`{"name", "href", "summary"}`，summary 為 port 摘要（如 `tcp/80, tcp/443`，仿 `_ip_list_summary` 樣式，過長 ellipsis）。

### 4.2 Browse 新端點

`GET /api/filter-objects/browse?type=<label|label_group|iplist|service|workload>&offset=<n>&limit=<n>`

- 消費者：空輸入下拉、modal 物件庫。限流與 suggest 同級。
- cached 四類從 filter_object_cache 回分頁結果；`label` 依 key 動態分組並附各組數量（key 不寫死，沿用前案原則）；其他類別平鋪。
- 回應含 `total`（類別總數，取自快取長度，零成本）供 chip 顯示 `Labels (46)`。
- `type=workload` 回 `{"browseable": false}`，前端顯示「請輸入關鍵字搜尋」。
- 不做 per-label workload 使用數（使用者核可捨棄）。

### 4.3 查詢層新 key（capability matrix 註冊 native）

| key | 型別 | 內容 | 行為 |
|-----|------|------|------|
| `services` / `ex_services` | list | service href（pill 另存名稱供顯示） | 查詢時經 `service_ports_cache` 展開為該 service 全部條目（port/proto、port range、windows_service_name、process_name——payload 組裝層已支援這些形狀），append 進 `services.include/exclude`，條目間 OR（PCE 語意）。**前置：擴充 `update_label_cache` 的快取建構**，把 `windows_services` 條目與純 proto 條目一併收進 `service_ports_cache`，且有任一條目即入快取（移除「必須有 port」守門），展開才完整 |
| `ports` / `ex_ports` | list | 字串：`80`、`443/tcp`、`1000-2000/tcp` | `_parse_port_range_entry` 擴充接受單一 port（`80` → `{"port": 80}`、`443/tcp` → `{"port": 443, "proto": 6}`） |

- 既有 scalar `port`/`proto`/`ex_port`/`port_range(s)` 全部保留（讀取相容），新寫入一律走新 list key。
- href 解析失敗（service 被刪）走既有 `_record_unresolved` 降級。
- 空 service（展開後 0 條目）視同 unresolved，不送空 `services.include`（避免意外全量查詢）。
- 展開後條目數設上限（仿 `_LABEL_OR_EXPANSION_CAP` 樣式），超過記 diagnostics 並降級 client-side。

### 4.4 cache 讀取路徑（df_filter）

- service href 在**進 df_filter 前**由查詢組裝層（有 ApiClient 處）展開成 port 條目清單；df_filter 維持離線純函式。
- df_filter 新增：port range 比對、`port/proto` 成對比對、`ex_ports` 排除語意（目前只有單 port int）。
- 名稱型條目（windows_service_name/process_name）在 cache 路徑**無法**以 port 比對：展開時僅取 port/proto 型條目進 df_filter，名稱型條目忽略並記 diagnostics（native 路徑不受影響，照常送 PCE）。

## 5. 前端設計（FilterBar）

### 5.1 服務類別

- 新類別「服務」，**無方向概念**：pill 一律中性樣式（不帶來源/目的色），pill 小選單只有「包含/排除」與移除，無改方向。方向分段按鈕對服務 pill 不生效。
- 打字搜尋走 suggest；輸入合法 port 語法時比照 IP/CIDR 出現置頂候選「加入 Port」，非法（port > 65535、亂字串）不出現。
- 序列化：service pill → `services`/`ex_services`；port pill → `ports`/`ex_ports`。`setFilters()` 反序列化含舊 scalar `port`/`ex_port`（舊 config 轉 pill 顯示）。
- options 加 `allowServices`：流量相關落點開啟（流量分析器、即時報表、排程報表、Dashboard 儲存查詢、traffic/bandwidth 規則）；workload 搜尋、事件檢視器不開。
- 流量分析器現有 `qt-port` 文字欄位移除，由 pill 取代（後端讀取端保留 `port`/`ex_port` 相容）。

### 5.2 瀏覽（案 C 混合，互動 mockup 已由使用者選定）

- **空輸入下拉**：點進輸入框未打字 → 下拉顯示類別 chip 列（含總數）。點 chip → 該類別分組清單（label 依 key 分組），每批 20 筆＋「載入更多」接 browse 端點；點項目即成 pill，下拉不關閉可連續加。取代現有「無輸入顯示類別捷徑」（chip 即捷徑，行為向下相容）。
- **Modal 物件庫**：下拉底部固定入口「在視窗中瀏覽全部…」。含類別分頁、內建搜尋框、分頁表格、勾選多選、「加入為來源/目的 pill」（服務分頁無方向選擇）。workload 分頁顯示「請輸入關鍵字搜尋」。沿用既有 dialog 樣式與 CSP 規範（`data-action` 分派、無 inline script）。
- 降級：browse 5xx → 下拉/modal 顯示錯誤列，打字搜尋照常（等於現行體驗）。

### 5.3 i18n 與樣式

- 新鍵 `gui_fb_svc_*`、`gui_fb_browse_*` 雙語同步；JS 引用鍵以稽核測試守護。
- pill 與摘要過長 ellipsis 處理、不無聲截斷（專案截斷規範）。樣式進 `app.css` 沿用 `objfb-*` token。

## 6. CLI 設計（object_picker）

- `_CAT_ORDER` 新增「服務（PCE 物件）」與「Port（手動）」。
- 服務類別：questionary autocomplete，候選自 service 快取（名稱＋port 摘要），與 Web 同語意；PCE 離線退回手動輸入並提示。
- Port 類別：直接輸入，與前端共用同一套解析規則驗證三種語法。
- 不做 modal/瀏覽（autocomplete 清單即可瀏覽全部候選）。
- `picked_to_flat_filters` 序列化同前端 key；`legacy_rule_to_preselected` 支援舊 port 欄位轉 pill。
- 落點：traffic/bandwidth 規則精靈、`pce_cache_cli` traffic filter。

## 7. 資料流與相容性

```
輸入/瀏覽/勾選 → pill {cat: service|port, name, href?, raw?, neg}
  → 扁平 filter dict（services、ex_services、ports、ex_ports）
  → build_traffic_query_spec（native 分流）
      ├→ native：href 展開 → services.include/exclude
      └→ cache：組裝層展開 → df_filter（range/proto 比對）
```

- **零遷移**：舊 config 的 scalar port key 讀取端全保留；排程報表、儲存查詢既有 port 設定不改檔即可執行。
- **展開時機定案**：pill/config 存 href、每次查詢時展開（PCE 上改 service 定義，排程報表自動跟上；與 label/iplist pill 行為一致）。

## 8. 錯誤處理

| 情境 | 行為 |
|------|------|
| service 快取未填且 PCE 離線 | 服務類別回 `pce_unreachable`，下拉顯示錯誤列；手動 port 不受影響（純本地解析） |
| service href 失效（物件被刪） | `_record_unresolved` 降級記 diagnostics；pill 顯示警示樣式（沿用既有 unresolved 處理） |
| service 展開後 0 條目 | 視同 unresolved，不送空 services.include |
| 非法 port 語法 | 不出現「加入 Port」候選、Enter 無作用；CLI 拒絕並提示格式 |
| browse 端點 5xx | 下拉/modal 錯誤列，打字搜尋照常 |
| 展開條目數超上限 | 記 diagnostics、降級 client-side |

## 9. 測試

1. 後端：suggest service 類型（分組/摘要/離線降級）；browse 分頁、label 依 key 分組、workload 不可瀏覽、`total`、限流。
2. 查詢層：`services` 展開 payload 斷言（含 windows_service_name、空 service、href 失效、上限降級）；`ports` 三種語法（含新單一 port）；舊 scalar key 迴歸。
3. df_filter：range/proto 成對比對、`ex_ports` 排除。
4. 前端：`test_component_filter_bar.py` 擴充（服務 pill round-trip、舊 port config 讀入）、CSP 稽核、i18n 雙語稽核。
5. Playwright E2E：空輸入瀏覽 → 點類別 → 載入更多 → 成 pill；modal 多選加入；打 `443/tcp` 成 pill 送查詢。
6. CLI：mock questionary 服務/Port 類別流程。
7. 交付前測試機（172.16.15.106）真實 PCE 走一遍：選 service 物件查流量、手動 port、手動 IP/CIDR（一併完成 IP 輸入驗證），逐頁檢查無截斷/溢出並附回報。

## 附錄：需求決策紀錄

| 決策點 | 選擇 |
|--------|------|
| UI 呈現 | 整合進 FilterBar 新增「服務」類別（不另留獨立 port 欄位） |
| 套用範圍 | 全部流量相關落點（Web 5 處＋CLI 3 處） |
| 展開時機 | 存 href、查詢時展開 |
| 手動 port 語法 | 全支援（`80`、`443/tcp`、`1000-2000/tcp`） |
| 瀏覽互動 | 案 C 混合：空輸入下拉快查＋modal 物件庫深挖（mockup 比選） |
| workload 使用數 | 捨棄（成本過高） |
| workload 全量瀏覽 | 不做，維持打字搜尋 |
