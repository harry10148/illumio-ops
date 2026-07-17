---
title: 報表家族
audience: [operator]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - src/report/report_generator.py
  - src/report/audit_generator.py
  - src/report/policy_usage_generator.py
  - src/report/ven_status_generator.py
  - src/report/readiness_report.py
  - src/report/rule_hit_count_generator.py
  - src/report/rule_hit_count_enablement.py
  - src/report/policy_diff_report.py
  - src/report/policy_resolver_report.py
  - src/report/cache_support.py
  - src/report_scheduler.py
  - src/cli/report.py
---

# 報表家族

illumio-ops 提供 9 種報表（GUI Reports 分頁的 Generate 鈕與 CLI `illumio-ops report <type>` 子命令一一對應），可用 CLI、GUI 或排程三種方式產生。除了這 9 種，Traffic 報表底下還有幾個共用同一份產生器的變體子命令（`draft-policy`／`inventory`／`app-summary`），詳見「1. Traffic Flow Report」節末的說明。

## 報表總覽

| 報表 | 回答什麼問題 | 資料來源 | 輸出格式 |
|---|---|---|---|
| Traffic Flow（`traffic`） | 這段時間誰跟誰通了什麼、政策決策分布如何、有沒有安全訊號 | cache(hybrid，可切換) + live PCE，或 CSV 匯入 | html / csv / xlsx / all |
| Security & Risk（`security`） | 目前有哪些安全風險（未覆蓋流量、橫向移動、暴露埠） | 同 Traffic | html / csv / xlsx / all |
| Audit & System Events（`audit`） | 誰在什麼時候透過 API/GUI/agent 改了什麼 | cache(hybrid，自動) + live 補洞 | html / csv / xlsx / all |
| Policy Usage（`policy-usage`） | 哪些 Active 規則有被流量用到，哪些可能是死規則 | live（逐規則 async 查詢），或 workloader CSV 匯入 | html / csv / xlsx / all |
| VEN Status（`ven-status`） | 哪些 VEN 離線／失聯，失聯多久 | 即時 live only | html / csv / xlsx / all |
| Enforcement Readiness（`readiness`） | 哪個 App(Env) 可以安全推進到下一個 enforcement mode | cache(hybrid，可切換) + live | html / csv / all |
| Rule Hit Count（`rule-hit-count`） | 哪些 Active 規則實際在 VEN 防火牆被命中過（原生量測） | live（PCE native pull），或 PCE UI 原生 CSV 匯入 | html / csv / all |
| Policy Diff（`policy-diff`） | draft policy 佈署後政策物件會怎麼變、是誰改的 | live（同時抓 draft／active） | html / csv / all |
| Policy Resolver（`resolve`） | ACTIVE label-based policy 展開成 IP 層防火牆規則長什麼樣 | live（僅 ACTIVE） | json / csv / all |

「資料來源」欄的 hybrid／live／cache-only 語意見各報表節與下方「cache vs live」說明；輸出格式欄位是 `_REPORT_FORMATS`／各子命令 `--format` 的實際 `choices`，不是全報表統一集合。

## cache 與 live 資料來源

支援 `--data-source` 的報表（Traffic／Security／Inventory／App Summary／Readiness）共用同一套三態邏輯（`src/report/cache_support.py`）：

- `hybrid`（預設）：優先讀 pce_cache，缺口用 live PCE 查詢補齊。
- `live`：整段時間窗口一律即時查 PCE，不碰 cache。
- `cache-only`：只讀 cache 涵蓋範圍內的資料，最快但可能漏掉尚未寫入 cache 的最新資料；若 cache 不可用會自動退回 live 並印出警告，不會靜默用空結果。

舊版 `--cache/--no-cache` 旗標已棄用，行為保留但建議改用 `--data-source`。`clip_to_cache` 是額外選項（`generate_from_api(clip_to_cache=True)`）：把查詢起點往後夾到 cache 最早資料點，省去撈一段 cache 已經沒有、PCE 也早已過期的前段窗口；若 cache 最早資料點比請求結束時間還晚，會直接跳過夾取並記錄日誌，不會誤夾出空窗口。

Audit 報表也走 cache + live 補洞（`mixed`/`cache`/`api` 三種 `source` 標記），但**沒有** CLI 旗標讓操作者手動切換——完全由產生器內部判斷。VEN Status／Policy Usage／Rule Hit Count／Policy Diff／Policy Resolver 這幾種報表本質上是「當下狀態」或「逐條即時查詢」，一律 live，沒有 cache 選項。

## 1. Traffic Flow Report

用途：回答一段時間窗口內誰跟誰通了什麼、政策決策（allowed／blocked／potentially_blocked／unknown）分布，並跑過完整的安全分析管線（mod01–mod12：政策覆蓋率、未覆蓋流量、橫向移動路徑、Cross-Label Matrix、Unmanaged Hosts 等）。

