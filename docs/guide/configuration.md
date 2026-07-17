---
title: 設定參照
audience: [operator]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - src/config_models.py
  - src/config.py
  - config/config.json.example
  - config/report_config.yaml
  - src/cli/config.py
  - src/cli/gui_cmd.py
  - src/scheduler/__init__.py
  - src/scheduler/jobs.py
  - src/alerts/plugins.py
  - src/gui/routes/config.py
---

# 設定參照

本文件是 `config/config.json` 每個鍵的權威參照，以 `src/config_models.py`（pydantic
schema）為 ground truth——`ConfigManager.load()` 時會用這份 schema 驗證整份設定檔，
未知鍵一律拒絕（`extra="forbid"`，少數子區塊例外會在該節註明）。`config/config.json.example`
是安裝範本，內容可能落後於 schema；本文件遇到範本與 schema 不一致的地方，一律以
schema 的預設值為準，並在下方「已知落差」標註。

安裝與升級流程見 installation.md（安裝與部署）；監控規則／告警通道的規則語意見
monitoring-alerts.md（規則語意不在本文件範圍）。

## 設定檔案總表

illumio-ops 的設定分散在四個檔案，全部位於 `config/`（`.gitignore` 已排除，因為含密鑰）：

| 檔案 | 內容 | 驗證方式 |
|---|---|---|
| `config.json` | 主設定檔，本文件涵蓋的所有區塊 | `ConfigSchema`（pydantic，`extra="forbid"`） |
| `alerts.json` | 告警規則定義（event／traffic／bandwidth），原子寫入，權限 `0600` | 無獨立 pydantic schema，語意見 monitoring-alerts.md |
| `report_config.yaml` | 報表分析參數（風險埠分級、B/L 系列規則門檻、輸出設定） | 無 pydantic 驗證，純 YAML |
| `rule_schedules.json` | Rule Scheduler 的排程紀錄（依 PCE rule/ruleset href 索引），由程式維護 | 無 pydantic 驗證，一般不手動編輯 |

> **安全性提醒**：`config.json` 內含 PCE API 密鑰、SMTP 密碼、LINE/Telegram/Teams token。
> 檔案權限應維持 `0600`，切勿提交進版本控制。SMTP 密碼可改用環境變數
> `ILLUMIO_SMTP_PASSWORD` 覆寫，避免以明文存在磁碟上（`src/alerts/plugins.py`）。

### 用 CLI 操作 config.json

```bash
illumio-ops config show                       # 印出完整（已驗證）設定
illumio-ops config show --section api          # 只看單一區塊
illumio-ops config validate                    # 用 pydantic schema 驗證
illumio-ops config set api.url https://pce.example.com:8443   # 寫入單一鍵（落地磁碟）
illumio-ops config login --url ... --key ... --secret ... [--org-id ...]  # 設定 PCE 憑證（落地磁碟）
```

`config set` 與 `config login` 會驗證後直接**覆寫**磁碟上的 `config.json`（輸出時密鑰已遮蔽）。

## config.json 結構總覽

| 頂層鍵 | 對應 pydantic model | 用途一句話 |
|---|---|---|
| `api` | `ApiSettings` | 目前生效中的單一 PCE 連線資訊 |
| `pce_profiles` / `active_pce_id` | `list[PceProfile]` / `Optional[int]` | 多 PCE 設定檔清單與目前啟用的 id |
| `alerts` | `AlertsSettings` | 告警通道清單與各通道憑證 |
| `email` / `smtp` | `EmailSettings` / `SmtpSettings` | 郵件寄件人/收件人；SMTP 連線設定 |
| `settings` | `GeneralSettings` | 語言、主題、時區、健康檢查、儀表板查詢 |
| `rules` | `list[Rule]` | 見下方「rules 區塊」 |
| `report` / `report_schedules` | `ReportSettings` / `list[ReportSchedule]` | 報表產出預設值與排程清單 |
| `rule_scheduler` | `RuleSchedulerSettings` | Rule Scheduler 輪詢頻率開關 |
| `scheduler` | `SchedulerSettings` | APScheduler 執行期設定（已棄用欄位） |
| `web_gui` | `WebGuiSettings`（含 `tls`） | GUI 帳密、IP 白名單、TLS |
| `logging` | `LoggingSettings` | loguru 日誌等級與輪替 |
| `rule_backups` | `list` | 內部用：套用 best practices 時寫入的規則備份快照，不建議手動編輯 |
| `pce_cache` | `PceCacheSettings`（含 `traffic_filter`／`traffic_sampling`） | 本機 SQLite cache 與 archive |
| `siem` | `SiemForwarderSettings`（含 `destinations`） | SIEM 轉送目的地與佇列 |

