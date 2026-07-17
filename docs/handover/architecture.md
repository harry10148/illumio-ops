---
title: 架構導覽與模組地圖
audience: [developer]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - illumio-ops.py
  - src/main.py
  - src/api_client.py
  - src/api/labels.py
  - src/api/async_jobs.py
  - src/api/traffic_query.py
  - src/api/reports.py
  - src/analyzer.py
  - src/pce_cache/rate_limiter.py
  - src/pce_cache/reader.py
  - src/pce_cache/archive.py
  - src/pce_cache/capacity.py
  - src/events/__init__.py
  - src/report/report_generator.py
  - src/report/cache_support.py
  - src/report_scheduler.py
  - src/rule_scheduler.py
  - src/reporter.py
  - src/alerts/base.py
  - src/siem/dispatcher.py
  - src/gui/__init__.py
  - src/gui/routes/
  - src/scheduler/__init__.py
  - src/scheduler/jobs.py
  - src/job_health.py
  - src/cli/_runtime.py
  - src/cli/gui_cmd.py
  - src/config_models.py
---

# 架構導覽與模組地圖

本文件的讀者是**零背景接手這個 codebase 的開發者**。目標：讀完能回答「資料從哪裡進、在哪裡算、從哪裡出」、每個 `src/` 頂層模組是做什麼的、以及幾個關鍵設計決策背後的為什麼。所有敘述以程式碼為準；引用的原始碼路徑都是查證錨點。

## 1. 一句話定位

illumio-ops 是一個**單一 Python 進程**的 Illumio PCE 維運工具：agentless、只透過 PCE 的 HTTPS REST API 取資料（不裝任何 agent、不碰 VEN），把流量、事件、政策、工作負載資料拉回本地，經過快取、規則引擎與報表引擎，最後從 Web GUI、CLI、排程報表、告警通道與 SIEM 轉送等出口交付。

同一個進程內同時存在：Flask Web GUI（主執行緒）、headless 監控迴圈（背景執行緒）、APScheduler 背景排程（含專用 `cache_writer` executor）。三者共用同一份 `ConfigManager` 設定與同一顆 pce_cache SQLite。進程入口與模式切換見第 5 節。

## 2. 資料流總覽

```text
                Illumio PCE（一或多個連線設定檔）
                REST API：workloads / labels / rulesets /
                events / traffic flows / draft policy
                          |
                          |  agentless，只走 HTTPS REST
                          v
        +--------------------------------------------+
        |  src/api_client.py（ApiClient facade）       |
        |  + src/api/：LabelResolver、AsyncJobManager、 |
        |    TrafficQueryBuilder、reports（原生 RHC）    |
        +--------------------------------------------+
             |                          |
             | 即時查詢                  | 背景輪詢（ingest jobs）
             |（報表、GUI 即查）          v
             |            +------------------------------+
             |            |  src/pce_cache/（SQLite 鏡像）  |
             |            |  raw flows / events、聚合、     |
             |            |  保留、封存 JSONL、容量監控       |
             |            +------------------------------+
             |                 |                |
             v                 v                | enqueue（與寫入同交易）
   +--------------------------------------+    v
   | 消費端（同進程）                        |  +------------------+
   |  analyzer.py  監控循環＋告警規則評估     |  | src/siem/         |
   |  events/      事件正規化/比對/節流      |  | dispatcher + DLQ  |
   |  report/      報表家族（HTML 等產物）    |  +------------------+
   +--------------------------------------+          |
             |                                        v
             v                                  SIEM destinations
   +-----------------------------------------------------------+
   | 出口                                                        |
   |  gui/（Flask SPA） - cli/（click） - 互動選單（main.py）        |
   |  report_scheduler / rule_scheduler（排程觸發）                |
   |  reporter.py 告警派送（alerts/ 外掛：mail/webhook/LINE/...）   |
   +-----------------------------------------------------------+
```

幾條主要路徑：

