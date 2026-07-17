---
title: 故障排除
audience: [operator]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - src/job_health.py
  - src/module_log.py
  - src/loguru_config.py
  - src/main.py
  - src/cli/status.py
  - src/cli/gui_cmd.py
  - src/cli/siem.py
  - src/cli/cache.py
  - src/gui/routes/dashboard.py
  - src/gui/routes/admin.py
  - src/pce_cache/web.py
  - src/api_client.py
  - src/config_models.py
  - src/reporter.py
  - src/analyzer.py
  - src/report/report_generator.py
  - src/scheduler/jobs.py
  - deploy/illumio-ops.service
  - scripts/verify_deps.py
  - scripts/setup-prod-git.sh
---

# 故障排除

本篇是**症狀導向**的排錯 runbook：每條先描述觀察到的現象，再給判讀依據，最後給實際可執行的處置指令。設定鍵的完整語意見
[configuration.md](configuration.md)；GUI 各分頁操作見 [gui-tour.md](gui-tour.md)；子系統的深入操作（cache／告警／SIEM／排程）
分別在對應篇章，本篇只挑「排錯」的切面，避免與那些篇章重複太多細節。

先備知識：正式部署的 systemd 服務單元名稱固定是 `illumio-ops`（`deploy/illumio-ops.service`）；GUI 預設埠 `5001`；正式
執行檔為 `illumio-ops` CLI wrapper 或 bundle 內建直譯器（見 [installation.md](installation.md)）。任何排錯的起手式都建議先跑：

```bash
illumio-ops status                    # PCE URL、語言、規則數、日誌最後活動時間
sudo systemctl status illumio-ops -l  # 服務是否 active (running)
```

---

## 1. 服務起不來

### 1.1 從原始碼安裝：`ModuleNotFoundError` 或啟動即退出

用對的直譯器跑相依檢查：

```bash
/opt/illumio-ops/python/bin/python3 scripts/verify_deps.py --offline-bundle   # bundle 安裝
venv/bin/python scripts/verify_deps.py                                        # 從原始碼安裝
```

Ubuntu/Debian 系統層 `pip install` 會被 PEP 668 的 `externally-managed-environment` 擋下——一律改用
venv（見 [installation.md](installation.md)「從原始碼安裝」）。

### 1.2 `TypeError: unsupported operand type(s) for |`

直譯器版本低於 3.10（`X | Y` 型別聯集語法需要 3.10+）。離線 bundle 內建 CPython 3.12，不受主機 Python 版本影響；
從原始碼安裝需重建 venv 為 3.10 以上直譯器。

### 1.3 systemd 服務啟動失敗

```bash
sudo systemctl status illumio-ops -l
sudo journalctl -u illumio-ops -n 100 --no-pager
```

常見原因，依 journalctl 輸出對應排查：

- **`config.json` 缺失或語法錯**：`python3 -m json.tool config/config.json` 驗證能否解析。
- **`logs/`／`data/` 權限不足**：服務以 `illumio-ops` 系統使用者執行（見 `deploy/illumio-ops.service` 的
  `User=`/`Group=`），這兩個目錄須可寫：`sudo chown -R illumio-ops:illumio-ops logs data`。
- **埠 `5001` 已被占用**：`ss -tlnp | grep 5001`；找到占用行程後或改用 `illumio-ops gui --port <其他埠>`
  換埠（`--monitor-gui`／`--gui` 模式無獨立換埠選項，需改 systemd 啟動旗標）。CLI 對此有明確錯誤訊息
  `Port {port} 已被占用：{exc}`（exit code 69）。

> 修正：舊文件曾提到可改 `settings.port` 設定鍵讓服務換埠，該鍵**不存在**——埠只能透過 `--port` 旗標（或
> systemd 啟動參數）控制，見 `src/cli/gui_cmd.py`。

Windows（NSSM 服務）對應檢查：`Get-Service IllumioOps` 應顯示 `Running`；停在 `Stopped`／`StartPending` 時查
Windows 事件檢視器（應用程式記錄，來源為服務行程），成因與上列 Linux 三項相同（設定檔、目錄權限、埠衝突）。

---

## 2. PCE 連不上／憑證

### 2.1 401 / 403（認證失敗）

`api.key`／`api.secret` 錯誤或金鑰已在 PCE 撤銷。於 PCE Console 重發一組 API 金鑰，更新
`config/config.json` 後重啟服務（`sudo systemctl restart illumio-ops`）。

### 2.2 Connection refused／逾時

先確認網路可達與 PCE 自身健康狀態；本專案內部也是打同一個端點做健康檢查（`ApiClient.check_health()`）：

