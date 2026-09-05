---
title: Web GUI 導覽
audience: [operator]
version: 5.0.0
last_verified: 2026-09-05
verified_against:
  - src/templates/index.html
  - src/templates/login.html
  - src/static/js/v2/app.mjs
  - src/static/js/v2/shell.mjs
  - src/static/js/v2/core/router.mjs
  - src/static/js/v2/areas/home.mjs
  - src/static/js/v2/areas/alerts.mjs
  - src/static/js/v2/areas/investigate.mjs
  - src/static/js/v2/areas/policy_rules.mjs
  - src/static/js/v2/areas/policy_scheduler.mjs
  - src/static/js/v2/areas/reports.mjs
  - src/static/js/v2/areas/system.mjs
  - src/static/js/v2/areas/login.mjs
  - src/static/js/v2/components/healthbar.mjs
  - src/static/js/v2/components/page.mjs
  - src/static/js/v2/components/filter-bar.mjs
  - src/static/js/v2/components/palette.mjs
  - src/gui/__init__.py
  - src/gui/routes/auth.py
  - src/gui/routes/dashboard.py
  - src/gui/routes/actions.py
  - src/gui/routes/rules.py
  - src/gui/routes/events.py
  - src/gui/routes/reports.py
  - src/gui/routes/rule_scheduler.py
  - src/gui/routes/config.py
  - src/gui/routes/admin.py
  - src/gui/routes/filter_objects.py
  - src/gui/filter_object_cache.py
  - src/config.py
  - src/job_health.py
  - src/cli/gui_cmd.py
---

# Web GUI 導覽

Web GUI 是單頁式應用（SPA）。登入後畫面分成**五個區**——首頁、調查、規則、
報表、系統——底下共 **23 條路由**，以 URL 的 hash 表示（例如
`#/investigate/traffic`）。區的導覽在**畫面左側**（224px 一欄；v3.1，
2026-09-05 起），目前所在的區會展開它的子項；≤1000px 時導覽收成頂列。
設計依據 `docs/superpowers/specs/2026-09-04-ui-redesign-v3-1-workbench-design.md`
（取代 v3 spec 的 §1／§2／§3／§5／§8）。切區不重新整頁：hash 一變，router 就 lazy-mount
對應的區模組，只有被造訪過的區才會被下載。內容全部由前端 ES module 向約
85 條 JSON API（`/api/...`）取資料，精確端點清單見
[rest-api.md](../reference/rest-api.md)。

前端沒有打包步驟（zero-build）：`src/templates/index.html` 直接以
`<script type="module">` 載入 `src/static/js/v2/app.mjs`，模組分成
`core/`（router、api、i18n、theme、fmt…）、`components/`（page、healthbar、
palette、table、drawer、modal、filter-bar…）、`areas/`（home、alerts、investigate、policy_rules、policy_scheduler、reports、system，加上共用卡片庫 cards）三層。
頁首（麵包屑＋標題句＋動作列）與清單列、晶片都由 `components/page.mjs` 提供，
各區只畫內容。

啟動方式與埠號見 `illumio-ops gui`（預設埠 **5001**，`--host 0.0.0.0`），
完整 CLI 選項見 [cli.md](../reference/cli.md)。

**五區與其路由**（判準：首頁看「現在」、調查查「這件事」、規則改「規則」、報表產「交付物」、系統改「系統」）

> 區名「規則」在英文介面是 `Policy`。左側導覽的 `Policy`／`Rulesets` 兩項
> 自 2026-09-05 起在中文介面譯為「規則」「規則集」；這兩個詞在報表、CLI 與
> 頁面內文仍維持英文（`src/i18n/data/glossary.json` 的 `exempt_keys` 只對這
> 兩個鍵開豁免）。

