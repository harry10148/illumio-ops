---
title: Architecture Overview
audience: [developer, security, api]
last_verified: 2026-05-15
verified_against:
  - src/ (module tree)
  - illumio-ops.py
  - deploy/
  - data/, config/, vendor/, logs/
  - docs/Architecture.md (legacy, fully audited)
  - docs/fonts-vendoring.md (legacy, folded in)
  - commit 54f70a3
related_docs:
  - report-engine.md
  - siem-pipeline.md
  - i18n-contract.md
  - ../user-guide/settings-and-pce-cache.md
---

> **[English](overview.md)** | **[繁體中文](overview_zh.md)**
> 📍 [INDEX](../INDEX.md) › 架構 › 總覽
> 🔍 最後驗證 **2026-05-15** 對 commit `54f70a3` — 詳見 frontmatter

# 架構總覽

illumio-ops 是一個 Python 應用程式，連接一或多個 Illumio Policy Compute Engine (PCE)
實例，將資料本地快取至 SQLite，透過規則引擎分析後，透過 Flask 網頁 GUI、Click CLI、
排程報告，以及可選的 SIEM 轉發管線呈現結果。

---

## 高階架構圖

```text
┌──────────────────────────────────────────────────────────────────┐
│                          Illumio PCE                             │
│   REST API (HTTPS :8443 / :443)                                  │
│   資源：workloads, labels, rulesets, events, traffic flows       │
└──────────────┬───────────────────────────────────────────────────┘
               │  requests（HTTP 客戶端）
               │  輪詢：events 每 5 分鐘，traffic 每 10 分鐘
               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         illumio-ops core                                    │
│                                                                             │
│   ┌──────────────┐   ┌──────────────┐   ┌────────────────┐                 │
│   │  pce_cache/  │◄──│    api/      │──►│   alerts/      │                 │
│   │  SQLite DB   │   │  PCE 客戶端  │   │  事件驅動       │                 │
│   │  （可選）    │   │  + 模型      │   │  通知           │                 │
│   └──────┬───────┘   └──────────────┘   │  (mail/LINE/   │                 │
│          │                              │   webhook)     │                 │
│          │  讀取                        └────────────────┘                 │
│          ▼                                                                  │
│   ┌──────────────┐   ┌──────────────┐   ┌────────────────┐                 │
│   │   report/    │   │  scheduler/  │   │    events/     │                 │
│   │  規則引擎    │   │  APScheduler │   │  事件目錄      │                 │
│   │  + 匯出器    │   │  執行緒      │   │  + 派發器      │                 │
│   └──────┬───────┘   └──────────────┘   └────────────────┘                 │
│          │                                                                  │
│          │ 輸出                                                             │
│          ▼                                                                  │
│   ┌──────────────┐   ┌──────────────┐   ┌────────────────┐                 │
│   │    gui/      │   │    cli/      │   │    siem/       │                 │
│   │  Flask 應用  │   │  Click 指令  │   │  格式化器      │                 │
│   │  cheroot     │   │  + 選單      │   │  + 傳輸器      │                 │
│   │  WSGI 伺服器 │   │              │   │  (Splunk HEC,  │                 │
│   └──────┬───────┘   └──────┬───────┘   │   Syslog 等)   │                 │
│          │                  │           └───────┬────────┘                 │
└──────────┼──────────────────┼───────────────────┼──────────────────────────┘
           │                  │                   │
           ▼                  ▼                   ▼
      瀏覽器使用者        終端機使用者         SIEM 平台
      (HTTP/HTTPS)       （互動或腳本）       (Splunk, QRadar,
                                              Elastic, syslog)
```

**事件驅動告警** — `alerts/` 模組訂閱 `events/` 事件匯流排。當輪詢到 PCE 事件或
觸發閾值時，告警插件非同步發送通知（電子郵件、LINE Notify、webhook），不會阻塞
GUI 或 CLI。

---

## 模組導覽（src/）

### gui/

**13 個 Python 檔案** — Flask 應用程式、路由藍圖及伺服器輔助程式。

`src/gui/__init__.py` 建立 Flask 應用程式、註冊藍圖，並啟動 cheroot WSGI 伺服器
（執行緒池、原生 TLS）。  
`src/gui/routes/` 包含 10 個藍圖：

