# 詞彙表

<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](../README.md) | [README_zh.md](../README_zh.md) |
| Installation | [Installation.md](./Installation.md) | [Installation_zh.md](./Installation_zh.md) |
| User Manual | [User_Manual.md](./User_Manual.md) | [User_Manual_zh.md](./User_Manual_zh.md) |
| Report Modules | [Report_Modules.md](./Report_Modules.md) | [Report_Modules_zh.md](./Report_Modules_zh.md) |
| Security Rules | [Security_Rules_Reference.md](./Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](./Security_Rules_Reference_zh.md) |
| SIEM Integration | [SIEM_Integration.md](./SIEM_Integration.md) | [SIEM_Integration_zh.md](./SIEM_Integration_zh.md) |
| Architecture | [Architecture.md](./Architecture.md) | [Architecture_zh.md](./Architecture_zh.md) |
| PCE Cache | [PCE_Cache.md](./PCE_Cache.md) | [PCE_Cache_zh.md](./PCE_Cache_zh.md) |
| API Cookbook | [API_Cookbook.md](./API_Cookbook.md) | [API_Cookbook_zh.md](./API_Cookbook_zh.md) |
<!-- END:doc-map -->

> [English](Glossary.md) | [繁體中文](Glossary_zh.md)

---

本頁是給新進人員的快速參考。每個條目都自成段落：只讀單一條目即可掌握概念，需要完整脈絡時再依交叉參照前往對應章節。

## Illumio 平台術語

