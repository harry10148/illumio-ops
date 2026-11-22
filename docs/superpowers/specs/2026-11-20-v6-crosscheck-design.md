# 交叉檢查工具：事件、告警、報表數字對 PCE 原始資料

日期：2026-11-20 ｜ 狀態：使用者提出需求，設計待審
標記：【使用者】使用者說的；【判斷】我的決定。

## 1. 為什麼

使用者原話：「我想要完整的驗證事件可靠和準確還有報表的數字……先用 api 去撈出所有事件，內建 event filter list 應該有全事件，
然後跟現在的告警比較作交叉檢查，接著再去驗證報表，你用 query raw 來去比對報表有沒有出入」【使用者】。

過去的缺陷大多是「測試全綠、真跑才發現」（[[running-it-finds-what-gates-cannot]]）：測試用的是我們自己造的資料，驗不到「跟 PCE 對不對得上」。
這個工具拿 PCE 的原始資料當標準答案，對本系統收到的、算出的、報出的東西逐項比對。

## 2. 目標、非目標、反目標

**目標**

1. 事件：PCE API 的全部事件 vs 內建事件清單（294 種）vs 本系統收進來的事件。
2. 告警：用 PCE 原始事件，照目前啟用的事件規則獨立重算，對實際告警紀錄找漏報與沒有事件支撐的告警。
3. 報表：每份報表的關鍵數字（KPI）用 PCE 原始流量查詢（async traffic query）或 API 獨立重算，列出差異。
4. 可重複執行：做成產品裡的命令列工具，之後每次升級或懷疑數字時都能再跑【判斷】。

**非目標**

- 不修任何發現的缺陷（發現的列成清單，另外排）。
- 流量規則與偵測（橫向移動、異常）的告警這一版不重算：要先有報表那段的原始流量查詢，第二版再做【判斷】。
- 不做排程、不做畫面：命令列跑、輸出檔案。

**反目標**

- **檢查器呼叫了它要檢查的程式**：那只會證明程式跟自己一致。檢查器不可 import `normalize_event`、`event_matches`、`eventsource`、`flowsource`、
  報表產生器、偵測器；只可用 `PceClient`（傳輸層）、設定讀取、資料庫連線。比對邏輯自己寫，寫得比產品簡單也沒關係，寫不出來的情況列成「沒檢查」。
- 對 PCE 寫入任何東西。例外只有 async traffic query 本身：建立與輪詢查詢、對本工具建立的查詢呼叫 `update_rules`（PUT，取得 draft 判定）、刪除本工具建立的查詢（DELETE）。報表本來就做同樣的呼叫，這些都是讀取用途【使用者 2026-11-20：lab 與 NFR 都允許】。
- 寫入本系統的資料庫（一律唯讀開啟 `mode=ro`）。
- 把「沒檢查」說成「沒問題」：每一項輸出都要分「一致」「不一致」「沒檢查（原因）」。

## 3. 怎麼跑

```
sudo -u illumio-ops env PYTHONPATH=/opt/illumio-ops PYTHONNOUSERSITE=1 /opt/illumio-ops/python/bin/python3 \
  -m illumio_ops.crosscheck all --days 7 --out /var/tmp/crosscheck-<日期>
```

- 子命令：`events`、`alerts`、`reports`、`all`。`--days` 預設 7；期間結尾取「現在減 30 分鐘」，避開還沒收到的晚到資料（[[pce-traffic-late-arrival]]）。
- 在服務執行中跑（不拿服務鎖）；讀設定檔取得 PCE 連線。
- 輸出：`report.md`（給人看）＋`findings.json`（給程式比對）；有不一致時結束碼 1，否則 0。
- 跟 `rescue` 一樣是允許 print 的模組（現有「只有 rescue 能 print」的閘門要加這一個）。

## 4. 檢查內容

### 4.1 事件

```
PCE /events（期間切到不被 10,000 筆上限截斷為止；上限時 PCE 只回最新的，必須再切）
  ├─ event_type 不在內建事件清單 → 「清單漏掉的事件類型」（附筆數與一筆範例的欄位名，不印內容值）
  ├─ 內建清單有、但期間內 PCE 沒出現 → 只列計數，不算錯
  └─ 依 href 對本系統 events 表
       ├─ PCE 有、本系統沒有 → 漏收（扣掉收集關閉、保留期限外的時段，那些列為「沒檢查」）
       └─ 本系統有、PCE 沒有 → 多收（可能是 PCE 已刪除的事件；列出不判定）
```

### 4.2 告警（事件規則）

- 只比對**目前啟用的事件規則**；規則在期間內改過的話以現在的為準，報告開頭寫明這個限制【判斷：設定沒有歷史】。
- 獨立比對器支援：確切類型、`a|b`、`*`；`status`／`event_severity` 的全部、單值、`|` 串；`error`＝`err`。
  用到正規表示式、`!`、`match_fields` 的規則列為「沒檢查」。
- 每個符合的 PCE 事件，要能被解釋：同一條規則有一筆告警的 `[first_seen, last_seen]` 包含它；或那條規則在冷卻或頻率限制期間內
  （同規則前一筆告警的 `fired_at` 加冷卻／限制期間涵蓋它）；或它早於規則的評估起點。都不是 → 「可能漏報」。
- 每筆告警，期間內要找得到至少一個符合的 PCE 事件落在它的 `[first_seen, last_seen]` → 找不到 → 「沒有事件支撐」。
- 累積次數規則：每筆告警在 `[fired_at − window, fired_at]` 內符合的 PCE 事件數要 ≥ 門檻；不夠 → 「門檻不足」。
- 告警的主體（主機）比對這一版不做，只比對規則層級【判斷：主機對應要重寫一套 host 解析，先求規則層級對得上】。

### 4.3 報表