| 區 | 路由 | 內容 |
|---|---|---|
| 首頁 | `#/home` | 頂端四格儀表（VEN 健康／被標記的流量／擷取管線／24 小時告警），下方最近的告警（前 10 列，未處理／全部切換），右欄三張背景卡：系統健康六燈、今天的排程、Policy 現況 |
| 調查 | `#/investigate/alerts`（`?id=` 告警頁）、`/traffic`（`?alert=`、`?f=` 帶條件）、`/workloads`、`/events` | 告警清單與告警頁；流量搜尋；Workload 搜尋與隔離；事件檢視器 |
| 規則 | `#/policy/alert-rules`、`/ops`、`/rulesets`（`?rs=&rule=`）、`/schedules` | 告警規則 CRUD 與手動動作；Rule Scheduler 的 ruleset／rule 瀏覽與排程變更 |
| 報表 | `#/reports`、`/schedules` | 11 型報表產生、產出清單、報表排程 |
| 系統 | `#/system/{pce,cache,siem,tls,security,display,channels,alerting,jobs,logs}` | 所有設定、告警通道與測試、背景 job、日誌 |

舊路由仍可用，router 以 `replace` 轉到上表對應頁並保留 query：v2 六區的
`#/overview`、`#/alerting/*`、`#/automation/*`，以及 3B 的
`#/investigate/inbox`（含 `?id=`）。

<details><summary>v2 六區路由表（2026-09-04 前，供舊書籤對照）</summary>

| 區 | 路由 | 內容 |
|---|---|---|
| 總覽 | `#/overview` | 系統狀態、posture、排行、報表摘要、健康列 |
| 調查 | `#/investigate/traffic`、`/workloads`、`/events` | 流量分析、Workload 搜尋與隔離、事件檢視 |
| 告警 | `#/alerting/rules`、`/ops` | 告警規則 CRUD、手動動作與測試 |
| 自動化 | `#/automation/rules`、`/reports`、`/jobs` | Rule Scheduler、報表排程、背景 job 健康 |
| 報表 | `#/reports` | 11 型報表產生與產出清單 |
| 系統 | `#/system/{pce,cache,siem,tls,security,display,channels,logs}` | 所有設定 |

</details>

未知的 hash 會落到 placeholder mount，不會讓畫面壞掉；直接輸入任何一條
路由網址都能到達（覆蓋率閘門 `tools/gate_coverage_live.py` 就是靠逐一開啟
每條路由、檢查 108 個 `data-cov` 錨點在不在來把關的）。

> **全域安全提醒**：除 `/login`、`/api/login`、`/logout`、`/api/csrf-token` 外，
> 所有路由都需登入 session。`web_gui.allowed_ips` 提供 IP 允許清單，比對的是
> **直接連線來源 IP**（`request.remote_addr`），被拒的連線以 TCP RST 靜默切斷
> （避免被埠掃描偵測到有服務在監聽）。所有 POST／PUT／DELETE 都需 CSRF token。
> 設定細節見 [configuration.md](configuration.md) 的「web_gui／TLS」一節。

## 登入與 session

- 登入頁在 `GET /login`，前端呼叫 `POST /api/login`（JSON，帳密），成功後
  `flask_login` 建立 session（`session.permanent = True`），並回傳
  `csrf_token` 供後續寫入操作使用。
- 預設帳密固定為 **`illumio` / `illumio`**（帳號可由 `web_gui.username` 覆寫），
  密碼以 **Argon2id** 雜湊儲存。
- **強制改密門檻現況**：程式碼裡確實存在 `must_change_password` 閘門
  （`src/gui/__init__.py` 的 `security_check`：旗標為真時，除 `Security`
  設定頁、登出、CSRF-token 端點外，其餘所有已驗證 API 一律回 **HTTP 423**）。
  但 `src/config.py` 首次啟動產生預設密碼時**明確把這個旗標寫死為
  `False`**（程式碼註解：「forced first-login password change...is DISABLED
  by operator request — the default stays valid until the admin changes it
  manually in Settings」）。也就是說：**目前預設帳密 `illumio`/`illumio`
  會一直有效，直到管理者自行到 Settings → Security 手動改密**，登入後不會
  被強制導向改密表單。前端仍保留「登入回應帶 `must_change_password` 旗標時
  顯示內嵌改密表單」的邏輯（`src/static/js/v2/areas/login.mjs`），只是預設路徑不會觸發它——若日後
  該旗標被改回 `True`，這段 UI 會自動生效。
- 登入頁與相關文件如提到「首次登入強制改密」，以本節（依原始碼查核）為準。


## 跨區機制

這幾樣不屬於任何一區，但每一區都會用到。

### 左側導覽與使用者選單

