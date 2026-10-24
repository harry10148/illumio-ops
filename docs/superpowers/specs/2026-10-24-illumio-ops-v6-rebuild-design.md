# illumio-ops v6 重建設計

> 狀態：**使用者已核可（2026-10-24）**。下一步：實作計畫（superpowers:writing-plans）。
> 性質：**整個專案推倒重做**，回收可用程式碼；舊版（5.x）不再並行維護。
> 依據：2026-10-24 全專案現況盤點（`tmp/rearch-2026-10-24/survey/`，gitignored；
> 彙整見 `99-synthesis.md`，分檔 a–f 為 Claude 盤點、g 為 Codex 獨立判讀）與同日需求對談。
> 標記：**【使用者】** 是使用者在對談中的決定；**【判斷】** 是撰寫者的決定，使用者可推翻；
> 未標記的段落是事實或由前兩者直接推得。

---

## 1. 為什麼要做這個產品

Illumio PCE **沒有內建告警機制**，要告警只能把 log 拋到 SIEM 再由 SIEM 處理；**SaaS 版**還必須
另外準備 S3 空間暫存 log，很多客戶沒有這個條件，結果就是收不到任何告警。PCE 的**內建報表也很少**，
微分段收集到的東西向流量沒有被轉成資安或網管看得懂的東西。【使用者】

本產品裝在客戶環境，**透過 PCE REST API 調閱資料**，補上這兩塊：

```
一般做法：  PCE ──syslog / S3──> SIEM ──> 告警          ← SaaS 客戶常卡在 S3
本產品：    PCE <──API 調閱── illumio-ops ──> 依規則告警（email / LINE / Telegram / Teams / webhook）
                                       ├──> 轉送 log 到客戶的 SIEM
                                       └──> 東西向流量報表與潛在風險發現
```

## 2. 為什麼要重做

產品從單一 CLI 工具長成「daemon＋SQLite＋Web GUI＋11 型報表＋SIEM」平台（v4.1.0→v5.2.0 三個月內
src +55k／−22k 行）。雜亂的主因不是功能多，而是**同一件事在多處各寫一次、共用狀態沒有擁有者**：

- 同一能力有 6 種入口（argparse 舊旗標、click、互動選單、3 支獨立選單、GUI、排程），跨入口行為差異 18 項。
- 「資料從 cache／live／archive 哪裡拿」寫了 3–4 份；traffic filter 有 3 種以上執行表示；GUI 的
  policy decision 有 6 套值域、其中 3 套整數編碼互相衝突；嚴重度表 7 份、SMTP 實作 3 份。
- `state.json` 23 鍵多方寫入；設定在驗證失敗時 dict 與 typed model 分歧；裸 `ConfigManager()` 40 處。
- 相依倒置（資料層 import GUI 與分析層）、import 環 2 個、分析層經 stdout 把結果交給 GUI。
- 無讀者的路由、功能與資料；永遠不會被清掉的檔案與資料列。

測試機使用痕跡（2026-10-24 唯讀調查）：持續運作且有產出的只有**資料收集、事件告警（LINE＋email）、
SIEM 轉送（22.4 萬筆全數送達）**；GUI 告警收件匣 146 則從未被處理、報表排程只有一筆 demo 且型別不合法、
規則排程的目標都已刪除、VEN 推進從未執行、隔離零紀錄。

## 3. 給誰

- **已購買 Illumio 的客戶**，on-prem PCE 與 SaaS PCE 都要支援。【使用者】
- 操作者是客戶的**資安或網管人員**。【使用者】
- 已有**少數客戶部署了 5.x**（尚未正式交付），**全部是 v5.0.0、離線 bundle 安裝，升級由使用者本人
  執行**；已知沒有用 CLI 建立規則。【使用者】

## 4. 目標、非目標、反目標

### 4.1 目標（依優先序）【使用者】

1. **告警**：依設定的規則，從 PCE 事件、流量、PCE 健康狀態產生告警並送到通知通道。
2. **log 轉送到客戶 SIEM**：讓沒有 S3 的 SaaS 客戶也能把 audit 事件與流量送進 SIEM。
   （由「最初核心問題」推得，使用者未反對；測試機上是實際使用量最大的一塊。）