- 第一步是盤點：16 種報表的每一個 KPI，讀程式寫下它的定義、資料來源、能不能從 PCE 原始資料獨立重算。這張表放進報告與本文件附錄。
- 能重算的：在同一期間用 PCE async traffic query（不經 `flowsource`）或 PCE API 自己算，對本系統**最近一份完成的同型報表**的 `kpis_json`；
  期間不同時改成用那份報表的期間查。數字容許差異：流量類因晚到資料可能有差，報告寫出差異量與百分比，不設門檻自動判對錯【判斷】。
- 不能重算的（例：依本系統自己的偵測或快照算出的）列為「沒檢查」並寫原因。
- 每份報表的原始查詢條件與筆數寫進報告，方便人工複查。

## 5. 驗收

- 單元測試：獨立比對器對各種規則寫法；期間切分遇到上限會再切；漏收／多收／漏報／沒有事件支撐的判斷；唯讀開啟（寫入會失敗）。
- 守門測試：`illumio_ops/crosscheck` 不 import 反目標列出的模組（AST 檢查）；先注入缺陷確認會紅。
- 在 .106 對 lab PCE 跑一次 `all --days 7`，報告交給使用者，逐項說明不一致的是工具錯還是產品錯。
- NFR（.135）不跑，除非使用者同意（唯讀，但會建立 async query）。

## 6. 我替使用者做的決定

1. 做成產品內的命令列工具（`python -m illumio_ops.crosscheck`），不是一次性腳本。
2. 流量規則與偵測的告警重算放第二版。
3. 告警只比對到規則層級，不比對主機。
4. 報表數字差異只列出、不設自動判定的門檻。
5. 期間結尾預設留 30 分鐘給晚到資料。

## 附錄 A：報表 KPI 盤點

盤點日期 2026-11-20，對 `feat/v6-crosscheck`（基底 6.12.5）的程式逐一讀出。範圍是 `illumio_ops/services/reports/registry.py`
的 16 種報表，加上 policy_usage 報表裡原本是 rule_hit_count 的那一章（`ReportType.RULE_HIT_COUNT` 已退役，見 `registry.py:138` 的 `RETIRED`）。
行號指的是這個分支的檔案。

### A.0 總結

| | 數量 |
|---|---|
| KPI 總數（16 種報表＋RHC 章） | 93 |
| 可（yes） | 14 |
| 部分（partly） | 53 |
| 否（no） | 26 |

- **custom** 沒有 KPI（`custom.py:161` 的 `kpis=()`），不列表。
- 三種判定的意思：
  - **可**：在那份報表的期間，用 PCE 原始資料直接重算，定義不依賴本系統自己的推導；差異只來自晚到資料，或期間之後 PCE 上的刪改。
  - **部分**：能重算，但要另寫產品的某段規則（流量配對、管理 port 清單、label 對應），或只能拿「現在」的 PCE 狀態去比（盤點類、政策類），或要用 PCE 的 draft 重算。
  - **否**：本系統自己的分析、評分、偵測、規則引擎或告警的輸出，或要寫入 PCE 才拿得到。
- 可直接重算的 14 個：audit 的 8 個、traffic 的 sources 與 destinations、unmanaged 的 total／private／public、weekly_overview 的 provisions。

### A.1 共通定義（各表引用，不再重複）

**F（流量類）**：本系統的流量數字讀 flows 表的「主要列」（`is_primary = 1`）。
- **期間**：`last_detected >= start AND first_detected <= end`（`domain/filter.py:439`），是重疊判斷，報表的 end 不含。
- **期間邊界**：報表期間是顯示時區的整天，存成 UTC（`generate.py:79-95`）。
- **一列是什麼**：一列就是 PCE 回傳的一筆 traffic record（`domain/flows.py:97-145`）。
  - 主要列：同一個 4-tuple、方向相反、時間相距不超過 600 秒的兩筆配成一對，保留 outbound 那筆；配不到的各自算主要列（`domain/flows.py:188`）。
  - 端點鍵：`workload.href`，沒有 href 時是 `ip:<位址>`（`domain/identity.py:21-23`）。
  - managed 旗標：取 record 裡 `workload.managed`（`domain/flows.py:128`）。
- **record 的時間單位**：PCE 以 UTC 日彙總 record，視窗碰到哪一天就回那天整天的次數（`collect/windows.py:48-54`）；本系統不讓查詢跨 UTC 午夜。所以期間頭尾若落在 UTC 日中間，那兩天會整天算進去。
- **上限**：收集每次查詢上限 200,000 筆、每次一小時（`collect/traffic.py:51`、`collect/windows.py:11-13`）；同一筆 record 重抓時以 `record_key` 合併，次數取大（`domain/flows.py:146-185`）。
- **獨立算法**：
  - 對期間碰到的每個 UTC 日各送一次 async traffic query（`traffic_payload`，`pce/async_query.py:46-60`）：`start_date`＝當日 00:00:00Z，`end_date`＝當日 23:59:59Z，`policy_decisions: []`（全部），`sources/destinations include [[]]`，`max_results` 200,000。
  - 若回傳筆數 ≥ 上限（`capped`，`async_query.py:161`），就切小時窗再查；切到最小仍滿的，該報表列為 unchecked。
  - 自己做配對（與產品相同規則的簡化版），再依各 KPI 計算。
- **報表有 filter（`params_json.filter`）**：能譯成 payload 的條件（labels、IP、port/proto、decision）帶進查詢；帶不進的（process、user、文字、windows service 等）該報表 unchecked。
- **已知差異來源**（所有 F 類共用）：
  - 晚到流量：lab 實測最多約 18 分鐘，收集時抓不到、重算時抓得到。
  - 配對規則的簡化版與產品不同。
  - record 上的 labels 是查詢當時的 labels，報表產出後 label 改過就會不同。
  - PCE 對較舊的流量以週彙總（`flowsource.py:595-599`）：期間早於約兩週時，日 record 變週 record，次數不可比，列 unchecked。