一欄 224px：最上是產品標誌，中間是五個區——目前所在的區會展開它的子項，
未處理告警數以小圓標掛在「調查」上——底部是指令面板入口（`SH-03`）與使用者
彈出選單（`SH-02`）：登出，以及主題與密度的快速切換。完整的顯示偏好（時區、
語言、主題、密度）在 `#/system/display`，兩處改的是同一份設定。

導覽的高亮跟著網址走（`SH-01`）：直接貼一條深層路由進網址列，對應的區會
展開且該子項標為目前頁。≤1000px 時整欄折成可橫向捲動的頂列，子項隱藏。

### 指令面板（Cmd+K）

`XC-02`。按 <kbd>Cmd</kbd>/<kbd>Ctrl</kbd>+<kbd>K</kbd> 開啟，輸入關鍵字
直接跳到任何一條路由或動作，不必逐層點選。這是最快的導航方式，尤其適合系統區那 10 個子頁。

### 系統健康（只在首頁）

`HM-02`。首頁右欄第一張卡，六盞燈各一句話：**背景工作**、**PCE 連線與探測**、
**擷取延遲**、**SIEM 轉發**（成功率低於 95% 至少升為 warn）、**告警管道**、
**VEN**。每盞燈可展開看判斷的原因與前往該項設定的連結。

**它只在首頁**：v3.1 之前這是橫跨頁面上緣的全域健康列，現在是首頁自己的
內容（`areas/home.mjs` 用 `healthbar.mjs` 的 `computeLights` 算燈號），
離開首頁自然就不在。

### 主題、密度與雙語

`XC-05`／`XC-06`。亮／暗主題與 compact／comfortable 密度**立即生效**，不需
重新載入頁面；時區與語言（English／繁體中文）同樣即時套用。設定位置在
`#/system/display`。

### 錯誤卡與重試

`XC-10`。API 失敗時該區塊會換成錯誤卡，附**重試**按鈕與可展開的技術細節
（狀態碼、端點），而不是整頁白畫面或靜默留白。

### 網址即狀態

`SH-01`。目前所在區、子頁都反映在 hash 上，可直接複製網址分享或加書籤。

## FilterBar v2 物件選擇器

流量查詢（Traffic Analyzer）與部分報表篩選共用同一套「PCE 風格 filter
物件選擇器」元件（`src/static/js/v2/components/filter-bar.mjs` 的 `createFilterBar()`，
每個容器可各自實例化一份，狀態互不影響）。這是全庫目前唯一的圖形化物件
選擇入口，過去沒有文件記錄過其操作語意，以下按元件內部語意逐項說明。

### 可選物件類別（pill 分類）

依欄位不同，可選類別包含：`label`（單一 label）、`label_group`（label
group）、`iplist`（IP List）、`workload`（單一 workload）、`ip`（手動輸入
IP／CIDR／範圍）、`service`（Policy Service 物件）、`port`（埠／埠範圍，
可選 TCP-only／UDP-only／both）、`process`（process name 自由字串）、
`winservice`（Windows service name 自由字串）、`transmission`（僅
Destination 欄位可用，值域固定 `unicast`／`broadcast`／`multicast`，無需
查詢）。

- **輸入引導**：Service 欄位輸入純數字時（如 `443`）會列出「TCP+UDP（預設）
  ／僅 TCP／僅 UDP」三選一；輸入埠範圍（`1000-2000`）同樣給三選一；已帶
  `/tcp`、`/udp` 尾碼則直接視為單一候選。純文字輸入則同時給出 Process
  Name 與 Windows Service 兩種自由值候選。
- **物件查詢**（`GET /api/filter-objects/suggest`，`src/gui/routes/
  filter_objects.py`）：debounce 250ms、AbortController 取消舊請求。
  Labels／Label Groups／IP Lists／Services 走跨-request 的 module 快取
  （`filter_object_cache`），PCE 離線時仍可用快取內容回應；Workload 為即時
  查詢（同時比對 name 與 hostname、依 href 去重），PCE 離線時該類會回
  `error: "pce_unreachable"` 並降級為空清單，不影響其餘可快取類別。
- **瀏覽端點**（`GET /api/filter-objects/browse`）：供「不用輸入關鍵字、
  直接翻頁看全部」的瀏覽模式，僅 4 個可快取類別支援（`workload` 回
  `browseable: false`）。

### include／exclude（is-not 排除列）