```bash
curl -v --max-time 5 https://pce.example.com:8443/api/v2/health
```

GUI 頁首的 **PCE 狀態晶片**（綠 ok／琥珀 warn／紅 err／灰 unknown）即時反映這支健康檢查的結果，是比逐條看
日誌更快的第一手判讀入口。

### 2.3 lab PCE 的 `SSLCertVerificationError`

lab／測試 PCE 常用自簽憑證，預設 `verify_ssl: true` 會驗證失敗。**安全護欄**：`profile="production"` 時把
`verify_ssl` 設為 `false` 會在設定載入階段直接被拒絕（`ValueError: verify_ssl=False is not allowed when
profile='production'. Set profile='dev' explicitly to disable TLS verification.`）——這是刻意設計，避免正式
環境不小心關掉憑證驗證。要在 lab 跳過驗證，須先把 `profile` 明確改成 `"dev"`，才能同時設 `verify_ssl: false`；
或改把 PCE 的 CA 憑證裝入系統信任庫，兩者擇一。

---

## 3. GUI 502／埠衝突

### 3.1 埠已被占用

啟動時直接失敗（見 §1.3 第三項），不是「跑起來後 502」的情境——`ss -tlnp | grep 5001` 找出占用的行程，
或用 `illumio-ops gui --port <其他埠>` 換一個埠測試。

### 3.2 反向代理回 502 Bad Gateway

illumio-ops 自身沒有內建反向代理，502 一律代表**上游（illumio-ops 行程）沒有在代理設定的位址／埠監聽**：

1. 確認服務本身是 active：`sudo systemctl status illumio-ops`。
2. 確認代理設定指向的 host/port 與服務實際綁定的一致——服務端旗標是 `--host`／`--port`（預設
   `0.0.0.0:5001`，systemd 單元見 `deploy/illumio-ops.service`），代理端 upstream 位址須對應。
3. 若服務改綁 `127.0.0.1`（例如只讓反向代理對外，見下方安全注意），代理需部署在同一台主機才連得到。

> **安全注意**：`web_gui.allowed_ips` 比對的是**直接連線的來源 IP**（`request.remote_addr`），程式碼未套用
> `ProxyFix`、不信任 `X-Forwarded-For`。把服務放在反向代理後方時，這份白名單只會比對到代理自己的位址而失效——
> 要嘛在代理層做來源限制，要嘛讓服務只綁 `127.0.0.1`（`--host 127.0.0.1`）由代理負責存取控制。詳細鍵值見
> [configuration.md](configuration.md)「web_gui」節。

---

## 4. 報表數字異常

### 4.1 症狀：某次產出的 traffic／security 報表，總流量數字突然比平常多很多

**判讀**：不是資料異常，是查詢預設值變了——2026-07 起，未顯式指定 `policy_decisions` 篩選的流量查詢，預設含
四值 `blocked`／`potentially_blocked`／`allowed`／`unknown`（`unknown` 涵蓋 idle／快照模式 VEN 與 Flowlink
未管理流量）。舊版預設只含前三值，`unknown` 那一塊本來就被漏掉；升級後看到的數字才是完整值，變多是預期行為。
完整值域說明見 [pce-domain-notes.md](../handover/pce-domain-notes.md)「policy_decision 值域」節，報表層的對應
說明見 [reports.md](reports.md) 各報表「注意事項」小節。

**處置**：無需處置——先確認是否沿用舊版習慣手動指定只含前三值的 filter，若是，移除該手動限制即可看到完整數字。

### 4.2 症狀：走 cache（hybrid／cache-only）的報表，`unknown` 這一類始終是 0 或明顯偏少

**判讀**：該時間範圍的 cache 資料是在支援 `unknown` 值之前寫入的舊資料，不會自動回填。

**處置**：對該時間窗重跑一次 traffic backfill（backfill 不套用 `traffic_filter`，會把查詢端的新預設一次性套用回歷史窗口）：

```bash
illumio-ops cache backfill --source traffic --since <較早日期> --until <目前日期>
```

`flow_hash` 去重保證重跑安全、不會造成重複列。完整操作語意與真機案例見 [cache-maintenance.md](cache-maintenance.md)
「重跑 backfill 補齊 unknown flows」一節。

### 4.3 症狀：`--format pdf` 沒有產生任何檔案，也沒有錯誤訊息

**判讀**：`pdf` 目前是可接受的 CLI 選項值（`traffic`／`security`／`inventory`／`audit`／`ven-status`／
`policy-usage` 六個子命令的 `_REPORT_FORMATS` 都列了它），但對應 exporter（`ReportGenerator.export()`／
`VenStatusReport.export()` 等）目前**沒有實作 `pdf` 分支**——選這個格式會靜默不輸出任何檔案（exit code 仍為
0）。這是現況程式落差，不是操作錯誤。