3. **報表**：把東西向流量轉成資安／網管看得懂的報表，並**找出潛在風險**。
4. **隔離與調查**：排最後，延到 v6.1（§6.5）。
5. **從 5.x 升級**：已部署客戶的**設定**必須能帶過來。【使用者】

### 4.2 非目標

- **CLI**：整個拋棄。【使用者】只保留安裝／升級腳本與極少數救援指令（§6.2）。【判斷】
- **資料遷移**：5.x 的 cache、封存、告警紀錄、舊報表不搬。【使用者】
- **舊版並行維護**：不做。【使用者】
- **告警收件匣的處理流程**（new/ack/done）：不做；只要能檢視最近的告警與單筆詳情。
  （使用者 2026-09-04 v3.1 決策：「不需要收件匣與事件調查流程，只要能檢視最近的告警」；
  測試機 146 則告警從未被處理，佐證。）
- 一台設備對接多個 PCE、多使用者／角色：不做。【判斷，前提見 §5】
- plugger 移植 2–4（app-dependency-intel、vuln-scan-import、workload-isolator）：v6.0 不做，
  原 spec 保留供日後評估。GUI clarity 批次 3：由本設計的前端取代，不另做。

### 4.3 反目標（做出來但違反這些就算失敗）

這些來自 5.x 反覆發生的事故，是本設計的硬性品質規則：

1. **失敗不得看起來像成功或像空結果。** 取資料失敗、部分失敗、截斷、降級，都要在 API 回應與畫面上
   明說；不得吞錯回 `[]`、不得回退成預設值後繼續跑。（5.x：設定驗證失敗回退預設值會無聲關掉 cache
   與 SIEM；`has_draft_changes` 失敗回 False 後照樣 provision；報表排程型別不合法卻每分鐘「執行成功」。）
2. **每份持久資料只有一個寫入模組。** 不得有多方共寫的 JSON 檔。
3. **每個值域只定義一次**，後端與前端共用（前端型別由後端定義產生）。
4. **沒有讀者的東西不出貨**：每條路由有畫面呼叫、每個設定鍵有程式讀、每份產出有清理機制。
5. **截斷要明說**：報表與畫面的長度上限、截斷方式（換行／省略／分頁）必須明確，不可無聲截斷
   （專案 CLAUDE.md 規則）。
6. **設定在寫入時驗證**，不合法就拒寫；載入時驗證失敗則拒絕啟動並指出哪一欄。
7. **路徑全部從單一安裝根目錄解析**，不得依賴執行時的工作目錄。

## 5. 約束與前提

- 執行環境：Linux x86_64（RHEL／Rocky 系），**可能離線**；以離線 bundle 安裝到 `/opt/illumio-ops`，
  內含 PBS CPython 3.12 與所有 wheel，systemd 服務。Windows 已於 2026-08 移除，不恢復。
- PCE：on-prem 與 SaaS；SaaS `/events` 有 22–60 秒以上的固定延遲，timeout 必須可設定。
- 語系：繁體中文與英文。
- 安全：既有 GUI 安全機制已多輪審查（登入、CSRF、IP 允許清單、限流、Talisman、TLS 自簽／續期／CSR／
  匯入），行為必須保留。憑證只存設定檔（0600），不得出現在 log、畫面或 API 回應。
- **前提（不符請告知）**【判斷】：一台設備只對接一個 PCE；單一管理者帳號；客戶規模與測試機相當
  （測試機 cache：events 7.7 萬、raw flows 11 萬、agg 42.5 萬，DB 1.3 GB）。

## 6. 已定的做法

### 6.1 技術選擇【判斷，使用者授權由撰寫者評估】

| 項目 | 決定 | 理由 |
|---|---|---|
| 後端 | Python 3.12＋SQLite＋離線 bundle | 回收最多；離線安裝已解決 |
| Web | 沿用 Flask 與既有安全機制 | 雜亂來自契約未定義，不是框架 |
| API 契約 | 每個 API 的請求／回應以 pydantic 定義一次；**單一回應信封**；前端 TypeScript 型別由此產生 | 消滅值域漂移（policy decision 6 套編碼）與 6 種回應信封 |
| 前端 | TypeScript＋React，開發時建置，bundle 只帶靜態檔；客戶機器不需要 node | 型別與元件防止重複與值域衝突；React 另可接上使用者既有的設計同步流程 |
| 執行模型 | **單一行程**（Flask＋APScheduler 同行程），每份資料單一寫入者 | CLI 拿掉後沒有第二寫入者；跨行程鎖與 `state.json` 多方寫入可整批消失 |
| CI | 用出貨的 Python 3.12 與**同一份** lock 檔跑測試 | 5.x CI 跑 3.10/3.11，出貨 3.12，兩份 lock 差 28 個套件 |
| 版本 | v6.0.0 | 重大不相容（無 CLI、新設定格式） |