每個 pill 可標記為 include（預設）或 exclude（is-not）。Exclude 列預設
收合（`exclOpen` 狀態初值 `false`），需展開才會顯示。序列化時 exclude
pill 一律加上 `ex_` 前綴對應到 native filter key（例如 `dst_labels` 的
排除版是 `ex_dst_labels`）。

### 同 key OR、跨 key AND

這是元件與後端比對器共用的核心語意（`src/analyzer.py` 原始碼註解語意摘要）：

- **同一個 filter key 內的多個值 = OR**。例如同時加兩個 Destination Label
  pill（`Env=prod`、`Env=staging`），序列化為 `dst_labels: ["Env=prod",
  "Env=staging"]`，比對時符合任一個即算命中。
- **不同 key 之間 = AND**。例如同時設定 Source Label 與 Destination
  Port，兩個條件必須同時成立。
- `any_*` 系列（不分方向，同時比對 src 與 dst）是 Phase 1 遺留的單值 key，
  同一類別重複加入時**取最後一個值**（非陣列、不是 OR 清單）；且
  `label_group` 明確**不支援** any 方向（加入時前端會擋、序列化邊界也有
  防禦性拒絕並在 console 留警告），因為 group 展開只在 PCE 端進行，若
  被誤當成 `any_label` 比對會 fail-closed 回 0 筆，而非給出誤導的結果。

### mode：and／or（欄位配置）

`mode: 'and'` 是預設版面：Source／Destination 各自一欄，pill 各自歸類到
對應方向的 key。`mode: 'or'` 會把兩欄合併成一欄，此時該欄新增的 pill 一律
落在 `any_*` key（即「來源或目的其中一邊符合即可」，適用不區分方向的查
詢情境，例如「這個 IP List 不管出現在來源還是目的都要看到」）。

### 與既有查詢表單的關係

FilterBar 序列化出的 key（`src_labels`／`dst_workloads`／`services`／
`ports`／`process_name`／`windows_service_name`／`transmission`／
`any_iplist`… 等）直接對齊 `analyzer.query_flows` 的 native filter
白名單，可與既有的 Policy Decision、時間範圍等純表單欄位並用，兩者最終
一起交給同一組 AND 條件求值。


## 五區逐一導覽

> **過渡註記（2026-09-05）**：首頁與告警兩節（下方）已依 v3.1 重寫；其餘各節
> 仍是 v2 六區時期的畫面說明，功能描述正確，路由與分區名稱以上表為準。
> 對照：總覽→首頁；告警規則／手動動作→政策區（手動動作與通道測試在
> `#/system/alerting`）；自動化的 Rule Scheduler→政策區、報表排程→報表區、
> 背景 job→`#/system/jobs`。

### 首頁（`#/home`）

標題就是這一頁的答案：「N 件告警還沒處理，系統有 M 項要看一下」。

- **四格儀表**（HM-06）：VEN 健康（線上／總數）、被標記的流量（近 7 天
  blocked ＋ potentially blocked，附與前一期的比較）、擷取管線（判定字＋近一
  小時送達率與死信佇列筆數）、24 小時內發出的告警（附送出失敗與被抑制數）。
  四格各自是連結，分別到 `#/system/pce`、`#/investigate/traffic`、
  `#/system/cache`、`#/investigate/alerts`。資料取自 `/api/dashboard/overview`，
  與健康燈同一次載入。快取未開或該面板算不出來時顯示破折號並說明原因，不印 0。
- **最近的告警**（HM-01）：前 10 則，一列一件——左側嚴重度色條、時間、規則名
  與一句摘要、狀態晶片。整列就是連結，點進去是那一件的告警頁。上方可在
  「未處理／全部」之間切換，右上「看全部」到 `#/investigate/alerts`。
- **系統健康**（HM-02）：六盞燈，見上面的〈系統健康〉。
- **今天的排程**（HM-03）：今天會發生的規則排程、報表排程與 retention／archive
  工作，各一行連到它自己的頁。
- **Policy 現況**（HM-05）：posture 分數、已納管 workload 比例、ruleset 數，
  以及到報表區的連結。

### 告警（`#/investigate/alerts`）

