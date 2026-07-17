---
title: Web GUI 導覽
audience: [operator]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - src/templates/index.html
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
  - src/static/js/filter-bar.js
  - src/static/js/dashboard.js
  - src/static/js/integrations.js
  - src/static/js/settings.js
  - src/static/js/quarantine.js
  - src/config.py
  - src/job_health.py
  - src/cli/gui_cmd.py
  - docs/operations-manual_zh.md（§3，素材來源，已依現況校正）
---

# Web GUI 導覽

Web GUI 是單頁式應用（SPA）：登入後以頂部 8 個分頁切換，內容全部由前端 JS 模組向約
109 條 JSON API（`/api/...`）取資料，伺服器不重新整頁。啟動方式與埠號見
`illumio-ops gui`（預設埠 **5001**，`--host 0.0.0.0`），完整 CLI 選項見
reference/cli.md。

> **全域安全提醒**：除 `/login`、`/api/login`、`/logout`、`/api/csrf-token` 外，
> 所有路由都需登入 session。`web_gui.allowed_ips` 提供 IP 允許清單，比對的是
> **直接連線來源 IP**（`request.remote_addr`），被拒的連線以 TCP RST 靜默切斷
> （避免被埠掃描偵測到有服務在監聽）。所有 POST／PUT／DELETE 都需 CSRF token。
> 設定細節見 configuration.md 的「web_gui／TLS」一節。

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
  顯示內嵌改密表單」的邏輯（`login.js`），只是預設路徑不會觸發它——若日後
  該旗標被改回 `True`，這段 UI 會自動生效。
- 登入頁與相關文件如提到「首次登入強制改密」，以本節（依原始碼查核）為準。

## 頁首

- 左側：產品標誌與標題。
- 中央：**PCE 狀態晶片（status chip）**——連線健康燈號（綠 ok／琥珀
  warn／紅 err／灰 unknown）、PCE 主機、Rules 數、Schedules 數、設定載入
  時間（相對時間顯示）。
- 右側：**Operations** 下拉選單——Theme（Auto／Dark／Light）、Density
  （Compact／Comfortable）、**Logs**（開啟維運日誌檢視窗）、**Stop**（停止
  Web 服務，會跳出確認框；僅非持久模式〔`--gui`／`--monitor-gui`
  以外的一次性啟動〕可用）。

## FilterBar v2 物件選擇器

流量查詢（Traffic Analyzer）與部分報表篩選共用同一套「PCE 風格 filter
物件選擇器」元件（`src/static/js/filter-bar.js` 的 `createFilterBar()`，
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

這是元件與後端比對器共用的核心語意（`src/analyzer.py` 原始碼註解逐字
確認：「同 key OR、跨 key 委派報表路徑同一套比對器 `_flow_matches_filters`
…與 native 語意一致」）：

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

## 分頁逐一導覽

### 1) Dashboard

即時總覽首頁，區分兩大區塊：

- **Security Posture**：分數卡（Posture Score）＋ 各分項指標（風險健康、
  policy 覆蓋率、readiness 等）＋ Top Risk Findings 清單；未曾產生過
  Security Posture 報表時顯示「Run a Security Posture report to populate
  this section」提示，不會顯示假資料。
- **Operations & Estate**：VEN Health（在線／離線／降級數、最舊心跳
  年齡）、Pipeline（cache 擷取健康）、OS Distribution、Enforcement
  Modes 四張磚塊，另有 Alerts 磚塊顯示近 24 小時觸發／抑制／失敗數。
- 下方保留即時狀態卡（Health／Traffic／Risk 三組）與 Traffic Analyzer／
  Workload Search 子頁（見下一節）。
- 「auto-refresh 10m」勾選與 **Refresh** 鈕只是重新抓取 `/api/dashboard/
  overview` 等端點的最新快照，**不會**重新計算或重新產生報表快照。

**資料新鮮度變灰（全庫未記錄，`src/static/js/dashboard.js`）**：Dashboard
各磚塊各自比對自己資料的時戳，超過門檻視為 stale，此時**數字本身變灰**
（`color: var(--dim)`）並在磚塊下方多出一行「stale + 已過去的時間」（例如
「stale 42m」），而不是隱藏或顯示零值：

| 磚塊 | 新鮮度依據欄位 | stale 門檻 |
|---|---|---|
| Security Posture 分數＋分項指標 | `posture.generated_at` | 30 分鐘 |
| VEN Health 大數字（在線／總數） | `ven.computed_at` | 15 分鐘 |