**已知落差**（`config.json.example` 範本 vs. schema 預設值，以 schema 為準）：

| 鍵 | schema 預設 | 範本內容 | 說明 |
|---|---|---|---|
| `rule_scheduler.enabled` | `true` | `false` | 範本明確關閉排程；套用範本後需自行改回 `true` 才會排程執行 |
| `pce_cache.traffic_poll_interval_seconds` | `3600` | `600` | 範本示範較密集的輪詢頻率 |
| `siem.dispatch_tick_seconds` | `30` | `5` | 範本示範較密集的送出頻率 |

## api（PCE 連線）

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `url` | str | `"https://pce.example.com:8443"` | PCE base URL，只接受 `http`/`https`；驗證時自動去除結尾斜線 |
| `org_id` | str | `"1"` | PCE organization id |
| `key` | str | `""` | API key |
| `secret` | str | `""` | API secret |
| `profile` | `"production"` \| `"dev"` | `"production"` | 見下方安全護欄 |
| `verify_ssl` | bool | `true` | 是否驗證 PCE TLS 憑證 |

> **安全護欄**：`profile="production"` 時 `verify_ssl=false` 會直接拒絕載入（`ValueError`）。
> 要在 lab 環境跳過憑證驗證，須先把 `profile` 明確改成 `"dev"`。

## pce_profiles ／ active_pce_id（多 PCE）

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `pce_profiles[].id` | int（≥1） | 必填 | 設定檔內部識別碼 |
| `pce_profiles[].url` | str | 必填 | 該 PCE 的 URL |
| `pce_profiles[].org_id` | str | `"1"` | organization id |
| `pce_profiles[].key` | str | `""` | API key |
| `pce_profiles[].secret` | str | `""` | API secret |
| `pce_profiles[].name` | str | `""` | 顯示名稱 |
| `active_pce_id` | Optional[int] | `null` | 目前生效中的 profile id |

`PceProfile` 為 `extra="allow"`，只強制要求 `id`／`url`，其餘欄位形狀可能隨版本擴充。
同一時間只有一個 profile 生效，監控/報表/規則/cache 一律指向 `active_pce_id` 對應的
profile。切換方式：

- **Web GUI**：Settings → PCE，點該 profile 的 **Activate**（不是 Save）。`activate_pce_profile()`
  會把該 profile 的 `url`/`org_id`/`key`/`secret`/`verify_ssl` 複製進 `api` 區塊並立即存檔，
  同一進程下次輪詢即生效，不需重啟（`src/config.py` `activate_pce_profile`）。
- **手動編輯**：改 `active_pce_id` 後需重啟行程，`api` 區塊不會自動同步。

## alerts（告警通道）

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `active` | list[str] | `["mail"]` | 啟用中的通道清單 |
| `line_channel_access_token` | str | `""` | LINE channel access token（相容舊鍵名 `line_token`） |
| `line_target_id` | str | `""` | LINE 推播目標 id |
| `webhook_url` | str | `""` | 通用 webhook URL，僅接受 `https://` |
| `telegram_bot_token` | str | `""` | Telegram bot token |
| `telegram_chat_id` | str | `""` | Telegram chat id |
| `teams_webhook_url` | str | `""` | Teams webhook URL，僅接受 `https://` |