- **清單**（AT-01）：與首頁同一種列，加上狀態篩選與頁尾計數。
- **告警頁**（`?id=`，AT-03）：標題是那件事本身（例如「onlineboutique 內
  4,662 條連線命中『高 Blocked 流量』」），內容依固定順序：
  **發生了什麼**（一段話＋三個數字）、**誰在跟誰講話**（流量表，載入時自動
  對前 8 條流量問 PCE「哪條規則在管」並逐列回填，AT-04）、**該怎麼辦**
  （2–3 個具體行動，第一個是建議，AT-05）、**更多**（派送紀錄與觸發條件，
  預設收合）。右欄三張卡：這件事的進度、受影響的範圍、類似的告警。
- **狀態**（AT-02）：頁首右側的「未處理／處理中／已處理」，改了即時寫回。
- 流量搜尋的 `?alert=` 入口仍在：頁首會用一行說明條件是哪一則告警帶入的，
  並提供回到那則告警的連結（AT-06）。

### 總覽（`#/overview`）

一頁看完系統狀態，卡片皆為唯讀摘要，要動手的操作都在各自的區。

- **系統狀態**（OV-01）與**整合狀態**（OV-16）：PCE 連線、cache、SIEM 等
  子系統的當前健康。
- **Posture Score**（OV-02）：安全成熟度分數與分項。分數來自最近一次
  Security Posture 報表的快照，**不是即時計算**；快照超過 26 小時時卡片
  底部會多一行「stale since <時長>」註記（`overview.mjs` 的 `postureAge`），
  數字本身照常顯示。沒有任何報表快照時卡片顯示提示，不會顯示假資料。
- **Top 3 行動建議**（OV-03）：由 posture 分析導出的優先處置建議。
- **排行總覽／排行統計**（OV-04、OV-05）：自訂查詢卡的 CRUD 與 Top-10 查詢。
- **報表摘要**：最新 Audit（OV-06）、最新流量報表（OV-08）、Policy 使用
  報表（OV-07）、報表最近產出 meta（OV-09）。
- **管線健康**（OV-10）、**Job 健康**（OV-11）、**資料完整性**（OV-12）、
  **TLS 憑證**（OV-14）、**警示通道**（OV-15）：唯讀健康摘要，內容與判讀
  規則見下方「系統區」與 [automation.md](automation.md)。
- **近期事件**（OV-13）：最近的 PCE 稽核事件，點進去是調查區的事件檢視。

### 調查（`#/investigate/*`）

#### 流量分析（`#/investigate/traffic`）

依 Policy Decision（Blocked／Potentially Blocked／Allowed／All，含 unknown
語意）與 FilterBar 物件選擇器（見下節）篩選流量，KPI 條顯示 flows／
connections／目的 IP 數／尖峰頻寬。

查詢工具列的**資料來源**三選一（IV-02）：

- **快取優先**（預設）：先讀本機 cache，只為 cache 沒涵蓋到的區段補打 PCE。
- **直接查 PCE**：完全略過 cache，較慢但保證即時。
- **封存（Archive）**：直接掃描封存日檔。切到封存時，時間窗控制換成一組
  起訖日期欄位。

封存查詢一定要帶至少一個縮小範圍的條件；label group／actor group（AMS）／
草稿 policy decision／全文搜尋這些只有即時查詢算得出的條件在封存下無法
評估，帶了會**直接回錯誤並列出哪些條件不支援**，不會靜默忽略。

結果上方會標明這次實際由誰回答——快取、直接向 PCE 查詢、快取加 PCE 補查
缺口，或封存；結果被上限截斷時另有提示；封存查詢的彙總統計是有界的
top-N，被捨棄的分組數也會標出來。封存檔案概況（涵蓋的最早／最晚日期、
檔案數）見查詢區旁的狀態列（IV-06），細節見
[cache-maintenance.md](cache-maintenance.md) §3.4。

同頁另有**流量查詢指南**（IV-04）與**說明側欄**（XC-11）解釋篩選語法，
以及 cache backfill 入口（IV-07）。

#### Workload 搜尋與隔離（`#/investigate/workloads`）

依名稱／IP／hostname 查 Workload（IV-08），顯示線上狀態、介面、labels、
管理狀態。

**Quarantine（隔離）——雙重確認流程**

在流量列或 Workload 列勾選目標後按 **Isolate**：

