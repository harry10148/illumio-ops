# illumio-ops

![Version](https://img.shields.io/badge/Version-v4.1.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow?style=flat-square&logo=python&logoColor=white)
![API](https://img.shields.io/badge/Illumio_API-v25.2-green?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-lightgrey?style=flat-square)

> **[English](README.md)** | **[繁體中文](README_zh.md)**

## 這是什麼

**illumio-ops** 是 **Illumio Core** 的維運輔助工具。先講一句話科普：**PCE（Policy Compute Engine）**是
Illumio 微分段方案的大腦——所有主機（PCE 稱為 **Workload**）上跑的 **VEN** agent 會把流量資料回報給
PCE，PCE 再依據你設定的 **Label**（角色、應用、環境、位置）與 **Ruleset／Policy** 計算出每台主機該放行
或阻擋哪些流量，並把決策下發回 VEN 落地執行。

illumio-ops 本身**不是** VEN、**不部署任何 agent**、也**不碰觸任何 Workload**——它是一個獨立跑在別處的
Python 程序，**只透過 PCE 對外開放的 REST API** 讀取（少數情況下寫回，如 draft policy 更新、規則排程的
enable/disable）資料，把 PCE Web Console 沒做到的維運能力補上：排程報表、對 traffic flow 跑安全規則引
擎、多通道告警、SIEM 轉送、安全的規則排程，以及 Workload 隔離。全部功能收斂在單一 Python 進程裡，對外
提供 Flask Web GUI、Click CLI 與背景排程器三種介面。

## 架構總覽

illumio-ops 以**單一 Python 進程**運行。它透過 REST API 從一個或多個 PCE 拉取資料，選擇性地快取於本地
SQLite，交給規則引擎與報表引擎評估，最後透過 Web GUI、CLI、排程報表、告警與 SIEM pipeline 呈現結果。
（完整版與模組地圖見 [docs/handover/architecture.md](docs/handover/architecture.md)。）

```text
                Illumio PCE（一或多個連線設定檔）
                REST API：workloads / labels / rulesets /
                events / traffic flows / draft policy
                          |
                          |  agentless，只走 HTTPS REST
                          v
        +--------------------------------------------+
        |  api_client.py facade ＋ api/ 領域類          |
        |  （label 解析、async job、流量查詢、原生報表）    |
        +--------------------------------------------+
             |                          |
             | 即時查詢                  | 背景輪詢（ingest jobs）
             v                          v
   +--------------------------+   +------------------------------+
   | 消費端（同進程）            |   |  pce_cache/（SQLite 鏡像）      |
   |  analyzer  監控＋告警規則   |   |  raw flows / events、聚合、      |
   |  events    事件正規化/比對  |   |  保留、封存 JSONL、容量監控        |
   |  report    報表家族        |   +------------------------------+
   +--------------------------+                |
             |                                 v enqueue
             v                          +------------------+
   +-----------------------------+      | siem/            |
   | 出口                         |      | dispatcher + DLQ |
   |  gui/（Flask）· cli/（click） |      +------------------+
   |  report_scheduler／rule_    |               |
   |  scheduler（排程觸發）        |               v
   |  reporter.py 告警派送        |        SIEM destinations
   |  （Email/LINE/Webhook/...）  |
   +-----------------------------+
```

**資料流：** `PCE REST API → pce_cache (SQLite) → analyzer／report rule engine → reports + alerts + SIEM`，
Web GUI 與 CLI 位於其上，排程器負責驅動週期性工作。

## 功能一覽

- **9 報表家族** — traffic、security & risk、audit、policy usage、VEN status、enforcement readiness、rule
  hit count、policy diff（draft vs active）、policy resolver，輸出為 HTML／CSV／XLSX。
- **B/L/R 安全規則引擎** — B 系列（ransomware／涵蓋率）與 L 系列（lateral movement／資料外洩）對 traffic
  flow 進行評估，加上 R 系列（R01–R05）draft policy 對齊檢查。
- **FilterBar v2 物件選擇器** — PCE 風格的 label／IP-list／service 篩選物件，GUI 與報表引擎共用，取代自
  由文字篩選字串。
- **5 種告警通道** — Email、LINE、Webhook、Telegram、Teams，具備每目的地 DLQ 與 watchdog。
- **SIEM 轉送** — CEF、JSON、RFC5424 syslog，以及 Splunk HEC，透過 UDP／TCP／TLS／HTTPS 傳送。
- **規則排程器** — 依時間窗 enable/disable PCE 規則，CLI／GUI 皆有明確確認關卡。
- **Workload 隔離（quarantine）** — 從 GUI 或 CLI 套用／解除隔離，並留有稽核紀錄。
- **pce_cache SQLite 鏡像** — 選用的 WAL 模式本地快取，讓報表與儀表板不必反覆查詢 PCE。
- **Job health 可觀測性** — 每個背景 job 都把 `last_run`／`last_status` 記錄到 `logs/job_health.json`，
  讓「應跑未跑」可被看見。
- **離線安裝包（offline bundle）** — 適用氣隙（air-gapped）環境的安裝路徑，隨原始碼樹一併打包已釘選版本
  的 wheel。

## 快速開始

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

進入點 `illumio-ops.py` 會將子命令分派到 **Click** 命令樹（例如 `illumio-ops report traffic --format
html`、`illumio-ops status`），同時保留 **legacy argparse** 路徑以支援傳統的 `--monitor`／`--gui`／
`--report` flag——兩種風格皆可使用。

## 文件導航

完整文件地圖見 **[docs/INDEX.md](docs/INDEX.md)**。以下依讀者角色分類：

### 操作（給維運人員）

| 文件 | 內容 |
|---|---|
| [docs/guide/installation.md](docs/guide/installation.md) | 安裝與部署（systemd／NSSM／離線安裝包） |
| [docs/guide/configuration.md](docs/guide/configuration.md) | 設定檔完整參照 |
| [docs/guide/gui-tour.md](docs/guide/gui-tour.md) | Web GUI 導覽 |
| [docs/guide/reports.md](docs/guide/reports.md) | 9 報表家族逐一說明 |
| [docs/guide/monitoring-alerts.md](docs/guide/monitoring-alerts.md) | 監控規則、告警通道、事件規則 |
| [docs/guide/automation.md](docs/guide/automation.md) | 規則排程、Workload 隔離、背景 job |
| [docs/guide/siem.md](docs/guide/siem.md) | SIEM 轉送設定與 DLQ 操作 |
| [docs/guide/cache-maintenance.md](docs/guide/cache-maintenance.md) | pce_cache 維運與容量規劃 |
| [docs/guide/troubleshooting.md](docs/guide/troubleshooting.md) | 故障排除運行手冊 |

### 接手開發（給開發者）

| 文件 | 內容 |
|---|---|
| [docs/handover/architecture.md](docs/handover/architecture.md) | 架構導覽與模組地圖 |
| [docs/handover/pce-domain-notes.md](docs/handover/pce-domain-notes.md) | PCE domain 須知（vendor 事實集） |
| [docs/handover/development.md](docs/handover/development.md) | 開發流程與慣習 |

### 參考

| 文件 | 內容 |
|---|---|
| [docs/reference/cli.md](docs/reference/cli.md) | CLI 參考手冊 |
| [docs/reference/glossary.md](docs/reference/glossary.md) | 術語表 |
| [docs/reference/rest-api.md](docs/reference/rest-api.md) | PCE REST API 使用參考 |

## 授權

以 **MIT License** 釋出——詳見 [LICENSE](LICENSE)。