前端多出一套 node 建置工具鏈（目前 repo 沒有任何 node 步驟；Playwright 走 Python 套件）。

### 6.2 介面：只有 GUI【使用者】

- 所有操作都在 GUI。刪除：click 命令樹、argparse 舊旗標、互動選單、`siem_cli`／`pce_cache_cli`／
  `rule_scheduler_cli`。
- 保留安裝面腳本：`build_offline_bundle.sh`、`install.sh`、`preflight.sh`、`uninstall.sh`。
- **救援指令**【判斷】：GUI 進不去時（忘記密碼、TLS 設壞、設定檔損毀拒絕啟動）需要的最小集合——
  重設管理員密碼、驗證設定檔並指出錯誤欄位、（可選）以 HTTP 暫時啟動。**只在服務停止時可執行**，
  不構成第二寫入者。
- GUI 的資訊架構與視覺沿用使用者已核可的 v3.1 決策：左側導覽、清單→詳情、每頁一顆主要動作、
  人話文案、畫面不印路由／設定鍵名／原始 JSON；Direction D 視覺 token（白底、細線、Orange 只給動作、
  Montserrat＋Noto Sans TC）。見 `2026-09-04-ui-redesign-v3-1-workbench-design.md`。

### 6.3 架構分層【判斷】

```
 ┌──────── 前端（TS＋React，建置後的靜態檔）────────┐
 │ 頁面 → 型別化 API client（由後端契約產生）        │
 └──────────────────────┬───────────────────────────┘
 ┌──────── Web 層（Flask）─────────────────────────┐
 │ 認證／CSRF／TLS／限流 │ 路由只做：驗證輸入→呼叫服務→包信封 │
 └──────────────────────┬───────────────────────────┘
 ┌──────── 服務層 ───────────────────────────────────┐
 │ 收集 │ 告警 │ SIEM 轉送 │ 報表 │ 管理 │ （調查、政策動作：v6.1 位置）│
 └──────────────────────┬───────────────────────────┘
 ┌──────── 領域核心（純函式，無 I/O）─────────────────┐
 │ 值域登錄 │ filter 模型 │ 規則評估 │ 報表分析 │ 計量（頻寬／量） │
 └──────────────────────┬───────────────────────────┘
 ┌──────── 資料存取 ──────────────────────────────────┐
 │ PCE client │ FlowSource／EventSource（store／live／archive 唯一實作）│ Store │ Settings │
 └───────────────────────────────────────────────────┘
 排程（APScheduler，同行程）只負責「何時呼叫哪個服務」。
```

相依規則：箭頭只能往下；下層不得 import 上層；領域核心不得做 I/O、不得 print、不得讀全域設定。

三個「只准寫一次」的核心，對應 5.x 最大的三處重複：

1. **值域登錄**：policy decision（四值）、draft policy decision（七值軸）、rule 型別
   （allow/deny/override_deny）、告警規則型別、嚴重度、協定、報表型別、SIEM 格式／傳輸、資料來源等，
   全部在此定義一次，前端型別由此產生。編碼只用字串，不用整數。
2. **filter 模型**：一個 filter 定義，編譯成三種執行形式——PCE async query payload、store 查詢、
   DataFrame 篩選；能力限制（某來源不支援某條件）由模型宣告，不由各呼叫端各自白名單。
3. **FlowSource**：「這次查詢的資料從 store、live PCE 還是 archive 拿、缺口怎麼補、結果標示什麼來源與
   完整度」只有一個實作；告警、報表、調查、SIEM 都經由它。

### 6.4 資料與狀態【判斷】

- **設定**：一個有驗證、帶 `schema_version` 的設定檔（操作者可檢視、可備份、是遷移的對象）。
  寫入時整份驗證，不合法拒寫；所有設定鍵都必須在 schema 宣告。
