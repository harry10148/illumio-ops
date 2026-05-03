# 疑難排解

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
| Troubleshooting | [Troubleshooting.md](./Troubleshooting.md) | [Troubleshooting_zh.md](./Troubleshooting_zh.md) |
<!-- END:doc-map -->

> **[English](Troubleshooting.md)** | **[繁體中文](Troubleshooting_zh.md)**

---

本頁是常見營運問題的單一彙整入口。各功能文件（User Manual、PCE Cache、SIEM Integration）仍保留各自的疑難排解片段；本頁將其整合，並補充跨功能項目。

## 1. 安裝與服務

| 症狀 | 可能原因 | 解決方案 |
|---|---|---|
| Ubuntu/Debian 出現 `externally-managed-environment` pip 錯誤 | Ubuntu 22.04+ / Debian 12+ 受 PEP 668 限制，禁止系統範圍 `pip install` | 建立 venv：`python3 -m venv venv && source venv/bin/activate && venv/bin/pip install -r requirements.txt`。每次開新終端都需重新啟用 venv。 |
| Web GUI / `--monitor` 無法啟動，出現缺少模組錯誤 | 在當前直譯器下未安裝相依套件 | **正式（離線 bundle）**：執行 `/opt/illumio-ops/python/bin/python3 /opt/illumio-ops/scripts/verify_deps.py` 找出缺少的套件，再重新執行 `sudo ./install.sh`。**開發**：`pip install -r requirements.txt`（Ubuntu 22.04+ / Debian 12+ 須改用 venv）。 |
| systemd：`illumio-ops` 服務啟動後立即退出 | `config.json` 錯誤、`data/` 或 `logs/` 路徑無寫入權限，或 PCE 憑證遺漏 | 執行 `sudo systemctl status illumio-ops -l` 與 `sudo journalctl -u illumio-ops -n 100`。對安裝根目錄執行 `illumio-ops config validate`。確認 `illumio-ops` 系統帳號擁有 `/opt/illumio-ops/{data,logs,config}`。 |
| Windows：`IllumioOps` 服務啟動後立即停止 | NSSM 找不到內附 Python、`config.json` 無效，或服務帳號對安裝目錄缺少權限 | 檢查 `C:\illumio-ops\logs\illumio_ops.log`；執行 `nssm.exe get IllumioOps Application` 確認指向內附 `python\python.exe`；以系統管理員身分重新執行 `.\install.ps1`。 |
| Windows：安裝過程顯示 `nssm.exe not found` | `deploy\nssm.exe` 被刪除或解壓不完整 | NSSM 已內含於 bundle `deploy\nssm.exe`；重新解壓 bundle ZIP，再執行 `.\install.ps1`。 |
| 升級後仍載入舊設定 | `install.sh` / `install.ps1` 刻意保留整個 `config/` 目錄 | 與新範本比對：`diff /opt/illumio-ops/config/config.json.example /opt/illumio-ops/config/config.json`，並手動合併新欄位。 |
| `--purge` 意外移除設定 | `uninstall.sh --purge` 文件記載為具破壞性，會移除 `config/` | 從備份還原。不含 `--purge` 時，預設解除安裝始終保留 `config/`。 |
| 升級後 `report_config.yaml` 被重置 | 安裝程式會替換內附的 `report_config.yaml`（可能含新分析參數） | 升級前先備份：`sudo cp config/report_config.yaml config/report_config.yaml.bak`，執行 `sudo ./install.sh`，再合併您的修改。 |

## 2. PCE 連線