- **PCE（Policy Compute Engine）** —— Illumio 平台的伺服器端核心。負責為每個 workload 計算量身訂製的安全策略，並將其推送至每個配對的強制執行代理。內部跨四個服務層（Front End、Processing、Service/Caching、Persistence）。完整說明見 [Architecture §Background.1](./Architecture_zh.md#background1-pce-與-ven)。

- **VEN（Virtual Enforcement Node）** —— 一個輕量級代理，執行於每個受管 workload（裸機、VM 或容器主機）之上。對主機原生防火牆進行程式設定（Linux 的 `iptables`/`nftables`、Windows 的 WFP 等）、收集流量遙測，並套用從 PCE 接收的策略。透過 TLS 與 PCE 通訊（內部部署為 TCP 8443/8444；SaaS 為 443）。見 [Architecture §Background.1](./Architecture_zh.md#background1-pce-與-ven)。

- **Workload（受管 / 非受管 / 容器）** —— PCE 將網路實體分為三類。*受管* = 已配對 VEN 並回報即時流量。*非受管* = 僅有 IP 與 label 的實體（筆記型電腦、設備、PKI/Kerberos 端點），無 VEN。*容器* = 透過 Illumio Kubelink 監控的 Kubernetes/OpenShift Pod，VEN 安裝於主機節點。見 [Architecture §Background.3](./Architecture_zh.md#background3-workload-類型)。

- **Label / Label 維度** —— 附加於 workload 的鍵值中繼資料。Illumio 採用四個維度：`role`（在應用程式中的功能，例如 `web`、`database`）、`app`（業務服務，例如 `HRM`）、`env`（SDLC 階段，例如 `production`）、`loc`（地理位置，例如 `aws-east1`）。規則以 label 為目標而非 IP，因此 `role=web, env=production` 規則會適用於所有具備這些 label 的 workload。見 [Architecture §Background.2](./Architecture_zh.md#background2-label-維度)。

- **Ruleset** —— 具範圍（scope）的容器，將相關安全規則歸成一組並套用至一組 workload（通常以 `app`+`env` label 定義範圍）。它是策略生命週期中寫入與佈建的單位。

- **Rule** —— Ruleset 內的單一允許／拒絕語句，以「provider × consumer × service」表達。Provider 與 consumer 通常都是 label 選擇器。

- **Service** —— 一個或多個「protocol+port」組合的可重複使用定義（例如 `tcp/443、tcp/80`），規則引用此定義而非直接內嵌埠號。

- **IP List** —— 具名的 IP 位址或 CIDR 範圍集合，作為規則中的 provider 或 consumer，用以表達非 workload 端點的流量（例如外部合作夥伴、網際網路出口）。

- **Label Group** —— 同一維度內多個 label 值的具名集合，可用一條規則同時套用至多個環境或應用程式，避免重複撰寫。

- **Enforcement Boundary** —— 與一般規則分開的具範圍拒絕語句。在多組 workload 之間定義「防爆牆」；於 Selective 強制模式下，VEN 僅阻擋違反 boundary 的流量。

- **Policy 生命週期：Draft → Pending → Active** —— 任何對策略物件的寫入操作首先進入 **Draft** 狀態（對 VEN 不可見），儲存後進入 **Pending** 佇列以供審查與影響分析，最後需經明確的佈建（Provision）操作提升至 **Active** 狀態才會在 workload 上生效。PCE 隨後重新計算策略圖，並將新的防火牆規則推送至每個受影響的 VEN。完整生命週期見 [Architecture §Background.4](./Architecture_zh.md#background4-policy-生命週期)。

- **強制模式：Idle / Visibility Only / Selective / Full** —— VEN 的四種狀態。*Idle* = 強制執行關閉、不記錄日誌。*Visibility Only* = 被動監控、不阻擋。*Selective* = 僅阻擋違反 Enforcement Boundary 的流量。*Full* = default-deny / zero-trust，僅允許白名單。Full 模式是生產環境微分段的目標狀態。見 [Architecture §Background.5](./Architecture_zh.md#background5-強制模式)。

- **Heartbeat（心跳）** —— VEN 與 PCE 的週期性回報機制（每 5 分鐘回報狀態、每 10 分鐘回報彙總流量記錄）。當長連線 lightning-bolt 通道不可用時，PCE 也會藉由 heartbeat 回應作為策略更新的退回通道。

- **`policy_decision` vs `draft_policy_decision`** —— 每筆流量都帶有兩個欄位。`policy_decision` 是 VEN 在流量產生當下記錄的*歷史*判定（永遠是 `allowed`、`potentially_blocked`、`blocked` 三者之一）。`draft_policy_decision` 是在呼叫 `PUT {job_href}/update_rules` 後*動態重算*的結果，根據當前 active + draft 規則重新評估，因此反映「若立即佈建草稿後會發生什麼」。完整數值表見 [Security Rules Reference §Policy Decision 欄位](./Security_Rules_Reference_zh.md#policy-decision-欄位)。

## 工具特定術語（illumio-ops）

- **PCE Cache（PCE 快取）** —— 選用的本機 SQLite（WAL）資料庫，儲存 PCE 稽核事件與流量記錄的滾動窗口。作為 SIEM 轉發器、報表模組與告警／監控迴圈的共享緩衝區，避免衝撞 PCE 的 500 req/min 速率限制。預設停用；在 `config/config.json` 設定 `pce_cache.enabled` 即可啟用。見 [PCE Cache](./PCE_Cache_zh.md)。

- **Ingestor** —— 背景輪詢器（每個資料來源一個：`events`、`traffic`），依固定排程從 PCE API 拉取新資料列至快取。所有 Ingestor 共用一個全域令牌桶速率限制器（預設 400/min），確保 daemon 不會超出 PCE 配額。

- **Watermark（水位）** —— 儲存於 `ingestion_watermarks` 表的每來源游標，記錄各來源最後成功擷取的時間戳記。重啟後仍存續，使輪詢可無縫接續、無遺漏或重複。`cache_lag_monitor` 任務會監視 `last_sync_at` 以偵測停頓的 ingestor。

- **Backfill（回填）** —— 透過 `illumio-ops cache backfill --source {events|traffic} --since YYYY-MM-DD [--until YYYY-MM-DD]` 手動觸發的歷史日期範圍填補。直接寫入 `pce_events` / `pce_traffic_flows_raw`，繞過 watermark。常用於既有部署啟用快取後補齊歷史資料。見 [PCE Cache §Backfill](./PCE_Cache_zh.md#backfill)。

- **DLQ（Dead Letter Queue／死信佇列）** —— 快取中的 `dead_letter` 表。保留所有達最大重試次數仍失敗的 SIEM 派送，隔離 30 天，讓操作員得以檢查失敗原因而不阻塞主佇列。

- **SIEM dispatch（SIEM 派送）** —— `siem_dispatch` 出站佇列表。SIEM 轉發器從此佇列讀取，將事件送往機外（syslog／Splunk／Elastic），成功送達的資料列即移除；持續失敗者會被移入 DLQ。

- **Draft policy 對齊（R 系列規則）** —— [Security Rules Reference](./Security_Rules_Reference_zh.md) 中的 R01–R05 偵測規則，由 `compute_draft` 實作。它們從 PCE 讀取 Draft 狀態的規則，並在策略進入 Active 之前標記差距（例如：仍處於 Idle／Visibility Only 的生產環境 workload）。

- **Multi-PCE Profile（多 PCE 設定檔）** —— `config/config.json` 中的設定槽位，每個槽位保存一個 PCE 的完整憑證與端點設定。使用者可切換 active 設定檔（例如 lab 與 production），無需重新輸入憑證，使單一 illumio-ops 安裝可指向多個 PCE。

- **`must_change_password` / `_initial_password`** —— Web GUI 認證強制變更密碼機制。管理員（重新）建立使用者時，`_initial_password` 攜帶臨時密碼並設定 `must_change_password`；使用者首次登入時會被強制走完密碼重設流程，方可進行任何其他操作。

## 延伸閱讀

- [Architecture](./Architecture_zh.md) Background —— 完整 Illumio 平台脈絡（PCE/VEN、label、workload 類型、policy 生命週期、強制模式）
- [Security Rules Reference](./Security_Rules_Reference_zh.md) §Policy Decision 欄位 —— `policy_decision` 與 `draft_policy_decision` 的完整數值表
- [PCE Cache](./PCE_Cache_zh.md) —— schema、保留策略、backfill 與操作命令