其餘磚塊（Pipeline／OS Distribution／Enforcement／Alerts）目前沒有各自的
stale 灰化邏輯，僅在資料不可用（`verdict === 'unknown'` 或 `no_cache`）
時顯示 `—` 或「Enable PCE Cache」提示。整體重新整理列（`ov-fresh`，
「as of HH:MM:SS」）也有自己的 stale 判斷：距 `as_of` 超過 60 秒即整列變色
（`.ov-fresh.stale`，紅字，門檻與磚塊各自的門檻是獨立邏輯）。

對應設定：儀表板顯示語言／主題見 configuration.md 的「settings（一般
設定）」；Security Posture 報表產生方式見 reports.md（尚待建立）。

### 2) Traffic & Workloads

- **Traffic Analyzer**：依 Policy Decision（Blocked／Potentially
  Blocked／Allowed／All，含 unknown 語意）、以及 FilterBar 物件選擇器
  （見上節）篩選流量，KPI 條顯示 flows／connections／目的 IP 數／尖峰頻
  寬，並有 7 天趨勢圖（可切換「僅顯示已標記」）。
- **Workload Search**：依名稱／IP／hostname 查 Workload，顯示線上狀態、
  介面、labels、管理狀態。
- **Rankings（legacy）**：舊版 Top-N 排行小工具，維持向下相容，UI 上以
  較低對比度標示為次要功能。

#### Quarantine（隔離）——雙重確認流程

在流量列或 Workload 列勾選目標後按 **Isolate**：

1. 開啟 Quarantine modal：若目標包含「有方向的一對」（例如某筆流量的來源
   與目的都是內部 Workload），會顯示方向選擇（Source／Destination／
   Both）；僅從 Workload Search 選取的項目一律直接隔離，不受方向選項
   影響（modal 內有提示文字）。同時選擇 **Isolation Severity Level**：
   `Mild`／`Moderate`／`Severe`（決定套用哪一個 Quarantine label）。
2. 按下 Apply 後，前端跳出瀏覽器原生 `confirm()` 對話框，文字包含目標
   數量與 severity 等級，二次確認後才真正呼叫 API——這是本功能的兩層
   確認：先在 modal 內選定範圍與嚴重度，再由 `confirm()` 做最終攔截。

> **真實副作用（高風險）**：確認後呼叫 `POST /api/quarantine/apply`
> （單一目標）或 `/bulk_apply`（多目標，最多 5 個並行 worker）。伺服器端
> 會在 PCE 上**用選定 severity 對應的 `Quarantine` label 覆蓋** Workload
> 既有的 Quarantine label（同一 workload 只會有一個 Quarantine label，
> 重新套用等於換嚴重度，不會疊加），**立即改變其 enforcement**，直到手動
> 解除。首次使用會自動建立 Quarantine labels（`POST /api/init_quarantine`）。
> 每次套用／解除都會寫入 `actions` 模組日誌（`user=<帳號> href=... level=...`），
> 是 best-effort 稽核紀錄（記錄失敗不會擋下操作本身）。

解除隔離：Workload 列的 **Lift** 按鈕，同樣先跳出 `confirm()`，確認後呼叫
`POST /api/quarantine/lift`，移除該 Workload 的 Quarantine label、保留其
餘 label。

- **Accelerate**：對受管 Workload 暫時提高流量回報頻率（`POST
  /api/workloads/accelerate`，呼叫 PCE `set_flow_reporting_frequency`）。
  > **真實副作用**：會變更 PCE 上該 Workload 的遙測頻率（不改
  > enforcement）。僅受管 Workload 可用；持續模式由前端每 10 分鐘重送。

對應設定：無獨立設定區塊；quarantine label 建立與 severity 對映屬程式
內建行為。

### 3) Event Viewer

PCE 稽核事件檢視，左表右詳版面：可依時間視窗、category／group／type、
關鍵字篩選；點選事件展開右側詳情（normalized 欄位＋raw JSON）。另含
**Shadow Compare**（規則對實際事件的命中比對）、**Rule Test**（單一規則
測試）、**Event Catalog**（事件型錄，vendor catalog 對映）。以上皆為
**唯讀**功能，會即時呼叫 PCE API 取事件，不寫入本地狀態。事件規則語意
與 vendor catalog 詳見 monitoring-alerts.md（尚待建立）。

### 4) Rules（告警規則，分頁標題為 Alerts）

- **Rules 子頁**：依型別（Event／Traffic／Bandwidth／System Health）篩
  選、搜尋、編輯、刪除、批次刪除規則；新增規則開對應 modal。儲存／刪除
  會**寫入 `config/alerts.json`**。**Load Best Practices** 可一鍵附加
  或取代為內建最佳實務規則組（17 條 event + 1 條 traffic），操作前會有
  兩層 `confirm()`（先警告會覆寫、再次確認）。規則型別與門檻語意見
  monitoring-alerts.md（尚待建立）。