1. 開啟 Quarantine modal：若目標包含「有方向的一對」（例如某筆流量的來源
   與目的都是內部 Workload），會顯示方向選擇（Source／Destination／Both）；
   僅從 Workload 搜尋選取的項目一律直接隔離，不受方向選項影響（modal 內
   有提示文字）。同時選擇 **Isolation Severity Level**：`Mild`／`Moderate`／
   `Severe`（決定套用哪一個 Quarantine label）。
2. 按下 Apply 後跳出破壞性動作確認（XC-08），文字包含目標數量與 severity
   等級，二次確認後才真正呼叫 API。

> **真實副作用（高風險）**：確認後呼叫 `POST /api/quarantine/apply`
> （單一目標）或 `/bulk_apply`（多目標，最多 5 個並行 worker）。伺服器端
> 會在 PCE 上**用選定 severity 對應的 `Quarantine` label 覆蓋** Workload
> 既有的 Quarantine label（同一 workload 只會有一個 Quarantine label，
> 重新套用等於換嚴重度，不會疊加），**立即改變其 enforcement**，直到手動
> 解除。首次使用會自動建立 Quarantine labels（`POST /api/init_quarantine`）。
> 每次套用／解除都會寫入 `actions` 模組日誌（`user=<帳號> href=... level=...`），
> 是 best-effort 稽核紀錄（記錄失敗不會擋下操作本身）。

解除隔離是 Workload 列的 **Lift**（IV-11），同樣要確認，確認後呼叫
`POST /api/quarantine/lift`，移除該 Workload 的 Quarantine label、保留其餘 label。

**Accelerate**（IV-12）：對受管 Workload 暫時提高流量回報頻率（`POST
/api/workloads/accelerate`，呼叫 PCE `set_flow_reporting_frequency`），畫面
有倒數。

> **真實副作用**：會變更 PCE 上該 Workload 的遙測頻率（不改 enforcement）。
> 僅受管 Workload 可用。

#### 事件檢視（`#/investigate/events`）

PCE 稽核事件檢視器（IV-13），三層 catalog（category／group／type）加關鍵字
與時間窗篩選；點選事件展開詳情卡（normalized 欄位＋raw JSON），清單以
load-more 增量載入（IV-14）。另含 **Shadow 比對**（IV-15，新舊事件比對器）。
以上皆為**唯讀**，會即時呼叫 PCE API 取事件，不寫入本地狀態。事件規則語意
與 vendor catalog 詳見 [monitoring-alerts.md](monitoring-alerts.md)。

### 告警（`#/alerting/*`）

#### 規則（`#/alerting/rules`）

規則清單（AL-01）可依型別篩選、搜尋、啟停、刪除；新增／編輯開對應的 drawer：
Event（AL-02）、System health（AL-03）、Traffic（AL-04）、Bandwidth（AL-05）
四種型別各一套欄位。儲存／刪除會**寫入 `config/alerts.json`**。另有規則
JSON 定位（AL-06）與**規則測試沙盤**（AL-07）可在不發送的前提下試跑規則。
規則型別與門檻語意見 [monitoring-alerts.md](monitoring-alerts.md)。

#### 維運動作（`#/alerting/ops`）

- **執行一次監控**（AL-08，`/api/actions/run`）：立即跑一輪分析，會查 PCE
  並**可能實際觸發告警**。
- **Debug 模式**（AL-09）與**輸出主控台**（AL-13）：即時看分析輸出。
- **發送測試告警**（AL-10，`/api/actions/test-alert`）：**實際發送**測試訊息
  到全部或指定通道（email／LINE／webhook／Telegram／Teams）。請勿在正式
  環境隨意點按。
- **重置事件 Watermark**（AL-11）：清空 event watermark，下次會重抓全部事件
  並可能重觸發告警。
- **載入最佳實踐**（AL-12）：一鍵附加或取代為內建最佳實務規則組（16 條
  event + 1 條 traffic）。replace 模式要兩層確認，append 一層。
- **告警管道**（AL-14）：各通道當前狀態，唯讀；要改設定去 `#/system/channels`。

### 自動化（`#/automation/*`）

#### Rule Scheduler（`#/automation/rules`）

