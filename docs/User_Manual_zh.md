# Illumio PCE Ops — 使用手冊

本手冊是操作面的 canonical 文件，合併原本分散在 User Manual、PCE Cache、SIEM Forwarder 與部分部署文件中的內容。架構請看 [Project_Architecture_zh.md](Project_Architecture_zh.md)，規則語意請看 [Security_Rules_Reference_zh.md](Security_Rules_Reference_zh.md)，API 範例請看 [API_Cookbook_zh.md](API_Cookbook_zh.md)。

## 1. 安裝與前置需求

### 1.1 系統需求

- Python 3.8+。
- CLI / daemon 基礎功能以標準函式庫為主。
- Web GUI 需要 Flask 相關套件。
- 報表需要 pandas、pyyaml；HTML 圖表使用 Plotly；XLSX 使用 openpyxl；PDF 使用 ReportLab。
- Cache、SIEM Preview、scheduler persistence 會用到 SQLAlchemy / APScheduler 等相依套件。

### 1.2 一般開發安裝

```bash
cp config/config.json.example config/config.json
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python illumio_ops.py
```

`config/config.json` 至少需要設定：

```json
{
  "api": {
    "url": "https://pce.example.com:8443",
    "org_id": "1",
    "key": "PCE_API_KEY",
    "secret": "PCE_API_SECRET",
    "verify_ssl": true
  }
}
```

### 1.3 離線部署

Linux 與 Windows 離線 bundle 由 `scripts/build_offline_bundle.sh` 建立，輸出到 `dist/`。部署前建議先跑 preflight：

```bash
scripts/preflight.sh
scripts/install.sh
```

Windows 使用：

```powershell
.\preflight.ps1
.\install.ps1
```

安裝腳本會保留既有 `config/config.json` 與 `config/rule_schedules.json`。升級時先停止服務，再解壓新 bundle 並執行 install 腳本。

## 2. 執行模式

### 2.1 互動式 CLI

```bash
python illumio_ops.py
```

未指定子命令時會進入 legacy interactive menu。

### 2.2 Web GUI

```bash
python illumio_ops.py --gui
python illumio_ops.py gui --port 5001
```

Web GUI 提供 Dashboard、Rules、Settings、Reports、Report Schedules、Quarantine、Rule Scheduler、Logs、PCE Cache、SIEM Preview 等功能。

### 2.3 背景監控 Daemon

```bash
python illumio_ops.py --monitor --interval 5
python illumio_ops.py monitor -i 5
```

Daemon 週期性執行事件與流量分析，依規則觸發 Email、LINE、Webhook 等告警。

### 2.4 Daemon + Web GUI

```bash
python illumio_ops.py --monitor-gui --interval 5 --port 5001
```

此模式會在背景執行監控 loop，主執行緒啟動 Web GUI。

### 2.5 Click 子命令速查

```bash
python illumio_ops.py status
python illumio_ops.py version
python illumio_ops.py report traffic --format html
python illumio_ops.py report audit --start-date 2026-04-01 --end-date 2026-04-27
python illumio_ops.py report ven-status --format xlsx
python illumio_ops.py report policy-usage --format html
python illumio_ops.py workload list --limit 50
python illumio_ops.py rule list
python illumio_ops.py cache status
python illumio_ops.py siem status
```

## 3. 設定檔

設定由 `src.config.ConfigManager` 載入，並透過 `src.config_models.ConfigSchema` 驗證。主要區塊：

| 區塊 | 用途 |
|:---|:---|
| `api` | PCE URL、org id、API key/secret、TLS 驗證 |
| `alerts` / `email` / `smtp` | 告警通道與 SMTP |
| `settings` | 語言、theme、timezone、dashboard query |
| `rules` | 事件/系統/流量/頻寬/流量量規則 |
| `report` | 報表格式、輸出目錄、保留天數、snapshot、threat intel |
| `report_schedules` | Web GUI 報表排程 |
| `pce_profiles` / `active_pce_id` | 多 PCE profile |
| `rule_scheduler` | PCE rule 啟停排程器 |
| `scheduler` | APScheduler persistence |
| `web_gui` | Web GUI 帳號、存取限制、TLS |
| `pce_cache` | SQLite cache、poll interval、retention、filter、sampling |
| `siem` | SIEM Preview destinations、DLQ、dispatch tick |

### 3.1 i18n 規則

任何 CLI、Web UI、報表、告警的使用者可見文字都要使用 i18n key，並同步新增：

- `src/i18n_en.json`
- `src/i18n_zh_TW.json`

合併前必跑：

```bash
python3 scripts/audit_i18n_usage.py
python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py
```