| 症狀 | 可能原因 | 解決方案 |
|---|---|---|
| `verify_ssl` / SSL 驗證錯誤 | PCE 使用自簽或私有 CA 憑證 | 設定 `api.verify_ssl: false`（僅供測試環境），或將 PCE CA bundle 放於本機並將 `api.verify_ssl` 指向該 CA 檔案路徑。 |
| PCE 回傳 `401 Unauthorized` | `api.key` / `api.secret` 錯誤、API Key 已過期，或角色權限不足 | 在 PCE Console 重新產生 API Key（**User Menu → My API Keys → Add**）。最低角色：監控用 `read_only`；隔離操作用 `owner`。 |
| `Connection refused` / 連線逾時 | PCE 主機無法連線、埠號錯誤、代理伺服器或防火牆阻擋 | 確認 `api.url` 包含埠號（預設 `:8443`）；以 `curl -kv https://pce.lab.local:8443/api/v2/health` 測試;檢查對外代理 / 公司防火牆規則。 |
| 流量查詢出現 `410 Gone` | 非同步查詢結果在 PCE 端已過期 | 重新執行查詢——PCE 上的非同步流量結果存活期短，會被自動清理。 |
| PCE 回傳 `429 Too Many Requests` | 命中 PCE 500 req/min 速率限制 | 系統會自動以指數退避重試。若持續發生，將 `pce_cache.rate_limit_per_minute`（預設 400）降至 200–300，或降低報表 / 告警頻率。 |
| PCE Profile 切換無效果 | 變更後 `ApiClient` 未重新初始化 | 使用 GUI **Activate** 按鈕或 CLI Profile 切換流程——兩者皆會觸發重新初始化。手動編輯 `config.json` 而未重新載入無法生效。 |

## 3. Web GUI 登入

| 症狀 | 可能原因 | 解決方案 |
|---|---|---|
| 首次啟動後無法登入 Web GUI | 尚未讀取初始密碼 | 從 `config/config.json` 讀取 `web_gui._initial_password`，或檢視啟動時 console 橫幅 / `logs/illumio_ops.log`。預設使用者名稱為 `illumio`。 |
| 遺失密碼 / 被鎖在外 | 首次登入變更密碼後忘記 | 停止服務，於 `config/config.json` 清除 `web_gui.password`（若存在則一併清除 `web_gui._initial_password`），重新啟動——系統將產生新初始密碼並重新觸發強制變更流程。 |
| 所有端點皆回傳 `423 Locked` | 首次登入強制變更密碼流程啟用中（`web_gui.must_change_password: true`） | 登入後於 **Settings → Web GUI Security** 完成流程。在使用者設定新密碼前，其他端點均刻意鎖定。 |
| 登入頁出現 `429 Too Many Requests` | 觸發登入速率限制（每 IP 每分鐘 5 次） | 等待 60 秒，或重啟服務以清除記憶體中的限制器。持續 429 表示遭暴力破解嘗試——請檢視 `logs/illumio_ops.log`。 |
| 正確登入後仍出現 `403 Forbidden` | 來源 IP 不在 `web_gui.allowed_ips` 允許清單中 | 將用戶端 IP 或 CIDR（如 `192.168.1.50` 或 `10.0.0.0/24`）加入 `web_gui.allowed_ips`。空清單代表允許所有來源。GUI 位於代理之後時，允許清單會採用 `X-Forwarded-For`。 |
| 解除安裝後重新安裝，Web GUI 登入失敗 | 重新安裝期間保留了含舊 Argon2id `web_gui.password` 的 `config.json` | 雜湊密碼在升級間保留；以先前設定的密碼登入。若要重新觸發初始密碼流程，於 `config/config.json` 清除 `web_gui.password` 與 `web_gui._initial_password`。 |
| 無法連上 `https://<host>:5000`（TLS 交握失敗） | 用戶端 TLS 版本低於 `web_gui.tls.min_version`（預設 `TLSv1.2`），或瀏覽器拒絕自簽憑證 | 確認用戶端支援設定的 `min_version`。對自簽憑證可接受瀏覽器警告，或將自動產生於 `data/web_gui_cert.pem` 的憑證發布給用戶端。 |
| POST/PUT/DELETE 出現 CSRF token 錯誤 | 分頁過期 / 缺少 `X-CSRF-Token` 標頭 | 重新整理頁面；token 透過 `X-CSRF-Token` 回應標頭與 `<meta>` 標籤遞送，並必須隨所有狀態變更請求一起送出。 |

## 4. 報表