| 檔案 | 藍圖 |
|---|---|
| `dashboard.py` | 即時儀表板（圖表、story-mode 面板） |
| `reports.py` | 隨需報告生成與下載 |
| `rules.py` | 安全規則瀏覽器 |
| `events.py` | PCE 事件串流檢視器 |
| `config.py` | PCE 設定檔 + 設定編輯器 |
| `auth.py` | 登入 / 工作階段管理（flask-login + argon2） |
| `admin.py` | 管理員面板（日誌檢視、快取管理） |
| `actions.py` | 工作負載隔離 / 解除隔離 + 加速 |
| `rule_scheduler.py` | 排程規則執行狀態 |
| `__init__.py` | 藍圖聚合 |

安全中介軟體：flask-wtf（CSRF）、flask-talisman（CSP/HSTS）、
flask-limiter（速率限制）、flask-login（工作階段驗證）。

### cli/

**30 個 Python 檔案** — 基於 Click 的指令樹及互動式選單。

透過 `illumio-ops.py` 派發器進入，依據 `argv[1]` 路由至 Click 或舊版 argparse。
Click 頂層子指令：`monitor`、`gui`、`report`、`rule`、`workload`、`config`、
`status`、`version`、`siem`、`cache`、`alert`。

`src/cli/menus/`（11 個檔案）— 以 questionary 驅動的互動式 TUI 選單，涵蓋告警設定、
頻寬規則、事件規則、流量規則、規則排程、系統健康、報告排程及網頁 GUI/TLS 設定。

### report/

**72 個 Python 檔案** — 分析模組、規則引擎、解析器及匯出器。
這是最大的模組。內部詳情請參閱 [Report Engine](report-engine.md)。

子目錄結構：

| 子目錄 | 用途 |
|---|---|
| `analysis/` | 20+ 個分析模組（mod01–mod15 + 攻擊態勢、草稿、ringfence、政策使用） |
| `analysis/audit/` | 稽核日誌分析 |
| `analysis/policy_usage/` | 政策使用分析 |
| `exporters/` | HTML、XLSX、CSV、圖表渲染、CSS、i18n 標籤輔助程式 |
| `parsers/` | PCE API 解析器、CSV 解析器、驗證器 |
| `rules/` | 規則引擎（R01–R05：草稿拒絕、覆寫拒絕、可視性違規、跨邊界允許、不符） |

頂層檔案：`report_generator.py`、`rules_engine.py`、`dashboard_summaries.py`、
`snapshot_store.py`、`trend_store.py`、`audit_generator.py`、
`policy_usage_generator.py`、`ven_status_generator.py`、`section_guidance.py`、
`report_metadata.py`、`tz_utils.py`。

> 透過 ReportLab 生成 PDF 的功能已移除（commit `92143a6`）。報告現僅支援 HTML + XLSX。

### siem/

**19 個 Python 檔案** — 具備可插拔格式化器和傳輸器的事件轉發器。
完整內部詳情請參閱 [SIEM Pipeline](siem-pipeline.md)。

| 子目錄 / 檔案 | 用途 |
|---|---|
| `formatters/` | CEF、Syslog-CEF、Syslog-JSON、Splunk-HEC、Normalised-JSON |
| `transports/` | Splunk HEC、syslog（TCP/UDP）、通用 HTTP |
| `dispatcher.py` | 派發迴圈（週期：`siem.dispatch_tick_seconds`，預設 5 秒） |
| `dlq.py` | 死信佇列（SQLite 儲存，每個目的地有深度上限） |
| `preview.py` | GUI 內格式預覽 |
| `tester.py` | 合成測試事件發送器 |
| `web.py` | SIEM 目的地管理的 GUI 路由 |

目的地儲存於 `config.json`（`siem.destinations[]`），使用 `host` + `port` 欄位
（從 `d350d3d` 中從舊版 `endpoint` 遷移而來）。

### pce_cache/

**15 個 Python 檔案** — 可選的 SQLite 本地 PCE 事件與流量資料鏡像。

關鍵檔案：`schema.py`（資料表定義）、`models.py`（ORM 式模型）、
`ingestor_events.py` + `ingestor_traffic.py`（輪詢器）、`aggregator.py`
（流量聚合）、`reader.py`（報告模組的查詢介面）、`retention.py`（行級 TTL 執行）、
`watermark.py`（游標追蹤）、`rate_limiter.py`（PCE API 速率上限，預設 400 req/min）、
`lag_monitor.py`、`backfill.py`、`subscriber.py`、`traffic_filter.py`、`web.py`（GUI 路由）。

