---
title: PCE domain 須知（vendor 事實集）
audience: [developer]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - src/api/traffic_query.py
  - src/api_client.py
  - src/api/async_jobs.py
  - src/api/labels.py
  - src/api/reports.py
  - src/analyzer.py
  - src/report/policy_diff_report.py
  - src/report/policy_resolver_report.py
  - src/report/analysis/policy_resolver.py
  - src/report/rule_hit_count_generator.py
---

# PCE domain 須知（vendor 事實集）

本文件收錄本專案累積的 Illumio PCE vendor 知識——**無法從程式碼反推、踩過坑才知道**的事實。每條事實標注來源等級：

- `[真機驗證]`：本專案對真實 PCE（25.2.40）實測確認，repo 內有對應程式碼錨點。
- `[官方文件]`：已逐條對 Illumio 官方文件（NotebookLM Illumio 筆記本，2026-07-17 查證）確認。
- `[推測待驗]`：合理推測，尚未經真機或官方文件確認，引用前需自行驗證。

架構與模組全貌見 [architecture.md](architecture.md)。文末「[本專案對應防護](#本專案對應防護)」列出每條事實在 repo 內的落地位置。

---

## 1. Policy 模型

### 1.1 draft vs active 與 provision 生命週期 `[官方文件]`

可 provision 的物件（ruleset、rule、IP list、service、label group 等）同時存在兩個版本：

- **`/sec_policy/draft`**：工作中的未提交狀態。所有寫入（POST／PUT／DELETE）都必須打 draft 版本。
- **`/sec_policy/active`**：目前實際生效的策略，**唯讀**——只能 GET，不能直接修改 active 物件。

draft 的變更不會立即影響 workload；必須執行 provision（`POST /sec_policy`）才會轉為 active。PCE 內部的 provision 流程分四階段：資料庫提交 → 以 label scope 對 workload 做策略計算 → label 解析為 IP 並編譯 host 防火牆規則（iptables／nftables／WFP）→ 通知受影響的 VEN 拉取套用。每次 provision 都存成帶時戳的版本，可稽核、可還原。

### 1.2 Rule 動作語意與優先序 `[官方文件]`

Illumio 是 allowlist 模型，rule 動作分三種，衝突時優先序固定：

| 優先序 | 動作 | 語意 |
|--------|------|------|
| 1（最高） | `override_deny` | 無條件封鎖，**任何 allow 都蓋不過**。用於緊急封鎖（資安事件、全域封高風險 port）。 |
| 2 | `allow` | 明確放行。**可蓋過一般 deny**——deny 擋的流量若有 allow 明確放行，結果是放行。 |
| 3（最低） | `deny` | 封鎖已知問題流量；只在沒有 allow 明確放行時生效。Zero Trust 導入早期常用，成熟後逐步被 allow 規則取代。 |

### 1.3 Enforcement mode 四態 `[官方文件]`

Workload 的 enforcement mode 決定 VEN 對原生 OS 防火牆的介入程度（API 值域：`idle`／`visibility_only`／`selective`／`full`）：

- **`idle`**：VEN 不接管 OS 防火牆、不擋任何流量，僅每 10 分鐘取一次流量快照回報 PCE（snapshot 模式）。
- **`visibility_only`**（舊稱 Illuminated）：持續記錄即時 flow、不擋流量；用於建依賴地圖與測試策略。
- **`selective`**：只對策略明確指定的 inbound port／service 執行封鎖，其餘維持 visibility；**只管 inbound，outbound 不管**。
- **`full`**：inbound 與 outbound 全面執行；未被 provision 過的 allow 規則放行的流量一律封鎖。

### 1.4 API 調得到但 GUI 看不到的 policy 面向 `[真機驗證]`

PCE GUI 只呈現 policy 資料的一部分；以下是本專案靠 API 補上的實例：

- **物件層 policy diff**：GUI 的 provision 預覽只列「有異動的物件清單」，不做逐欄位 diff。本專案對每類物件分別以 `pversion="draft"` 與 `pversion="active"` 抓兩份集合做結構化 diff（`src/report/policy_diff_report.py`）。
- **deny rules 的展開**：GUI Explorer 與 ruleset 畫面不會把 deny／override_deny 規則展開成「哪些 IP 對會被擋」；本專案的 Policy Resolver 報表把 active ruleset（含三種動作）全部解析成平面 IP 列（`src/report/analysis/policy_resolver.py`）。
- **draft 物件的 API 形狀**：同一物件的 draft href 與 active href 只差路徑段（`/draft/` vs `/active/`），跨版本關聯要靠 href 置換對映，GUI 完全不暴露這層（`src/report/policy_diff_report.py` 的 href 對映註解）。
- **scope／exclusion 語意**：ruleset scope 內的 entries 取 AND、多個 scope 取 OR、`exclusion: true` 的 entry 是「交集後扣除」而非聯集——這套語意 GUI 不會明示，本專案在 `_scope_ip_set()` 逐條實作並以真機驗證（歷史 bug：舊實作誤用 label href 比對，帶 scope 的 ruleset 恆解析為 0 列）。

---

## 2. Traffic 與 Explorer

### 2.1 policy_decision 值域是四值，預設漏掉 unknown 數字會大幅偏低 `[真機驗證]`

Traffic flow 的 `policy_decision` 值域是 **blocked／potentially_blocked／allowed／unknown** 四值，不是三值。`unknown`（原始資料中 `pd=3`）涵蓋：

- idle／snapshot 模式 VEN 回報的流量（VEN 沒接管防火牆，PCE 無從判定決策）；
- Flowlink 或 bulk-upload API 匯入的未管理流量。

查詢時若只帶前三值（許多範例程式的寫法），unknown 流量整批消失，環境內 idle VEN 或 Flowlink 越多、總量偏低越嚴重。本專案自 2026-07-16 起所有未明確指定 policy decisions 的查詢**預設含 unknown**（`src/analyzer.py` `query_flows` 預設值）；在此之前快取／回填的 traffic 資料不含 unknown，需要時要重跑 cache backfill。

### 2.2 draft_policy_decision 是查詢時 on-demand 計算 `[官方文件]`

`policy_decision`（reported）是 VEN 當下記錄的靜態歷史值；`draft_policy_decision` 則是 PCE 在查詢執行當下，把歷史 flow 套上目前 draft 策略做的 what-if 模擬，**不隨 flow 儲存**。因此：

- 帶 draft decision 的查詢明顯比 reported 慢（PCE 要現算 rule coverage）；
- 同一批 flow 在不同時間查，draft 值可能不同（draft 策略變了）；
- 想用 draft decision 過濾時，reported 端要查全量再由 draft 值篩，不能預先縮小 reported 範圍（本專案 `src/analyzer.py` 的 draft 過濾即如此處理）。

### 2.3 Async traffic query 全流程 `[真機驗證]`

大量 traffic 資料唯一可靠的取法：

1. `POST /traffic_flows/async_queries` 提交查詢 spec（本專案 `max_results` 帶 200000，見 `src/api/traffic_query.py` `MAX_TRAFFIC_RESULTS`）。
2. PCE 回 202 與 job href。
3. 輪詢 job 直到 `status == "completed"`（注意：**這裡是 completed，與 Jobs API 的 done 不同**，見 3.1）。
4. 從結果 href 下載 **gzip 壓縮的 JSON**，解壓後才是 flow 陣列（`src/api/traffic_query.py` 下載段）。

全環境無過濾的查詢在 PCE 端可能算好幾分鐘；本專案輪詢上限設 900 秒（`_ASYNC_QUERY_MAX_WAIT_SECONDS`，歷史教訓：舊的 120 秒預算在大環境會靜默回 0 筆）。

---

## 3. API 行為實測事實

### 3.1 兩套 async 機制的終態字彙不同 `[真機驗證]`

- **Jobs API**（`/orgs/N/jobs`，即 `Prefer: respond-async` 集合 GET 與 rule hit count report 走的機制）：成功終態是 **`done`，不是 `completed`**（`src/api_client.py` `_async_collection_get` docstring 明載此 vendor 事實）。
- **Async traffic query**（`/traffic_flows/async_queries`）：成功終態是 **`completed`**；失敗終態含 **`failed`／`cancel_requested`／`cancelled`／`canceled`**（注意兩種拼法都會出現，`src/api/async_jobs.py` 輪詢處逐一列舉）。

拿錯字彙輪詢的結果是永遠等到 timeout。

### 3.2 同步集合 GET 硬上限 500 筆，超限靜默截斷 `[官方文件]`

同步集合 GET 最多回 **500** 個物件。超過時 PCE **不報錯、不分頁**，直接截斷只回 500 筆。要拿完整集合必須走 async：GET 加 `Prefer: respond-async` header 轉為背景 job。官方另提供探測技巧：先帶 `max_results=1` 查一次、讀 `X-Total-Count` header 判斷總量是否超過 500（但見 3.3 的過濾陷阱）。

### 3.3 X-Total-Count 在帶 query filter 時回「未過濾」總數 `[真機驗證]`

帶 query filter 的集合 GET（如 `workloads?managed=true`），`X-Total-Count` 回的是**未過濾的全集合總數**，不是過濾後筆數。PCE 25.2.40 真機實測：回 20 列 managed workload、header 卻是 30（全 workload 數）。因此「header > 實收筆數」**不能**直接當截斷訊號；本專案的截斷判準是「實收筆數達 500 上限**且** header 更大」才觸發（`src/api_client.py` `_get_collection`）。

### 3.4 `Prefer: respond-async` fallback 全流程 `[真機驗證]`

集合 GET 截斷時的官方補救流程，本專案已實作並真機驗證：

1. 對同一 path 發 GET，headers 帶 `Prefer: respond-async`；預期 **202**，回應 headers 含 `Location`（job href）與 `Retry-After`。
2. 輪詢 `GET /api/v2{job_href}` 直到 body `status == "done"`（見 3.1）；`failed` 或逾時放棄。
3. `done` 後從 body 的 `result.href` 取得 datafile href，下載完整 JSON 陣列。

### 3.5 日期參數必須是完整 ISO 時戳，純日期回 406 `[真機驗證]`

帶日期的 API 參數（如 rule hit count report 的區間）給純 `YYYY-MM-DD` 會被 PCE 以 **406** 拒絕，必須展開成完整 ISO-8601 時戳（`2026-07-17T00:00:00Z`）。真 PCE 25.2.40 實測；本專案在 `src/api/reports.py` `_to_iso_timestamp()` 統一展開。同場加映兩個真機驗證的 406 形狀陷阱（`src/api/traffic_query.py`、`src/api/labels.py` 註解）：

- traffic query 的 `ip_address` native actor 只吃 plain string，包成 `{"value": ...}` 會 406 且被 stream 層吞掉、靜默回 0 筆；
- `destinations.include` 的 actor schema 不接受 transmission entry（unicast／broadcast／multicast 得 client 端過濾），硬塞會 406。

### 3.6 429 可安全重試一次，但 POST 絕不可交給傳輸層自動重試 `[真機驗證]`

收到 **429** 代表 PCE 已回應、**尚未實際處理**這次請求，單次重試安全。但 POST 不可放進 urllib3 Retry 的 allowed_methods：read-timeout 後傳輸層自動重送 POST 時，PCE 可能已處理完第一次請求，provision／create 類端點會**重複執行**。本專案的 Retry 設定 `allowed_methods` 只含 GET／HEAD／PUT／DELETE，429 的補償改在 `_request()` 內做應用層單次重試（`src/api_client.py`）。

### 3.7 Traffic 查詢的 label group 過濾只能交給 PCE 端展開 `[真機驗證]`

Flow 紀錄裡只有 workload 的 label，不帶 label group 成員資訊，client 端**無法**拿 flow 資料本地比對 label group。可靠做法是把 label group href 塞進查詢 spec 的 `sources/destinations.include`，由 PCE 原生展開成員（`src/api/traffic_query.py` `_TRAFFIC_FILTER_CAPABILITIES` 中所有 label_group 鍵皆標 `native`、無 client fallback）。若確實需要 client 端成員清單（如 Policy Resolver 解析 scope），必須另抓 label_groups 集合遞迴攤平巢狀成員（`src/report/policy_resolver_report.py` `build_label_group_to_labels()`）。

---

## 4. Rule Hit Count `[官方文件]`

以下條件全數經官方文件確認：

- **版本門檻**：SaaS PCE 24.2.0+；地端 PCE 23.5.10+；VEN 23.2.30+。
- **只計 Active 規則**：draft／未 provision 的規則不計；Illumio 平台自身運作所需的 essential rules 也排除在外。
- **保留期**：hit count 資料保留 **90 天**（最舊資料滾動丟棄）；「Last Hit」時戳則保留至 PCE 生命週期結束。
- **規則最佳化可能高估**：PCE 寫入 host 防火牆時會合併最佳化規則，原本不重疊的規則在 host 層可能重疊——單一 flow 可能同時遞增多條規則的計數。
- **每 flow 最多歸因 100 條**：單筆 flow 回報最多帶 100 個 rule ID，超過即截斷。
- **hit 與 flow 計數語意不同**：Explorer 的 flow 數是端到端連線數；rule hit 是 VEN 上防火牆規則被命中的次數。兩端都有 VEN 的連線，src 與 dst VEN **各自**回報一次——單一 flow 常對應 hit count 2。加上重疊規則全報，hit 數不能直接當流量數解讀。

本專案的 Rule Hit Count 報表只用 VEN 原生量測資料（native pull 或 PCE UI 的 CSV 匯出），不做流量近似推算——那是 Policy Usage 報表的職責（`src/report/rule_hit_count_generator.py` 檔頭）。報表清理門檻 90 天即對應官方保留期（`CLEANUP_DAYS_THRESHOLD`）。

---

## 本專案對應防護

每條 vendor 事實在 repo 內的落地位置（防止知識只存在文件裡）：

| vendor 事實 | repo 落地位置 |
|-------------|----------------|
| policy_decision 四值、預設含 unknown | `src/analyzer.py` `query_flows` 預設 policy_decisions（含值域註解）；`CHANGELOG.md` Unreleased 遷移說明 |
| draft 物件 API 形狀（pversion、href 置換） | `src/report/policy_diff_report.py`（`pversion="draft"` 抓取、`/draft/` 與 `/active/` href 對映） |
| deny／override_deny 展開、scope AND-OR、exclusion 扣除 | `src/report/analysis/policy_resolver.py` `_scope_ip_set()` 與 action 欄解析 |
| draft decision 過濾須查全量 reported | `src/analyzer.py` draft 過濾段（查全 reported PD 再篩 draft 值） |
| Jobs API 終態 `done` | `src/api_client.py` `_async_collection_get()`（docstring 明載＋輪詢實作） |
| async traffic query 終態 `completed`／四種失敗態 | `src/api/async_jobs.py` `_wait_for_async_query()` 終態列舉；`src/api/traffic_query.py:756、1621` |
| 集合 GET 500 上限與截斷偵測 | `src/api_client.py` `_get_collection()`（`max_results` 一律 500、截斷記錄）；`tests/test_api_collection_truncation.py` |
| X-Total-Count 未過濾總數陷阱 | `src/api_client.py` `_get_collection()` 截斷判準（實收達 500 才視為截斷）＋行內註解（PCE 25.2.40 實測數字） |
| respond-async fallback 流程 | `src/api_client.py` `_async_collection_get()` |
| 日期參數 406 | `src/api/reports.py` `_to_iso_timestamp()` 與行內註解 |
| ip_address／transmission 的 406 形狀陷阱 | `src/api/labels.py` `_resolve_ip_filter_to_actor` 註解；`src/api/traffic_query.py` `_TRAFFIC_FILTER_CAPABILITIES["transmission"]` |
| 429 單次重試、POST 排除自動重試 | `src/api_client.py` `Retry(allowed_methods=...)` 註解與 `_request()` 429 補償 |
| label group 只能 PCE 端展開 | `src/api/traffic_query.py` `_TRAFFIC_FILTER_CAPABILITIES`（label_group 鍵全 native）；`src/api/labels.py` `_resolve_label_group_filter_to_actor()`；`src/report/policy_resolver_report.py` `build_label_group_to_labels()` |
| async query 逾時與筆數上限 | `src/api/traffic_query.py` `MAX_TRAFFIC_RESULTS = 200000`、`_ASYNC_QUERY_MAX_WAIT_SECONDS = 900` |
| rule hit count 90 天保留、只計 Active | `src/report/rule_hit_count_generator.py` `CLEANUP_DAYS_THRESHOLD = 90`、draft→active href 正規化；`src/report/rule_hit_count_enablement.py` 啟用檢查 |