- **執行期狀態**（watermark、冷卻、throttle、job 健康、報表工作進度、告警紀錄、SIEM 佇列與 DLQ、
  排程狀態、儀表板摘要）：SQLite 資料表，**每張表一個擁有模組**。不再有 `state.json`、
  `dashboard_summary.json`、`job_health.json`、`async_query_jobs.json` 這類共寫檔。
- **大量資料**（events、flows、聚合、封存）與**應用狀態**分開管理，清除、回填、換 PCE 都不碰設定與
  告警紀錄。實體上是兩個 DB 還是同庫分表，由 builder 決定。
- 每種產出（報表檔、封存、快照、log）都有保留期限與清理機制，並列入同一份清單核對。
- 換 PCE（url／org_id 改變）時清除所有衍生資料，清單只有一份。

### 6.5 v6.0 功能範圍

**必做**（§4.1 目標 1、2、5 與管理面）：

- **資料收集**：events 與 traffic flows 經 API 收進 store；聚合、保留、封存、回填；PCE 速率限制；
  延遲與容量監控；截斷與資料遺失偵測（5.x 的看門狗／meta-alert 行為保留）。
- **告警**：規則型別 event、traffic、bandwidth、volume、system（PCE 健康）；門檻
  （立即／計數）、視窗、冷卻、throttle；通道 email（SMTP）、LINE、Telegram、Teams、webhook；
  逐通道測試；最佳實務規則包；告警紀錄保留；GUI 檢視最近告警與單筆詳情（含流量對應的政策解釋）。
- **SIEM 轉送**：audit 事件與流量；格式 cef、json、syslog_cef、syslog_json、cef_pce、syslog_cef_pce；
  傳輸 udp、tcp、tls、hec；依 policy decision 過濾；PII 遮罩；DLQ 檢視、重送、清除、匯出；狀態頁。
  `cef_pce` 已經 Graylog 實測驗收（2026-09-12），格式行為保留。
- **管理**：PCE 連線（on-prem／SaaS、console_url、verify_ssl、事件 timeout）與手動健康檢查、
  管理者帳號（初始密碼與改密閘沿用 5.x：閘門機制存在，但依使用者先前要求預設不強制首次改密，
  `config.py` `_ensure_web_gui_secret`）、允許 IP、TLS、通知通道、語言／時區、資料保留設定、背景工作健康、模組日誌。
- **升級遷移**（§7）。

**報表**（§4.1 目標 3）：產生、排程、寄信、HTML（report_shell）與 XLSX 輸出。保留的型別：

| 型別 | 回答的問題 | 決定 |
|---|---|---|
| traffic、security_risk、network_inventory | 東西向流量全貌與潛在風險（findings 規則引擎 B/L/R 系列） | 保留（風險主體） |
| readiness | 能不能切強制模式 | 保留 |
| app_summary | 單一應用的依賴與基線 | 保留 |
| policy_diff | 草稿與已佈署政策差在哪 | 保留 |
| audit | PCE 事件稽核 | 保留 |
| ven_status | agent 健康與版本分布 | 保留 |
| policy_usage | **草稿政策**下哪些規則會被流量用到、哪些流量會被草稿擋掉（draft rulesets＋`compute_draft`） | 保留【使用者】 |
| rule_hit_count | **已佈署規則**的實際命中次數（PCE 原生 RHC 報表） | 保留，**含啟用 RHC**：RHC 只能經 API 開啟，**SaaS 與地端都要能在本產品開啟**【使用者，2026-10-24】（見下「RHC 啟用」）。**RHC 只記錄已 provision 的規則**【使用者】：報表必須區分「沒有紀錄」（草稿規則、或期間內尚未佈署）與「有紀錄但 0 次」，不得把前者顯示成 0；草稿規則導向 policy_usage。RHC 是否只從啟用時刻起累計：NFR 尚無法實測，P5 在可啟用的環境驗證 |
| policy_resolver | 把已佈署規則展開成 IP 層級的平面列，供其他工具使用（例如與傳統防火牆規則比對） | 保留，維持 JSON＋CSV 輸出、不做 HTML；列數上限與截斷揭露照舊【使用者】 |