- **監控路徑**：`scheduler/jobs.py:run_monitor_cycle` 觸發 `src/analyzer.py` 的分析循環。pce_cache 啟用時，analyzer 透過 cache subscriber 游標消費本地資料（`src/main.py:_make_subscribers`、`src/pce_cache/models.py:IngestionCursor`），30 秒一輪；未啟用時直接打 PCE API，依設定的分鐘級間隔輪詢。命中規則交給 `src/reporter.py` 渲染並派送到 `src/alerts/` 外掛。
- **報表路徑**：GUI（`src/gui/routes/reports.py`）、CLI（`src/cli/report.py`）、排程（`src/report_scheduler.py`）三個入口共用 `src/report/` 下的產生器；traffic 家族的資料來源（live API 或 cache）由 `src/report/cache_support.py` 統一裁決。
- **SIEM 路徑**：ingestor 寫入 cache 的同一個交易內 enqueue（`src/siem/dispatcher.py:enqueue`），`siem_dispatch` job 逐目的地派送，失敗進 DLQ。
- **封存路徑**：`pce_cache_archive` job 把 cache 的 traffic/audit 列增量匯出成分日 JSONL（`src/pce_cache/archive.py:ArchiveExporter`，at-least-once 語意），之後可用 `src/pce_cache/archive_import.py` 還原成 review DB 供歷史查詢。

## 3. 模組地圖

`src/` 每個頂層模組一列，依角色分三張表。表格單格只放一句話，細節以各檔 docstring 為準。

### 3.1 核心鏈（PCE 資料進來到算完）

| 模組 | 職責 | 關鍵入口點 | 主要依賴 |
|---|---|---|---|
| `api_client.py` | PCE REST 客戶端 facade：HTTP 基礎設施、簡單端點、TTL 快取與鎖 | `ApiClient` | requests、`src/api/` |
| `api/` | 由 facade 拆出的領域類：label 解析、async job、流量查詢、原生報表拉取 | `LabelResolver`、`AsyncJobManager`、`TrafficQueryBuilder`、`reports.py` | `api_client`（共享狀態在 facade 上） |
| `pce_cache/` | PCE 資料的本地 SQLite 鏡像：ingest、聚合、保留、封存、容量、出站限速 | `ingestor_traffic` / `ingestor_events`、`reader.CacheReader`、`schema.init_schema` | SQLAlchemy、`api_client` |
| `analyzer.py` | 監控循環：流量／事件／頻寬告警規則評估與統計 | `Analyzer.run_analysis`、`Analyzer.query_flows(params)` | `api/`、`pce_cache/reader`、`events/`、`reporter` |
| `events/` | 事件管線：vendor 事件目錄、正規化、watermark 輪詢、規則比對、節流 | `poller`、`matcher`、`catalog` | （純邏輯，供 analyzer 使用） |
| `report/` | 報表引擎：traffic 家族＋各獨立報表產生器與共用分析元件 | `ReportGenerator`、各 `*_report.py` / `*_generator.py` facade | `api_client`、`pce_cache`（經 `cache_support`） |

### 3.2 出口層（結果怎麼交付）

| 模組 | 職責 | 關鍵入口點 | 主要依賴 |
|---|---|---|---|
| `gui/` | Flask Web GUI（SPA＋REST API，10 個 Blueprint 在 `routes/`） | `build_app` / `launch_gui`（`gui/__init__.py`） | Flask、各核心鏈引擎 |
| `cli/` | click 子命令 CLI（monitor/gui/report/rule/workload/config/status 等） | `cli/root.py`、`cli/_runtime.py` | click、各核心鏈引擎 |
| `main.py` | 互動式選單＋舊 argparse 相容層 | `main()`、各 `_run_*_menu` | `cli/_runtime`（daemon 邏輯的唯一實作） |
| `reporter.py` | 告警訊息渲染與派送（mail/webhook/LINE/Telegram/Teams）＋報表 email 寄送 | `Reporter.send_alerts`、`send_report_email` | `alerts/`、`events/runbooks` |
| `alerts/` | 告警輸出外掛的基底類與註冊表（內建外掛＋metadata） | `base.py`、`plugins.py` | `reporter` 呼叫 |
| `siem/` | 審計事件轉送 SIEM：佇列派送、DLQ、PII 遮罩、synthetic 測試 | `dispatcher.build_dispatcher`、`dlq` | `pce_cache`（共用 DB） |
| `report_scheduler.py` | 報表排程引擎：每分鐘 tick 評估到期排程並執行 | `ReportScheduler.tick()` | `report/`、`reporter` |
| `rule_scheduler.py` | 規則排程引擎：依時程 enable/disable PCE 規則並 provision | `rule_scheduler.py` 核心（CLI 在 `rule_scheduler_cli.py`） | `api_client` |