`webhook_url`／`teams_webhook_url` 若填非空值但不是 `https://` 開頭會驗證失敗。

## email ／ smtp

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `email.sender` | str | `"monitor@localhost"` | 寄件人地址 |
| `email.recipients` | list[str] | `["admin@example.com"]` | 收件人清單 |
| `smtp.host` | str | `"localhost"` | SMTP 主機 |
| `smtp.port` | int | `25` | SMTP 埠（1–65535） |
| `smtp.user` | str | `""` | SMTP 帳號 |
| `smtp.password` | str | `""` | SMTP 密碼；可改用環境變數 `ILLUMIO_SMTP_PASSWORD` 覆寫 |
| `smtp.enable_auth` | bool | `false` | 是否使用帳密驗證 |
| `smtp.enable_tls` | bool | `false` | 是否使用 STARTTLS |

## settings（一般設定）

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `language` | `"en"` \| `"zh_TW"` | `"en"` | 介面語言，見下方「語言」一節 |
| `theme` | `"light"` \| `"dark"` | `"light"` | GUI 主題 |
| `timezone` | str | `"local"` | 顯示用時區 |
| `enable_health_check` | bool | `true` | 是否啟用健康檢查旗標 |
| `dashboard_queries` | list[dict] | `[]` | GUI 儀表板自訂查詢；型別未經 pydantic 深層驗證（`list[dict]`），實際欄位形狀（`name`/`rank_by`/`pd`/`port`/`proto`/`src_label`/… 等）見 `config.json.example` 或 GUI 儀表板設定頁 |

## rules 區塊

`rules`（`list[Rule]`，每筆只固定 `type`／`name` 兩鍵、其餘欄位任意）在記憶體中的實際
內容是從獨立檔案 `config/alerts.json` 讀入合併（`ConfigManager._read_alerts_file`／
`_write_alerts_file`），`config.json` 磁碟上的 `rules` 陣列本身不使用；完整的規則型別、
欄位語意與最佳實務規則集見 monitoring-alerts.md。

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `type` | str | 必填 | 規則型別（`event`／`traffic`／`bandwidth`，語意見 monitoring-alerts.md） |
| `name` | str | `""` | 規則顯示名稱或 i18n key |

## report ／ report_schedules（報表預設值）

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `enabled` | bool | `false` | 是否啟用排程報表 |
| `schedule` | `"daily"`\|`"weekly"`\|`"monthly"` | `"weekly"` | 排程週期 |
| `day_of_week` | 星期字串 | `"monday"` | `schedule="weekly"` 時生效 |
| `hour` | int（0–23） | `8` | 產出時刻（小時） |
| `source` | `"api"`\|`"csv"` | `"api"` | 資料來源 |
| `format` | list[`"html"`\|`"csv"`\|`"xlsx"`\|`"all"`] | `["html"]` | 輸出格式 |
| `email_report` | bool | `false` | 產出後是否寄送 email |
| `output_dir` | str | `"reports/"` | 輸出目錄 |
| `retention_days` | int（≥1） | `30` | 產出檔保留天數 |
| `include_raw_data` | bool | `false` | 是否附原始資料工作表 |
| `max_top_n` | int（1–100） | `20` | 各排行榜表格列數上限 |
| `snapshot_retention_days` | int（1–3650） | `90` | Readiness 等快照保留天數 |
| `draft_actions_enabled` | bool | `true` | 是否允許報表觸發 draft 相關動作 |
| `api_query.start_date` | Optional[str] | `null` | 覆寫查詢起始日期 |
| `api_query.end_date` | Optional[str] | `null` | 覆寫查詢結束日期 |
| `api_query.max_results` | int（1–1,000,000） | `200000` | 單次查詢結果數上限 |

