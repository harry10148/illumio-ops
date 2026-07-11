# illumio-ops

![Version](https://img.shields.io/badge/Version-v4.1.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-lightgrey?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

**illumio-ops** 是 **Illumio Core** 的 **agentless（無代理）** 監控與自動化輔助工具，**僅透過 PCE（Policy Compute Engine）REST API** 與 PCE 溝通——不部署任何 agent，也不碰觸任何 Workload。它補足 PCE Web Console 在維運上的不足：排程式的 traffic / audit / policy-usage / VEN status 報表、針對 traffic flow 的 B/L/R 安全規則引擎、多通道告警、SIEM 轉送、安全的規則排程、Workload 隔離（quarantine），以及多 PCE 管理——全部由單一 Python 程序完成，並對外提供 Flask Web GUI、Click CLI 與背景排程器。

---

## 重點功能（Highlights）

- **四種執行模式** — 背景 daemon（`--monitor`）、獨立 Web GUI（`--gui`）、monitor + GUI 合併模式（`--monitor-gui`），以及互動式 CLI 選單。
- **24 條自動化安全規則** — B 系列（ransomware／涵蓋率）、L 系列（lateral movement／資料外洩），以及 R 系列 R01–R05（Draft policy 對齊），對 PCE traffic flow 進行評估。
- **完整報表引擎** — 三種流量報表 profile（`report traffic` 純流量事實、`report security` 15 模組安全風險分析、`report inventory` 網路盤點），加上 audit、policy-usage、VEN status 與 Enforcement 就緒度（`report readiness`——哪個 App/Env 可以安全推進到下一階段 Enforcement）報表，輸出為 **HTML / CSV / XLSX**。
- **多通道告警** — Email、LINE、Webhook、Telegram 與 Teams。
- **SIEM 轉送器** — CEF、JSON、RFC5424 syslog，以及 Splunk HEC，透過 UDP / TCP / TLS / HTTPS 傳送，並具備每目的地的 dead-letter queue（DLQ）。
- **本地 SQLite 快取** — 選用的 WAL 模式 PCE event 與 traffic 鏡像，搭配 retention TTL，讓報表與儀表板不必反覆查詢 PCE。
- **強化的 Web GUI** — cheroot HTTPS server、Argon2id 密碼雜湊、CSRF/CSP/HSTS middleware、流量限制（rate limiting）與 IP allowlist。
- **完整雙語 i18n** — 英文與繁體中文對等（各約 4,043 個 key），涵蓋 CLI、Web GUI、報表與告警；並以 glossary 將 Illumio 術語（PCE、VEN、Workload、Service、Port、Policy）保留為英文。

---

## 架構總覽（Architecture Overview）

illumio-ops 以**單一 Python 程序**運行。它透過 REST API 從一個或多個 PCE 拉取資料，選擇性地快取於 SQLite，以規則與報表引擎進行評估，最後透過 Web GUI、CLI、排程報表、告警與 SIEM pipeline 呈現結果。

```text
┌───────────────────────────────────────────────────────────────────────┐
│  Illumio Core — PCE (Policy Compute Engine)                           │
│  REST API over HTTPS · workloads, labels, rulesets, events,          │
│  traffic flows, draft policy                                         │
└──────────────────────────────┬────────────────────────────────────────┘
                               │  agentless · PCE REST API only
                               │  async traffic (Explorer) queries · native filters
                               ▼
┌───────────────────────────────────────────────────────────────────────┐
│  api/ + api_client.py        PCE REST client (requests)               │
└──────────────────────────────┬────────────────────────────────────────┘
                               ▼
┌───────────────────────────────────────────────────────────────────────┐
│  pce_cache/                  SQLite (WAL) local mirror                 │
│  ingestors · aggregator · retention · reader · subscriber · backfill  │
└──────────────────────────────┬────────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────┐   ┌────────────────────────────┐
│  analyzer.py + report/ rule engine   │   │  events/ pipeline           │
│  B/L/R flow→rule matching · monitor  │   │  poll → normalize → dedup → │
│  cycle · 15 traffic modules + audit  │   │  throttle → classify        │
│  + policy-usage + VEN status         │   │  (vendor catalog) → shadow  │
│                                      │   │  → stats → runbooks         │
└──────────────────┬───────────────────┘   └─────────────┬──────────────┘
                   │                                     │
       ┌───────────┴───────────────┬─────────────────────┘
       ▼                           ▼                     ▼
┌──────────────┐  ┌────────────────────────┐  ┌───────────────────────────────┐
│ report/      │  │ reporter.py + alerts/  │  │ siem/ forwarder               │
│ exporters    │  │ Email · LINE · Webhook │  │ CEF · JSON · RFC5424 syslog · │
│ HTML·CSV·XLSX│  │ · Telegram · Teams     │  │ Splunk HEC over UDP/TCP/TLS/  │
│              │  │                        │  │ HTTPS + per-dest DLQ          │
└──────────────┘  └────────────────────────┘  └───────────────────────────────┘

   呈現層：  gui/ (Flask + cheroot HTTPS, ~88 routes)  ·  cli/ (Click + interactive menu)
   排程驅動：scheduler/ (cron jobs: scheduled reports, cache polls, rule-scheduler checks)
```

**資料流：** `PCE REST API → pce_cache (SQLite) → analyzer／report rule engine → reports + alerts + SIEM`，Web GUI 與 CLI 位於其上，排程器負責驅動週期性工作。

### 子系統（`src/`）

| 子系統 | 職責 |
|---|---|
| `api/` + `api_client.py` | PCE REST client — async traffic（Explorer）查詢、native server-side filter、label／Workload／ruleset／event 取得，以及 draft policy 的 `update_rules`。 |
| `pce_cache/` | 選用的 SQLite WAL 本地鏡像 — event 與 traffic ingestor、aggregator、retention（TTL）、reader、subscriber、backfill、watermark cursor 與 PCE rate limiter。 |
| `analyzer.py` | B/L/R flow-to-rule 比對引擎與 monitor cycle（event／traffic 分析與狀態管理）。 |
| `events/` | Event pipeline — poll → normalize → dedup → throttle → 比對 vendor event catalog 進行 classify → shadow → stats → runbooks。 |
| `report/` | 報表引擎 — 15 個 traffic 分析模組，加上 audit、policy-usage、VEN status 與 R 規則；HTML／CSV／XLSX exporter、PCE parser，以及 B/L rules engine。 |
| `reporter.py` + `alerts/` | 多通道告警派送 — Email、LINE、Webhook、Telegram、Teams plugin。 |
| `siem/` | SIEM 轉送器 — CEF／JSON／RFC5424-syslog／Splunk-HEC formatter，透過 UDP／TCP／TLS／HTTPS transport，並具備每目的地 DLQ。 |
| `gui/` | Flask Web GUI（~88 routes），分布於 `auth`／`admin`／`dashboard`／`events`／`reports`／`rules`／`rule_scheduler`／`actions`／`config` 等 blueprint，由 cheroot 以 HTTPS 提供服務。 |
| `cli/` | Click 命令樹（`monitor`、`monitor-gui`、`gui`、`report`、`rule`、`workload`、`siem`、`cache`、`config`、`status`、`version`）加上 questionary 互動式選單。 |
| `scheduler/` | Cron 式排程工作 — 排程報表、cache poll，以及 rule-scheduler 檢查。 |
| `config.py` + `settings/` | `ConfigManager`（Argon2id GUI 密碼、atomic 寫入）與互動式設定精靈。 |
| `i18n/` | Runtime 翻譯層 — 英文 + 繁體中文對等（~4,043 個 key），並保留 glossary 術語為英文。 |

更完整、逐檔的導覽現已併入**維運手冊** — **[docs/operations-manual_zh.md](docs/operations-manual_zh.md)**（操作手冊，繁體中文）。

---

## 快速開始（Quick Start）

```bash
git clone <repo-url>
cd illumio-ops
cp config/config.json.example config/config.json   # 編輯 api.url / api.org_id / api.key / api.secret
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# daemon + Web GUI 合併模式，網址 https://127.0.0.1:5001
python illumio-ops.py --monitor-gui --interval 5 --port 5001
```

**首次登入：** 帳號為 `illumio`，**首次使用時強制變更密碼**。GUI 密碼以 **Argon2id** 雜湊。

### 執行模式

| 模式 | 指令 | 說明 |
|---|---|---|
| 背景 daemon | `python illumio-ops.py --monitor --interval 5` | 無介面的 monitor cycle：輪詢 PCE、執行規則、送出告警、轉送 SIEM。 |
| 獨立 Web GUI | `python illumio-ops.py --gui --port 5001` | 只提供 Flask 儀表板。 |
| Monitor + GUI | `python illumio-ops.py --monitor-gui --interval 5 --port 5001` | 上述兩者於同一程序執行（建議用於服務部署）。 |
| 互動式 CLI 選單 | `python illumio-ops.py` | questionary 驅動的 TUI，用於設定與一次性操作。 |

進入點 `illumio-ops.py` 會將子命令分派到 **Click** 命令樹（例如 `illumio-ops report traffic`、`illumio-ops status`），同時保留 **legacy argparse** 路徑以支援傳統的 `--monitor`／`--gui`／`--report` flag——兩種風格皆可使用。

關於離線（air-gapped）安裝、systemd 服務與 Windows（NSSM）部署，請見 **[docs/getting-started.md](docs/getting-started.md)**。

---

## 專案結構（Project Structure）

```text
illumio-ops/
├── illumio-ops.py              # 進入點 — 分派至 Click 子命令或 legacy argparse 路徑
├── src/
│   ├── main.py                 # Legacy argparse 路徑（--monitor / --gui / --report）+ 互動式選單
│   ├── api_client.py           # PCE REST client（async jobs、native filter、draft-policy update_rules）
│   ├── api/                    # PCE API 輔助 — async_jobs、labels、traffic_query（Explorer）
│   ├── analyzer.py             # B/L/R flow-to-rule 比對引擎 + monitor cycle
│   ├── cli/                    # Click 命令樹 + 共用 output/exit-code 輔助 + menus/
│   ├── gui/                    # Flask Web GUI — app shell（cheroot HTTPS）+ routes/ blueprint（~88 routes）
│   ├── config.py               # ConfigManager（Argon2id GUI 密碼、atomic 寫入）
│   ├── config_models.py        # pydantic 設定模型
│   ├── reporter.py             # 多通道告警派送協調
│   ├── alerts/                 # 告警 plugin — Email、LINE、Webhook、Telegram、Teams
│   ├── events/                 # Event pipeline — catalog、normalizer、throttle、shadow、stats、runbooks
│   ├── report/                 # 報表引擎 — analysis/（15 模組）、rules/（R01–R05）、exporters/、parsers/
│   ├── report_scheduler.py     # 排程報表執行 + retention
│   ├── scheduler/              # APScheduler 式 cron 工作
│   ├── pce_cache/              # SQLite WAL 快取 + ingestors/aggregator/retention/reader/subscriber/backfill
│   ├── siem/                   # SIEM 轉送器 — formatters/（CEF/JSON/syslog）、transports/（UDP/TCP/TLS/HEC）、DLQ
│   ├── settings/               # 互動式設定精靈
│   ├── i18n/                   # i18n 引擎（glossary、strict prefix）；catalog 位於 src/i18n_en.json／src/i18n_zh_TW.json
│   ├── templates/              # Flask HTML 樣板（login、index）
│   └── static/                 # 內嵌字型、JS、CSS
├── config/                     # config.json（+ .example）、alerts.json、rule_schedules.json、tls/（secrets 已 gitignore）
├── docs/                       # 雙語文件（EN + 繁體中文）— 由 docs/INDEX.md 開始
├── deploy/                     # systemd unit + Windows NSSM 服務設定 + log-shipping 範例
├── scripts/                    # install.sh、離線 bundle 建置、preflight、版本 bump
├── tests/                      # 測試套件
└── reports/                    # 產生的報表輸出 + audit 結果
```

---

## 文件（Documentation）

所有文件皆位於 [`docs/`](docs/)。請由總覽入口開始，再深入核心手冊：

- **[docs/INDEX.md](docs/INDEX.md)** / **[docs/INDEX_zh.md](docs/INDEX_zh.md)** — 文件地圖。
- **操作手冊（Operations Manual）：** [docs/operations-manual_zh.md](docs/operations-manual_zh.md) — 安裝、部署、設定、執行與維運 illumio-ops（繁體中文）。
- **事件規則說明（Event Rules）：** [docs/event-rules_zh.md](docs/event-rules_zh.md) — 即時監控規則引擎、B/L/R 報表規則引擎，以及事件管線，逐條對照原始碼（繁體中文）。
- **快速上手：** [docs/getting-started.md](docs/getting-started.md) / [docs/getting-started_zh.md](docs/getting-started_zh.md)。
- **參考（Reference）：** [reference/cli_zh.md](docs/reference/cli_zh.md)、[reference/glossary_zh.md](docs/reference/glossary_zh.md)、[reference/rest-api_zh.md](docs/reference/rest-api_zh.md)（皆有英文對照）。
- **貢獻指引（Contributing）：** [contributing/dev-setup_zh.md](docs/contributing/dev-setup_zh.md)、[contributing/i18n-workflow_zh.md](docs/contributing/i18n-workflow_zh.md)、[contributing/release-process_zh.md](docs/contributing/release-process_zh.md)。
- **最新稽核：** [reports/audit/2026-06-26-static-findings.md](reports/audit/2026-06-26-static-findings.md)。

歷史與已被取代的文件（舊版 `user-guide/` 與 `architecture/`、UX 審查、2026-05-22 安全稽核，以及 session handoff）已自文件樹移除；仍可從 git 歷史還原。

---

## 安全規則（Security Rules）

illumio-ops 內建 **24 條自動化規則**，由報表 rule engine 對 PCE traffic flow 進行評估：

- **B 系列（B001–B009）** — ransomware 暴露面與 segmentation 涵蓋率相關發現。
- **L 系列（L001–L010）** — lateral movement 與資料外洩相關發現。
- **R 系列（R01–R05）** — Draft policy 對齊（draft-deny 偵測、override-deny、visibility-boundary breach、allowed-across-boundary、draft/reported mismatch）。

每條規則皆帶有 severity、雙語 `desc_key`／`rec_key` i18n key 與修補建議。規則目錄可於 GUI 的 **Rules** 頁瀏覽；判斷邏輯實作於 `src/report/rules_engine.py` 與 `src/report/rules/`。

> **說明：** R 系列（R01–R05）引擎**已串接** — `RulesEngine.evaluate()` 會呼叫 `_eval_draft_pd()`，只要 unified DataFrame 帶有 `draft_policy_decision` 欄位（由 `flatten_flow_record` 填入），即會執行 R01–R05。**2026-06-26 的實機 PCE 測試**證實：當 traffic 查詢以 draft 計算（`update_rules`，約 12 秒）執行時，PCE 會為每一筆 flow 回傳 `draft_policy_decision`，因此 draft 資料**確實可取得**。其啟用為**按需（on-demand）**的 draft-policy 分析，而非串進每一份報表——由快取供應的報表沒有 draft 欄位，會略過 R 規則、不必負擔約 12 秒成本。詳見 [狀態與備註](#狀態與備註status--notes)。

---

## 部署與安全注意事項（Deployment & Security Notes）

### 標準安裝路徑（`/opt/illumio-ops`）

官方支援的安裝路徑為 **`/opt/illumio-ops`**，透過 **[`scripts/install.sh`](scripts/install.sh)** 佈署，並建立一個強化的 systemd 服務：

- 建立專用、無法登入的系統帳號（`useradd --system --no-create-home --shell /sbin/nologin`）。
- 安裝至 `/opt/illumio-ops`，並註冊 `deploy/illumio-ops.service`（含 `NoNewPrivileges=true` 與 `ProtectHome=true`）。

> 請**勿**部署於 `/root/illumio-ops`——那是過時、未強化的開發用佈局。

### Reverse proxy（ProxyFix）

本服務**不會**自動設定 Flask `ProxyFix`。於 nginx／Apache／Traefik 之後部署時，**必須**在 cheroot server 啟動前套用 `ProxyFix`（僅信任一個 hop），否則 IP allowlist 只會看到 proxy 的位址，所有請求都會看似來自該位址。

### TLS／自簽憑證

GUI 可以 HTTP（開發／內網）或 HTTPS 執行。cheroot 以強化 cipher list 原生終結 TLS。請使用內建的 CSR／自簽憑證流程（GUI 設定或 `illumio-ops config`），並將 key／cert 置於 `config/tls/`。

### IP allowlist

`web_gui.allowed_ips` 可限制哪些 client 位址能存取 GUI。可搭配 `--host 127.0.0.1` 與／或 reverse proxy 形成縱深防禦。

### Secrets

`config/config.json` 以明文保存 PCE API 憑證與告警通道 secret，因此它——連同 `config/alerts.json`、`config/rule_schedules.json` 與 `config/tls/`——皆已 **gitignore**。請套用嚴格的檔案權限（例如 `chmod 600`）。illumio-ops **不進行任何對外遙測（telemetry）**：唯一的對外連線是連到設定的 PCE，以及 SIEM／告警目的地。

### Telegram alert plugin — token 經 proxy access log 洩漏

Telegram Bot API 將 bot token 嵌在 **URL path**（`https://api.telegram.org/bot<TOKEN>/sendMessage`）。在高敏感環境部署時，請禁止任何 forward proxy 或 WAF 將完整 URL path 寫入 access log、改用 NoProxy direct 連線繞過企業代理，或改用 webhook 模式（webhook URL 不含 token）。Loguru 的 token 屏蔽只能遮蔽本機 log，無法保護中介網路設備。

### Server header 指紋識別

cheroot 預設輸出 `Server: Cheroot/<version>` 響應 header，會將版本資訊暴露給指紋識別。若稽核政策要求隱藏，請在 reverse proxy 端以 `proxy_hide_header Server;`（nginx）或相應指令移除。

### 正式環境 Git 流程 — autoStash 與可重現性

`scripts/setup-prod-git.sh` 啟用 `git config merge.autoStash=true`，prod box 在 `git pull` 時可能靜默 stash 未提交的本地編輯，導致與所部署的 git tag **不是 bit-for-bit reproducible**。每次部署後請執行 `git stash list` 確認為空；若需保證可重現性，請改用 `scripts/setup.sh`。

---

## 狀態與備註（Status & Notes）

本分支已解決**全部 11 項 HIGH 嚴重度發現**，以及 **2026-06-26 稽核**（[`reports/audit/2026-06-26-static-findings.md`](reports/audit/2026-06-26-static-findings.md)）的絕大多數項目。先前草稿曾列為限制的稽核項目——報表排程器 local-timezone 當機、報表輸出 HTML 跳脫／XSS、SIEM syslog-over-TLS 自訂 CA 處理，以及 pce_cache 增量擷取邊界情況——現已**全部修復**。完整測試套件通過（**1,969 項測試**），且 2026-06-26 的實機 PCE 測試已驗證端到端行為。

目前真正的備註：

- **R 系列規則為按需啟用** — R01–R05 引擎已串接，且 PCE draft 資料確實可取得（2026-06-26 實機驗證）；它以 draft-policy 分析的方式執行，而非每份報表都跑（詳見 [安全規則](#安全規則security-rules)）。
- **無 PDF 報表輸出** — 報表僅輸出 **HTML／CSV／XLSX**；不存在 PDF exporter（`--format pdf` flag 為 legacy no-op）。
- **少量 i18n／型別待辦** — 仍有少數 low/info 嚴重度的 i18n 標籤（analyzer debug 輸出、`run_ven_summary`），以及既有的 `mypy` 型別註記待辦。
- **App 不會自動套用 ProxyFix** — 於 reverse proxy 之後部署時，維運人員須自行加上 Flask `ProxyFix`，否則 IP allowlist 只會看到 proxy 的位址。

---

## 國際化（i18n）

所有使用者可見文字皆使用 `t(key, lang=lang)`。唯一真實來源為 **`src/i18n_en.json`** 與 **`src/i18n_zh_TW.json`**（各約 4,043 個 key，且對等——每個 key 於兩檔皆存在，無 runtime 自動翻譯）。**glossary**（`src/i18n/data/glossary.json`）會將領域術語——PCE、VEN、Workload、Service、Port、Policy、Ruleset、Enforcement——在中文值中保留為英文。

新增 key 時，請**同時**加入兩個 JSON 檔，並以 `t("your_key", lang=lang)` 引用；依 [AGENTS.md](AGENTS.md) 的 guardrail，合併前請執行 `python3 scripts/audit_i18n_usage.py` 與 i18n 測試。完整工作流程請見 [docs/contributing/i18n-workflow_zh.md](docs/contributing/i18n-workflow_zh.md)。

---

## 授權（License）

以 **MIT License** 釋出——詳見 [LICENSE](LICENSE)。