### 3.3 支撐層（設定、狀態、基礎設施）

| 模組 | 職責 | 關鍵入口點 | 主要依賴 |
|---|---|---|---|
| `scheduler/` | APScheduler factory＋全部背景 job callables | `scheduler/__init__.py:build_scheduler`、`jobs.py` | apscheduler、`job_health` |
| `job_health.py` | 每個排程 job 的 last_run/last_status 落地 `logs/job_health.json` | `record_job_registered`、`record_job_run` | `state_store`（檔案鎖＋原子寫） |
| `config.py`、`config_models.py` | config.json 載入、深合併與 pydantic v2 驗證 | `ConfigManager`、`ConfigSchema` | pydantic |
| `state_store.py` | 狀態檔讀寫（跨執行緒檔案鎖＋原子寫） | `load_state_file`、`update_state_file` | — |
| `dashboard_store.py`、`dashboard_hero.py` | dashboard 摘要資料的持久儲存與健康敘述產生 | 各檔 module 函式 | 背景 job 寫、GUI API 讀 |
| `i18n/`（＋`i18n_*.json`） | 雙語字串子系統 | `t(key)`、`set_language` | — |
| `settings/` | 設定引擎（`engine.py`）＋向後相容 re-export shim | `settings/engine.py` | `config` |
| `auth_models.py` | GUI 單管理員登入模型（flask-login＋pydantic 表單） | `User`、`LoginForm` | flask-login |
| `exceptions.py`、`interfaces.py` | 型別化例外階層；Protocol 結構介面（供無 mock 測試） | — | — |
| `href_utils.py`、`tz_utils.py`、`port_token.py`、`rule_id.py` | 小型純函式工具：href 解析、時區解析、port token、rule id | 各檔 module 函式 | — |
| `loguru_config.py`、`module_log.py` | 全域 loguru 設定（含機密遮罩）；每模組執行紀錄 | `setup_loguru`、`ModuleLog` | loguru |
| `runtime_checks.py` | 進程啟動時的執行環境守門（SQLite 版本等） | module 函式 | — |
| `pce_cache_cli.py`、`siem_cli.py`、`rule_scheduler_cli.py` | 各子系統的互動式終端選單 | 各檔 `main` 選單 | 對應子系統 |
| `humanize_ext.py`、`utils.py` | humanize 的 i18n 包裝；舊 `src.utils` import 相容 shim | — | — |
| `static/`、`templates/` | GUI 前端資產（JS/CSS）與 Jinja 模板 | — | `gui/` 使用 |

## 4. 關鍵設計決策的為什麼

### 4.1 為什麼有 pce_cache（SQLite 鏡像）

PCE 的流量查詢又貴又慢（async query 要 submit、poll、download，分鐘級），且 PCE 對 API 呼叫有限流；每個消費端都直接打 PCE 既撐不起近即時監控、也會把 PCE 打掛。pce_cache 用背景 ingestor 持續把 events 與 traffic flows 鏡像進本地 SQLite，讓監控循環從分鐘級 API 輪詢降到 30 秒本地 tick（`src/scheduler/__init__.py` 中 `_cache_enabled` 分支），報表也能走 cache 路徑（`src/report/cache_support.py`）。配套護欄：出站呼叫有行程級 token-bucket 限速器（`src/pce_cache/rate_limiter.py`），cache 讀取有 `read_max_rows` 護欄防止大窗查詢撐爆常駐進程（`src/pce_cache/reader.py:CacheReadTooLarge`）。

### 4.2 為什麼報表拆家族