`report_schedules[]`（`extra="allow"`）：

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `id` | Optional[int] | `null` | 排程 id |
| `name` | str | `""` | 排程名稱 |
| `cron_expr` | Optional[str] | `null` | cron 表示式，例 `"0 8 * * MON-FRI"` |
| `timezone` | Optional[str] | `null` | 例 `"Asia/Taipei"`、`"UTC"`、`"UTC+8"` |

### report_config.yaml（分析參數，非 config.json）

`config/report_config.yaml` 是報表安全分析用的參數檔，**不受 pydantic schema 驗證**，
也不屬於 `config.json`；多數操作者不需要修改。內容包含勒索軟體風險埠分級
（critical/high/medium/low）、橫向移動埠清單、B/L 系列規則門檻（例如
`min_policy_coverage_pct: 30`）與輸出設定（`top_n`、`include_raw_data`、
`filename_prefix`）。門檻背後對應哪條規則、如何解讀，見 monitoring-alerts.md。

各報表本身（種類、產生方式、欄位）見 reports.md。

## rule_scheduler

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `enabled` | bool | `true` | 是否啟用 Rule Scheduler 輪詢（schema 預設 `true`；範本 `config.json.example` 明確設為 `false`，見上方已知落差） |
| `check_interval_seconds` | int（≥60） | `300` | 輪詢間隔（秒），下限 60 秒 |

Rule Scheduler 的排程建立、時窗語意與安全約束見 automation.md。

## scheduler（APScheduler 執行期，已棄用欄位）

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `persist` | bool | `false` | **已棄用**，不再生效。原為 SQLAlchemy job store 持久化開關；該實作已移除（`ConfigManager` 持有的 RLock 無法 pickle，且所有 job 皆為 interval 型、每次啟動都 `replace_existing=True` 全部重建，持久化本無收益）。設為 `true` 只會記一筆 warning，不會拒絕啟動 |
| `db_path` | str | `"config/scheduler.db"` | **已棄用**，`persist` 移除後不使用 |

## pce_cache（本機 SQLite cache）

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `enabled` | bool | `false` | 是否啟用本機 cache |
| `db_path` | str | `"data/pce_cache.sqlite"` | cache DB 路徑 |
| `events_retention_days` | int（≥1） | `90` | events 明細保留天數 |
| `traffic_raw_retention_days` | int（≥1） | `7` | traffic 明細保留天數 |
| `traffic_agg_retention_days` | int（≥1） | `90` | traffic 聚合資料保留天數 |
| `events_poll_interval_seconds` | int（≥30） | `300` | events 輪詢間隔 |
| `traffic_poll_interval_seconds` | int（≥60） | `3600` | traffic 輪詢間隔（範本示範 `600`，見上方已知落差） |
| `rate_limit_per_minute` | int（10–500） | `400` | 對 PCE 的每分鐘請求上限 |
| `async_threshold_events` | int（1–10000） | `10000` | 超過此筆數才走 async query |
| `archive_enabled` | bool | `false` | 是否啟用 archive |
| `archive_dir` | str | `"data/archive"` | archive 檔輸出目錄 |
| `archive_interval_hours` | int（≥1） | `24` | archive 執行間隔（小時） |
| `archive_gzip_after_days` | int（≥1） | `7` | 超過幾天的 archive 檔要壓縮 |
| `archive_retention_days` | int（≥0） | `0` | archive 檔保留天數，`0` 表示永久保留（不刪） |
| `archive_review_max_days` | int（≥1） | `31` | archive 查閱介面單次載入的日期範圍上限 |
| `disk_free_warn_gb` | int（≥1） | `10` | 磁碟剩餘低於此 GB 數時告警 |
| `siem_pending_warn_rows` | int（≥1000） | `50000` | SIEM 佇列積壓筆數告警門檻 |
| `cache_read_max_rows` | int（≥10000） | `500000` | cache 讀取單次視窗列數護欄 |