**I（盤點類）**：讀 inventory 表，也就是收集器 `GET /workloads?managed=true` 的結果（`collect/inventory.py:306`）。
- 這是報表產出「當時」的狀態；重算只能拿「現在」去比。
- 差異來源：報表產出後的配對、解除配對、模式或 label 變更。所以 crosscheck 只在報表剛產出時比才有意義。

**E（事件類）**：讀 flows DB 的 `events` 表。期間是 `timestamp >= start AND < end`（`eventsource.py:231-232`）。
- 獨立算法：`GET /events`，用與事件區相同的抓取方式（切期間、依 href 去重）。
- 差異來源：漏收或多收（由事件區負責），以及 PCE 刪除的事件。

**D（draft 重算類）**：async traffic query 之後再呼叫 `update_rules` 取得 draft 判定（`pce/async_query.py:3`、`:121`，`compute_draft=True`）；產品查完會刪掉這個查詢。
- **已決定（使用者 2026-11-20）**：允許。對本工具建立的查詢呼叫 `update_rules`（PUT），並刪除該查詢（DELETE，一定放在 `finally`）；lab 與 NFR 都適用，因為產品產出 policy_usage／readiness 報表時本來就做同樣的呼叫。刪除失敗時在 report.md 列為殘留，附上查詢的 href。
- 差異來源：報表產出後 draft 被改過。

### A.2 weekly_overview（`weekly_overview.py`）

| KPI | 標籤（zh／en） | 單位 | 定義（file:line） | 產品來源 | 重算 | 獨立算法與差異 |
|---|---|---|---|---|---|---|
| `new_alerts` | 本期告警／Alerts this period | count | 本 PCE（pce_url、org_id）`fired_at ∈ [start, end)` 的所有告警，各嚴重度加總；`grouped` 不另算（`weekly_overview.py:171-176`、`:258`；`store/alerts.py:112-115`、`:165-174`） | alerts 表 | 否 | 是本系統的輸出，不是 PCE 的資料。事件規則那部分已由告警區驗證 |
| `vens_not_online` | 失聯的 VEN／VENs out of contact | count | 受管主機中 bucket 為 lost_24h、lost_48h、long_offline 的數量（`:300-301`；bucket 定義見 A.10） | inventory（I） | 部分 | 現在的 `GET /workloads?managed=true`，依 A.10 的 bucket 重算；只能比「現在」 |
| `pb_connections` | Potentially Blocked 的連線／Potentially Blocked connections | count | 期間內主要列、decision＝potentially_blocked 的 `num_connections` 總和，不套 filter（`:181-182`、`:402`；`flowsource.py:626-630`） | flows（F）；期間不在保留範圍內時自己向 PCE 拉（`:207-233`） | 部分 | F：`policy_decisions: ["potentially_blocked"]`，配對後加總 `num_connections` |
| `critical_high_alerts` | 嚴重與高風險告警／Critical and high alerts | count | 同 `new_alerts`，只算 critical＋high（`:144-145`） | alerts 表 | 否 | 同 `new_alerts` |
| `new_connections` | 新出現的連線／New connections | count | 同 new_connections 報表的 `new`（`:194`，見 A.4） | connection_baseline | 部分 | 見 A.4 |
| `provisions` | 政策 Provision／Policy provisions | count | 期間內 `event_type = sec_policy.create` 的事件數（`:434`；`domain/audit.py:22`）；期間內沒有任何事件時為 None | events（E） | 可 | E：`GET /events` 計 `sec_policy.create`。前期值只在前期事件沒有缺口時才有（`:435`） |

前期值：告警只在 `alerts_known_from` 之後才給（`:148-168`、`:259-260`）；流量前期值需要前期也收齊（`:189-191`）。

### A.3 lateral_posture（`lateral_posture.py`）

| KPI | 標籤 | 單位 | 定義 | 產品來源 | 重算 | 獨立算法與差異 |
|---|---|---|---|---|---|---|
| `assets_reachable` | 可被觸及的重要資產／Critical assets reachable | count | 期間最後一天（或之前）的 exposure 快照 `assets_reachable_now`；沒有快照時用目前 exposure 結果裡 `sources_now` 非空的重要資產數；沒設重要資產就不顯示（`lateral_posture.py:114-139`） | exposure 分析與每日快照 | 否 | 是本系統自己的可達性圖分析（hops、管理 port、重要資產選擇器） |
| `pivots` | 樞紐主機／Pivot hosts | count | 同上，`pivots_now`（`:124`、`:140`） | 同上 | 否 | 同上 |
| `new_detections` | 本期新偵測／New detections | count | 期間內的新偵測數（`:141-142`，由 builder 傳入） | detections | 否 | 是本系統偵測器的輸出 |
| `cross_env` | 跨環境管理連線／Cross-environment management connections | count | exposure 的 `cross_env_edges`／`cross_env_total`（`:125`、`:143`） | exposure | 否 | 同 `assets_reachable` |

### A.4 new_connections（`new_connections.py`）

共通定義：計 `connection_baseline` 表中 `first_seen ∈ [start, end)`、`0 <= port < 49152` 的列（`new_connections.py:47-48`、`:62-65`；`DYNAMIC_PORTS_FROM`，`domain/values.py:423`）。一列是一組（src_key, dst_key, port, proto），由主要流量寫入（`store/flowdb/flows.py:251`、`:289`）；超過 `baseline_days` 沒再出現就刪掉（`flows.py:606`）。

