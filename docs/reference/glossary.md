---
title: 詞彙表
audience: [operator, developer]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - src/i18n/data/zh_explicit.json
  - src/config_models.py
  - src/pce_cache_cli.py
  - src/job_health.py
  - docs/handover/pce-domain-notes.md
---

# 詞彙表

本頁為新進人員提供快速參考，繁體中文單語。決策/狀態類術語（如 `blocked`、`draft`）維持英文原文——與產品 UI 的 zh_TW 翻譯慣例一致（見 `src/i18n/data/zh_explicit.json`），故意不強譯，避免文件用語與畫面顯示不一致。

---

## Illumio 核心術語

| 術語 | 定義 | 延伸閱讀 |
|------|------|----------|
| Application Group（應用群組） | 共享同一 `app` 標籤值的工作負載邏輯群組，代表一個業務服務（例如 `HRM`、`Payments`）。規則集通常以 Application Group 為範圍。 | [報表家族](../guide/reports.md) |
| Enforcement Boundary（強制邊界，新版 PCE 稱 Deny Rules） | 獨立於一般規則的範圍式拒絕聲明，在工作負載群組之間建立「防爆牆」。Selective 模式下 VEN 僅封鎖違反邊界的入站流量，違反邊界的出站流量仍記為 `potentially_blocked`。 | [PCE domain 須知](../handover/pce-domain-notes.md) |
| Enforcement Mode（強制模式） | VEN 的運作狀態，API 值域四值：`idle`（不接管防火牆，僅定期回報流量快照）、`visibility_only`（持續記錄流量、不擋）、`selective`（只對策略指定的 inbound port/service 封鎖，outbound 不管）、`full`（inbound/outbound 全面執行，預設拒絕）。Unmanaged 工作負載與透過 NEN 管理的工作負載無法使用 `selective`。 | [PCE domain 須知 §1.3](../handover/pce-domain-notes.md) |
| Environment（環境） | `env` 標籤維度，記錄工作負載的 SDLC 階段（例如 `production`、`staging`、`dev`）。用於規則集限定規則適用的生命週期階段。 | [監控規則、告警與 SIEM](../guide/monitoring-alerts.md) |
| Heartbeat（心跳） | VEN 定期向 PCE 回報狀態（約每 5 分鐘一次），另每約 10 分鐘傳送摘要流量記錄；也作為 policy 更新的備援傳輸通道。 | [PCE domain 須知](../handover/pce-domain-notes.md) |
| IP List（IP 清單） | 命名的 IP 位址或 CIDR 範圍集合，用於規則的 provider 或 consumer，表達與非工作負載端點（外部夥伴、網際網路出口）之間的流量。 | [Web GUI 導覽](../guide/gui-tour.md) |
| Label（標籤） | 附加於工作負載的鍵值中繼資料。Illumio 使用四個維度：`role`、`app`、`env`、`loc`。規則以標籤為目標而非 IP，因此 policy 可自動跟隨工作負載。 | [Web GUI 導覽](../guide/gui-tour.md) |
| Label Group（標籤群組） | 同一維度內命名的標籤值集合，用於編寫一條規則同時適用於多個環境或應用，無需重複。label group 成員展開只在 PCE 端進行，client 端無法本地比對。 | [PCE domain 須知 §3.7](../handover/pce-domain-notes.md) |
| Location（位置） | `loc` 標籤維度，記錄工作負載的地理位置或基礎設施區域（例如 `aws-east1`、`on-prem-nyc`）。 | [Web GUI 導覽](../guide/gui-tour.md) |
| Pairing Profile（配對設定檔） | PCE 物件，捆綁 VEN 安裝並配對時套用於工作負載的組態（標籤、強制模式、可見性層級），產生一次性配對金鑰。 | [PCE domain 須知](../handover/pce-domain-notes.md) |
| PCE（Policy Compute Engine，政策運算引擎） | Illumio 平台的伺服器端核心，計算每個工作負載的安全 policy 並推送至每個已配對的 VEN。illumio-ops 為 agentless 設計，只透過 PCE REST API 存取資料，不在 workload 上安裝任何元件。 | [架構導覽](../handover/architecture.md) |
| Policy Lifecycle（政策生命週期，draft vs active） | 可 provision 的物件（ruleset、rule、IP list、service、label group 等）同時存在兩個版本：`/sec_policy/draft`（工作中的未提交狀態，所有寫入都打此版本）與 `/sec_policy/active`（目前實際生效、唯讀）。draft 變更需執行 provision 才轉為 active；每次 provision 都存成帶時戳的版本，可稽核、可還原。 | [PCE domain 須知 §1.1](../handover/pce-domain-notes.md) |
| Rule（規則） | Ruleset 內的單一允許/拒絕聲明，以 `provider × consumer × service` 表達。動作分三種、衝突時優先序固定：`override_deny`（最高，無條件封鎖）> `allow`（可蓋過一般 deny）> `deny`（僅擋未被 allow 涵蓋的流量）。 | [PCE domain 須知 §1.2](../handover/pce-domain-notes.md) |
| Ruleset（規則集） | 分組相關 Rule 並套用至一組工作負載的範圍容器（通常以 `app`+`env` 標籤定義），是 policy lifecycle 中寫入/佈署的基本單位。 | [PCE domain 須知](../handover/pce-domain-notes.md) |
| Scope（範圍） | 附加於 Ruleset 或 Enforcement Boundary 的標籤選擇器，決定其管轄的工作負載。`app=HRM, env=production` 的範圍僅將規則集套用於生產環境 HRM 工作負載。 | [PCE domain 須知](../handover/pce-domain-notes.md) |
| Service（服務） | 一個或多個 `protocol+port` 組合的可重用定義（例如 `tcp/443, tcp/80`），由規則引用而不直接內嵌埠號。 | [Web GUI 導覽](../guide/gui-tour.md) |
| Service Account（服務帳號） | PCE 中的非人類身分，供自動化工具（腳本、CI/CD 流程）透過 API 金鑰驗證 PCE API，不與使用者帳號綁定。 | [設定參照](../guide/configuration.md) |
| VEN（Virtual Enforcement Node，虛擬強制節點） | 安裝於每個受管工作負載的輕量代理程式。設定主機原生防火牆（`iptables`/`nftables`、WFP），收集流量遙測，並透過 TLS TCP 8443/8444 套用從 PCE 接收的 policy。 | [PCE domain 須知](../handover/pce-domain-notes.md) |
| Visibility Level（可見性層級） | 控制 VEN 記錄多少流量：`Off`、`Blocked`、`Blocked + Allowed`、`Enhanced Data Collection`。原為 Full 強制模式專屬設定，PCE 25.2.10 起 `Enhanced Data Collection` 在所有強制模式皆可啟用。 | [PCE domain 須知](../handover/pce-domain-notes.md) |
| Workload（工作負載） | PCE 追蹤的受管運算資源。三種子類型：`Managed`（已配對 VEN，即時遙測）、`Unmanaged`（僅標籤 IP，無 VEN）、`Container`（透過 Kubelink 的 Kubernetes/OpenShift Pod）。 | [Web GUI 導覽](../guide/gui-tour.md) |

