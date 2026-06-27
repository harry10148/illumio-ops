---
title: Glossary
audience: [operator, developer, api, security]
last_verified: 2026-06-26
verified_against:
  - src/i18n/data/zh_explicit.json
  - docs/Glossary.md (legacy, audited)
  - commit 838ee40
related_docs:
  - ../INDEX.md
  - i18n-contract.md
  - ../user-guide/dashboard.md
  - ../contributing/i18n-workflow.md
---

> 🌐 **[English](glossary.md)** | **[繁體中文](glossary_zh.md)**
> 📍 [INDEX](../INDEX.md) › 參考 › 詞彙表
> 🔍 最後驗證 **2026-05-15** 對 commit `838ee40` — 詳見 frontmatter

# 詞彙表

本頁為新進人員提供快速參考。每則條目皆可獨立閱讀：讀完一則即可掌握要旨，再循交叉引用深入了解。

---

## Illumio 核心術語

**Application Group**（應用群組）— 共享同一 `app` 標籤值的工作負載邏輯群組，代表一個業務服務（例如 `HRM`、`Payments`）。規則集通常以 Application Group 為範圍。

**Enforcement Boundary**（強制邊界）— 獨立於一般規則的範圍式拒絕聲明。在工作負載群組之間建立「防爆牆」；在 Selective 強制模式下，VEN 僅封鎖違反邊界的流量。

**Enforcement Mode**（強制模式）— VEN 的運作狀態：*Idle*（關閉，無記錄）、*Visibility Only*（僅被動監控）、*Selective*（僅封鎖邊界違規）、*Full*（預設拒絕 / 零信任，僅允許清單）。Full 是生產環境微分段的目標狀態。

**Environment**（環境）— `env` 標籤維度，記錄工作負載的 SDLC 階段（例如 `production`、`staging`、`dev`）。用於規則集以限定規則適用的生命週期階段。

**Heartbeat**（心跳）— VEN 定期向 PCE 回報狀態（每 5 分鐘回報一次，每 10 分鐘傳送摘要流量記錄）。也作為 Policy 更新的備援傳輸通道。

**IP List**（IP 清單）— 命名的 IP 位址或 CIDR 範圍集合，用於規則的提供方或消費方，表達與非工作負載端點（例如外部夥伴、網際網路出口）之間的流量。

**Label**（標籤）— 附加於工作負載的鍵值中繼資料。Illumio 使用四個維度：`role`、`app`、`env`、`loc`。規則以標籤為目標而非 IP，因此 Policy 可自動跟隨工作負載。

**Label Group**（標籤群組）— 同一維度內命名的標籤值集合，用於編寫一條規則同時適用於多個環境或應用，無需重複。

**Location**（位置）— `loc` 標籤維度，記錄工作負載的地理位置或基礎設施區域（例如 `aws-east1`、`on-prem-nyc`）。

**Pairing Profile**（配對設定檔）— PCE 物件，捆綁 VEN 安裝並配對時套用於工作負載的組態（標籤、強制模式、可見性層級）。產生一次性配對金鑰。

**PCE (Policy Compute Engine)**（政策運算引擎）— Illumio 平台的伺服器端核心。計算每個工作負載的安全政策，並推送至每個已配對的 VEN。內部橫跨四個服務層：前端、處理、服務/快取、持久化。

**Policy Lifecycle**（政策生命週期）— 每次政策變更所經歷的三階段流程：*Draft*（草稿，VEN 不可見）、*Pending*（批次等待審查與影響分析）、*Active*（已佈署並推送至 VEN）。

**Rule**（規則）— 規則集內的單一允許/拒絕聲明，以 `提供方 × 消費方 × 服務` 表達。提供方與消費方通常為標籤選擇器。

**Ruleset**（規則集）— 分組相關安全規則並套用至一組工作負載的範圍容器（通常以 `app`+`env` 標籤定義）。政策生命週期中寫入/佈署的基本單位。

**Scope**（範圍）— 附加於規則集或強制邊界的標籤選擇器，決定其管轄的工作負載。`app=HRM, env=production` 的範圍僅將規則集套用於生產環境 HRM 工作負載。

**Service**（服務）— 一個或多個 `協定+埠` 組合的可重用定義（例如 `tcp/443, tcp/80`），由規則引用而不直接內嵌埠號。