另【判斷】：拿掉所有 CSV 上傳輸入（PCE UI 匯出、workloader、vuln CSV）與獨立的 `draft_policy`
偽型別——產品前提是走 API；draft policy decision 已是 traffic 家族報表的內建欄位。

**RHC 啟用（v6.0 唯一會寫 PCE 的動作）**【使用者，2026-10-24 定案】：RHC 只能經 API 開啟，**不分 SaaS
或地端**（REST API〈Rule Hit Count〉：PCE 與 VEN 預設都關閉，兩邊都要開）。流程：

1. **狀態檢查**：產品隨時能回答「RHC 開了沒」。判定依兩個讀取：
   `GET /orgs/{org}/report_templates/rule_hit_count_report` 的 `enabled`（PCE 端），以及
   `GET /orgs/{org}/sec_policy/active/firewall_settings` 的 `rule_hit_count_enabled_scopes`（VEN 端，非空才算開；
   `[[]]` 為全部 VEN，否則為指定 scope）。狀態為：已開啟／只開了一半（指出哪一半）／未開啟／無法判定（權限或連線錯誤，
   照實顯示原因，不猜）。
2. **報表反灰**：未完全開啟時，報表頁的 rule_hit_count **反灰、不能產生，也不能排程**，旁邊說明原因並連到設定頁；
   已排程的 RHC 報表在執行時若發現未開啟，記為失敗並寫明原因，不產出空報表。
3. **在設定頁開啟**：開啟動作只放在設定頁（報表前置設定），不放在報表頁。按下後才經 API 執行：
   `PUT /orgs/{org}/report_templates/rule_hit_count_report {"enabled": true}` →
   `PUT /orgs/{org}/sec_policy/draft/firewall_settings`（`rule_hit_count_enabled_scopes`，預設 `[[]]`）→
   `POST /orgs/{org}/sec_policy`，`change_subset` 只含 firewall_settings（不會順帶 provision 客戶其他草稿）。
   已開的那一半不重做。

防護【判斷】：
- 執行前顯示將做的步驟與「會 provision firewall_settings」，操作者確認後才執行；任一步失敗即停，回報已完成到哪一步，
  之後重新檢查狀態並顯示。
- 執行前比對 draft 與 active 的 firewall_settings；若已有客戶自己尚未 provision 的 firewall_settings 變更，
  拒絕執行並說明（否則會被一併 provision）。
- PCE 拒絕（403 等）時照實顯示 PCE 的回應與「需要可寫入、具組織管理權限的 API key」，不得顯示成功。
- 架構上歸在報表服務的「報表前置設定」，不開「政策動作」服務。

**P5 開工時要先釐清的已知風險**：NFR SaaS（26.40.2）以 owner 角色的 user API key 對
`PUT /report_templates/rule_hit_count_report` 回 403（連 `enabled:false` 也是），`optional_features` 沒有相關旗標，
官方文件也未列 SaaS 差異。P5 要在 NFR 找出原因（例如 API key 的類型或角色、租戶設定），在那之前上述流程的第 3 步
在該租戶會走「PCE 拒絕」分支並如實顯示。

**v6.0 不做，延到 v6.1**【判斷，使用者未表示異議；可推翻】：調查工具（流量搜尋、workload 搜尋、
事件檢視、VEN 車隊總覽）與其他**會寫 PCE** 的動作（隔離、規則／ruleset 定時啟停並 provision、
VEN enforcement 推進、心跳加速）。理由：使用者排序最後、測試機無使用痕跡。
架構保留「調查」與「政策動作」服務的位置，v6.1 加入時不需改動下層。

因此 v6.0：除 RHC 啟用外，PCE client 不做任何政策或 workload 寫入；**目標是日常運作只需唯讀 API
角色**，啟用 RHC 是一次性動作、需要可寫入的權限。讀取路徑仍有三個 POST——
`/traffic_flows/async_queries`（流量查詢）、`/sec_policy/{pversion}/rule_search`（政策解釋）、
`POST /orgs/{org}/reports`（拉 RHC 報表，會在 PCE 建立報表物件）。

**NFR 實測（2026-10-24，SaaS 26.40.2，以 API 臨時建立 `read_only` 角色的 service account，測完即刪）**：
- `POST /traffic_flows/async_queries` → 202、`POST /sec_policy/active/rule_search` → 200：**唯讀角色可用**。
- `POST /reports` → 403（RHC、executive_summary、ransomware_risk 三種範本皆同；同一請求用 owner key → 201）：
  **唯讀角色不能產生任何 PCE 原生報表**。所以只要要拉 RHC 報表，日常 key 就不能是 `read_only`。