報表的成本都在資料抓取。traffic 家族（traffic、security_risk、network_inventory 三個 profile，加上 app-summary、readiness）共用 `ReportGenerator` 的同一次流量 DataFrame 抓取與分析管線（`src/report/report_generator.py`；`src/report/app_summary_report.py`、`src/report/readiness_report.py` 的 docstring 都明講 reuse ReportGenerator 的 fetch）。其餘報表的資料來源根本不同——audit 吃事件（`audit_generator.py`）、ven-status 吃工作負載（`ven_status_generator.py`）、policy-usage/policy-diff/policy-resolver 吃政策物件、rule-hit-count 吃 VEN 原生計數（`rule_hit_count_generator.py`）——硬塞進同一條 pipeline 只會互相牽制，所以各自是獨立的 generator facade，只共用 exporter、trend/snapshot store 等基座。

### 4.3 為什麼 ApiClient 是 facade＋composition

`ApiClient` 原本是 2569 行的 god class，後來拆成 `src/api/` 下三個領域類（`LabelResolver`、`AsyncJobManager`、`TrafficQueryBuilder`；見 `src/api_client.py` 模組 docstring）。選 composition 而非直接搬走狀態，是為了相容：TTL 快取、`_cache_lock`、state file 等欄位仍由 facade 持有，公開方法保留薄委派，因此既有測試與外部呼叫端照舊存取 `api.label_cache`、`api._label_href_cache` 不用改。facade 同時集中 HTTP 基礎設施（Session、Retry、認證標頭、`_request`），包括「POST 不進 urllib3 自動重試、429 才安全地單次補償重試」這類全域策略（`src/api_client.py` `__init__` 的 Retry 設定與 `_request`）。

### 4.4 為什麼 label cache 用 build-then-swap

如果更新快取採「先 clear 再抓」，抓取的數秒內所有讀者都會看到空快取——GUI 顯示原始 href、報表大量 cache miss 直接打 PCE。`LabelResolver.update_label_cache` 因此在鎖外用區域 dict 組裝，等 labels/ip_lists/services/label_groups 四個集合全部回 200 才在 `_cache_lock` 內一次 clear+update swap（保留 TTLCache 實例與別名引用）；任一集合失敗或途中例外，共享快取完全不動、回傳 False（`src/api/labels.py:update_label_cache` docstring）。讀者要嘛看到整組舊資料、要嘛看到整組新資料，沒有中間態。

### 4.5 為什麼集合 GET 有 async fallback

PCE 的同步集合 GET 有 500 筆硬上限，超過就默默截斷——對 rulesets、workloads 這類會成長的集合，截斷等於報表算錯。`_get_collection` 用回應的 `X-Total-Count` 偵測截斷，觸發官方 async GET 流程補救：同一路徑帶 `Prefer: respond-async` 重發，收 202＋`Location` job href，輪詢到 `done` 後從 `result.href` 下載完整集合（`src/api_client.py:_get_collection`、`_async_collection_get`）。fallback 失敗時保留截斷資料＋錯誤 log，行為永遠不比沒有 fallback 差。X-Total-Count 帶 filter 時的語意陷阱等 vendor 事實見 [pce-domain-notes.md](pce-domain-notes.md)。

### 4.6 為什麼只有一把 `_cache_lock`（RLock）

facade 上的所有 TTL 快取（label、href 別名快取等）共用一把 `threading.RLock`（`src/api_client.py` `__init__`）。單一把鎖讓「多個快取一起 swap」天然原子，也不存在多鎖順序死結問題；因為抓取都在鎖外進行（見 4.4），持鎖區只剩記憶體操作，單鎖不會成為瓶頸。選 RLock 而非 Lock 是因為呼叫鏈會重入——`update_label_cache` 在持鎖流程中呼叫 `invalidate_*` 系列方法，原始碼行內註解明講這個理由。

## 5. 執行模式與排程 job

### 5.1 進程入口

`illumio-ops.py` 是唯一入口，內含一個 dispatcher，讓兩套解析器共存（見該檔 docstring）：