---

## Traffic / Policy 判定術語

| 術語 | 定義 | 延伸閱讀 |
|------|------|----------|
| policy_decision（四值域） | Traffic flow 的 policy 判定欄位，值域固定四值：`blocked`／`potentially_blocked`／`allowed`／`unknown`。`unknown` 涵蓋 idle/快照模式 VEN 回報的流量與 Flowlink 未管理流量；查詢時若只帶前三值，`unknown` 流量整批消失、統計數字會大幅偏低。本專案自 2026-07-16 起所有未明確指定的查詢**預設含 unknown**（`src/analyzer.py` `query_flows` 預設值）。 | [PCE domain 須知 §2.1](../handover/pce-domain-notes.md) |
| draft_policy_decision | PCE 在查詢執行當下，把歷史 flow 套上目前 draft policy 做的 what-if 模擬判定，是 on-demand 計算、不隨 flow 儲存；與 `policy_decision`（VEN 當下記錄的靜態歷史值）不同。 | [PCE domain 須知 §2.2](../handover/pce-domain-notes.md) |
| Async Traffic Query | Explorer/traffic flow 查詢的非同步流程：`POST /traffic_flows/async_queries` → 202 → 輪詢 job 狀態直到終態 `completed` → 下載 gzip JSON 結果。失敗終態另含 `failed`／`cancel_requested`／`cancelled`／`canceled`。注意：`completed` 僅屬此 async traffic query 機制；另一套 Jobs API（`Prefer: respond-async` 集合 GET／rule hit count report）的成功終態是 `done`，兩套字彙不同、不可混用。 | [PCE domain 須知 §2.3、§3.1](../handover/pce-domain-notes.md) |
| Rule Hit Count | VEN 原生量測的規則命中次數，回答「哪些 Active 規則實際被命中過」。只計 Active 規則（draft 不計）；保留期 90 天；規則最佳化可能使命中數高估；每 flow 最多歸因 100 條規則；hit 與 flow 計數語意不同（src/dst 各自回報一次，故常見 1 flow 對應 2 hit）。啟用需寫入 draft `firewall_settings` 並 provision 到生產 policy，版本門檻 SaaS PCE 24.2.0+／地端 23.5.10+／VEN 23.2.30+。 | [PCE domain 須知 §4](../handover/pce-domain-notes.md)、[報表家族 §7](../guide/reports.md) |