對 PCE Draft policy 的 Ruleset／Rule 排定時間觸發啟用／停用。頁面有狀態列
與 KPI（AU-01）、過去 24 小時的切換時間軸（AU-02）、ruleset 瀏覽與詳情
（AU-03）、rule 個別搜尋（AU-04）；排程可建在 ruleset 層（AU-05）或 rule
層（AU-06），one-time 排程的 `expire_at` 語意見 drawer 內說明（AU-07）。
排程清單（AU-08）會顯示與 PCE 的對帳狀態，另有立即檢查（AU-09）與執行
紀錄（AU-10）。

> **真實副作用**：`POST /api/rule_scheduler/schedules` 會在 **PCE rule 的
> description 寫入英文排程註記**，並依排程在 PCE 上**啟用／停用該 rule**。
> **Draft（未佈署）規則會被擋下**，必須先在 PCE 佈署。刪除排程會盡力清除
> PCE 上的註記。
>
> **安全約束**：排程器**不會自動佈署 ruleset**——它只在 Draft 狀態切換
> rule 的啟用旗標，佈署需操作員另行處理；排程未啟用時只會顯示 warning，
> 絕不自動幫你 enable。

詳細操作流程與背景 job 對照表見 [automation.md](automation.md)。

#### 報表排程（`#/automation/reports`）

報表排程的 CRUD（AU-11）與啟停／立即執行／歷史（AU-12）。排程需 daemon
持續執行才會觸發；勾選 Email 需先設定好郵件通道（`#/system/channels`）。
`app_summary` 型排程必須指定 App，否則會被拒絕。

#### 背景 Job 健康（`#/automation/jobs`）

所有已註冊背景 job 的健康與歷史（AU-13，讀 `logs/job_health.json`），依嚴重度
排序。判讀規則：

- `error`：job 上次執行狀態為 `error`（實際跑過但失敗）。
- `warn`：兩種情況——(a) job 剛註冊、還沒真正跑過第一次且已超過 grace
  period（顯示「never ran」）；(b) 有跑過紀錄，但距上次 `last_run` 已超過
  grace period（顯示「（上次狀態）· overdue」）。兩者文案不同，後端判定
  等級相同。grace period = `max(2 × interval_seconds, 600)` 秒（至少 10 分鐘）。
- `ok`：正常週期內執行成功。

單一壞條目（例如手動改壞 `job_health.json` 造成 interval 非數字）不會讓整張
表炸掉，只會跳過該筆。

### 報表（`#/reports`）

- **報表型錄**（RP-01）：11 型報表各一張卡，顯示最近一次產出。**產生**開
  drawer（RP-02），每型有自己的參數欄位；產生過程顯示步驟式進度並輪詢
  非同步結果（RP-03、XC-07 統一進度元件）；只跑出部分結果時會明確提示
  （RP-04）。
- **Rule Hit Count** 需要 PCE 端啟用，卡片會先做 enablement 檢查並提供啟用
  入口（RP-05）。
- **報表輸出**（RP-06、RP-07）：產出清單可下載、瀏覽、單刪或批刪
  （**會刪檔，不可復原**）。
- **報表語言**（RP-08）與 **App Label 查詢輔助**（RP-09）。

產生報表會在伺服器端排入背景執行緒、即時查詢 PCE 並寫出檔案，可能耗時
數分鐘。各型報表的內容與版面見 [reports.md](reports.md)。

### 系統（`#/system/*`）

八個子頁，是 `config.json` 大部分區塊的圖形化編輯介面。改動未存檔時儲存列
會顯示 dirty 狀態（SY-18）。逐鍵對照見 [configuration.md](configuration.md)。

依 v3.1 §5.1 的設定頁型（2026-09-06）：**有多個同型項目的頁面用左清單＋右表單**
（目前只有通知通道），**其餘頁面的表單分節**——每節一個人話標題與一句「這節是
做什麼的」，放在欄位旁邊。SIEM 與 TLS 的表單各只有三、四個控制項，面板標題已經
命名它們，因此不再分節。