| KPI | 標籤 | 單位 | 定義 | 產品來源 | 重算 | 獨立算法與差異 |
|---|---|---|---|---|---|---|
| `new` | 新出現的連線／New connections | count | 上述全部（`:51-59` kind 為 new 時條件為 `1`） | connection_baseline | 部分 | F：查 `[start − baseline_days, end)`，每個（src_key, dst_key, port, proto）取最早出現的 UTC 日，計首次出現在期間內的數量。差異：產品的 baseline 從安裝或 backfill 才開始（首次出現時間會被「看到的時間」截斷）；PCE 的週彙總讓早期首次出現的時間只精確到週；`baseline_days` 之外刪除的組合會被當成新的 |
| `admin` | 管理 port 的新連線／On management ports | count | 上述且（port, proto）在 lateral context 的管理 port 清單中（`:52-53`） | 同上 | 部分 | 同上，另需管理 port 清單：產品內建 `LATERAL_PORTS_DEFAULT`＋PCE 管理服務＋設定增減（`analysis/context.py:95-97`，`effective_admin_ports`）。crosscheck 不能 import，需自備一份 |
| `critical` | 連入重要資產／Into critical assets | count | 上述且 `dst_key` 是重要資產（設定的 `lateral.critical_assets` 選擇器配主機 labels，`:54-56`、`analysis/context.py:84-90`） | 同上＋inventory | 部分 | 同上，用設定的選擇器配「現在」的 workload labels |
| `unmanaged_source` | 來自非受管來源／From unmanaged sources | count | 上述且 `src_key LIKE 'ip:%'`（來源沒有 workload 物件，`:57-58`） | 同上 | 部分 | 同上，來源端 `workload.href` 為空 |

前期值：只在前期仍在 baseline 保留範圍內、且流量收齊時才有（`:87-93`）。

### A.5 unmanaged_endpoints（`unmanaged.py`）

共通定義：讀 `flow_rollup_daily`，期間涵蓋的 UTC 日（`reads.py:30-33`）。rollup 每天由主要列彙總（`last_detected` 落在那天，`store/flowdb/flows.py:498-505`）。只取一端是 `ip:`、另一端不是的列；「端點」指 `ip:` 那一端（`unmanaged.py:40-44`、`:65-72`）。

| KPI | 標籤 | 單位 | 定義 | 產品來源 | 重算 | 獨立算法與差異 |
|---|---|---|---|---|---|---|
| `total` | 非受管位址／Unmanaged addresses | count | 上述不重複的 `ip:` 端點數，不分 decision（`:107`） | rollup | 可 | F（不必配對：兩個方向的 record 端點相同）：逐日查，取一端沒有 `workload.href`、另一端有的 record，計前者 IP 的不重複數。差異只有晚到與頭尾 UTC 日 |
| `private` | 非公網位址／Non-public addresses | count | 上述中 `ipaddress.ip_address(ip).is_global` 為假的；無法解析的字串也算進來（`:107`；`domain/anomaly.py:61-65`） | 同上 | 可 | 同上，用同樣的 `is_global` 判斷 |
| `admin_sources` | 對受管主機使用管理 port／Using management ports into managed hosts | count | 上述且有「非受管端為來源、在管理 port 上連入受管主機」的列（`:80-88`、`:108`） | 同上 | 部分 | 同上，另需管理 port 清單（見 A.4 `admin`） |
| `public` | 公網位址／Internet addresses | count | 上述中 `is_global` 為真的（`:109`） | 同上 | 可 | 同 `private` |

前期值：前期流量收齊時才有（`:101`、`:104`）。

### A.6 traffic（`traffic.py`）

| KPI | 標籤 | 單位 | 定義 | 產品來源 | 重算 | 獨立算法與差異 |
|---|---|---|---|---|---|---|
| `flows` | 流量筆數／Flows | count | 期間（套 filter）的主要列筆數，含沒有 decision 的（`traffic.py:46-47`、`:59`；`flowsource.py:646`） | flows（F） | 部分 | F，配對後計 record 數。差異：store 每小時重抓並以 `record_key`（含 `first_detected`）合併，一天一個連線可能留下不只一筆（**待確認**：以真資料核對 store 裡每個連線每天的列數）；配對簡化版的差異 |
| `connections` | 連線次數／Connections | count | 同上，`num_connections` 總和（`flowsource.py:646`） | flows（F） | 部分 | F，配對後加總；不配對會把成對的兩筆重複計入 |
| `sources` | 不重複來源／Distinct sources | count | 不重複 `src_key`（`flowsource.py:631`） | flows（F） | 可 | F，不必配對（兩個方向的 src 相同）：不重複的（`src.workload.href` 或 `ip:`＋src.ip） |
| `destinations` | 不重複目的端／Distinct destinations | count | 不重複 `dst_key`（`flowsource.py:631`） | flows（F） | 可 | 同上，用 dst |

前期值：前期流量收齊才有（`traffic.py:61-64`）。沒有流量時四個值都是 None。

### A.7 security_risk（`security_risk.py`）