| 症狀 | 可能原因 | 解決方案 |
|---|---|---|
| 報表為空 | 資料尚未進入快取且 API 視窗過於狹窄 | 執行 `illumio-ops cache backfill --source events --since YYYY-MM-DD`（與 `--source traffic`），或在報表指令上拓寬 `--since` / `--until`。 |
| 報表顯示所有 VEN 均為線上 | 快取狀態過時或 PCE 回應缺少 `hours_since_last_heartbeat` | 確認您的 PCE 版本有回傳 `hours_since_last_heartbeat`；檢查 PCE API 原始回應中的 `agent.status` 欄位。 |
| Policy Usage 報表顯示 0 命中 | 僅查詢 active（已佈建）的規則 | 在 PCE Console 佈建 draft 規則；僅為 draft 的規則會被刻意排除。 |
| `mod_change_impact` 顯示 `skipped: no_previous_snapshot` | 首次報表執行，或先前快照已被保留策略清除 | 在首次報表後再產生一次。快照保留 `report.snapshot_retention_days` 天。 |
| PDF 渲染：缺少 CJK 字符 / 出現方塊 | `reportlab` 在主機上找不到 CJK 字型 | 安裝 CJK 字型（Debian/Ubuntu 為 `fonts-noto-cjk`，RHEL 為 `google-noto-cjk-fonts`）。PDF 設計上即為靜態英文摘要——若需完整本地化內容請優先使用 `--format html` / `--format xlsx`。 |
| 未寄出郵件 | SMTP 設定 `enable_auth: false` 但伺服器要求驗證，或憑證錯誤 | 切換 `smtp.enable_auth: true`，設定 `smtp.user` 並使用 `smtp.password` 或 `ILLUMIO_SMTP_PASSWORD` 環境變數。以 **CLI Menu 1. Alert Rules → 6. Send Test Alert** 驗證。 |
| `siem test` 顯示 `Destination not found` | 目的地名稱錯誤,或目的地 `enabled: false` | 確認 `siem.destinations[].name` 與 CLI 引數完全相符;確保該目的地 `enabled: true`。 |

## 5. PCE 快取