快取預設停用（`pce_cache.enabled: false`）。啟用後，事件每隔
`events_poll_interval_seconds`（預設 300 秒）輪詢一次，流量每隔
`traffic_poll_interval_seconds`（預設 600 秒）輪詢一次。

操作員設定請參閱 [Settings & PCE Cache](../user-guide/settings-and-pce-cache.md)。

### alerts/ + events/

**alerts/ — 5 個 Python 檔案**（+ 3 個範本）：

| 檔案 | 用途 |
|---|---|
| `base.py` | 告警基底類別 |
| `plugins.py` | 發送插件（電子郵件、LINE Notify、webhook） |
| `metadata.py` | 告警規則詮釋資料 |
| `template_utils.py` | Jinja2 範本輔助程式 |
| `templates/` | `mail_wrapper.html.tmpl`、`line_digest.txt.tmpl`、`webhook_payload.json.tmpl` |

**events/ — 8 個 Python 檔案** — 事件目錄、事件匯流排及派發器。
定義 PCE 事件類型的標準清單（`FULL_EVENT_CATALOG`、`ACTION_EVENTS`、
`SEVERITY_FILTER_EVENTS`、`DISCOVERY_EVENTS`），並處理從 PCE 輪詢迴圈
到告警訂閱者的內部路由。

### scheduler/

**2 個 Python 檔案** — APScheduler 整合。

`jobs.py` 將定時任務（報告排程、規則排程器檢查、快取輪詢）
向 APScheduler `BackgroundScheduler` 註冊。  
`__init__.py` 初始化排程器。

當 `scheduler.persist=true` 時 APScheduler 需要 SQLAlchemy（任務儲存跨重啟持久化）。

### i18n/

**2 個 Python 檔案**（+ JSON 資料目錄）— 執行期翻譯層。
完整合約請參閱 [i18n Contract](i18n-contract.md)。

`src/i18n/__init__.py` — 翻譯查找引擎。  
`src/i18n/data/` — 語言 JSON 字典（`en.json`、`zh_TW.json`）。

GUI 在 Jinja2 範本中使用 `{{ _('key') }}`；CLI 和報告模組使用 `t('key')` 輔助函式。
所有鍵值集中於 JSON 字典中 — 範本中不使用行內字串字面值。

### api/

**4 個 Python 檔案** — PCE REST API 客戶端及領域模型。

| 檔案 | 用途 |
|---|---|
| `__init__.py` | PCE 客戶端（基於 requests，org 範圍） |
| + 最多 3 個領域模型檔案 | Workload、Label、Ruleset、Event 領域物件 |

取得標籤定義、工作負載、規則集、事件及流量流。
啟用快取時結果儲存至 `pce_cache.sqlite`，否則為單次請求分析保留於記憶體中。

內部 HTTP API 請參閱 [REST API Reference](../reference/rest-api.md)。

### settings/

**1 個 Python 檔案** — 向後相容性重匯出填充層。

`src/settings/__init__.py` 從 `src/events/catalog`、`src/cli/menus/*` 及
`src/utils` 重匯出符號，使舊版匯入器（`from src.settings import X`）
無需修改即可繼續運作。

實際設定管理位於 `src/config.py`（`ConfigManager`），
讀寫 `config/config.json` 並以 pydantic 驗證值。

---

## 資料流

```text
PCE REST API
  │
  │  1. api/ 客戶端：GET /orgs/{org_id}/events, /traffic_flows, /workloads, ...
  │     (requests + orjson；標籤查詢以 cachetools TTL 重試)
  ▼
pce_cache/ 擷取器（當 cache.enabled 時）
  │  2. pce_cache/ingestor_events.py  → 儲存事件列     → SQLite
  │     pce_cache/ingestor_traffic.py → 儲存流量列     → SQLite
  │     pce_cache/aggregator.py       → 聚合流量       → SQLite
  │     pce_cache/watermark.py        → 追蹤輪詢游標
  │     pce_cache/retention.py        → 執行 TTL（事件 90 天、原始流量 7 天、聚合 90 天）
  ▼
report/ 分析（隨需或排程）
  │  3. reader.py 從 SQLite 讀取（快取路徑）
  │     或 api/ 即時取得（無快取路徑）
  │  4. rules_engine.py 針對政策物件評估 R01–R05
  │  5. analysis/mod*.py 模組建立段落資料
  │  6. exporters/ 渲染 HTML / XLSX / CSV
  ▼
  ├── gui/routes/reports.py   → 瀏覽器下載 / 行內檢視
  ├── gui/routes/dashboard.py → 即時儀表板面板
  ├── cli/ 子指令             → stdout / 儲存檔案
  └── siem/ 派發器            → 轉發事件至 SIEM 目的地
        │
        ▼
      siem/formatters/（CEF / Syslog-CEF / Syslog-JSON / HEC / NormJSON）
        │
        ▼
      siem/transports/（Splunk HEC / syslog TCP-UDP / HTTP）
        │
        ▼
      SIEM 平台
```