| KPI | 標籤 | 單位 | 定義 | 產品來源 | 重算 | 獨立算法與差異 |
|---|---|---|---|---|---|---|
| `maturity` | 分段成熟度（0–100）／Segmentation maturity | count | `domain/maturity.py` 的加權分數（Full／Selective 主機比例、allowed、undecided、管理 port、非受管來源、勒索服務），四捨五入（`security_risk.py:105-115`、`:193`、`:220`） | 流量＋inventory＋勒索分析 | 否 | 是本系統的評分公式 |
| `enforced_hosts_pct` | Full 模式的受管主機／Managed hosts in Full enforcement | percent | 範圍內受管主機中 `enforcement_mode == full` 的比例，取一位小數；Selective 不算（`:123-127`、`:168-169`、`:221`） | inventory（I） | 部分 | I：`GET /workloads?managed=true`，套報表 filter 的 label 範圍（`flowsections.host_in_scope`），算 full 的比例。只能比「現在」 |
| `allowed_pct` | 有規則允許的連線（Allowed）／Connections allowed by a rule | percent | allowed 的 `num_connections` ÷ 有 decision（allowed＋potentially_blocked＋blocked）的 `num_connections`（`:94-99`） | flows（F） | 部分 | F，配對後計算；unknown 不算在分母 |
| `pb_flows` | Potentially Blocked 的流量／Potentially Blocked flows | count | decision＝potentially_blocked 的主要列筆數（`:100`） | flows（F） | 部分 | F，配對後計 record 數，差異同 A.6 `flows` |
| `blocked_flows` | 已被擋下的流量（Blocked）／Blocked flows | count | decision＝blocked 的主要列筆數（`:101`） | flows（F） | 部分 | 同上 |
| `unmanaged_connections` | 有判定的非受管來源連線／Connections with a decision from unmanaged sources | count | `src_managed = 0` 且有 decision 的 `num_connections`（`:102`；`flowsource.py:633-634`）。注意 managed 旗標取 record 的 `workload.managed`，所以 PCE 上的非受管 workload 物件也算非受管 | flows（F） | 部分 | F：來源端 `workload.managed` 不為真、decision ∈ 三種，配對後加總 |
| `admin_open_connections` | 未被擋的管理 port 連線／Management-port connections not blocked | count | port 屬於管理 port 中 REMOTE 類，且 decision ∈（allowed, potentially_blocked）的 `num_connections`（`:156`；`flowsource.py:617-619`、`:635`） | flows（F）＋管理 port 清單 | 部分 | F，另需 REMOTE 類管理 port 清單（見 A.4 `admin`）；**待確認**：PCE 管理服務的那部分 port 能否只用 GET 讀到 |
| `critical_high_findings` | 嚴重與高風險發現／Critical and high findings | count | 規則引擎 `findings.run_rules` 輸出中 critical＋high 的數量（`:211-213`、`:223`） | 規則引擎 | 否 | 是本系統的規則與門檻 |
| `ransomware_protected_pct` | 已防護的嚴重／高勒索風險服務／Critical/high ransomware-risk services protected | percent | 勒索分析結果中 severity 為 critical/high、且 `protection_state` 可判的服務裡，`protected*` 的比例（`:130-140`、`:224`；`domain/ransomware.py:24-32`）；有 filter 時只算範圍內主機 | 勒索分析（每小時最新一次） | 部分 | 現在對每台受管主機讀 `GET <workload href>/risk_details`（`collect/inventory.py:207`），用同樣的 critical/high 與 protected* 判斷計算。只能比「現在」；這個 KPI 本來就只有最新一次 |

前期值：流量 KPI 需要前期收齊（`:161-165`）；`enforced_hosts_pct` 與 `maturity` 用前期最後一個 UTC 日的每日快照，而且只在報表沒有 filter、期間結束在今天或昨天時才有（`:175-189`、`:253-257`）。

### A.8 network_inventory（`network_inventory.py`）

| KPI | 標籤 | 單位 | 定義 | 產品來源 | 重算 | 獨立算法與差異 |
|---|---|---|---|---|---|---|
| `managed_hosts` | 受管主機／Managed hosts | count | inventory 中套 filter 範圍的主機數（`network_inventory.py:58-60`、`:154`） | inventory（I） | 部分 | I |
| `hosts_missing_labels` | 缺 Label 的受管主機／Managed hosts missing a label | count | 上述主機中，app、環境 key（設定 `lateral.environment_label_key`）、loc、role 任一沒有值的數量（`:35`、`:57-63`、`:155`） | inventory（I） | 部分 | I：看 workload labels 是否缺這幾個 key |
| `apps` | 有流量進入的 app／Apps receiving traffic | count | 「目的端 app × service」排名中不重複且非空的目的端 app 數。這個排名最多讀 `PAIR_LIMIT = 1000` 組，超過時會少算（`:33`、`:90-106`、`:157`） | flows（F）＋segment ranking | 部分 | F：目的端 record labels 中 app 非空的不重複數（配對後、有連線的）。產品撞到 1000 組上限時會比重算少，報表的 limit_note 會寫出來 |
| `cross_env_connections` | 跨環境連線次數／Cross-environment connections | count | 兩端環境 label 都有值且不同的 `num_connections`（`flowsource.py:751-773`；`network_inventory.py:71-75`、`:159-161`） | flows（F） | 部分 | F，用 record 上的 labels，配對後加總 |

### A.9 app_summary（`app_summary.py`）

定義前提：filter 必須只在一側指定 app（`registry.app_filter_ok`）。「app 端點」是那一側的所有 label 條件（`app_summary.py:45-51`）。三個部分互斥（`:54-64`）：inbound 是 `dst=app` 且 `src` 不是 app；outbound 是 `src=app` 且 `dst` 不是 app；intra 是兩端都是 app。

| KPI | 標籤 | 單位 | 定義 | 產品來源 | 重算 | 獨立算法與差異 |
|---|---|---|---|---|---|---|
| `inbound_connections` | 連入連線次數／Inbound connections | count | inbound 部分的 `num_connections`（`:91`、`:230`） | flows（F） | 部分 | F：destinations include 帶 app 的 labels，sources exclude 帶同一組；配對後加總。PCE 的 include／exclude 語意與產品 SQL 是否完全相同屬**待確認** |
| `outbound_connections` | 連出連線次數／Outbound connections | count | outbound 部分（`:230`） | flows（F） | 部分 | 同上，方向相反 |
| `intra_connections` | App 內連線次數／Intra-app connections | count | intra 部分（`:231`） | flows（F） | 部分 | 兩端 include 都帶 app labels |
| `allowed_pct` | 有規則允許的連線（Allowed） | percent | 三部分合計的 allowed 連線 ÷ 有 decision 的連線（`:229-232`） | flows（F） | 部分 | 同 A.7 |
| `pb_flows` | Potentially Blocked 的流量 | count | 三部分合計的 potentially_blocked 主要列筆數（`:233`） | flows（F） | 部分 | 同 A.7 |
| `hosts` | App 內的受管主機／Managed hosts in the app | count | inventory 中 managed、且 labels 符合 app 端點所有條件的主機數（`:112-114`、`:134`） | inventory（I） | 部分 | I |
| `enforced_hosts_pct` | Full 模式的受管主機 | percent | 上述主機中 full 的比例；沒有主機就不顯示；沒有前期值（`:138-141`） | inventory（I） | 部分 | I |

### A.10 ven_status（`ven_status.py`）