CLI 範例：

```
illumio-ops report traffic --format html
```

常用旗標：`--source api|csv`（預設 api）、`--file PATH`（csv 匯入時的來源檔）、`--output-dir`、`--email`（產出後寄送，需先設定郵件通道）、`--data-source hybrid|live|cache-only`（見上節）。

GUI：Reports → List 子頁 → Traffic 卡片 Generate 鈕；產出會排入伺服器端背景執行緒，即時查詢 PCE 並寫檔，視資料量可能耗時數分鐘。

關鍵欄位：Executive Summary KPI（總流量／連線數／政策覆蓋率）、Policy Decisions 分布、Top 未覆蓋流量、橫向移動路徑（攻擊路徑、fan-out 來源、bridge nodes）、Cross-Label Matrix、Unmanaged Hosts。

注意事項：

- **2026-07 起預設含 unknown**：查詢的 `policy_decisions` 篩選未指定時，預設含四值 `blocked, potentially_blocked, allowed, unknown`，涵蓋 idle／快照模式 VEN 與 Flowlink 未管理流量。若沿用舊版習慣手動指定只含前三值的 filter，統計出來的總量會明顯偏低；unknown 值域的完整說明見 [pce-domain-notes.md](../handover/pce-domain-notes.md) 「policy_decision 值域」節。
- 若走 cache（hybrid／cache-only），而快取資料是在支援 unknown 值之前寫入的舊資料，該時間範圍內的 unknown flows 不會自動補上，須重跑 backfill 才能取得完整含 unknown 的歷史資料（backfill 操作見 [cache-maintenance.md](cache-maintenance.md)）。
- HTML 版面對一般欄位（IP／port／label）沒有特別截斷；xlsx 匯出欄寬依內容自動估算但上限 60 字元寬，這只是欄位顯示寬度，不會截斷儲存格內容本身。
- 以下子命令與 Traffic 共用同一產生器（`report_generator.py`），未各自成節：
  - `illumio-ops report draft-policy` — DRAFT policy 影響評估，永遠即時查 PCE（含 `draft_policy_decision` 計算），不使用 cache；建議用 `--start-date`/`--end-date` 縮小窗口，全時間窗口計算成本較高。
  - `illumio-ops report inventory` — Network & Traffic Inventory，同一分析管線的資產盤點視角。
  - `illumio-ops report app-summary --app <App Label 值>` — 單一 App Label 的進出流量摘要，只支援 html 輸出。

## 2. Security & Risk Report

用途：盤點目前的安全風險——政策覆蓋率、未覆蓋流量、暴露埠、橫向移動路徑；若提供漏洞掃描 CSV，額外產出 Vulnerability-Exposure 對照。

CLI 範例：

```
illumio-ops report security --format html
```

`--vuln-csv PATH`（選填）：接受 Qualys／Tenable 等匯出的 CSV（需含 ip 與 cve 欄位），用來產出 V-E exposure 小節。其餘旗標與 Traffic 報表相同（`--source`、`--data-source`、`--email` 等）。

GUI：Reports → Security 卡片 Generate。

關鍵欄位：policy_coverage_pct、未覆蓋流量 Top 清單、攻擊面摘要、Enforcement Readiness 小節（與獨立的 Readiness 報表共用同一分析核心 mod13，是同一套邏輯的兩種呈現）。

注意事項：與 Traffic 報表相同——policy_decisions 預設含 unknown，且支援 `--data-source`。

## 3. Audit & System Events Report

用途：誰在什麼時候透過 API／GUI／agent 改了什麼（policy commit、物件變更前後值、workload 通知），用來回溯稽核操作。

CLI 範例：

```
illumio-ops report audit --start-date 2026-07-01 --end-date 2026-07-16 --format html
```

GUI：Reports → Audit 卡片 Generate。

關鍵欄位：`action.src_ip`／`api_method`／`api_endpoint`、`created_by`（分辨 user／agent／system 來源）、`change_detail`（欄位前後值摘要）、`workloads_affected`。

注意事項：這裡有兩層獨立的截斷，不要混為一談。第一層在 generator（`audit_generator.py`）組 `change_detail` 字串時就發生：每個 before/after 欄位值先裁到 80 字元、最多納入 8 個欄位（`_truncate_val(val, max_len=80)` ＋ `summaries[:8]`），HTML 與 CSV 的 `change_detail` 拿到的都是同一條已裁切字串，無法回復。第二層只在 HTML 匯出層（`audit_html_exporter.py` 的 `_LONG_TEXT_TRUNCATE_AT = 150`）：`change_detail` 字串若超過 150 字元會再用 `<details>` 折疊顯示，點開可看到 `change_detail` 的完整內容——但那仍是第一層裁過的摘要，不是原始值。真正未裁切的原始變更資料只在 `raw_events.csv`（CSV ZIP 內的獨立檔案）的 `resource_changes` 欄位裡。