- **click 子命令（建議）**：`illumio-ops monitor / gui / monitor-gui / report / rule / workload / cache / config / siem / status / version`（`src/cli/`）。
- **legacy argparse 旗標（向後相容）**：`--monitor`、`--gui`、`--monitor-gui`、`--report`、`-i`、`-p`。
- **不帶參數**：進入互動式選單（`src/main.py`），涵蓋監控、各報表子選單、log 檢視等。

實際的常駐邏輯只有一份，在 `src/cli/_runtime.py`：

| 模式 | 入口 | 行為 |
|---|---|---|
| 純監控 daemon | `run_daemon_loop` | headless 監控迴圈，APScheduler 驅動 |
| 純 GUI | `run_gui_only` | 只跑 Flask Web GUI，無背景 daemon |
| monitor-gui | `run_daemon_with_gui` | daemon 跑背景執行緒＋Flask GUI 佔主執行緒（生產常駐建議模式） |

GUI 預設埠為 **5001**（`src/cli/gui_cmd.py` 的 `--port` 預設值；`src/gui/__init__.py:launch_gui` 同值），預設走 HTTPS（self-signed 可自動換發，見下表 `tls_renew_check`）。

### 5.2 排程 job 一覽

daemon 啟動時由 `src/scheduler/__init__.py:build_scheduler` 註冊。每個 job 都包 `_instrument` wrapper：註冊當下先寫 `registered` 記錄、每次執行後寫 ok/error 到 `logs/job_health.json`（`src/job_health.py`），讓「應跑未跑」可觀測；長間隔 job 一律帶啟動後錯開的首跑 kick（2026-07-14 archive 事故的根治：IntervalTrigger 預設首跑排在啟動後一整個間隔，頻繁重啟會讓 24h 間隔的 job 永遠跑不到）。

全部條件開啟時共 14 個註冊 job（與測試機 `logs/job_health.json` 一致）：

| Job id | 職責 | 間隔（預設） | 註冊條件 | executor |
|---|---|---|---|---|
| `monitor_cycle` | 監控分析＋告警派送 | cache 啟用 30s，否則設定分鐘數 | 一律 | default |
| `tick_report_schedules` | 報表排程 tick | 60s | 一律 | default |
| `tick_rule_schedules` | 規則排程 tick | 設定值 | 一律 | default |
| `ven_summary` | VEN 健康摘要寫入 store | 300s | 一律 | default |
| `posture_summary` | posture 分數摘要 | 600s | 一律 | default |
| `tls_renew_check` | self-signed 憑證到期檢查與換發 | 24h | TLS 啟用＋self_signed＋auto_renew | default |
| `pce_cache_ingest_events` | 事件 ingest 進 cache | `events_poll_interval_seconds` | cache 啟用 | cache_writer |
| `pce_cache_ingest_traffic` | 流量 ingest 進 cache | `traffic_poll_interval_seconds` | cache 啟用 | cache_writer |
| `pce_cache_aggregate` | 流量聚合表更新 | 1h | cache 啟用 | cache_writer |
| `pce_cache_retention` | cache 保留清理 | 24h | cache 啟用 | cache_writer |
| `cache_lag_monitor` | ingest 落後偵測＋告警 | 60s | cache 啟用 | default |
| `pce_cache_capacity_monitor` | DB 大小／磁碟／佇列容量監控（唯讀） | 30m | cache 啟用 | default |
| `pce_cache_archive` | cache 增量封存成分日 JSONL | `archive_interval_hours` | cache＋archive 啟用 | cache_writer |
| `siem_dispatch` | SIEM 佇列派送 | `dispatch_tick_seconds` | SIEM 啟用 | default |

`cache_writer` 是單 worker 專用 executor：所有會寫 cache DB 的 job 序列化執行，避免 SQLite 寫入互撞；唯讀 job（如容量監控）刻意走 default executor 不佔用它（`src/scheduler/__init__.py`、`src/scheduler/jobs.py:run_capacity_monitor` docstring）。

### 5.3 下一步閱讀

- PCE API 與 policy 模型的 vendor 事實（值域、限流、版本門檻）：[pce-domain-notes.md](pce-domain-notes.md)
- 開發流程與測試守門：[development.md](development.md)
- 日常操作與 GUI 功能：見 docs/guide/ 系列（重寫中）。