## 4. Web GUI 安全性

目前 Web GUI 已具備：

- Flask-Login session。
- Login rate limit。
- CSRF synchronizer token。
- IP allowlist，支援單一 IP、CIDR、IPv4-mapped IPv6 loopback。
- 可選 TLS、自簽憑證、憑證自動更新。
- Security headers 由 Flask-Talisman 設定。

### 4.1 安全設定建議

- 首次部署後立即更換預設帳密。
- 限制 `config/` 目錄讀取權限，避免設定檔被非授權使用者讀取。
- 若 Web GUI 需要開放給非本機存取，請啟用 TLS 與 IP allowlist。
- 生產環境建議放在受控網段或反向代理後方，並搭配外部存取控管與稽核。

## 5. 監控、規則與告警

### 5.1 規則類型

| 類型 | 說明 |
|:---|:---|
| Event rule | 比對 PCE event type、status、severity、nested fields，支援 immediate/count threshold 與 throttle |
| System rule | PCE health、agent missed heartbeat、offline 類系統檢查 |
| Traffic rule | 對 traffic flows 依 policy decision、port、proto、label、IP 等條件比對 |
| Bandwidth rule | 以 Mbps 或 bytes volume 追蹤高頻寬流量 |
| Volume rule | 以累積流量量觸發 |

### 5.2 告警通道

- Email：SMTP 設定於 `smtp` 與 `email`。
- LINE Messaging API：`alerts.line_channel_access_token` 與 `alerts.line_target_id`。
- Webhook：`alerts.webhook_url`。

SMTP 密碼建議透過環境變數供應，不要硬寫在 config。

### 5.3 Best Practice 規則

`ConfigManager.apply_best_practices()` 可 append missing 或 replace，會保留最多 10 份備份於 `rule_backups`。

## 6. 報表

### 6.1 報表類型

| 報表 | 資料來源 | 輸出 | 主要用途 |
|:---|:---|:---|:---|
| Traffic | PCE API、CSV、PCE Cache、hybrid | HTML/CSV/PDF/XLSX | 流量風險、Policy coverage、橫向移動、draft decision |
| Audit | PCE events 或 cache | HTML/CSV/PDF/XLSX | 系統健康、使用者活動、policy change、事件關聯 |
| VEN Status | PCE workloads | HTML/CSV/PDF/XLSX | Agent/VEN health、policy sync、enforcement mode |
| Policy Usage | PCE rulesets + traffic count 或 CSV | HTML/CSV/XLSX | 規則命中、未使用規則、deny effectiveness |

### 6.2 Traffic Report profile

- `security_risk`：偏向安全風險、勒索軟體、橫向移動、資料外洩、enforcement readiness。
- `network_inventory`：偏向流量盤點、跨 label matrix、依賴關係、資產與連線摘要。

### 6.3 報表內容層級

Report 不提供 executive / standard / full 分級；輸出一律是完整 detail 內容。

CLI 與 Web GUI 不再提供 detail level 選項。若舊 automation 仍傳入 `detail_level`，目前程式會將它視為 legacy no-op，輸出仍維持完整 detail。

### 6.4 產生報表

```bash
python illumio_ops.py report traffic --format html --profile security_risk
python illumio_ops.py report traffic --source csv --file flows.csv --format all
python illumio_ops.py report audit --start-date 2026-04-01 --end-date 2026-04-27
python illumio_ops.py report ven-status --format xlsx
python illumio_ops.py report policy-usage --format html
```

Web GUI 會將報表寫入 `report.output_dir`，並提供列表、下載、刪除與 bulk delete。

### 6.5 Report Schedule

Web GUI 可建立每日/每週/每月或 cron-like schedule，並記錄執行狀態與歷史。CLI 舊式排程由 `report_scheduler.py` 支援。

## 7. PCE Cache

PCE Cache 是 SQLite-based local cache，目標是降低 PCE 查詢成本、支援離線/半離線分析，並讓報表可以從 cache 或 API/cache hybrid path 產生。

### 7.1 啟用

```json
{
  "pce_cache": {
    "enabled": true,
    "db_path": "data/pce_cache.sqlite",
    "events_retention_days": 90,
    "traffic_raw_retention_days": 7,
    "traffic_agg_retention_days": 90
  }
}
```

### 7.2 Cache 指令

```bash
python illumio_ops.py cache status
python illumio_ops.py cache backfill --source events --since 2026-04-01
python illumio_ops.py cache backfill --source traffic --since 2026-04-01 --until 2026-04-27
python illumio_ops.py cache retention
```

### 7.3 Web API