cache 架構、容量規劃與 archive 排程細節見 cache-maintenance.md。

### pce_cache.traffic_filter

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `actions` | list[str] | `["blocked", "potentially_blocked"]` | 要 ingest 的 policy_decision 值 |
| `workload_label_env` | list[str] | `[]` | 依 workload env label 過濾 |
| `ports` | list[int]（1–65535） | `[]` | 只 ingest 指定連接埠 |
| `protocols` | list[str] | `[]` | 只 ingest 指定通訊協定 |
| `exclude_src_ips` | list[str] | `[]` | 排除來源 IP（須為合法 IP 字串） |

### pce_cache.traffic_sampling

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `sample_ratio_allowed` | int（≥1） | `1` | allowed 流量的取樣比例（1 = 不取樣） |
| `max_rows_per_batch` | int（1–200000） | `200000` | 單批次 ingest 最大列數 |

## siem（SIEM 轉送）

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `enabled` | bool | `false` | 是否啟用 SIEM 轉送 |
| `dlq_max_per_dest` | int（≥100） | `10000` | 每個目的地 DLQ 上限筆數 |
| `dispatch_tick_seconds` | int（≥1） | `30` | 送出排程 tick 間隔（範本示範 `5`，見上方已知落差） |

`destinations[]`：

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `name` | str（1–64 字） | 必填 | 目的地名稱 |
| `enabled` | bool | `true` | 是否啟用該目的地 |
| `transport` | str | `"udp"` | `udp`／`tcp`／`tls`／`hec` |
| `format` | str | `"cef"` | `cef`／`json`／`syslog_cef`／`syslog_json` |
| `host` | str | `""` | 目的地主機 |
| `port` | int（1–65535） | `514` | 目的地埠 |
| `profile` | `"production"`\|`"dev"` | `"production"` | 同 `api.profile`，見下方安全護欄 |
| `tls_verify` | bool | `true` | 是否驗證目的地 TLS 憑證 |
| `tls_ca_bundle` | Optional[str] | `null` | 自訂 CA bundle 路徑 |
| `hec_token` | Optional[str] | `null` | Splunk HEC token（`transport="hec"` 時使用） |
| `batch_size` | int（1–10000） | `100` | 單批送出筆數 |
| `source_types` | list[str] | `["audit", "traffic"]` | 要轉送的資料型別 |
| `max_retries` | int（≥0） | `10` | 單筆最大重試次數 |
| `mask_pii` | bool | `false` | 開啟後於格式化前遮蔽 PII（管理者帳號/email、來源 IP、label/description 文字），每個目的地各自決定 |

> **安全護欄**：`profile="production"` 時 `tls_verify=false` 會拒絕載入，語意同 `api.profile`。

舊版設定的 `endpoint`（`"host:port"` 或 HEC URL 字串）會在載入時自動遷移成
`host`／`port`，不需手動轉換。DLQ 三命令與健康判讀見 siem.md。