- 用 **owner** 角色的 user API key `PUT /report_templates/rule_hit_count_report`（連 `enabled:false` 的 no-op 也一樣）
  → 403 `forbidden_error "Access denied."`；`POST /reports`（RHC）→ 403 `"report template type rule_hit_count_report
  not enabled"`。NFR 上 RHC 範本是停用的，**tenant owner 無法經 API 啟用**；官方文件（REST API 26.1）寫的是
  「organization administrator」可做，與實測不符。依防護規則第一步失敗即停，未動 firewall_settings。
- RHC 啟用的 SaaS 403 見上方「P5 開工時要先釐清的已知風險」。

**API key 角色實測（2026-10-24，lab 地端 26.2.20 與 NFR SaaS 26.40.2 結果相同）**：以 API 為每個角色臨時建立 service account，
跑 v6 會用到的呼叫（寫入類一律送無效 body：403＝無權限、406＝有權限但內容不合法，不改任何資料），測完即刪。

| 呼叫 | read_only | global_object_provisioner | ruleset_* / workload_manager | admin | owner |
|---|---|---|---|---|---|
| labels、workloads、rule_sets、流量查詢、rule_search | ✓ | ✓ | 多數 ✓（workload_manager ✗） | ✓ | ✓ |
| events、active firewall_settings | ✓ | ✓ | ✗ | ✓ | ✓ |
| 讀 RHC 報表範本（狀態檢查） | ✗ | ✗ | ✗ | ✓ | ✓ |
| 產生任何 PCE 原生報表（含 RHC 報表） | ✗ | ✗ | ✗ | **✗** | ✓ |
| 開啟 RHC 報表範本 | ✗ | ✗ | ✗ | ✗ | ✓ |
| 改 draft firewall_settings、provision、建 label／ruleset | ✗ | 部分（provision 全域物件） | 部分 | ✓ | ✓ |

- **只有 owner 能產生 PCE 原生報表與開啟 RHC 範本**，連 admin 都不行；owner 角色可以給 service account。
- 除了 RHC 以外，v6 的監控、告警、SIEM、資料收集與其他報表（都由本機收集的資料產生）只需要 `read_only`。
- 現況：客戶的 key 都給 owner【使用者，2026-10-24】。建議見 §6.5 決定紀錄（待使用者選擇）。

**PCE 健康檢查與網址（依部署型態）**【使用者要求依官方文件，2026-10-24；P1 已實作探測順序】：
- 共同基線：`GET /api/v2/noop`（驗證連線與 API 憑證，Public Stable API）。
- 地端另加：`GET /api/v2/health`（HTTP 200 且 body 狀態為 normal；warning／critical 等為不健康，讀不懂為「未知」）→
  `GET /api/v2/node_available`（200 或 202）。這兩個端點文件註明只適用地端，**SaaS 不呼叫**。
- SaaS 是否健康不能只靠一次 HTTP 探測；P2 起加上事件與流量收集的最新狀態與延遲。
- 網址格式不同：地端 API 網址是 PCE 本身（通常 `https://<pce-fqdn>:8443`），主控台就是同一個網址；SaaS 的 API
  網址是區域 SCP 主機（`https://<scp>.illum.io:443` 這類），人類登入走 Illumio Console（預設 `https://console.illum.io`，
  亦可為自訂的 `*.illumio.ai`），兩者不同。設定頁依部署型態給對應的範例與主控台預設值；`console_url` 留空時，
  SaaS 用 `https://console.illum.io`，地端用 API 網址。
- 部署型態是明確欄位（`on_prem`／`saas`），不從主機名稱推測。

告警詳情頁的主要動作為「在 PCE 主控台開啟」（`console_url`）。規則編輯器需要的 label／IP list 等
物件查詢、告警詳情裡的政策解釋仍要做。5.x 的規則排程（`rule_schedules.json`）與 VEN 推進紀錄
不遷移，升級報告列出它們並說明 v6.0 不支援。

## 7. 從 5.x 升級【使用者：設定必須帶過去，資料不必】