**更新週期**（可在 `config.json` 中設定）：

| 資料類型 | 預設輪詢間隔 |
|---|---|
| PCE 事件 | 300 秒（5 分鐘） |
| 流量流 | 600 秒（10 分鐘） |
| SIEM 派發週期 | 5 秒 |
| 規則排程器檢查 | 300 秒 |

---

## 設定

### config/ 目錄結構

```
config/
├── config.json             # 主要執行期設定（操作員擁有）
├── config.json.example     # 範本 — 複製後編輯
├── alerts.json             # 告警規則引擎狀態（自訂規則）
├── report_config.yaml      # 報告設定檔定義
├── rule_schedules.json     # 排程規則執行定義（由 GUI 建立）
└── tls/                    # TLS 憑證 + 金鑰（由 GUI/CLI CSR 工作流程建立）
```

**config.json 頂層節：**

| 節 | 用途 |
|---|---|
| `api` | PCE 連線：`url`、`org_id`、`key`、`secret`、`verify_ssl` |
| `alerts` | 告警頻道目的地（SMTP、LINE、webhook） |
| `web_gui` | 綁定位址/埠、使用者名稱、密碼雜湊、TLS、安全設定 |
| `rule_scheduler` | 啟用旗標 + 檢查間隔 |
| `report_schedules` | 排程報告定義清單 |
| `pce_cache` | 快取啟用、`db_path`、保留天數、輪詢間隔、速率限制 |
| `siem` | 啟用、目的地清單、DLQ 深度、派發週期 |

多個 PCE 設定檔透過 GUI 設定頁面管理（與 `api` 並排儲存為具名物件）。
切換作用中設定檔會更新 `config.json`。

### data/ 目錄結構

```
data/
└── pce_cache.sqlite    # SQLite 快取資料庫（pce_cache.enabled 時建立）
```

快照和趨勢資料儲存於 SQLite 資料庫內。執行期不會將其他持久性工件寫入 `data/`。

---

## 日誌

illumio-ops 使用 **loguru**（`>=0.7,<0.8`），在 `illumio-ops.py` 或
GUI 啟動路徑中設定。

```
logs/
├── illumio_ops.log     # 主要應用程式日誌（JSON 結構化行）
├── modules/            # 每模組日誌檔案（TODO：驗證執行期是否實際填充）
└── state.json          # 最後已知操作狀態（最後輪詢時間戳記等）
```

日誌輪轉和保留透過啟動設定區塊中的 loguru `rotation` / `retention` 參數設定。
JSON 結構化行可由 filebeat 或 rsyslog 擷取 — 參見 `deploy/filebeat.illumio_ops.yml`
和 `deploy/rsyslog.illumio_ops.conf` 的參考設定。

驗證時 `logs/modules/` 目錄存在但為空；每模組檔案日誌可能依日誌等級設定而有條件啟用。
**TODO：** 驗證 `logs/modules/` 在生產環境中是否實際填充。

---

## Vendor 與靜態資產

### vendor/

```
vendor/
└── windows/
    └── nssm-2.24.zip   # Windows 服務安裝用 NSSM 二進位檔
```

無 Python 套件 vendor — 執行期相依套件透過 pip 從 `requirements.txt`
（或離線部署用 `requirements-offline.txt`）安裝。

### src/static/

```
src/static/
├── css/     # 已編譯 CSS（基於 Tailwind 的 utility classes）
├── js/      # 前端 JS（Plotly、Alpine.js、圖表初始化、隔離 modal 等）
└── fonts/   # Vendor 網頁字體（見下方附錄 A）
```

字體檔案由 Flask 靜態檔案處理器直接提供。更新字體無需建置步驟
— 替換 woff2 檔案後重啟伺服器即可。

### 附錄 A — Vendor 字體

_（從 `docs/fonts-vendoring.md` 整合，commit `1d7f3c3`。）_