| 子頁 | 路由 | 內容 |
|---|---|---|
| PCE | `#/system/pce` | 連線表單分兩節：「PCE 在哪裡」（部署型態／URL／org id／主控台位址）與「憑證」（key／secret／verify SSL） |
| 快取 | `#/system/cache` | 狀態卡與 lag 列（SY-17）、設定表單（SY-02）、重啟 banner（SY-03）、retention 立即執行（SY-04）、流量過濾器與 IP 驗證（SY-05）、流量取樣（SY-06） |
| SIEM | `#/system/siem` | 轉發器設定（SY-07）、目的地 CRUD 與條件（SY-08）、測試送出（SY-09）、DLQ（SY-10） |
| TLS | `#/system/tls` | 憑證狀態、續期、CSR、匯入（SY-11） |
| 安全 | `#/system/security` | 分三節：誰可以登入、密碼、目前狀態（SY-12）；另有停止 Web GUI（SY-16） |
| 介面與報表 | `#/system/display` | 主題／密度／時區／語言（XC-05、XC-06），以及分兩節的介面與報表偏好（SY-13） |
| 通知通道 | `#/system/channels` | 設定頁型：左清單五個通道（狀態晶片＋還缺什麼），右邊一次編一個，含啟用切換與單通道測試（SY-14、OV-15） |
| 日誌 | `#/system/logs` | 模組日誌檢視（SY-15） |

幾點值得單獨說明：

- **改 PCE 連線位址會先問**。改 `api.url` 或 `api.org_id` 時會要求你選擇：
  清除 PCE 衍生的快取／watermark／告警冷卻／SIEM 佇列，或宣告這是同一個
  PCE 換了位址而保留它們。只換 key／secret 不會問。
- **快取設定改完要重啟 Monitor**（`POST /api/daemon/restart`）才生效，頁面
  會出現 banner 提醒。**Retention Now** 會永久刪除過期列，有確認。
- **DLQ 的 Purge 比一般確認更嚴**：全部清除需額外輸入 destination 名稱才能
  執行。Retry（replay）會重送失敗事件。
- **單通道測試**（`#/system/channels` 每張卡片的 Send test）呼叫與告警區
  相同的 `/api/actions/test-alert`，只帶該通道。判定「送達」的標準是回傳
  每一筆 `status === 'success'`——**`skipped` 也視為失敗**，用來揪出「卡片
  顯示已啟用，但憑證有問題所以被跳過」這種平時看不出來的假健康狀態。
- **TLS 的 Renew／Import／Generate CSR** 會在 `config/tls/` 產生或覆寫憑證
  與金鑰檔，**需重啟服務**才套用。

## 高風險動作彙整

下列動作會改變外部系統、資料庫或檔案，操作前請再三確認：

| 動作 | 端點 | 影響 |
|---|---|---|
| Quarantine apply／bulk_apply | `/api/quarantine/apply`、`/bulk_apply` | 在 PCE 對 Workload 覆蓋套用 Quarantine label，立即改變 enforcement |
| Quarantine lift | `/api/quarantine/lift` | 移除 Workload 上的 Quarantine label |
| Accelerate workload | `/api/workloads/accelerate` | 變更 PCE 遙測頻率 |
| Send Test Alert（告警區維運動作，全通道或指定通道） | `/api/actions/test-alert` | 實際發送通知到 email／LINE／webhook／Telegram／Teams |
| Send test（系統區管道，單一通道卡片） | `/api/actions/test-alert` | 同上端點，僅測該卡片對應通道 |
| 手動分析 Run | `/api/actions/run` | 查 PCE 並可能實際觸發告警 |
| Reset watermark | `/api/actions/reset-watermark` | 清空 event watermark／告警歷史，下次會重抓全部事件並可能重觸發告警 |
| Load Best Practices | `/api/actions/best-practices` | 覆寫／附加告警規則 |
| Rule Scheduler 建立／刪除 | `/api/rule_scheduler/schedules*` | 改寫 PCE rule 註記並切換 rule 啟用 |
| Report 產生／刪除 | `/api/reports/*`、`/api/*_report/generate` | 查 PCE、寫檔／刪檔；勾 Email 會寄信 |
| Cache backfill／retention | `/api/cache/backfill`、`/retention/run` | 查 PCE 寫入／永久刪除快取列 |
| SIEM test／DLQ replay／purge | `/api/siem/*` | 送測試事件／重送／永久刪除 |
| TLS Renew／Import／Generate CSR | `/api/tls/renew`、`/api/tls/import-cert`、`/api/tls/generate-csr` | 產生或覆寫憑證／金鑰檔，需重啟服務才套用 |
| 停止 Web GUI（系統區安全子頁） | `/api/shutdown` | 停止 Web 服務（僅非持久模式可用） |