- **Actions 子頁**：
  - **Send Test Alert（All）／Test [通道]**：`POST
    /api/actions/test-alert` 會**實際發送**測試訊息到指定（或全部）
    通道（email／LINE／webhook／Telegram／Teams）。請勿在正式環境隨意
    點按。（Settings → Channels 亦有同端點的每通道版本，見下方 Settings
    小節。）
  - 亦提供手動分析 Run、Reset watermark 等除錯動作，皆屬高風險（見文末
    彙整表）。

對應設定：告警規則欄位定義與通道金鑰見 configuration.md 的
「alerts（告警通道）」與「email／smtp」兩節。

### 5) Reports

- **List 子頁**：瀏覽已產生報表，可 View（HTML）、Download、Delete／批次
  Delete（**會刪檔，不可復原**），並提供各類報表的 **Generate** 鈕
  （Traffic／Security／Audit／Policy Usage／VEN Status／Readiness／
  Rule Hit Count／Policy Diff／Policy Resolver 等，各報表細節見
  reports.md，尚待建立）。產生報表會在伺服器端排入背景執行緒、即時查詢
  PCE 並寫出檔案，可能耗時數分鐘。
- **Schedules 子頁**：建立／編輯／啟用停用／立即執行（Run Now）／刪除報
  表排程。排程需 daemon 持續執行才會觸發；勾選 Email 需先設定好郵件通
  道（Settings → Channels）。

對應設定：輸出目錄與保留天數見 Settings → Display；報表排程資料結構見
configuration.md 的「report／report_schedules」節。

### 6) Rule Scheduler

對 PCE Draft policy 的 Ruleset／Rule 排定時間觸發啟用／停用，三個子頁：
**Browse**（瀏覽 ruleset／rule）、**Schedules**（排程清單，含各排程的
last-run 狀態）、**Logs**。

建立排程時選 Recurring（星期＋起迄時間＋時區）或 One-time（到期時
間），Action 為 `allow`（視窗內啟用）或 `disable`。

> **真實副作用**：`POST /api/rule_scheduler/schedules` 會在 **PCE rule
> 的 description 寫入英文排程註記**，並依排程在 PCE 上**啟用／停用該
> rule**。**Draft（未佈署）規則會被擋下**，必須先在 PCE 佈署。刪除排程
> 會盡力清除 PCE 上的註記。
>
> **安全約束**：排程器**不會自動佈署 ruleset**——它只在 Draft 狀態切換
> rule 的啟用旗標，佈署需操作員另行處理；排程未啟用時只會顯示 warning，
> 絕不自動幫你 enable。

詳細操作流程與背景 job 對照表見 automation.md（尚待建立）。

### 7) Integrations

四個子頁，`overview`／`cache`／`siem`／`dlq`：

- **Overview**：管線健康總覽，含以下兩項全庫未記錄過的卡片：

  **Job Health 表格**（`src/gui/routes/dashboard.py` 的
  `_overview_job_health()`，讀 `logs/job_health.json`）：列出所有已註冊
  背景 job，依嚴重度排序（error → warn → ok）。判讀規則：
  - `error`：job 上次執行狀態為 `error`（實際跑過但失敗）。
  - `warn`：分兩種情況——(a) job 剛註冊、還沒真正跑過第一次
    （`last_status == "registered"`）且已超過 grace period；(b)
    job 有跑過紀錄，但距上次 `last_run` 已超過 grace period（**overdue**）。
    grace period = `max(2 × interval_seconds, 600)` 秒（至少 10 分鐘）。
    表格上這兩種情況分別顯示為「never ran」與「（上次狀態文字）·
    overdue」，UI 上是兩種不同文案，但後端判定邏輯（level）相同，都歸
    類為 `warn`。
  - `ok`：正常週期內執行成功。
  - 單一壞條目（例如手動改壞 `job_health.json` 造成 interval 非數字）不
    會讓整張表炸掉，只會跳過該筆。

  **TLS 憑證卡**（`_tls_overview()`）：GUI 未啟用 TLS 時整張卡不顯示
  （`enabled: false`）；啟用時顯示剩餘天數，低於設定的 `auto_renew_days`
  門檻會額外標示「Expiring soon」。憑證輪替與每日續期 job 見
  configuration.md 的「TLS：self-signed 憑證每日續期 job」節。