| 檔案 | 授權 | 來源 | 大小 | 用途 |
|---|---|---|---|---|
| `NotoSansCJKtc-Regular.otf` | OFL | github.com/notofonts/noto-cjk | 15.7 MB | CJK 備用字體（PDF 輸出、GUI 需要 CJK 字符時） |
| `Montserrat-latin.woff2` | OFL | github.com/JulietaUla/Montserrat | 37 KB | 舊版電子郵件/報告內嵌樣式（`reporter.py`、`report_generator.py`、`report_css.py`、`chart_renderer.py`）— 已從 GUI CSS 備用鏈移除；在報告層遷移前保留 |
| `SpaceGrotesk-VF.woff2` | OFL | github.com/floriankarsten/space-grotesk | 48 KB | GUI 標題（Track A 重新設計後） |
| `Inter-VF.woff2` | OFL | @fontsource-variable/inter v5.2.8（latin 子集） | 48 KB | GUI 內文；報告內文 |
| `JetBrainsMono-VF.woff2` | OFL | @fontsource-variable/jetbrains-mono v5.2.8（latin 子集） | 40 KB | 程式碼區塊 / 表格數字（`tnum`） |

三種現用字體均為**可變字體**（帶有 `fvar` 軸的 woff2）。使用可變字體避免提供
多個靜態字重檔案，並將字體總承載保持在 280 KB 以下（三種現用可變字體共 136 KB）。

**來源說明：**
- `SpaceGrotesk-VF.woff2` — 來自 `floriankarsten/space-grotesk` 儲存庫（`wght` 軸 300–700）。
- `Inter-VF.woff2` — `@fontsource-variable/inter` 的 latin 子集可變字體；rsms/inter v4.0 完整 `InterVariable.woff2` 為 340 KB（包含所有語言），因此使用 latin 子集。
- `JetBrainsMono-VF.woff2` — `@fontsource-variable/jetbrains-mono` 的 latin 子集；JetBrains 上游發布 zip 只包含靜態 woff2 + 可變 ttf（無可變 woff2），因此使用 fontsource。

**更新字體：**
1. 從上方來源 URL 下載新的可變 woff2。
2. 驗證：`fontTools.ttLib.TTFont(...).flavor == 'woff2'` 且 `'fvar' in font`。
3. 替換 `src/static/fonts/` 中的檔案。
4. 更新本表格中的大小欄。
5. 重啟伺服器 — 無需建置步驟。

---

## 處理程序模型

illumio-ops 以**單一 Python 處理程序**運行：

```
python illumio-ops.py --monitor-gui --interval 10
  │
  ├── 主執行緒：由 cheroot WSGI 伺服器提供 Flask 應用程式
  │     cheroot 執行緒池（numthreads=10，可設定）
  │     HTTP：  cheroot 純 TCP 監聽器
  │     HTTPS： cheroot + BuiltinSSLAdapter（TLS，強化密碼清單）
  │
  ├── APScheduler BackgroundScheduler 執行緒
  │     - pce_cache 事件輪詢器（每 300 秒）
  │     - pce_cache 流量輪詢器（每 600 秒）
  │     - SIEM 派發器週期（每 5 秒）
  │     - 規則排程器檢查（每 300 秒）
  │     - 排程報告執行器
  │     任務儲存：記憶體內（預設）或 SQLAlchemy 支援（scheduler.persist=true）
  │
  └── 告警發送執行緒（每個告警事件派生，短暫存活）
```

CLI 路徑（`illumio-ops report traffic` 等）在主執行緒中執行，
不啟動網頁伺服器或 APScheduler — 為單次同步指令。

**不使用 gunicorn 或 uWSGI** — cheroot 為生產 WSGI 伺服器。
`requirements.txt` 中 `cheroot>=10.0,<12.0` 的版本鎖定為強制要求。

---

## 資料流與敏感欄位

_（稽核員 / 安全性橫切關注點 — 參見規格 §1。）_

### illumio-ops 儲存的資料