下列項目重用自 [PCE Cache § Troubleshooting](./PCE_Cache_zh.md#troubleshooting)。完整快取生命週期請參閱該頁。

| 症狀 | 可能原因 | 解決方案 |
|---|---|---|
| `Cache database not configured` | `pce_cache.enabled: false` 或 `pce_cache.db_path` 錯誤 / 無寫入權限 | 設定 `pce_cache.enabled: true`，並確認 `db_path`（預設 `data/pce_cache.sqlite`）對執行使用者可寫。 |
| 日誌中出現大量 `429` 錯誤 | PCE 速率限制命中 | 將 `pce_cache.rate_limit_per_minute`（預設 400）降至 200–300。 |
| 快取 DB 增長過快 | 對您的流量量而言 `traffic_raw_retention_days`（預設 7）過高 | 將 `traffic_raw_retention_days` 降至 3–5。彙總列（`pce_traffic_flows_agg`）仍依 `traffic_agg_retention_days` 保留。 |
| Watermark 未推進 | Events ingest 錯誤 | 在 `logs/illumio_ops.log` 搜尋 `Events ingest failed`；檢查 PCE API 連線與憑證。 |
| 出現 `Cache DB locked` 錯誤 | 多個行程同時寫入同一個 SQLite 檔 | 確保對同一 `db_path` 僅有一個 `--monitor` / `--monitor-gui` 行程在執行。 |
| 日誌中出現 `Global rate limiter timeout` | PCE 配額耗盡 | 降低 `pce_cache.rate_limit_per_minute`,並檢查是否多個用戶端共用同一把 PCE API Key。 |
| 出現快取延遲警告（`cache_lag_monitor`） | Ingestor 停滯時間超過 `3 × max(events_poll_interval, traffic_poll_interval)` 秒 | 在 `logs/illumio_ops.log` 檢視 ingestor 錯誤；檢查 PCE 連線狀態與速率限制餘裕。 |

## 6. SIEM 派送

| 症狀 | 可能原因 | 解決方案 |
|---|---|---|
| DLQ 持續增長 | 目的地無法連線,或格式不符（Splunk index、sourcetype、schema） | 以 `illumio-ops siem dlq --dest <name>` 列出死信事件。修復根本原因後執行 `illumio-ops siem replay --dest <name> --limit 1000`。 |
| Splunk HEC 回傳 `400 Bad Request` | 錯誤的 index / sourcetype / token,或 payload 與設定的 `format` 不符 | 確認 `hec_token`、Splunk 中的目的地 index、`format` 欄位（`json` 或 `cef`）。可參考 [SIEM Integration § Format Samples](./SIEM_Integration_zh.md#format-samples) 中的格式範例。 |
| TCP/TLS 連線被拒 | `endpoint`（`host:port`）錯誤、防火牆阻擋,或 syslog 伺服器未監聽 | 確認目的地設定中的 `endpoint`；以 `nc -vz <host> <port>` 測試,TLS 則使用 `openssl s_client -connect <host>:<port>`。 |
| TLS 驗證失敗 | 系統 CA 信任清單不含自訂 PKI | 將目的地的 `tls_ca_bundle` 設定為您的 CA bundle 路徑。僅在開發環境才設定 `tls_verify: false`。 |
| `siem test` 顯示 `Destination not found` | 目的地名稱錯誤或 `enabled: false` | 確認 `siem.destinations[].name` 與引數一致;確保 `enabled: true`。 |
| SIEM 轉送已啟用但無資料派送 | PCE cache 未啟用（轉送器自 `pce_cache.sqlite` 讀取）,或 `siem.enabled: false` | 先設定 `pce_cache.enabled: true`,再設定 `siem.enabled: true`。執行 `illumio-ops siem status` 檢視各目的地派送計數。 |
| 重啟後資料列卡在 `pending` 狀態 | 已知的 Preview 狀態缺口：payload 建構失敗時資料列可能持續停留於 `pending`（參見 SIEM_Integration § 狀態警告） | 在 `logs/illumio_ops.log` 檢查 formatter 錯誤；必要時手動從 `siem_dispatch` 清除卡住的列。 |

## 7. 日誌與診斷

- **日誌檔**位於安裝根目錄下的 `logs/`：
  - `logs/illumio_ops.log` — 人類可讀文字,10 MB 輪轉,保留 10 份備份。
  - `logs/illumio_ops.json.log` — 結構化 JSON sink（每行一筆紀錄）,當 `logging.json_sink: true` 時啟用。適合轉送至 Splunk / Elastic / Loki。
  - `logs/state.json` — 報表排程與規則 cooldown 的執行時狀態；請勿手動編輯。
- **啟用 DEBUG 日誌**：在 `config/config.json` 設定 `logging.level: DEBUG`,然後重啟服務。DEBUG 輸出量大——問題擷取後請改回 `INFO`。
- **檢視當前設定**：執行 `illumio-ops config show`（敏感欄位已遮罩）,或限定區段：`illumio-ops config show --section web_gui`。
- **重啟前驗證設定**：執行 `illumio-ops config validate`——非零退出代表 pydantic 驗證錯誤；訊息會指出問題欄位。升級後請與 `config/config.json.example` 比對找出新增鍵值。
- **快取診斷**：`illumio-ops cache status`（各表的列數與最後擷取時間）、`illumio-ops cache retention`（當前 TTL 策略）、`illumio-ops cache retention --run`（立即清理）。
- **SIEM 診斷**：`illumio-ops siem status`（各目的地派送計數）、`illumio-ops siem test <name>`（合成事件）、`illumio-ops siem dlq --dest <name>`（列出死信列）。
- **systemd / Windows 服務日誌**：Linux 使用 `sudo journalctl -u illumio-ops -n 200 -f`；Windows 使用事件檢視器 → 應用程式記錄（依來源 `IllumioOps` 篩選）。

## 延伸閱讀

- [使用手冊 § 3 Web GUI 安全性](./User_Manual_zh.md#3-web-gui-安全性)
- [使用手冊 § 10 疑難排解](./User_Manual_zh.md#10-疑難排解) — 本頁所整合的各功能疑難排解表格來源
- [PCE 快取 § Troubleshooting](./PCE_Cache_zh.md#troubleshooting)
- [SIEM 整合 § DLQ 操作指南](./SIEM_Integration_zh.md#dlq-操作指南)
- [安裝指南](./Installation_zh.md) — 各平台安裝、升級、解除安裝、離線 bundle