- **Cache**：PCE cache 狀態卡、設定表單（保留天數、輪詢間隔、traffic
  filter／sampling）。儲存後需 **Restart Monitor**（`POST
  /api/daemon/restart`）才生效。可手動 **Backfill**（補填歷史，會查 PCE
  並寫入 cache DB）或 **Retention Now**（會永久刪除過期列，UI 有
  `confirm()`）。詳見 cache-maintenance.md（尚待建立）。
- **SIEM**：destination 清單與 KPI（sent／failed／DLQ／成功率／延遲）。
  新增／編輯／刪除 destination，及 **Test**（會實際送出測試事件）。詳見
  siem.md（尚待建立）。
- **DLQ**：死信佇列檢視，可 **Retry（replay）**（重送失敗事件）或
  **Clear／Purge**（永久刪除，全部清除需額外輸入 destination 名稱確
  認——比一般 `confirm()` 更高一階的防呆）。

### 8) Settings

四個子頁，`pce`／`channels`／`display`／`security`：

- **PCE**：PCE profile 清單與 **Activate**（切換作用中 profile，立即對
  daemon 生效，無需重啟；只按 Save 不會切換）、以及 API 連線欄位。多
  PCE 設定細節見 configuration.md 的「pce_profiles／active_pce_id」節。
- **Channels**：各告警通道（mail、LINE、webhook、Telegram、Teams）的
  啟用開關與欄位。每張通道卡片有獨立的 **Send test** 按鈕（全庫未記錄
  過的功能，`src/static/js/settings.js` `testAlertChannel()`）：呼叫與
  Rules → Actions 相同的 `POST /api/actions/test-alert`，帶
  `{channel: <name>}`，只測該通道；判定「全部送達」的標準是回傳
  `results[]` 每一筆 `status === 'success'`，**`skipped` 也視為失敗**
  （用來揪出「卡片顯示已啟用，但其實憑證有問題所以被跳過」這種平時看
  不出來的假健康狀態），成功／失敗都以 toast 提示，不彈出 modal。
- **Display**：timezone、language（English／繁體中文）、theme，及報表
  輸出目錄／保留天數。
- **Security**：Web UI 密碼（含確認欄，前端先驗證一致性）、IP 允許清
  單，與 **TLS／HTTPS** 設定（啟用／停用、自簽 vs 自帶憑證、Generate
  CSR、Import Certificate、Renew）。
  > **真實副作用**：TLS 的 Renew／Import／Generate CSR 會在
  > `config/tls/` 產生或覆寫憑證／金鑰檔，並需**重啟服務**才套用；Renew
  > 前端有 `confirm()`。

對應設定：本分頁即 `config.json` 大部分區塊的圖形化編輯介面，逐鍵對照
表見 configuration.md。

## 高風險動作彙整

下列動作會改變外部系統、資料庫或檔案，操作前請再三確認：

| 動作 | 端點 | 影響 |
|---|---|---|
| Quarantine apply／bulk_apply | `/api/quarantine/apply`、`/bulk_apply` | 在 PCE 對 Workload 覆蓋套用 Quarantine label，立即改變 enforcement |
| Quarantine lift | `/api/quarantine/lift` | 移除 Workload 上的 Quarantine label |
| Accelerate workload | `/api/workloads/accelerate` | 變更 PCE 遙測頻率 |
| Send Test Alert（Rules → Actions，全通道或指定通道） | `/api/actions/test-alert` | 實際發送通知到 email／LINE／webhook／Telegram／Teams |
| Send test（Settings → Channels，單一通道卡片） | `/api/actions/test-alert` | 同上端點，僅測該卡片對應通道 |
| 手動分析 Run | `/api/actions/run` | 查 PCE 並可能實際觸發告警 |
| Reset watermark | `/api/actions/reset-watermark` | 清空 event watermark／告警歷史，下次會重抓全部事件並可能重觸發告警 |
| Load Best Practices | `/api/actions/best-practices` | 覆寫／附加告警規則 |
| Rule Scheduler 建立／刪除 | `/api/rule_scheduler/schedules*` | 改寫 PCE rule 註記並切換 rule 啟用 |
| Report 產生／刪除 | `/api/reports/*`、`/api/*_report/generate` | 查 PCE、寫檔／刪檔；勾 Email 會寄信 |
| Cache backfill／retention | `/api/cache/backfill`、`/retention/run` | 查 PCE 寫入／永久刪除快取列 |
| SIEM test／DLQ replay／purge | `/api/siem/*` | 送測試事件／重送／永久刪除 |
| TLS Renew／Import／Generate CSR | `/api/security`（TLS 區塊） | 產生或覆寫憑證／金鑰檔，需重啟服務才套用 |
| Stop（頁首 Operations 選單） | `/api/shutdown` | 停止 Web 服務（僅非持久模式可用） |