**處置**：改用 `--format html`（各報表的 HTML 版面都內建「Print / Save as PDF」按鈕，走瀏覽器原生列印功能可
達到相同效果）或 `--format xlsx`。

### 4.4 症狀：Policy Usage 報表規則命中大量為 0

**判讀**：Policy Usage 是「哪些 Active 規則實際被流量用到」的推算型報表（逐規則對 consumers／providers／
services 各自送一次 async traffic query）——規則若還停在 PCE 的 draft（未佈署）狀態、或剛佈署不久沒有累積
流量，命中自然是 0。這與下方 Rule Hit Count 報表的 VEN 原生量測語意不同，兩者不可互相替代解讀，細節見
[reports.md](reports.md) §4／§7。

**處置**：先確認規則已在 PCE 佈署（active policy），再視情況拉長查詢時間窗重新產生。

---

## 5. Job Health 表 never-ran／overdue 判讀

`logs/job_health.json`（`src/job_health.py`）記錄每個已註冊背景 job 的 `last_run`／`last_status`／
`interval_seconds`。GUI **Integrations → Overview** 的 Job Health 表格即時讀取這份檔案並排序呈現；沒有登入
GUI 時也可以直接看原始檔：

```bash
python3 -m json.tool logs/job_health.json
```

判讀規則（詳細語意見 [gui-tour.md](gui-tour.md)「Integrations」一節；全部 14 個註冊 job id 對照表見
[automation.md](automation.md) §3）：

| 表格顯示 | 條件 | 意義 |
|---|---|---|
| `error` | `last_status == "error"` | job 實際跑過但上次失敗，看該 job 相關的 `logs/` 內容找例外訊息 |
| never ran | `last_status == "registered"` 且已超過 grace period 沒有真正跑過第一次 | job 已註冊但從未成功執行 |
| （上次狀態文字）· overdue | 有跑過紀錄，但距上次 `last_run` 已超過 grace period | job 曾正常運作，現在卡住或沒被排程觸發 |
| `ok` | 正常週期內執行成功 | 無需處置 |

grace period = `max(2 × interval_seconds, 600)` 秒（至少 10 分鐘）。

**處置**：

1. 確認常駐模式正確——**只有 `--monitor-gui`／`--monitor` 會註冊背景 job**；純 `--gui`（GUI-only）模式完全
   不啟動排程器，所有 job 永遠是 never-ran，這是設計行為不是故障，見 [cache-maintenance.md](cache-maintenance.md)
   §4.3。
2. 若正確模式下仍出現 never-ran／overdue，先確認服務行程本身存活（`sudo systemctl status illumio-ops`），
   再查對應 job 名稱的執行結果（`detail` 欄位；error 級另見 §8「日誌怎麼看」用 job id 或模組名關鍵字搜尋）。
3. 手動壞掉的 `job_health.json`（例如 interval 被改成非數字）不會讓整張表炸掉，只會跳過那一筆——若某個 job
   整條消失不顯示，檢查該筆 JSON 是否被手動改壞。

---

## 6. DB 肥大與 archive 沒跑

**症狀**：`data/pce_cache.sqlite` 持續增大不受控，或磁碟用量異常上升。

**判讀**：先查 `GET /api/cache/health`（Integrations → Cache 卡片同一份資料）的 `capacity` 欄位，重點看
`archiver_lag_seconds`：

```bash
curl -s -b <session-cookie> https://<host>:5001/api/cache/health | python3 -m json.tool
```

- `archive_enabled=true` 時，retention 的刪除步驟**只會刪「已封存」的列**——archiver 游標若卡住不動
  （`archiver_lag_seconds` 持續上升，或超過 `archive_interval_hours` 的 2 倍），DB 就會在停滯的 archiver
  後面無上限成長，這是三個容量預警數字中最急迫的一個。
- 這正是 2026-07-14 archive 事故的成因：長間隔 job（`pce_cache_archive`／`pce_cache_aggregate`／
  `pce_cache_retention`）在頻繁重啟部署下，APScheduler 預設「首跑排在啟動後一整個間隔」，24 小時級 job
  永遠等不到首跑，`data/archive` 長期是空的、DB 無上限成長也沒被清理。現行版本已修復——這些 job 一律帶
  啟動後錯開的近期首跑 kick，若懷疑回歸，先確認執行的是修復後版本（`git -C /opt/illumio-ops rev-parse HEAD`）。

**處置**：