## 4. Policy Usage Report

用途：哪些 Active 規則實際被流量用到、哪些長期沒有流量可能是可以清掉的死規則。做法是對每條規則的 consumers→sources／providers→destinations／services 各自送一次獨立的 async traffic query，統計回傳的 flow 數判定 hit／unused。

CLI 範例：

```
illumio-ops report policy-usage --start-date 2026-07-01 --end-date 2026-07-16 --format html
```

`--source api|csv --file PATH`：也支援匯入 workloader 工具產出的 rule-usage CSV。

GUI：Reports → Policy Usage 卡片 Generate（逐規則各自查詢，規則數多時耗時較長）。

關鍵欄位：每條規則的 hit／unused 狀態、consumers／providers／services。

注意事項：

- 未使用規則清單超過 50 筆時，HTML 只顯示筆數提示（不列出全部列），完整清單要看 CSV 匯出。
- 這是「流量近似推算」得出的用量統計，語意不同於下方 Rule Hit Count 報表的 VEN 原生量測——兩者不可互相替代解讀（`rule_hit_count_generator.py` 檔頭明確區分這兩份報表的職責）。

## 5. VEN Status Report

用途：哪些受管 VEN 離線／失聯，失聯多久，用來排查連線斷線或代理程式異常。

CLI 範例：

```
illumio-ops report ven-status --format html
```

GUI：Reports → VEN Status 卡片 Generate。

關鍵欄位：Online／Offline 分類（同時要求行政狀態 `active` 且心跳在 1 小時內才算 Online，超過視為離線即使行政狀態仍是 active）；離線再分桶為近 24 小時、24–48 小時、48 小時以上或無心跳資訊。

注意事項：即時查詢，沒有 cache／`--data-source` 選項；PCE 的 `agent.status.status` 只反映行政狀態，不代表真的連得到，這是本報表存在的理由。

## 6. Enforcement Readiness Report

用途：哪個 App(Env) 可以安全推進到下一個 enforcement mode，依政策覆蓋率、ringfence 成熟度、目前 enforcement mode、staged readiness、remote app coverage 五個因子計分排序。

CLI 範例：

```
illumio-ops report readiness --start-date 2026-07-01 --end-date 2026-07-16 --format html
```

支援 `--data-source hybrid|live|cache-only`（同 Traffic）。

GUI：Reports → Readiness 卡片 Generate。

關鍵欄位：`readiness_score`、`grade`、`current_mode`、`blocking_factor`、`recommended_action`，以及依分數排序的推進候選佇列。

注意事項：與 Security 報表內嵌的 readiness 小節共用同一分析核心（mod13），但獨立報表的候選佇列涵蓋整個估算範圍，不像內嵌小節只列前 20 筆。HTML 長字串欄位同樣採截斷＋刪節號＋滑鼠停留顯示完整值（title 屬性）＋CSV 保留全值的模式，不會靜默截斷。

## 7. Rule Hit Count Report

用途：哪些 Active 規則實際在 VEN 防火牆上被命中過，資料來自 VEN 原生量測（不是流量推算），可用來驗證政策實際生效狀況。

CLI 範例：

```
illumio-ops report rule-hit-count --format html
```

`--source native|csv`：`native`（預設）呼叫 PCE pull API 即時取得；`csv` 匯入 PCE UI 匯出的原生 Rule Hit Count CSV。

GUI：Reports → Rule Hit Count 卡片 Generate。

**啟用精靈**：此功能需先在 PCE 上啟用——PCE 端把 `report_templates/rule_hit_count_report` 設為啟用，VEN 端則要寫入 draft `firewall_settings` 的 `rule_hit_count_enabled_scopes` 並 provision，這是一次正式的 production policy 寫入。CLI 偵測到尚未啟用時，僅在互動式終端機才會跳出啟用精靈：先顯示警告說明會寫入 production policy，要求操作者明確確認，再選擇套用範圍（全部 VEN 或指定 label 範圍），完成後提示 VEN 需要一段時間才會開始回報資料。排程執行（`report_scheduler.py`）遇到未啟用一律只記警告並跳過，絕不會自動觸發精靈或自動啟用。

**版本門檻**：SaaS PCE 24.2.0 以上、地端 PCE 23.5.10 以上、VEN 23.2.30 以上；PCE 回應 404 視為版本不支援。完整 vendor 事實（保留期、規則最佳化高估、每 flow 最多歸因 100 條規則、hit 與 flow 計數語意差異等）見 [pce-domain-notes.md](../handover/pce-domain-notes.md) 「Rule Hit Count」節。