主機範圍：inventory 中 `managed` 的 workload（`ven_status.py:146`）。bucket 的判斷（`:76-88`）：
- 心跳 `last_heartbeat_at` 沒有值：unknown。
- 年齡＝min(now, 該次 inventory 讀取時間 `fetched_at`) − 心跳時間。
- `online == 1` 且年齡 ≤ 1 小時：online；否則依年齡 ≤ 24 小時、≤ 48 小時、更久，分為三種失聯。

| KPI | 標籤 | 單位 | 定義 | 產品來源 | 重算 | 獨立算法與差異 |
|---|---|---|---|---|---|---|
| `managed` | 受管主機／Managed hosts | count | 上述主機數（`:217`） | inventory（I） | 部分 | I |
| `online` | 在線／Online | count | bucket online（`:217-218`） | inventory（I） | 部分 | I：用 workload 的 `online` 與 agent 的最後心跳。產品以 inventory 讀取時間計算年齡，重算以現在計算，差異最多是一個 inventory 週期（預設 1 小時）；PCE 欄位名與產品欄位的對應屬**待確認**（未讀 `collect/inventory.py` 的對應） |
| `lost_24h` | 失聯未滿 24 小時 | count | 同上 bucket（`:218`） | 同上 | 部分 | 同上 |
| `lost_48h` | 失聯 24–48 小時 | count | 同上 | 同上 | 部分 | 同上 |
| `long_offline` | 失聯超過 48 小時 | count | 同上 | 同上 | 部分 | 同上 |
| `status_unknown` | 狀態未收集 | count | bucket unknown（`:218`） | 同上 | 部分 | 同上 |
| `sync_problems` | 在線但政策同步有問題 | count | online 主機中 `problems()` 非空的數量：sync_state 不是 applied/synced、fw_config 不是最新、收過政策但未套用或落後、agent health 有 error/warning（`:91-106`、`:153`、`:219`） | 同上 | 部分 | I，從 workload 的 agent status 欄位用同樣規則判斷；欄位對應屬**待確認** |
| `unexplained_tamper` | 有未解釋竄改的主機（7 天） | count | 竄改分析結果中 `unexplained_7d > 0` 的主機數；分析沒跑過就不顯示（`:160`、`:219`） | 竄改分析 | 否 | 是本系統的竄改型態判斷 |

前期值：取同參數、結束於本期起點的上一份已完成報表的 KPI（`history.py:15-24`），不是重算出來的。

### A.11 audit（`audit.py`）

共通定義：E，期間 `[start, end)`；計數來自 `eventsource.audit_counts`（`eventsource.py:227-264`）。

| KPI | 標籤 | 單位 | 定義 | 產品來源 | 重算 | 獨立算法與差異 |
|---|---|---|---|---|---|---|
| `total` | 事件數／Events | count | 期間內全部事件（`audit.py:77`） | events（E） | 可 | E：計數 |
| `high_risk` | 嚴重與高風險事件 | count | `risk_of(event_type)` 為 critical 或 high 的事件：agent.tampering、agent.clone_detected（critical）；agent.suspend、workloads.unpair、agents.unpair、request.authorization_failed（high）（`audit.py:78`；`domain/audit.py:7-15`） | events（E） | 可 | E，用同一份清單（自備，不 import） |
| `auth_failed` | 登入失敗／Failed sign-ins | count | `request.authentication_failed`（`audit.py:79`；`domain/audit.py:20`） | events（E） | 可 | E |
| `authz_denied` | 權限拒絕（403） | count | `request.authorization_failed`（同上） | events（E） | 可 | E |
| `policy_provisions` | 政策 Provision | count | `sec_policy.create`（`audit.py:80`） | events（E） | 可 | E |
| `draft_changes` | Draft 規則變更 | count | event_type 以 `rule_set.` 或 `sec_rule.` 開頭（`audit.py:80`；`domain/audit.py:23`、`:39-40`） | events（E） | 可 | E |
| `agent_security` | VEN 安全事件 | count | agent.tampering、agent.clone_detected、agent.suspend、workloads.unpair、agents.unpair（`audit.py:81`；`domain/audit.py:30`） | events（E） | 可 | E |
| `actors` | 不重複使用者／Distinct users | count | `created_by_kind ∈ {user, service_account}` 且名稱非空的不重複 `created_by_name`（`eventsource.py:203`、`:233`、`:249-251`） | events（E） | 可 | E：從原始事件的 `created_by` 取 kind 與名稱。產品的 `created_by_kind` 與名稱取自原始 JSON 的哪個欄位屬**待確認**（未讀 `domain/events.py` 的 `_creator`） |
| `source_ips` | 不重複來源位址 | count | `action.src_ip`，沒有時用 `notifications[0].info.src_ip`，取不重複數（`eventsource.py:234-235`、`:249-251`） | events（E） | 部分 | E，用同樣兩個 JSON 路徑。這是產品依 lab 實測決定的路徑（`eventsource.py:280-281`），其他事件型態可能另有位址欄位 |

前期值：前期事件沒有缺口時才有（`audit.py:151`）。期間內沒有任何事件時全部為 None（`:154-157`）。

### A.12 ransomware（`ransomware_report.py`）