1. 查 `pce_cache_archive` 這個 job 在 `logs/job_health.json` 的健康狀態（見 §5）——若是 never-ran／overdue，
   照 §5 的處置排查；若是 `error`，看錯誤訊息（磁碟空間不足、`data/archive` 目錄權限等）。
2. 確認常駐模式是 `--monitor-gui`（純 `--gui` 模式不會跑任何 cache 相關 job，cache 只會單調成長不會被清理，
   見 §5 第 1 點）。
3. 修改輪詢間隔／archive 開關等排程類設定後，需讓 daemon 重新載入才生效：`POST /api/daemon/restart`（僅
   `--monitor-gui` 模式可用）或重啟整個服務。

完整容量規劃基準、三個預警數字、archive 交付語意見 [cache-maintenance.md](cache-maintenance.md) §3–§4。

---

## 7. 告警沒送到

**判讀順序**：告警派送（Email／LINE／Webhook／Telegram／Teams）與 SIEM 轉送是**兩條獨立管線**，症狀處置不同——
先確認是哪一條。SIEM 目的地收不到事件見 [siem.md](siem.md)（含 `illumio-ops siem test <destination>` 診斷指令）；
本節是告警通道。

### 7.1 先驗證通道本身能不能送

Settings → Channels 頁面每張通道卡片有各自的 **Send test** 按鈕（`POST /api/actions/test-alert`，帶
`channel` 參數，會真的送出一則測試訊息），或對 `alerts.active` 全部通道各發一次（省略 `channel`）。此端點
掛 `10 per hour` 限流，避免誤觸洗版；沒有對應的 CLI 子命令，只能透過 GUI／API 觸發。若測試都送不出去，先排除
通道本身設定錯誤（收件人、webhook URL、bot token 等，鍵值見 [monitoring-alerts.md](monitoring-alerts.md)
§4.1），再往下查可靠性機制是否卡住了正常告警。

### 7.2 Dead-letter queue（DLQ）— 連續失敗會被丟棄

若**所有**啟用通道皆失敗，告警不會直接消失，而是進 `state.json` 的 `alert_dlq`，下次派送時自動合併重送，
最多 3 次（`ALERT_DLQ_MAX_ATTEMPTS`）：

```bash
grep "Alert DLQ" logs/illumio_ops.log
```

- `Alert DLQ: all channels failed, queuing for retry (attempt N)`（warning）：還在重試中，通道仍未修復。
- `Alert DLQ: dropping N alert bucket(s) after 3 failed dispatch attempts`（error）：達到上限，該批告警已被
  **永久丟棄**——這代表在修好通道之前，這幾則告警已經遺失，需要往前查是什麼觸發了它們（`traffic`／`event`／
  `metric`／`health` 四種 bucket），確認是否需要人工補查。

**處置**：修好通道設定後用 §7.1 的 test-send 確認能送，下一次 `send_alerts()` 呼叫會自動嘗試重送尚未丟棄的
DLQ 積壓。完整重試語意見 [monitoring-alerts.md](monitoring-alerts.md) §5.1。

### 7.3 Watchdog 沒有自我告警

若 PCE 已經斷線一段時間，卻完全沒收到任何告警（連告警本身失敗的訊號都沒有），檢查 watchdog 是否也在冷卻期：

```bash
grep "Watchdog" logs/illumio_ops.log
```

`Watchdog: N consecutive PCE failures — self-alert dispatched`（error）——PCE 連續失敗達 3 次即觸發，但以
60 分鐘為冷卻，長時間中斷每小時只告警一次，這是刻意設計避免洗版，不是遺漏。若連這則訊息都沒有出現過，先確認
`monitor_cycle` job 本身有沒有在跑（見 §5 Job Health）。

---

## 8. TLS 憑證到期

**症狀**：瀏覽器出現 `NET::ERR_CERT_AUTHORITY_INVALID`，或 GUI Integrations → Overview 的 TLS 憑證卡顯示
「Expiring soon」。

**判讀**：

- 自簽憑證是新安裝的預期現象，瀏覽器不信任自簽 CA 屬正常；要嘛接受例外，要嘛改用 CA 簽發憑證，要嘛部署在
  TLS 終結的反向代理後方（見 §3.2）。
- 若使用自簽憑證且 `tls.self_signed=true`、`tls.auto_renew=true`，排程器每天會跑一次 `tls_renew_check` job
  （見 `logs/job_health.json` 的 `tls_renew_check` 鍵，判讀方式見 §5）：剩餘天數低於 `tls.auto_renew_days`
  （預設 30 天）時**就地在 `config/tls/` 目錄重新簽發**憑證檔。**續期只落地憑證檔，執行中的 GUI listener 不會
  熱換憑證**——續期後會記一筆 warning 級日誌提示需要重啟才套用新憑證；GUI 卡片上的到期天數在重啟前仍會顯示
  舊憑證的剩餘天數。