- **搬什麼**：PCE 連線（含憑證）、告警規則（`config/alerts.json`）、通知通道與 SMTP、SIEM 轉送與
  目的地、資料收集與保留設定、報表排程與輸出設定、語言／時區、GUI 管理者帳號（密碼雜湊）與允許 IP、
  TLS 設定與 `config/tls/` 憑證。規則排程（`config/rule_schedules.json`）v6.0 不支援，只列入報告
  （§6.5）；v6.1 加回時再補遷移。
- **不搬**：pce_cache DB、封存、`alerts.sqlite`、`state.json`、報表與趨勢歷史。v6 從空的 store 開始，
  在 PCE 仍保留的期間內自動回填。
- **格式容忍**：5.x 設定檔**沒有版本欄位**，遷移器必須吃下所有 5.x 形狀，至少包括：deprecated 鍵
  （`report.attack_surface`、`web_gui.tls.http_redirect_port`、`pce_profiles`、`active_pce_id`、
  `pce_cache.archive_review_max_days`）、`line_token` 別名、SIEM 舊 `endpoint` 欄、舊版 `alerts.json`
  為通道設定的形狀、traffic 規則的 legacy 純量鍵與 FilterBar 物件鍵兩種寫法、`pd` 整數編碼
  （0 allowed／1 potentially_blocked／2 blocked／-1 全部）、CLI `rule edit` 誤寫的 `threshold` 鍵
  （引擎實際讀 `threshold_count`）、未宣告在 schema 的鍵（`settings.fleet_*`、`events.overlap_seconds`、
  `dashboard.*`）、最佳實務規則的 `*_key` 欄位。
- **不無聲丟棄**：遷移器先產出報告（搬了什麼、改寫了什麼、丟掉了什麼、為什麼），操作者確認後才寫入；
  任何無法對應的鍵或規則都要列在報告裡。
- **確認發生在安裝時**【判斷】：`install.sh` 偵測到 5.x 安裝時執行遷移器，在 shell 顯示報告並互動確認；
  另提供非互動旗標（接受報告、或只產生報告不寫入）。這樣管理者帳號、允許 IP、TLS 在 v6 第一次啟動前
  就已就位，不需要 GUI 引導模式。遷移器屬於安裝面，不構成 CLI。
- **切換時的連續性**【判斷】：v6 回填的歷史資料**只供報表與檢視**，不送 SIEM、不進告警評估。
  SIEM 與事件告警的起點：遷移器盡力從 5.x 讀出各 SIEM 目的地／各來源已送到哪裡、事件告警的
  watermark（只讀這幾個高水位時間點，不搬資料），v6 從那裡接續，達成不重送也不漏送；讀不到時
  從 v6 安裝時刻開始，報告中明說停機期間的缺口。回退到 5.x 時，5.x 從它自己停下的地方接續，
  可能重送升級期間的資料，回退文件要寫明。
- VEN 推進紀錄（`config/fleet_progressions.json`，5.x 寫在執行目錄相對路徑）同上：v6.0 只列入報告。
  客戶為 v5.0.0，該檔要到 5.2.0 才存在，實務上應不會出現。
- **可回退**：升級保留 5.x 安裝目錄與資料原樣，提供文件化的回退步驟。
- **測試資料**：客戶設定檔拿不到，只能參考測試環境。【使用者】fixture 兩個來源：(1) 測試機 .106 的
  真實設定（去識別化，5.2.x 形狀）；(2) 由 git tag `v5.0.0` 的 `config_models.py`／`_DEFAULT_CONFIG`／
  GUI 寫入端推出的 5.0.0 形狀（客戶實際版本）。遷移器至少要涵蓋 5.0.0 到 5.2.x。
- **`pd` 對調風險**：5.1.0 以前 CLI 精靈存的 `pd` 0／1 對調；已知客戶沒有用 CLI 建規則，所以照現行
  序數轉換（0 allowed／1 potentially_blocked／2 blocked／-1 全部），不另做人工確認。【使用者】

## 8. 回收、重寫、刪除【判斷】

回收是「搬進新結構並保留其行為測試」，不是原地保留。依盤點的自足程度與契約測試覆蓋判定：