| KPI | 標籤 | 單位 | 定義 | 產品來源 | 重算 | 獨立算法與差異 |
|---|---|---|---|---|---|---|
| `rated_hosts` | 有勒索評等的主機 | count | 勒索分析最新一次結果的 `hosts` 數（`ransomware_report.py:102`、`:112`） | 勒索分析（讀 risk_details） | 部分 | 現在對受管主機讀 `risk_details`，計有評等的主機。**待確認**：分析把哪些主機放進 `hosts`（未讀 `services/analysis` 的勒索分析） |
| `org_percent` | 組織防護比例（PCE） | percent | 期間內最後一筆組織摘要的 `ransomware.ransomware_protection_coverage_percent`（`:82-85`、`:106-108`），來自收集器讀 `GET /reports/risk_summary` 的每日快照（`collect/inventory.py:185`） | 每日快照 | 部分 | `GET /reports/risk_summary` 讀現在的值。期間最後一天就是今天或昨天時才有意義 |
| `priority` | 優先修補的服務 | count | 分析結果 `priority` 清單長度（`:103`、`:112`） | 勒索分析 | 否 | 是本系統依流量使用情況做的分類 |
| `safe_to_block` | 可直接封鎖的服務 | count | `safe_to_block` 清單長度（`:113`） | 同上 | 否 | 同上 |
| `suspicious` | 可疑服務 | count | `suspicious` 清單長度（`:113`） | 同上 | 否 | 同上 |
| `contradictions` | 兩種分數差距大的主機 | count | 分析結果中標記 `contradiction` 的主機數（`:114`） | 同上 | 否 | 是本系統的分數比較 |
| `unprotected` | 未防護的服務 | count | 只在「一份清單」模式顯示（沒有流量可分類時）：`coverage == 0`（或 `protection_state == unprotected`）且 `traffic == unknown` 的服務數（`:70-73`、`:116-123`） | 同上 | 否 | 依賴分析的 coverage 與 traffic 分類 |

前期值：`org_percent` 取前期的組織摘要（`:108`）；其他取上一份報表（`history.py`）。

### A.13 policy_usage 與其 RHC 章（`policy_usage.py`、`rule_hit_count.py`）

policy_usage 的計算來源是 `rule_usage`（`analysis/rule_usage.py:141` 起）：逐日 async query（`PER_QUERY = 50,000`，滿了最多切半 3 次），再用 D 取得 draft 判定與命中的規則。規則清單是 `GET` draft rule_sets。

| KPI | 標籤 | 單位 | 定義 | 產品來源 | 重算 | 獨立算法與差異 |
|---|---|---|---|---|---|---|
| `rules` | Draft 中的允許規則 | count | draft 中 rule_type 為 allow 的規則數（含停用的，`policy_usage.py:59`、`:70`） | PCE draft（報表當時） | 部分 | `GET /sec_policy/draft/rule_sets`，數 `rules`。只能比現在的 draft |
| `used` | 有流量命中的規則 | count | allow 規則中，href 出現在期間 draft 重算命中裡的（`:62`、`:70`） | D | 部分 | D：用同樣的逐日查詢加 `update_rules`，收集各 record 的 allow 規則 href。差異：draft 已改、晚到流量、截斷（報表會標 read_only 註記，`:74`）。D 的權限屬**待確認** |
| `unused` | 沒有流量命中的規則 | count | 啟用中的 allow 規則中沒有命中的（`:64`、`:71`） | D | 部分 | 同上 |
| `disabled` | 停用的規則 | count | 停用的 allow 規則（`:65`、`:71`） | PCE draft | 部分 | `GET` draft rule_sets，數 `enabled == false` 的 allow 規則。只能比現在 |
| `deny_hit` | 擋下過流量的 Deny Rule | count | 非 allow 規則中有命中的（`:60`、`:66`、`:72`） | D | 部分 | 同 `used`，取 deny／override_deny 規則 href |
| `no_rule` | 沒有規則允許的連線次數 | count | draft 判定為「無規則」的連線總和（`analysis/rule_usage.py:69`、`:177`；`policy_usage.py:73`） | D | 部分 | 同 `used`。產品的「無規則」判定集合屬**待確認**（未讀 `rule_usage.py:100-120` 的 `_ALLOWED`／`_BY_DENY` 等常數） |
| `rhc_hit` | 期間內有命中的規則（含之後已刪除的） | count | PCE 原生 Rule Hit Count 報表中 `hit_count > 0` 的列數（`rule_hit_count.py:135`、`:189`） | PCE 報表（產品用 `POST /reports` 產生） | 否 | 要寫入 PCE（POST /reports）才拿得到。**待確認**：PCE 是否保留產品產生的那份報表，能否只用 GET 讀回來比對 |
| `rhc_zero` | 已生效規則：有紀錄、0 次 | count | 報表中 `hit_count == 0`、規則仍在 active 且不是期間結束後才建立的（`:137-141`、`:189`） | 同上＋`GET` active rule_sets | 否 | 同上 |
| `rhc_no_record` | 已生效規則：沒有紀錄 | count | active 中啟用、但 PCE 報表裡沒有紀錄的規則（`:145-146`、`:189`） | 同上 | 否 | 同上 |

RHC 未開啟時三個值都是 None，並附原因（`rule_hit_count.py:94-104`）。

### A.14 policy_diff（`policy_diff.py`）

所有值都是報表產出當時 draft 與 active 的比較（`domain/policy_diff.py`，純函式；資料來源 `analysis/policy_diff.py`），期間只用來找「誰改的」事件。

| KPI | 標籤 | 單位 | 定義 | 產品來源 | 重算 | 獨立算法與差異 |
|---|---|---|---|---|---|---|
| `total` | 變更數／Changes | count | 所有變更列（以欄位為單位：同一條規則改了兩個欄位算兩列，`policy_diff.py:142`） | PCE draft＋active（當時） | 部分 | `GET /sec_policy/draft/...` 與 `/sec_policy/active/...` 自己逐欄比較；或用 `GET /sec_policy/pending` 得到以物件為單位的計數（數字不同，需換算）。只能比現在。**待確認**：pending API 的回應格式 |
| `high` | 高風險 | count | 產品風險規則判為 high 的變更數（`:142`） | 同上 | 否 | 是本系統的風險規則（移植自 5.x） |
| `rule_sets` | 變更的 Ruleset | count | 不重複的變更 ruleset ref（`:143`） | 同上 | 部分 | 同 `total`，以 ruleset 為單位 |
| `rules` | 變更的規則 | count | 不重複的（規則 ref＋ruleset）（`:143`） | 同上 | 部分 | 同上 |
| `objects` | 變更的政策物件 | count | 不重複的（種類＋ref），種類為 ip_list、service、label_group（`:144`） | 同上 | 部分 | 同上 |
| `other_pending` | 其他待 Provision 項目 | count | 上述以外的 pending 項目數（`:133`、`:144`） | PCE pending（當時） | 部分 | `GET /sec_policy/pending`，扣除上述種類 |