---

## illumio-ops 專用術語

| 術語 | 定義 | 延伸閱讀 |
|------|------|----------|
| Action Matrix（動作矩陣） | `config/config.json` 中的組態表，將告警規則的嚴重性與類別對應至通知渠道（Email、LINE、Webhook、Telegram、Teams），決定每則告警的觸發方式與路由目的地。 | [監控規則、告警與 SIEM](../guide/monitoring-alerts.md) |
| Alert Rule（告警規則） | illumio-ops 中的命名偵測定義，監控 PCE 事件或指標的特定模式；觸發時告警引擎評估 Action Matrix 並派發通知。 | [監控規則、告警與 SIEM](../guide/monitoring-alerts.md) |
| Backfill（補填） | 以 `illumio-ops cache backfill` 觸發的歷史日期範圍填充，直接寫入 `pce_events`／`pce_traffic_flows_raw`，繞過 Watermark。用於首次啟用後補齊快取資料，或補齊舊資料缺少 `unknown` policy_decision 的缺口。 | [pce_cache 維運](../guide/cache-maintenance.md) |
| DLQ（Dead Letter Queue，死信佇列） | PCE Cache 中的 `dead_letter` 資料表，存放已用盡所有重試的 SIEM 派發，隔離保留 30 天供操作員檢查，不影響即時佇列。 | [SIEM 轉送](../guide/siem.md) |
| Draft Policy Alignment（R 系列） | `src/report/rules/r01`–`r05` 實作的 5 條治理型偵測規則（R01–R05），只在 DataFrame 帶 `draft_policy_decision` 欄時才會評估，該欄由查詢時 `compute_draft=True` 產生；標準／cache 報表路徑預設不含此欄，須透過獨立命令 `illumio-ops report draft-policy` 按需觸發即時 PCE 查詢。MITRE ATT&CK 全部刻意不對應（治理／衛生型規則）。 | [監控規則、告警與 SIEM §2.4](../guide/monitoring-alerts.md) |
| FilterBar（v2 物件選擇器） | GUI 各分頁共用的篩選元件（`src/static/js/filter-bar.js` 的 `createFilterBar()`），以 labels／label groups／IP lists／workloads／services pill 取代純文字輸入。序列化出的 key（`src_labels`／`dst_workloads`／`services` 等）同 key 之間為 OR、跨 key 之間為 AND；後端物件查詢由 `src/gui/routes/filter_objects.py` 提供。 | [Web GUI 導覽](../guide/gui-tour.md) |
| Hub Apps（中樞應用） | illumio-ops Web UI 中捆綁的第一方功能模組集合（Dashboard、Reports、Alerts、Settings、SIEM 等），每個 Hub App 是獨立的 Flask Blueprint。 | [Web GUI 導覽](../guide/gui-tour.md) |
| Ingestor（擷取器） | 每個資料來源（`events`、`traffic`）各一個的背景輪詢器，依固定排程從 PCE API 拉取新資料列至 PCE Cache，受共享 token-bucket 速率限制器管控。 | [pce_cache 維運](../guide/cache-maintenance.md) |
| Job Health（Job 健康） | 每個排程 job 的 last_run／last_status 落地 `logs/job_health.json`（`src/job_health.py`），是「應跑未跑」可觀測性的根治配套。GUI 的 Integrations → Overview 的 Job Health 表格用 `never-ran`／`overdue` 旗標呈現異常。 | [自動化：排程與 quarantine §3](../guide/automation.md)、[故障排除 §5](../guide/troubleshooting.md) |
| Multi-PCE Profile（多 PCE 設定檔） | `config/config.json` 中的命名組態槽，存放單一 PCE 的憑證與端點設定，允許單一 illumio-ops 安裝指向多個 PCE。 | [設定參照](../guide/configuration.md) |
| pce_cache（PCE Cache） | 位於 `data/pce_cache.sqlite`（`db_path` 設定鍵，`src/config_models.py`）的本地 SQLite（WAL 模式）資料庫，儲存 PCE 稽核事件與流量記錄的滾動窗口，作為 SIEM 轉發器、報表模組與告警迴圈的共享緩衝區。 | [pce_cache 維運](../guide/cache-maintenance.md) |
| Rule Scheduler（規則排程器） | illumio-ops 內基於 APScheduler 的作業執行器，依設定間隔執行擷取器、告警評估、SIEM 派發滴答與報表生成；亦指 GUI 的規則排程分頁，可對特定 monitoring rule 建立定期執行排程。 | [自動化：排程與 quarantine §1](../guide/automation.md) |
| SIEM Dispatch（SIEM 派發） | `siem_dispatch` 外寄佇列資料表，SIEM 轉發器從此佇列讀取、將事件傳送至 syslog／Splunk／Elastic，成功傳遞後移除資料列，失敗則移至 DLQ。 | [SIEM 轉送](../guide/siem.md) |
| Watermark（水位線） | `ingestion_watermarks` 資料表中的每擷取器游標，記錄各來源最後成功擷取的時間戳記，重啟後仍保留，確保輪詢無縫隙或重複地恢復。 | [pce_cache 維運](../guide/cache-maintenance.md) |