**Service Account**（服務帳號）— PCE 中的非人類身分，供自動化工具（腳本、CI/CD 流程）透過 API 金鑰驗證 PCE API，不與使用者帳號綁定。

**VEN (Virtual Enforcement Node)**（虛擬強制節點）— 安裝於每個受管工作負載的輕量代理程式。設定主機原生防火牆（`iptables`/`nftables`、WFP），收集流量遙測，並透過 TLS TCP 8443/8444 套用從 PCE 接收的政策。

**Workload**（工作負載）— PCE 追蹤的受管運算資源。三種子類型：*Managed*（已配對 VEN，即時遙測）、*Unmanaged*（僅標籤 IP，無 VEN）、*Container*（透過 Kubelink 的 Kubernetes/OpenShift Pod）。

---

## illumio-ops 專用術語

**Action Matrix**（動作矩陣）— `config/config.json` 中的組態表，將告警規則的嚴重性與類別對應至通知渠道（Email、LINE、Webhook、Telegram、Teams）。決定每則告警的觸發方式與路由目的地。

**Alert Rule**（告警規則）— illumio-ops 中的命名偵測定義，監控 PCE 事件或指標的特定模式。觸發時，告警引擎評估 Action Matrix 並派發通知。

**Backfill**（補填）— 以 `illumio-ops cache backfill` 觸發的歷史日期範圍填充。直接寫入 `pce_events` / `pce_traffic_flows_raw`，繞過 Watermark。用於首次啟用後補齊快取資料。

**DLQ (Dead Letter Queue)**（死信佇列）— PCE Cache 中的 `dead_letter` 資料表。存放已用盡所有重試的 SIEM 派發，隔離保留 30 天供操作員檢查，不影響即時佇列。

**Draft Policy Alignment (R-series)**（草稿政策對齊，R 系列）— 由 `compute_draft` 實作的 R01–R05 偵測規則。從 PCE 讀取草稿狀態規則，在佈署前標記缺口（例如生產環境中仍處於 Idle/Visibility Only 的工作負載）。

**Hub Apps**（中樞應用）— illumio-ops Web UI 中捆綁的第一方功能模組集合（儀表板、報表、告警、設定、SIEM）。每個 Hub App 是獨立的 Flask Blueprint。

**Ingestor**（擷取器）— 每個資料來源（`events`、`traffic`）一個的背景輪詢器，依固定排程從 PCE API 拉取新資料列至 PCE Cache，受共享令牌桶速率限制器管控。

**Multi-PCE Profile**（多 PCE 設定檔）— `config/config.json` 中的命名組態槽，存放單一 PCE 的憑證與端點設定。允許單一 illumio-ops 安裝指向多個 PCE。

**PCE Cache**（PCE 快取）— 位於 `data/pce_cache.sqlite` 的本地 SQLite (WAL) 資料庫，儲存 PCE 稽核事件與流量記錄的滾動窗口，作為 SIEM 轉發器、報表模組與告警迴圈的共享緩衝區。

**Rule Scheduler**（規則排程器）— illumio-ops 內基於 APScheduler 的作業執行器，依設定間隔執行擷取器、告警評估、SIEM 派發滴答與報表生成。

**SIEM Dispatch**（SIEM 派發）— `siem_dispatch` 外寄佇列資料表。SIEM 轉發器從此佇列讀取，將事件傳送至 syslog/Splunk/Elastic，成功傳遞後移除資料列；失敗則移至 DLQ。

**Watermark**（水位線）— `ingestion_watermarks` 資料表中的每擷取器游標，記錄各來源最後成功擷取的時間戳記。重啟後仍保留，確保輪詢無縫隙或重複地恢復。

---

## i18n 相關術語

**`desc_key`** — 欄位人類可讀說明字串的 i18n 鍵命名慣例。用於 zh_explicit.json 條目（如 `alert_field_desc`），提供已翻譯的工具提示或輔助文字。

**`label_key`** — 欄位在 UI 顯示標籤的 i18n 鍵命名慣例（例如 `alert_field_action` → `動作`）。與 `name_key`（實體名稱）和 `desc_key`（說明）有所區別。

**`name_key`** — 實體顯示名稱的 i18n 鍵命名慣例。與 `label_key`（表單標籤）和 `desc_key`（說明）分離，允許各個介面分別翻譯。