### A.15 policy_resolver（`policy_resolver.py`）

| KPI | 標籤 | 單位 | 定義 | 產品來源 | 重算 | 獨立算法與差異 |
|---|---|---|---|---|---|---|
| `rulesets` | Ruleset 數 | count | active rule_sets 依「名稱」分組的組數，含停用的；同名的兩個 ruleset 會算成一個（`analysis/policy_resolver.py:89`、`:96`；`policy_resolver.py:62`） | PCE active（當時） | 部分 | `GET /sec_policy/active/rule_sets`，計不重複名稱（沒名稱的用 href）。只能比現在 |
| `rules` | 生效中的規則 | count | 啟用的 ruleset 中，啟用的 `rules`＋`deny_rules`（`analysis/policy_resolver.py:90-92`） | 同上 | 部分 | 同上 |
| `rows` | 列數 | count | 展開後的 IP 列數，不含提示列（`policy_resolver.py:61-62`） | 產品的展開 | 否 | 是本系統的展開演算法與上限 |
| `capped` | 以摘要表示的規則 | count | 展開時被摘要的規則數（`analysis/policy_resolver.py:95`、`:106`） | 同上 | 否 | 同上 |
| `omitted` | 被省略的列 | count | 超過總列數上限而省略的列（`:102-104`） | 同上 | 否 | 同上 |
| `not_expanded` | 無法展開的規則 | count | 展開時遇到無法對應的參照（`:100-101`） | 同上 | 否 | 同上 |
| `no_address` | 沒有位址可展開的規則 | count | 兩側解析不到任何位址的（規則, 側）組數（`:97`、`:106`）。注意這是「組數」，不是不重複的規則數 | 同上 | 否 | 同上 |

### A.16 readiness（`readiness.py`）

| KPI | 標籤 | 單位 | 定義 | 產品來源 | 重算 | 獨立算法與差異 |
|---|---|---|---|---|---|---|
| `apps` | 評估的 app 數 | count | 目的端為受管主機的主要列，依（目的端 app, 目的端環境）分組、連線數 > 0 的組數；沒有 label 的（None, None）也算一組（`readiness.py:86-87`、`:102-106`、`:127`；`flowsource.py:904-929`） | flows（F） | 部分 | F：目的端 `workload.managed` 為真的 record，依 record 上的目的端 app／環境 label 分組，計有連線的組數 |
| `ready` | 可切換（A 或 B） | count | 依 `domain/readiness` 公式評為 A 或 B 的組數（`:107-111`、`:127`） | 評分公式 | 否 | 是本系統的評分 |
| `held_back` | 受阻（D 或 F） | count | 評為 D 或 F 的組數（`:128`） | 同上 | 否 | 同上 |
| `overall` | 平均分數（0–100） | count | 已評分組的平均分數，四捨五入（`:125`、`:129`） | 同上 | 否 | 同上 |
| `predicted_blocked` | Draft 政策會擋下的連線次數 | count | D 重算中 draft 判定為擋下的連線數（`predicted_summary`，`analysis/predicted_block.py:176-202`；`PREDICTED_MAX_RESULTS = 50,000`，`readiness.py:54`）；有 undetermined 且 blocked 為 0 時不顯示（`:122-123`、`:130`） | D | 部分 | D，套報表 filter。差異：draft 已改、截斷、權限（D 的**待確認**） |

前期值：取上一份報表的值（`history.py`）。

### A.17 待確認清單

| # | 項目 | 原因 |
|---|---|---|
| 1 | ~~D 類：`policy_usage` 的 `used`／`unused`／`deny_hit`／`no_rule`、`readiness` 的 `predicted_blocked`~~ | **已解決（使用者 2026-11-20）**：允許對本工具建立的查詢 PUT `update_rules` 與 DELETE（lab、NFR 皆可）。Task 5 v1 會重算這 5 個 |
| 2 | `rhc_hit`／`rhc_zero`／`rhc_no_record` | 重產需要 `POST /reports`（寫入），**不允許**（2026-11-20 維持）；這 3 個在報告裡列為 unchecked 並寫原因。PCE 是否保留產品產生的那份報表、能否只用 GET 讀回，未查 |
| 3 | traffic `flows`（以及所有「主要列筆數」類：`pb_flows`、`blocked_flows`） | store 以每小時重抓並依 `record_key`（含 `first_detected`）合併，一個連線每天是否只留一列，需要用真資料確認 |
| 4 | security_risk `admin_open_connections`、new_connections `admin`、unmanaged `admin_sources` | 管理 port 清單含「PCE 管理服務」那部分，能否只用 GET 從 PCE 讀到未查；內建清單需自備 |
| 5 | app_summary 三個方向的連線數 | PCE async query 的 include／exclude 語意是否與產品 SQL 的 `dst=app AND NOT src=app` 等價 |
| 6 | ven_status 的 online、三種失聯、unknown、`sync_problems` | 產品欄位（`last_heartbeat_at`、`online`、`policy_sync_state`、`fw_config_current`、`policy_received_at`／`policy_applied_at`、`agent_health_json`）與 PCE workload JSON 的對應未讀（`collect/inventory.py`） |
| 7 | audit `actors` | `created_by_kind`／`created_by_name` 取自原始事件哪個欄位未讀（`domain/events.py`） |
| 8 | ransomware `rated_hosts` | 勒索分析把哪些主機放進結果未讀 |
| 9 | policy_usage `no_rule` | 產品「無規則」的 draft 判定集合未讀 |
| 10 | policy_diff `total` 等 | `GET /sec_policy/pending` 的回應格式與以欄位為單位的變更數如何換算 |