## web_gui ／ TLS

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `username` | str | `"illumio"` | GUI 登入帳號 |
| `password` | str | `"illumio"`（首次啟動自動雜湊） | 首次啟動時若為空，會用預設密碼 `illumio` 以 Argon2id 雜湊後寫入；**不會**強制要求變更（`must_change_password` 目前固定停用，密碼在管理者手動於 Settings 更改前持續有效） |
| `secret_key` | str | `""`（自動產生） | Flask session 密鑰；長度不足 64 字元（32 bytes hex）時自動重新產生，所有現有 session 立即失效 |
| `allowed_ips` | list[str] | `[]` | GUI 存取來源 IP 白名單，空清單表示不限制 |
| `must_change_password` | bool | `false` | 強制變更密碼旗標（目前首次啟動流程不會將其設為 `true`） |
| `tls.enabled` | bool | `true` | 是否啟用 HTTPS（GUI 目前為 HTTPS-only，無 HTTP 自動轉導） |
| `tls.cert_file` | str | `""` | 自備憑證檔路徑；留空則使用 self-signed |
| `tls.key_file` | str | `""` | 自備金鑰檔路徑 |
| `tls.self_signed` | bool | `true` | 是否使用內建 self-signed 憑證 |
| `tls.auto_renew` | bool | `true` | 是否啟用每日自動續期檢查 |
| `tls.auto_renew_days` | int（≥1） | `30` | 憑證剩餘天數低於此門檻即續期 |
| `tls.min_version` | str | `"TLSv1.2"` | TLS 最低版本 |
| `tls.ciphers` | Optional[str] | `null` | 自訂 cipher suite 字串，`null` 表示使用預設組合 |
| `tls.key_algorithm` | str | `"ecdsa-p256"` | self-signed 憑證的金鑰演算法 |
| `tls.validity_days` | int（≥1） | `397` | self-signed 憑證有效期（天） |

`web_gui` 為 `extra="allow"`：除表列欄位外，`_initial_password`（首次啟動的明文密碼，
首次登入後清除，僅供輔助檢視）等運作期旗標也會透過同一份 schema 存活，不會被
驗證階段剔除。

> GUI 監聽埠**不是** `config.json` 鍵；由 CLI 選項決定，`illumio-ops gui --port`
> 預設埠為 `5001`（`src/cli/gui_cmd.py`），服務化安裝時同一預設值也會寫進
> systemd/NSSM 服務定義（見 installation.md）。

### TLS：self-signed 憑證每日續期 job

`tls.self_signed=true` 且 `tls.auto_renew=true`、`tls.enabled=true`、且未同時填
`cert_file`／`key_file`（自備憑證）時，排程器會註冊一個每日執行一次的背景 job
（`tls_renew_check`，`IntervalTrigger(hours=24)`，id `tls_renew_check`，
`src/scheduler/__init__.py` 註冊、`src/scheduler/jobs.py` `run_tls_renew_check` 實作）：

1. 讀取憑證剩餘天數，低於 `tls.auto_renew_days`（預設 30 天）就地在
   `config/tls/` 目錄重新簽發 self-signed 憑證。
2. **續期只落地憑證檔，執行中的 GUI listener 不會熱換憑證**——續期後會記一筆
   `warning` 級日誌提示「需要重啟服務才會套用新憑證」；到期天數的常態可視性由
   GUI overview 頁的 TLS 卡涵蓋。
3. 若已設定自備憑證（`cert_file`/`key_file` 皆非空）或關閉 `auto_renew`/`self_signed`，
   此 job 不會被註冊。

## logging

| 鍵 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `level` | str | `"INFO"` | loguru 日誌等級字串 |
| `json_sink` | bool | `false` | 是否額外輸出結構化 JSON 日誌 |
| `rotation` | str | `"10 MB"` | loguru 輪替門檻（可用大小或時間字串） |
| `retention` | int | `10` | 輪替檔保留數量 |

## 語言

`settings.language` 只接受 `"en"` 或 `"zh_TW"`（`Literal`，不接受其他值）。新增/調整
介面字串的流程（en/zh_TW 雙檔同步、JS 引用鍵稽核）見 development.md 的 i18n
workflow 一節。

## 下一步

- [installation.md](installation.md) — 安裝、升級與「升級後保留的檔案」清單
- monitoring-alerts.md — 監控規則、告警通道規則語意、事件規則、B/L/R 系列門檻解讀
- reports.md — 各報表種類、產生方式與欄位
- automation.md — Rule Scheduler 排程語意與 quarantine
- siem.md — SIEM 目的地設定、DLQ 三命令、健康判讀
- cache-maintenance.md — pce_cache 架構、容量規劃、archive 操作
- [development.md](../handover/development.md) — i18n workflow、開發環境、常見斷鏈坑