**處置**：

1. 若已看到 `tls_renew_check` 續期成功的 warning 日誌，重啟服務套用新憑證即可：
   `sudo systemctl restart illumio-ops`。
2. 手動立即續期／換發：Settings → Security → Renew Certificate（GUI），或 `illumio-ops` 主選單的互動選單
   操作，完成後同樣需要重啟服務。
3. 正式環境改用 CA 簽發憑證：Settings → Security → TLS，Generate CSR → 送 CA 簽署 → Import Certificate（貼上
   含鏈的 PEM）→ 重啟服務。所有憑證變更都需要重啟才生效（無 in-process reload）。

> 修正：**沒有** `illumio-ops tls renew` 這樣的頂層 CLI 子命令（目前 13 個 subcommand 為 `cache`／
> `completion`／`config`／`gui`／`monitor`／`monitor-gui`／`report`／`rule`／`shell`／`siem`／`status`／
> `version`／`workload`）；TLS 續期只能透過 GUI、互動選單，或等每日排程 job 自動觸發。

---

## 9. 日誌怎麼看

illumio-ops 用 loguru 統一管理日誌，另外每個功能模組有獨立的 rotating log。啟動 daemon 時同時建立：

| 檔案 | 內容 | 輪替策略 |
|---|---|---|
| `logs/illumio_ops.log` | 全域主日誌（loguru，含所有模組的 log 訊息，同一份訊息也會輸出到 console／`journalctl`） | 每檔 10MB，保留 10 份，輪替時自動 gzip 並 `chmod 0640` |
| `logs/illumio_ops.json.log` | 結構化 JSON 日誌（僅 `logging.json_sink=true` 時才建立） | 同上 |
| `logs/modules/{monitor,rule_scheduler,report_scheduler,reports,actions}.log` | 各功能模組獨立日誌（`ModuleLog`，GUI「Logs」檢視窗即讀取這五個模組） | 每檔 5MB，保留 3 份輪替（單模組上限約 20MB） |
| `logs/job_health.json` | 排程 job 健康狀態（非日誌，是狀態快照，見 §5） | 無輪替，原子更新 |

**查看方式**：

```bash
# 主日誌，直接尾隨
tail -f logs/illumio_ops.log

# 依模組查（GUI 對應：頁首 Operations 下拉選單 → Logs）
tail -f logs/modules/rule_scheduler.log

# systemd 常駐時，等同於主日誌的 console 輸出（loguru 同時寫 stderr 與檔案，兩者內容一致）
sudo journalctl -u illumio-ops -n 100 --no-pager
sudo journalctl -u illumio-ops -f              # 即時尾隨

# 只看錯誤與例外
grep -n "ERROR\|Exception\|Traceback" logs/illumio_ops.log | tail -30
```

GUI 內建的 Logs 檢視窗（頁首 Operations 下拉選單）走 `GET /api/logs`（列出模組）與 `GET /api/logs/<module>`
（該模組最近 500 行的記憶體 ring buffer），不需要 SSH 到主機即可查看，但只涵蓋上表五個模組，PCE 連線層與
scheduler 本身的訊息仍要看 `logs/illumio_ops.log`。

> **敏感資訊已自動遮蔽**：日誌輸出前會套用一層 redaction filter，`api_key`／`secret`／`password`／
> `token`／`webhook_url`／`authorization` 等 key=value 樣式的值一律替換成 `[REDACTED]`；PCE href 中的資源
> UUID 也會被遮蔽（保留資源型別）。回報問題附上日誌片段前仍應人工複查一次，勿假設遮蔽必然完整。

---

## 10. 升級與回報問題

### 10.1 正式機 `git pull` 衝突

正式機曾就地修改受版控檔案時，`git pull` 會中止。一次性設定 autostash：

```bash
bash scripts/setup-prod-git.sh        # 啟用 merge.autoStash / rebase.autoStash
# 若當下已經卡住：
git stash && git pull && git stash pop
```

### 10.2 回報問題時請附上

```bash
illumio-ops --version
git -C /opt/illumio-ops rev-parse HEAD
grep -n "ERROR\|Exception\|Traceback" /opt/illumio-ops/logs/illumio_ops.log | tail -30
```

附設定檔時務必先遮蔽 `api.key`／`api.secret` 與所有密碼／token（見 §9 的自動遮蔽說明，但貼出前仍應人工複查），
切勿外洩。