---

## i18n 相關術語

| 術語 | 定義 | 延伸閱讀 |
|------|------|----------|
| `desc_key` | 欄位人類可讀說明字串的 i18n 鍵命名慣例，用於 `zh_explicit.json` 條目（如 `alert_field_desc`），提供已翻譯的工具提示或輔助文字。 | [開發流程](../handover/development.md) |
| `label_key` | 欄位在 UI 顯示標籤的 i18n 鍵命名慣例（例如 `alert_field_action` → `動作`），與 `name_key`（實體名稱）和 `desc_key`（說明）有所區別。 | [開發流程](../handover/development.md) |
| `name_key` | 實體顯示名稱的 i18n 鍵命名慣例，與 `label_key`（表單標籤）和 `desc_key`（說明）分離，允許各介面分別翻譯。 | [開發流程](../handover/development.md) |
| `rec_key` | 告警或驗證錯誤旁顯示的建議字串的 i18n 鍵命名慣例（例如 `alert_rec_agent_offline_check`），簡短、可操作、面向操作員。 | [開發流程](../handover/development.md) |
| `t()` 函式 | illumio-ops 中的 Python 執行期翻譯輔助函式，對照現用語系的 JSON 檔案解析 i18n 鍵，若未找到則回退至 `zh_explicit.json`。 | [開發流程](../handover/development.md) |
| `zh_explicit` | 檔案 `src/i18n/data/zh_explicit.json`，所有 Illumio 領域及 illumio-ops UI 字串的 zh_TW 核准翻譯主要來源，覆蓋基礎語系檔 `src/i18n_zh_TW.json` 中的產品專用術語。 | [開發流程](../handover/development.md) |
| zh_explicit override | 查找優先級規則：`src/i18n/data/zh_explicit.json` 中找到的鍵優先於基礎 `src/i18n_zh_TW.json` 中的相同鍵，確保告警訊息、欄位標籤與建議字串採用經核准、符合產品規範的翻譯（例如 `blocked`／`draft` 等決策術語刻意不強譯，本詞彙表沿用此慣例）。 | [開發流程](../handover/development.md) |

---

## 合規／稽核術語