關鍵欄位：`hit_count`、`last_hit_at`、`days_since_last_hit`、即時 enrich 出的規則 consumers／providers／services。

注意事項：只計 Active 規則，計數資料保留期 90 天（`CLEANUP_DAYS_THRESHOLD`）；HTML 長字串欄位同樣是截斷＋刪節號＋title 屬性顯示全值＋CSV 保留全值的模式。輸出格式只有 html／csv／all（沒有 xlsx）。

## 8. Policy Diff Report（DRAFT vs ACTIVE）

用途：draft policy 佈署後政策物件（ruleset／rule／ip_list／service／label_group）會發生什麼變化，並回溯是誰在什麼時候改的。

CLI 範例：

```
illumio-ops report policy-diff --format html --attribution-days 30
```

`--attribution-days N`（預設 30）：決定往回查多少天的 audit 事件來做操作歸因。

GUI：Reports → Policy Diff 卡片 Generate。

關鍵欄位：規則層 diff（含風險分級）＋物件層 diff（ip_lists／services／label_groups 各自的 added／removed／modified 計數）＋操作歸因（誰改的、何時改的，來自 audit 事件回溯）。

注意事項：抓取 draft／active rulesets 或任一物件庫存失敗時，報表直接失敗並往上拋錯，刻意不把「抓取失敗」誤當成「規則全部被移除」而產出誤導性的 diff 結果。DRAFT-ACTIVE 之間沒有任何變更時仍會產出一份空 diff 報表（不是跳過）。輸出格式只有 html／csv／all。

## 9. Policy Resolver Report

用途：把 ACTIVE label-based policy 展開成 IP 層防火牆規則，方便離線稽核、比對第三方防火牆規則或做合規證據。

CLI 範例：

```
illumio-ops report resolve --format json
```

（CLI 子命令名稱是 `resolve`，不是 `policy-resolver`。）

GUI：Reports → Policy Resolver 卡片 Generate。

關鍵欄位：依 ruleset 分組的展開結果——label→IP、iplist→CIDR/FQDN、label_group（遞迴展開子群組）→label、service→port 皆在本機用查表方式一次性展開，不是交給 PCE 端計算。

注意事項：只支援 ACTIVE policy（不含 draft）；展開結果為 0 筆時不寫出任何檔案，CLI／GUI 都會明確顯示「空結果」提示，避免與失敗混淆。輸出格式只有 json／csv／all（沒有 html／xlsx）。這裡展開的是**政策物件本身**的 label group 成員；與 traffic 查詢時 label group 過濾只能交給 PCE 端展開是兩件不同的事（後者見 [pce-domain-notes.md](../handover/pce-domain-notes.md)），不要混淆。

## 排程與寄送

`src/report_scheduler.py` 的 `ReportScheduler.tick()` 由背景 daemon 每 60 秒呼叫一次，逐一評估 `report_schedules[]` 裡的排程是否到期：

- **觸發方式**：每筆排程可用 `schedule_type`（`daily`／`weekly`／`monthly`，依當地時區的時／分匹配，並有限於「目標日當天」的補跑語意）或 `cron_expr`（優先於 `schedule_type`，用 APScheduler 的 cron 表示式，如 `0 8 * * MON-FRI`）擇一設定；時區依 `timezone` 欄位解析，未設定時視同 UTC。
- **可排程的 report_type**：`traffic`、`security_risk`、`network_inventory`、`audit`、`ven_status`、`policy_usage`、`policy_diff`、`policy_resolver`、`app_summary`、`rule_hit_count`、`readiness`——這 11 種直接對應內部 dispatch 字串，比 GUI Generate 鈕的 9 種多出 `network_inventory` 與 `app_summary`（後兩者在 GUI 是 Traffic 家族底下的變體，未各自出現在 Generate 鈕列）。
- **寄送**：排程設 `email_report: true` 時，成功產出後會組一封 HTML email 寄出（主旨含排程名稱與日期），收件人預設用系統郵件設定、可用 `email_recipients` 覆寫。寄送失敗不影響已產出的檔案。
- **保留**：`max_reports` 依 report_type 分組，只保留最新 N 份「報表」而非個別檔案（同一次產出的 html+csv 算同一份，一起留或一起刪）；`retention_days` 依時間裁剪過舊檔案。兩者鍵位語意見 [configuration.md](configuration.md) 「report／report_schedules」節。

GUI 排程操作（建立／編輯／啟用停用／立即執行 Run Now／刪除）見 [gui-tour.md](gui-tour.md) 「5) Reports」節的 Schedules 子頁；排程需 daemon 持續執行才會觸發，勾選 Email 需先在 Settings → Channels 設定好郵件通道。