| Endpoint | 用途 |
|:---|:---|
| `GET /api/cache/status` | 回傳 events、traffic raw、traffic agg row count |
| `POST /api/cache/backfill` | 同步 backfill events 或 traffic |
| `GET /api/cache/settings` | 讀取 cache 設定 |
| `PUT /api/cache/settings` | 驗證並儲存 cache 設定 |

### 7.4 Retention 與 sizing

- Events retention 預設 90 天。
- Raw traffic retention 預設 7 天。
- Aggregated traffic retention 預設 90 天。
- 大型 PCE 建議將 `data/` 放在可監控磁碟，並定期查 `cache status`、watermark、lag。

### 7.5 Cache miss 語意

- Full coverage：報表完全從 cache 讀。
- Partial coverage：若 cache 只覆蓋後段，前段由 API 補齊後 merge。
- Miss：直接走 PCE API。

## 8. SIEM Preview

內建 SIEM Forwarder 仍是 Preview。既有部署可維持相容使用，新生產部署應先做壓測與錯誤路徑驗證。

### 8.1 Destination

支援 transport：

- `udp`
- `tcp`
- `tls`
- `hec`

支援 format：

- `cef`
- `json`
- `syslog_cef`
- `syslog_json`

### 8.2 CLI

```bash
python illumio_ops.py siem status
python illumio_ops.py siem test <destination>
python illumio_ops.py siem dlq --dest <destination>
python illumio_ops.py siem replay --dest <destination> --limit 100
python illumio_ops.py siem purge --dest <destination> --older-than 30
```

### 8.3 Web API

| Endpoint | 用途 |
|:---|:---|
| `GET /api/siem/destinations` | 列出 destinations |
| `POST /api/siem/destinations` | 新增 destination |
| `PUT /api/siem/destinations/<name>` | 更新 destination |
| `DELETE /api/siem/destinations/<name>` | 刪除 destination |
| `POST /api/siem/destinations/<name>/test` | 發送 synthetic test event |
| `GET /api/siem/status` | per-destination pending/sent/failed/DLQ |
| `GET /api/siem/dlq` | 列出 DLQ |
| `POST /api/siem/dlq/replay` | DLQ replay |
| `POST /api/siem/dlq/purge` | DLQ purge |
| `GET /api/siem/dlq/export` | 匯出 DLQ CSV |

### 8.4 外部 collector

範例設定保留於 `deploy/`：

- `filebeat.illumio_ops.yml`
- `logstash.illumio_ops.conf`
- `rsyslog.illumio_ops.conf`
- `siem_destination.example.json`

舊英文整合文件保留於 [SIEM_Integration.md](SIEM_Integration.md)。

## 9. Rule Scheduler

Rule Scheduler 以 `config/rule_schedules.json` 儲存排程，依時間啟用/停用 PCE rulesets/rules。核心原則：

- 操作前先讀取目前 PCE draft 狀態。
- 避免意外 provision。
- Web GUI 可檢視 rulesets、搜尋 rules、建立/刪除 schedule、手動 check、查看 logs。

CLI 仍提供互動式 `rule_scheduler_cli.py`。

## 10. Quarantine 與多 PCE Profile

### 10.1 Quarantine

Web GUI 支援：

- 搜尋 workload。
- 驗證 workload href。
- 單筆或批次套用 Quarantine labels。
- 防止非 workload href 被送入 apply endpoint。

### 10.2 多 PCE Profile

`pce_profiles` 可保存多組 PCE 連線資訊，`active_pce_id` 會同步到 `api` 區塊。切換 profile 後建議重新測試 PCE 連線。

## 11. 日常維運

建議每日檢查：

```bash
python illumio_ops.py status
python illumio_ops.py cache status
python illumio_ops.py siem status
```

建議合併前檢查：

```bash
python3 scripts/audit_i18n_usage.py
python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py
```

合併前建議依變更範圍補跑對應 pytest 測試。

## 12. 疑難排解

| 症狀 | 檢查 |
|:---|:---|
| Web GUI 無法登入 | 檢查 `web_gui.username`、密碼欄位、rate limit、IP allowlist |
| CSRF 失敗 | 重新整理頁面取得新 token，確認 API helper 有帶 `X-CSRFToken` |
| 報表無資料 | 檢查 PCE API credentials、日期範圍、traffic filter、cache coverage |
| SIEM destination 失敗 | 先跑 `siem test`，再看 `/api/siem/status` 與 DLQ |
| Cache row count 不增加 | 檢查 `pce_cache.enabled`、db path 權限、poll interval、PCE API 回應 |
| i18n audit 失敗 | 補齊兩個 JSON locale，避免硬寫 UI/CLI/報表文字 |