| 術語 | 定義 | 延伸閱讀 |
|------|------|----------|
| Audit Event（稽核事件） | PCE 針對 policy 物件或使用者工作階段的每次建立/更新/刪除/驗證動作所發出的結構化日誌條目，儲存於 `pce_events` 並以 CEF 或 JSON Lines 格式轉發至 SIEM。 | [SIEM 轉送](../guide/siem.md) |
| Audit Log（稽核日誌） | 透過 `/api/v2/auditable_events` 從 PCE 匯出的完整歷史稽核事件串流，illumio-ops 輪詢此端點以填充 PCE Cache 並驅動告警評估。 | [報表家族 §3](../guide/reports.md) |
| Event Type（事件類型） | PCE 指派給每個稽核事件的類別字串（例如 `workload.create`、`ruleset.update`、`user.sign_in`），用於告警規則和 SIEM 查詢中的篩選維度。 | [監控規則、告警與 SIEM](../guide/monitoring-alerts.md) |
| SIEM Forwarding（SIEM 轉發） | 將 PCE 事件與流量記錄從 illumio-ops 傳遞至外部安全平台（Splunk、Elastic、QRadar 等）的管道，支援 CEF-over-syslog（UDP/TCP/TLS）與 Splunk HEC（HTTPS）。 | [SIEM 轉送](../guide/siem.md) |

---

## 縮寫

| 縮寫 | 全稱與定義 | 延伸閱讀 |
|------|------|----------|
| CEF | Common Event Format。illumio-ops 透過 UDP/TCP/TLS 向 SIEM 平台轉發稽核事件所使用的 syslog 相容結構化日誌標準。 | [SIEM 轉送](../guide/siem.md) |
| CSR | Certificate Signing Request（憑證簽署請求）。向 CA 提交以取得 TLS 憑證的檔案，用於將 GUI 從自簽憑證換成正式 CA 簽發憑證（Settings → Security → TLS → Generate CSR）。 | [Web GUI 導覽](../guide/gui-tour.md)、[故障排除](../guide/troubleshooting.md) |
| CSV | Comma-Separated Values。illumio-ops 報表模組產出的匯出格式之一，用於工作負載清單、流量摘要與 policy 缺口報表。 | [報表家族](../guide/reports.md) |
| DLQ | 見上方「illumio-ops 專用術語 → DLQ」。 | [SIEM 轉送](../guide/siem.md) |
| HEC | HTTP Event Collector。illumio-ops SIEM 轉發器支援的 Splunk HTTPS 資料匯入端點（`transport: hec`）。 | [SIEM 轉送](../guide/siem.md) |
| NSSM | Non-Sucking Service Manager。在 Windows 主機上以背景服務方式執行 illumio-ops 所使用的 Windows 服務包裝器。 | [安裝與部署](../guide/installation.md) |
| PCE | Policy Compute Engine（政策運算引擎）。見上方「Illumio 核心術語 → PCE」。 | [架構導覽](../handover/architecture.md) |
| REST | Representational State Transfer（表現層狀態轉換）。Illumio PCE API 採用的架構風格，illumio-ops 使用 PCE REST API（v2）進行所有資料擷取與 policy 讀取。 | [REST API 參考](rest-api.md) |
| RFC 5424 | 定義 syslog 訊息格式的協定標準（PRI、VERSION、TIMESTAMP、HOSTNAME、APP-NAME、MSGID、STRUCTURED-DATA）。illumio-ops 的 `syslog_cef`／`syslog_json` 傳輸格式在外層包一層 RFC 5424 header。 | [SIEM 轉送](../guide/siem.md) |
| TLS | Transport Layer Security。用於加密 PCE API 流量（TCP 8443/8444），以及 GUI Web 介面與可選的 SIEM syslog 轉發（`transport: tls`）。 | [設定參照](../guide/configuration.md) |
| VEN | Virtual Enforcement Node（虛擬強制節點）。見上方「Illumio 核心術語 → VEN」。 | [PCE domain 須知](../handover/pce-domain-notes.md) |

---

## 相關文件

- [文件總覽 INDEX](../INDEX.md) — 全部文件地圖
- [PCE domain 須知](../handover/pce-domain-notes.md) — vendor 事實查證來源
- [開發流程](../handover/development.md) — i18n 鍵值約定與新增字串流程
- [Web GUI 導覽](../guide/gui-tour.md) — 本表多數術語的實際呈現介面