**`rec_key`** — 告警或驗證錯誤旁顯示的建議字串的 i18n 鍵命名慣例（例如 `alert_rec_agent_offline_check`）。簡短、可操作、面向操作員。

**`t()` function**（`t()` 函式）— illumio-ops 中的 Python 執行期翻譯輔助函式。對照現用語系的 JSON 檔案解析 i18n 鍵，若未找到則回退至 `zh_explicit.json`。

**zh_explicit** — 檔案 `src/i18n/data/zh_explicit.json`。所有 Illumio 領域及 illumio-ops UI 字串的 zh_TW 核准翻譯主要來源。覆蓋基礎語系檔 `src/i18n_zh_TW.json` 中的產品專用術語。

**zh_explicit override**（zh_explicit 覆寫）— 查找優先級規則：`zh_explicit.json` 中找到的鍵優先於基礎 `src/i18n_zh_TW.json` 中的相同鍵。確保告警訊息、欄位標籤與建議字串採用經過核准、符合產品規範的翻譯。

---

## 合規 / 稽核術語

**Audit Event**（稽核事件）— PCE 針對政策物件或使用者工作階段的每次建立/更新/刪除/驗證動作所發出的結構化日誌條目。儲存於 `pce_events` 並以 CEF 或 JSON Lines 格式轉發至 SIEM。

**Audit Log**（稽核日誌）— 透過 `/api/v2/auditable_events` 從 PCE 匯出的完整歷史稽核事件串流。illumio-ops 輪詢此端點以填充 PCE Cache 並驅動告警評估。

**Event Type**（事件類型）— PCE 指派給每個稽核事件的類別字串（例如 `workload.create`、`ruleset.update`、`user.sign_in`）。用於告警規則和 SIEM 查詢中的篩選維度。

**SIEM Forwarding**（SIEM 轉發）— 將 PCE 事件與流量記錄從 illumio-ops 傳遞至外部安全平台（Splunk、Elastic、QRadar）的管道。支援 CEF-over-syslog（UDP/TCP/TLS）與 Splunk HEC（HTTPS）。

---

## 縮寫

**CEF** — Common Event Format（通用事件格式）。illumio-ops 透過 UDP/TCP/TLS 向 SIEM 平台轉發稽核事件所使用的 syslog 相容結構化日誌標準。

**CSR** — Certificate Signing Request（憑證簽署請求）。向 CA 提交以取得 TLS 憑證的檔案，用於設定 SIEM 轉發的 TLS 傳輸或 PCE API 雙向 TLS。

**CSV** — Comma-Separated Values（逗號分隔值）。illumio-ops 報表模組產出的匯出格式，用於工作負載清單、流量摘要與政策缺口報表。

**HEC** — HTTP Event Collector（HTTP 事件收集器）。illumio-ops SIEM 轉發器支援的 Splunk HTTPS 資料匯入端點（`transport: hec`）。

**NSSM** — Non-Sucking Service Manager（非劣質服務管理員）。在 Windows 主機上以背景服務方式執行 illumio-ops 所使用的 Windows 服務包裝器。

**PCE** — Policy Compute Engine（政策運算引擎）。參見 [Illumio 核心術語 → PCE](#illumio-核心術語)。

**REST** — Representational State Transfer（表現層狀態轉換）。Illumio PCE API 採用的架構風格。illumio-ops 使用 PCE REST API (v2) 進行所有資料擷取與政策讀取。

**RFC 5424** — 定義 syslog 訊息格式的協定標準（PRI、VERSION、TIMESTAMP、HOSTNAME、APP-NAME、MSGID、STRUCTURED-DATA）。illumio-ops 在 CEF syslog 訊息上發出符合 RFC 5424 的標頭。

**TLS** — Transport Layer Security（傳輸層安全）。用於加密 PCE API 流量（TCP 8443/8444），以及設定 `transport: tls` 時的 SIEM syslog 轉發。

**VEN** — Virtual Enforcement Node（虛擬強制節點）。參見 [Illumio 核心術語 → VEN](#illumio-核心術語)。

---

## 相關文件

- [INDEX](../INDEX.md) — 完整文件地圖
- [i18n Contract](i18n-contract.md) — 術語如何在執行期翻譯
- [操作手冊](../operations-manual_zh.md) — Web GUI 操作導覽（§3），許多術語的實際呈現介面（繁體中文）
- [i18n Workflow](../contributing/i18n-workflow.md) — 新增可翻譯術語的流程