| 資料類別 | 儲存位置 | 保留期 | 含 PII？ |
|---|---|---|---|
| PCE 事件記錄 | `pce_cache.sqlite` | 90 天（預設） | 稽核事件中的使用者名稱（PCE 來源） |
| 原始流量流 | `pce_cache.sqlite` | 7 天（預設） | 來源/目的地 IP、埠、工作負載名稱 |
| 聚合流量 | `pce_cache.sqlite` | 90 天（預設） | 聚合計數，無個別連線 IP |
| PCE API 憑證 | `config/config.json` | 至輪換為止 | API 金鑰 + 密鑰（JSON 中明文） |
| GUI 工作階段憑證 | `config/config.json` | 至變更為止 | argon2 雜湊密碼 |
| 告警頻道密鑰 | `config/config.json` | 至輪換為止 | SMTP 密碼、LINE token、webhook URL |
| 報告輸出 | 檔案系統（操作員選擇的路徑） | 操作員管理 | 工作負載名稱、IP、PCE 的使用者名稱 |
| 日誌 | `logs/illumio_ops.log` | Loguru 輪轉政策 | API 回應摘要、工作負載名稱 |

### 稽核員重點

- **config.json 屬敏感資料。** 包含明文 PCE API 憑證及告警頻道密鑰。
  套用 OS 層級檔案權限（`chmod 600`）並從版本控制中排除。
- **pce_cache.sqlite** 鏡像 PCE 事件和流量資料。PCE 稽核事件中的 IP 位址和
  使用者名稱均已儲存。根據資料分類政策套用適當的檔案系統 ACL。
- **保留期預設值**（90 / 7 / 90 天）可在 `config.json` 的
  `pce_cache.*_retention_days` 下設定。
- **無對外遙測** — illumio-ops 不會回傳資料。唯一的對外連線是到設定的 PCE
  (`api.url`) 及 SIEM 目的地 (`siem.destinations`)。
- **TLS** — GUI 可使用 HTTP（開發/內部）或 HTTPS 運行。生產環境請使用
  內建 CSR 生成工作流程（`illumio-ops config tls csr`，於 commit `86d550e` 新增）
  生成已簽署憑證並匯入 cheroot 的 TLS 配接器。

---

## 部署拓樸

### Linux — systemd

參考單元：`deploy/illumio-ops.service`。

```
[Service]
Type=simple
User=illumio-ops
Group=illumio-ops
WorkingDirectory=/opt/illumio-ops
ExecStart=/opt/illumio-ops/python/bin/python3 /opt/illumio-ops/illumio-ops.py \
          --monitor-gui --interval 10
Restart=always
RestartSec=10
```

單元使用 `python/bin/python3` 的捆綁 Python 直譯器執行（離線捆綁包佈局）。
基於 virtualenv 的安裝請調整路徑。

日誌輸出傳至 systemd journal（`StandardOutput=journal`）及透過 loguru
傳至 `logs/illumio_ops.log`。

### Windows — NSSM

參考腳本：`deploy/install_service.ps1`。  
NSSM 二進位檔：`vendor/windows/nssm-2.24.zip`。

```powershell
.\install_service.ps1 -Action install
.\install_service.ps1 -Action install -NssmPath "C:\Tools\nssm.exe" -Interval 5
.\install_service.ps1 -Action uninstall
.\install_service.ps1 -Action status
```

服務名稱：`IllumioOps` / 顯示名稱：`Illumio PCE Ops`。
預設以系統帳戶執行；如有需要請設定服務帳戶。

### 日誌傳送（可選）

`deploy/` 中的參考設定：

| 檔案 | 用途 |
|---|---|
| `filebeat.illumio_ops.yml` | Filebeat 輸入設定用於日誌傳送 |
| `rsyslog.illumio_ops.conf` | rsyslog 模組設定用於 syslog 中繼 |
| `logstash.illumio_ops.conf` | Logstash 管線用於結構化日誌擷取 |
| `siem_destination.example.json` | `config.json` 的 SIEM 目的地物件範例 |

### Docker

**TODO：** 驗證時在 `deploy/` 中未找到 Docker compose 檔案或 Dockerfile。
Docker 支援（如有）尚未記錄。

### 網路埠

| 埠 | 協定 | 用途 | 可設定 |
|---|---|---|---|
| 5000（預設） | HTTP 或 HTTPS | 網頁 GUI（cheroot） | config.json 的 `web_gui.port` |
| 8443 / 443 | HTTPS | 對外連至 PCE | config.json 的 `api.url` |
| 目的地特定 | TCP/UDP | 對外 SIEM 轉發 | 每個 `siem.destinations[]` |

---

## 相關文件

- [Report Engine](report-engine.md) — 內部報告管線（下一個任務）
- [SIEM Pipeline](siem-pipeline.md) — 內部 SIEM 轉發管線
- [i18n Contract](i18n-contract.md) — 執行期翻譯模型
- [Settings & PCE Cache](../user-guide/settings-and-pce-cache.md) — 操作員層級快取設定