| 處置 | 項目 |
|---|---|
| **回收** | `api_client` 的 HTTP 核心（重試、TLS、auth、速率限制）與**經真 PCE 驗證的行為及其測試**（X-Total-Count 為未過濾總數、500 上限＋async 回補、label 同 key 為 OR、ip_address 只接受純字串否則 406、裸日期 406、POST 429 只重試一次、Rule Search 6 份錄製 fixture）；`events/matcher`、`events/normalizer`、事件目錄；`pce_cache/traffic_filter`；`pce_target`；SIEM formatters／transports／DLQ／mask；報表 `analysis/*` 純模組（policy_resolver、policy_diff 四核心、posture／advisor、estate_inventory 等）、`df_filter`、`port_token`、`report_shell` 與 exporters；`rule_hit_count_enablement` 的三步啟用流程；i18n 字典（去掉 CLI 鍵）；安裝／預檢／移除腳本與 systemd hardening；Direction D 設計 token；`calculate_mbps` 三態計量 |
| **重寫** | 所有 GUI 路由與整個前端；`analyzer.py`／`reporter.py` 拆成收集→評估→通知；設定與狀態的所有權；報表產生入口（單一函式、單一參數結構）；cache／live／archive 取數（§6.3 FlowSource）；filter 執行（§6.3 filter 模型）；async job 生命週期（5.x 兩套、7 個輪詢迴圈）；SMTP（5.x 三份） |
| **刪除** | `src/cli/`、`src/main.py` 的選單與 argparse、三支 `*_cli.py`、`settings/`、所有相容 wrapper、無讀者的路由與功能（`shadow` 比對器、`alert_dlq`、`rule_backups`、`_rs_background_scheduler` 等） |

已知的 5.x 缺陷在新程式中不得重現，清單見 `tmp/rearch-2026-10-24/survey/99-synthesis.md` §6 與各分檔
「雜亂證據」節；builder 應把它們轉成新程式的守門測試。

## 9. 驗證方式

- 回收模組的行為測試隨模組搬移並持續通過。
- 告警、SIEM、報表、遷移各有對真實測試機（.106，lab PCE，on-prem）的端到端驗收；SaaS 另在
  **NFR SaaS 租戶**驗收，可自由使用，包括會觸發告警的臨時變更。【使用者】報表依專案規則以實際樣本
  資料完整產出、逐頁檢查截斷與溢出。
- GUI 以 Playwright（Python）做端到端測試；斷言使用者可見行為與不變量，不綁 DOM 結構。
- 守門測試在宣稱有效前，先注入它該抓的缺陷確認會變紅。
- 遷移器以 §7 的兩類 fixture（測試機真實設定、v5.0.0 形狀）驗證，並在測試機做一次 5.x→v6 實際升級
  與回退。注意 .106 目前持續以 5.x 運作（SIEM→Graylog、告警），切換驗收會中斷它，排程時要考慮。

## 10. 留給 builder 的

函式庫選擇（OpenAPI／型別產生工具、React 周邊套件）、DB 實體切分與 schema、模組與目錄命名、
頁面版面細節（在 v3.1 IA 與 Direction D 內）、程式碼放置方式（建議同 repo、新套件目錄、長期分支，
切換時刪除舊碼）、工作切分與順序。

## 11. 待使用者決定

（2026-10-24 builder check 後整理；使用者回答後改寫成決定並移到對應章節。）

全部已回答：試點客戶事實（§3、§7）、SaaS 驗收環境（§9）、policy_usage 保留、policy_resolver 維持
現狀（§6.5）。v6.0 範圍（調查與寫 PCE 動作延到 v6.1）使用者未回覆，已按建議寫入 §6.5 並標為可推翻。
遷移器對指向已移除型別或功能的報表排程，列入報告並略過。

## 12. 參考

- 現況盤點：`tmp/rearch-2026-10-24/survey/`（00 合約、a PCE 存取、b 快取與狀態、c 監控告警 SIEM、
  d 報表、e CLI 設定 i18n 部署、f GUI、g Codex 判讀、99 彙整）。
- v3.1 工作台設計：`docs/superpowers/specs/2026-09-04-ui-redesign-v3-1-workbench-design.md`。
- cef_pce 格式：`docs/superpowers/specs/2026-09-11-cef-pce-native-format-design.md`。
- 部署目標：測試機 .106（git checkout）、內部機 .135（離線 bundle）。
