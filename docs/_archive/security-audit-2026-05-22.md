# Illumio-Ops 全面資安與穩定性稽核報告

| 欄位 | 值 |
|------|----|
| 報告日期 | 2026-05-22 |
| 程式碼版本 | local: `6b542c1` (working tree) / test-host: `db0f3ed` (172.16.15.106) |
| 稽核範圍 | `/home/harry/rd/illumio-ops/` 全部 `src/`、`config/`、`scripts/`、`deploy/`、`requirements*` |
| 部署目標環境 | 高度合規 / 稽核要求嚴格的生產網段 |
| 稽核方法 | 4 個獨立 agent 平行靜態審查 + 實機（172.16.15.106）runtime 驗證 |
| 報告分級 | Critical / High / Medium / Low / Info |

---

## 1. 執行摘要

### 1.1 整體姿態

Illumio-Ops 的 **應用層安全控制基線屬於合格水準**：Argon2id 密碼雜湊、CSRF 全域強制、Talisman security headers、`SameSite` cookie、IP allowlist、HMAC 常數時間比較、登入限流、報告路徑遍歷雙層防護、無命令注入、無不安全的反序列化函式、無自製加密。**真正的稽核風險集中在「部署與運維層」而非應用程式碼**。

### 1.2 必須修復才能通過稽核（CRITICAL × 1 + HIGH × 7；其中 2 項明示接受 / 獨立 plan）

1. **CRITICAL — systemd unit 完全無加固**：實機 `illumio-ops.service` 為裸 unit、`User=root`、`systemd-analyze security` 評分 **9.6/10 UNSAFE**。專案 repo 內 `deploy/illumio-ops.service` 範例**未被部署**。
2. **HIGH — 預設 GUI bind `0.0.0.0` + `allowed_ips=[]` 不擋（fail-open）**：**明示接受**（lab 便利優先 + 強密碼/CSRF/HSTS 等補償控制，詳見 §3.2 H-1）
3. **HIGH — `ApiClient` / `SplunkHEC` 無 `close()` + 背景 thread 每分鐘建新 client**：長期 socket/session 累積（runtime 15 分鐘觀察平穩，仍需修補）
4. **HIGH — `_rs_background_scheduler` `while True: sleep(60)` 不檢查 shutdown_event**：與 APScheduler `tick_rule_schedules` 重複執行；停機優雅退出能力受損
5. **HIGH — 全專案 naive `datetime.now()`**：scheduler / rule_id / log timestamp 混用；DST 切換可能跳過或重複觸發（**獨立 plan** `docs/superpowers/plans/2026-05-22-datetime-tz-aware.md`）
6. **HIGH — LINE alert plugin `urllib.request.urlopen()` 無 `timeout=`**：對方失聯時 alert thread 永久阻塞，可被觸發為 DoS
7. **HIGH — `api.verify_ssl = False` 在實機生產 config 中**：PCE TLS 驗證關閉，無 production 護欄
8. **HIGH — `web_gui.secret_key` 實機長度 11 bytes**：Flask session 簽章金鑰過短（標準 ≥ 32 bytes）

### 1.3 強烈建議修復（MEDIUM 共 14 項）

詳見 §3.3 — 涵蓋 state.json 寫入 fsync、ScheduleDB 毀損處理、SMTP/LINE 重複 timeout、CSP `unsafe-inline`、`/api/security` 不要舊密碼、Filebeat/Logstash 範例無 TLS、缺 LICENSE/SBOM、`requirements.txt` 與 `lock` 不一致、CI 不 `--require-hashes`。

### 1.4 通過稽核需完成的最短行動清單

依優先順序：
1. 重新部署 `deploy/illumio-ops.service`（已存在於 repo）並補上進階 hardening directive、改用 system user 而非 root。
2. 為 `requests.Session`、SIEM transport 加 `close()`，並讓 `_rs_background_scheduler` 接 `shutdown_event`。
3. LINE plugin 補 `timeout=10`（已是 Telegram/Webhook 標準）。
4. `web_gui.secret_key` 改成 `secrets.token_hex(32)` 並於現場 rotate 一次。
5. 部署文件強制 production profile 拒絕 `verify_ssl=False`。
6. naive datetime → `datetime.now(timezone.utc)` 全域改造（影響面大，獨立 plan）。

**注意：H-1（GUI bind + allowlist）與 M-8（CSP `unsafe-inline`）為明示接受項目**，補償控制清單詳見 §3.2 H-1 / §3.3 M-8。未來導入更嚴格的 production 環境時需重新評估。

---

## 2. 稽核方法

### 2.1 靜態審查

4 個獨立 agent 平行執行，每個 agent 不知道其他 agent 的發現：

| Agent | 範圍 | 完成時間 |
|------|------|---------|
| Security | secrets / TLS / 注入 / 權限 / crypto | 884s, 33 tool calls |
| Stability | 資源洩漏 / threading / state files / error handling / 時區 | 744s, 12 tool calls |
| GUI/Web | authn / authz / CSRF / XSS / headers / 路由清單 | 1032s, 40 tool calls |
| Supply-chain | dependencies / vendor / Docker / systemd / SBOM | 745s, 30 tool calls |

### 2.2 實機驗證

於 `root@172.16.15.106`（Ubuntu 24.04.3 LTS，kernel 6.8.0-110，uptime 22 天）執行：

- **Phase A**（read-only baseline）：systemd security 分析、檔案權限、套件版本來源、log 機敏掃描、TLS cert 與 ciphers、HTTP security headers、FD / thread baseline、config.json 機敏欄位 masked 檢視
- **Phase B**（主動安全測試）：匿名 API probe（9 個 endpoint）、預設帳密登入測試、登入限流測試（10 次）、cookie flag 檢視、CSRF 拒絕測試、`/api/security` 不帶 old_password 測試、`allowed_ips=[]` 行為驗證
- **Phase C**（故障注入）：FD/socket/RSS/threads 15 分鐘趨勢、SIGTERM 計時、`kill -9` 復原驗證
- **Phase D**：以程式碼證據取代 runtime — `src/alerts/plugins.py:88` 缺 `timeout=` 明確可見

---

## 3. 發現分項

### 3.1 CRITICAL

#### C-1. systemd unit 完全無加固，以 root 執行
- **位置**：`/etc/systemd/system/illumio-ops.service`（測試機）
- **證據（實機）**：
  ```
  [Service]
  Type=simple
  User=root
  WorkingDirectory=/root/illumio-ops
  ExecStart=/root/illumio-ops/venv/bin/python illumio-ops.py --monitor-gui --interval 5
  ```
  `systemd-analyze security illumio-ops.service` 評分 **9.6 / 10 UNSAFE**。零 `PrivateTmp`、零 `ProtectSystem`、零 `Capability` 限制、零 `SystemCallFilter`、零 `IPAddressDeny`、零 `RestrictAddressFamilies`、零 `NoNewPrivileges`、零 `RestrictNamespaces`。
- **對比 repo**：`deploy/illumio-ops.service` 範例 **有** `NoNewPrivileges`、`ProtectSystem=strict`、`ProtectHome=true`、`PrivateTmp=true`、`ReadWritePaths=/opt/illumio-ops` — 但**未被實際部署**到測試機。
- **風險**：以 root 跑帶 GUI 服務 + 零加固，任何 RCE / 路徑遍歷 / 不安全反序列化漏洞都直通 root；任何稽核掃描器（Lynis、OpenSCAP、CIS-CAT）必報。
- **修復**：
  1. `useradd --system --no-create-home --shell /sbin/nologin illumio-ops`
  2. 用 repo 的 `deploy/illumio-ops.service`（已存在）取代裸 unit
  3. 加上 §3.4 L-9 列出的進階 directive
  4. `systemctl daemon-reload && systemctl restart illumio-ops`
  5. 確認 `systemd-analyze security` 評分 ≤ 3.0

### 3.2 HIGH

#### H-1. GUI 預設 bind `0.0.0.0` + `allowed_ips=[]` 為 allow-all
- **位置**：`src/gui/__init__.py:553`（`def launch_gui(cm, host='0.0.0.0', ...)`）+ `config/config.json` 實機 `web_gui.allowed_ips = []`
- **實測證據**：
  ```
  $ ss -tlnp | grep 5001
  LISTEN 0  5  0.0.0.0:5001  0.0.0.0:*
  $ curl -k https://172.16.15.106:5001/login  # from 192.168.20.x (off-subnet)
  -> 200
  ```
- **狀態：明示接受（2026-05-22 由專案 owner 決定）**
- **理由**：lab / dev 部署需要從多 IP 存取 GUI；強制 bind 127.0.0.1 + fail-closed allowlist 會破壞日常運維便利性。風險評估為「可接受」基於下列補償控制：
  - 強制 HTTPS（HSTS + 證書）
  - Argon2id 密碼雜湊 + `hmac.compare_digest` 常數時間比較
  - 登入限流 5/min（暴力破解保護）
  - CSRF 全域 + Talisman security headers
  - IP allowlist 「若設」會啟用 TCP RST drop（不洩 banner）
  - 預設帳號 `illumio/illumio` 在實機已被變更為強密碼
- **稽核員提示**：未來導入 production 環境（金融 / 國防）時應重新評估此項；可參考已撰寫但未執行的修補方向：(a) `launch_gui` 預設 `host='127.0.0.1'`；(b) `_check_ip_allowed([], ...)` 改 fail-closed；(c) profile=production 強制非空 allowlist

#### H-2. ApiClient / SplunkHEC / Syslog Transport 無 `close()`，背景 thread 每分鐘建新 client
- **位置**：
  - `src/api_client.py:96-160`（`__init__` 建 `requests.Session()` + HTTPAdapter pool 10/20，無 `close` / `__exit__` / `__del__`）
  - `src/siem/transports/splunk_hec.py:14-40`（`_session = _build_session()`，無 `close()`）
  - `src/scheduler/jobs.py:13-45`（`run_monitor_cycle` 每次 `ApiClient(cm)`）
  - `src/gui/__init__.py:128`（`_ApiClient(cm)` 每分鐘）
- **風險**：requests.Session 在 GC 才釋放；長時間運行下 connection pool 滿 + GC 延後 → file descriptor 累積；若 SIEM destination 在 GUI 被 reload，舊 transport socket 完全不釋放。
- **實機驗證**：Phase C FD 趨勢（見 §4）
- **修復**：
  1. `ApiClient` 加 `close()` 釋放 `_session.close()`，並實作 `__enter__`/`__exit__`
  2. job callable 在 finally 釋放
  3. SIEM forwarder reload 時呼叫舊 transport `close()`
  4. 或改成 module-level singleton，lifecycle 跟 daemon 一致

#### H-3. `_rs_background_scheduler` `while True: sleep(60)` 不檢查 shutdown_event
- **位置**：`src/gui/__init__.py:115-138`
- **問題**：daemon thread，每 60s 一次 tick；沒有 break / shutdown_event.wait()；**同時**與 APScheduler 的 `tick_rule_schedules` job 平行跑（兩條路徑都 `engine.check()` rule_schedules.json，可能競爭寫入）
- **風險**：SIGTERM 抵達時 cheroot stop 仍可能在中途，daemon thread 永遠不檢查停機訊號，僅靠 `daemon=True` 隨 process 死亡 — 若 in-flight 寫 state.json 可能留下 `.tmp` 或 `.lock` 殘檔。
- **實機驗證**：Phase C SIGTERM 計時（見 §4）
- **修復**：
  1. 改為 `_shutdown_event.wait(60)`，能在 0~60s 內優雅退出
  2. 與 APScheduler `tick_rule_schedules` 二擇一執行，避免重複 + 競爭
  3. `cli/_runtime.py` 的 `_gui_stopper` 後加 `t_daemon.join(timeout=10)`

#### H-4. naive `datetime.now()` 撒在 scheduler / rule_id / log / report
- **位置**：
  - `src/report_scheduler.py:36` — `now_local()` fallback 為 naive
  - `src/rule_scheduler.py:19,26` — naive
  - `src/gui/__init__.py:109`、`src/module_log.py:72` — log timestamp naive
  - `src/analyzer.py:502` — 報告 `time` 欄位 naive
  - `src/gui/routes/rules.py:88,118,163,208`、CLI menus — `int(datetime.datetime.now().timestamp())` 當 rule id 用
  - `src/report_scheduler.py:202+` — `should_run` 內 `now.replace(tzinfo=tz_obj)` 把可能是 naive 的 `now` 強加 tzinfo
- **風險**：
  - DST 切換當天，scheduler 可能跳過或重複觸發
  - rule_id 跨 DST 可能碰撞或回退
  - 跨機器 / 跨時區除錯困難
- **修復**：codebase-wide `datetime.now()` → `datetime.now(timezone.utc)`，UI 顯示時再轉 local；rule_id 改 UUID 或 monotonic counter。**獨立 plan，影響面大。**

#### H-5. LINE alert plugin `urlopen()` 無 `timeout=`
- **位置**：`src/alerts/plugins.py:88` — `with urllib.request.urlopen(req) as response:`
- **對比**：同檔 line 117（Telegram）、line 162（webhook）都有 `timeout=10`
- **風險**：`api.line.me` 失聯（網路黑洞 / DNS 故障 / 防火牆 SYN drop）時，整個 alert dispatcher thread 永久阻塞。任何能觸發告警的事件 → 部分 DoS。
- **實機驗證**：以程式碼證據為準（差異明顯，靜態 + 動態都會發現）
- **修復**：加 `timeout=10`，並對 alert channel 加 cooldown（連續失敗暫時 disable，避免每 tick 都打）。

#### H-6. `api.verify_ssl = False` 在實機 production config 中
- **位置**：實機 `/root/illumio-ops/config/config.json` 顯示 `api.verify_ssl = False`
- **程式碼路徑**：`src/api_client.py:127-132` — `verify_ssl=False` → `urllib3.disable_warnings(InsecureRequestWarning)`，僅 logger 警告一次
- **風險**：PCE API TLS 連線無憑證驗證 — 任何 MITM 可竄改流量、注入假 workload 資訊。lab 環境可接受，**production 不可接受**。
- **修復**：
  1. `config_models` 加 production profile validator，強制 `verify_ssl=True`
  2. 提供 `--allow-insecure-tls` CLI flag，僅在明示時允許關閉
  3. README 加部署 checklist

#### H-7. `web_gui.secret_key` 實機長度 11 bytes
- **位置**：實機 `/root/illumio-ops/config/config.json` → `web_gui.secret_key = <set, len=11>`
- **預期**：`secrets.token_hex(32)` 產生 64 chars（256-bit），程式碼 `src/gui/__init__.py:194` 確實使用此 fallback
- **問題**：實機 secret_key 是手動短設，未經 fallback
- **風險**：11 chars 的 Flask session secret 易被暴力枚舉，可偽造 session cookie 繞過認證
- **修復**：
  1. 啟動時驗證 `len(secret_key) >= 32`，否則強制 regenerate
  2. 現場立即 rotate：`python -c "import secrets; print(secrets.token_hex(32))"` 寫入 config.json
  3. 變更後所有現有 session 失效（這是預期行為）

### 3.3 MEDIUM

#### M-1. `/api/security` 變更密碼不需 `old_password`（刻意設計）
- **位置**：`src/gui/routes/config.py:51-86`，line 59-62 明確註解此為設計選擇
- **風險**：XSS / session 劫持 / 短暫桌面接管 → 永久帳號接管，受害者無法經 web 找回（須走 CLI `python -m src.cli set-password`）
- **可被合理化**：CLI 恢復路徑存在；CSRF + Argon2 + session_protection=strong 已提供深度防禦
- **稽核者立場**：NIST 800-53 IA-5、PCI-DSS 8.3 一般要求變更敏感認證須重新驗證
- **修復**：
  1. 加 `old_password` 必填驗證（`must_change_password=True` 例外）
  2. 提供 `--allow-no-old-password` CLI / config flag 供緊急情境
  3. 最低密碼長度 8 → 12（line 79）

#### M-2. `state_store.update_state_file` 寫 tmp 後沒 `fsync()`
- **位置**：`src/state_store.py:60-78` — `os.fdopen(fd, "w") ... os.replace(tmp_path, state_file)` **沒有 `f.flush(); os.fsync(fd)`**
- **風險**：系統電源異常時，可能 replace 已落盤但內容仍在 page cache → state.json 變 0 bytes 或 truncated
- **修復**：
  ```python
  with os.fdopen(fd, "w") as f:
      json.dump(data, f, ...)
      f.flush()
      os.fsync(f.fileno())
  os.replace(tmp_path, state_file)
  # optional: fsync parent directory for metadata
  dirfd = os.open(os.path.dirname(state_file), os.O_RDONLY)
  os.fsync(dirfd)
  os.close(dirfd)
  ```

#### M-3. `ScheduleDB.load` 對毀損檔案直接清空成 `{}`
- **位置**：`src/rule_scheduler.py:51-58` — `except Exception: self.db = {}`
- **風險**：靜默吞錯誤；schedule 設定在下次 save 時被空字典覆寫；**使用者所有規則消失**。
- **修復**：load 失敗時 rename 成 `.corrupt.<timestamp>` + `logger.error()`，**拒絕啟動**而非清空。

#### M-4. `ScheduleDB.save` fallback 路徑非 atomic
- **位置**：`src/rule_scheduler.py:60-78` — atomic 失敗的 fallback 直接 `open('w')`
- **風險**：遇到 EINTR / process 死掉會 truncate schedule DB
- **修復**：移除 fallback，atomic 失敗直接 raise；或先寫 `.bak` 不覆蓋原檔

#### M-5. `/api/actions/*` 重型端點無細粒度限流
- **位置**：`src/gui/routes/actions.py:300,319,365`、`src/gui/routes/dashboard.py:288`、`src/gui/routes/reports.py:324,372,515`
- **風險**：已登入攻擊者可耗盡 PCE 連線額度 / cheroot thread pool / 磁碟（報告檔案）
- **修復**：補 `@limiter.limit("10 per hour")` 或 `"5 per minute"`，類似 `/api/reports/generate` 的 `30/hour`

#### M-6. TLS `verify=False` 可被關閉但無 production 護欄（PCE / Syslog / Splunk / Webhook）
- **位置**：
  - `src/api_client.py:127-132` — PCE
  - `src/siem/transports/syslog_tls.py:31-34` — syslog TLS
  - `src/siem/transports/splunk_hec.py:21,49` — Splunk HEC
- **風險**：管理員可意外或被社工關閉 TLS 驗證 → SIEM 出站可被 MITM
- **修復**：config_models 加 production profile validator + CLI flag 才能解除

#### M-7. Webhook URL 不擋 `http://` scheme（GUI 寫入時）
- **位置**：`src/config_models.py:59` `webhook_url: str = ""` 無 validator
- **對比**：`src/gui/routes/config.py:148-154` 有 `api.url` 的 https warning，但 webhook 沒有
- **修復**：`WebhookConfig` 加 `@validator` 強制 `https://`

#### M-8. CSP 啟用 `'unsafe-inline'`
- **位置**：`src/gui/__init__.py:266-274`（程式碼註解標明為知情接受，等 data-action 改造完才能拿掉）
- **實測 HTTP header**：`Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; ...`
- **狀態：明示接受（2026-05-22 由專案 owner 決定）**
- **理由**：40+ 處動態 `onclick=` 改成 `data-action` event delegation 成本過高，回歸測試覆蓋每個 UI 按鈕；屬 securityheaders.com / Mozilla Observatory 扣分項而非實質漏洞。風險評估為「可接受」基於下列補償控制：
  - CSRF 全域生效（state-changing 端點皆需 token，且每次失敗 token 旋轉）
  - `escapeHtml` JS helper 套用於所有動態渲染（`src/static/js/utils.js:63`、`src/static/js/integrations.js:7`）
  - Argon2id 密碼雜湊 + `session_protection='strong'`（IP/UA 變動即 invalidate）
  - 無 `Markup(`、無 `render_template_string` 用 user input、無 unescape sinks
- **稽核員提示**：CSP nonce-based mode 已在程式碼中存在（`csp_nonce()` helper），等 `unsafe-inline` 拿掉即可生效。未來若要通過 Mozilla Observatory A+ / OWASP ZAP 全綠，需啟動 data-action 改造（預估 5-7 工作日含完整 UI 回歸測試）

#### M-9. SMTP 例外路徑無 `quit()`；LINE/SMTP plugin 無 timeout
- **位置**：`src/reporter.py:1754-1769`、`src/alerts/plugins.py`（MailAlertPlugin）
- **風險**：TLS 失敗等例外時 SMTP socket 留給 GC；alert 流程例外失敗時可能阻塞 thread
- **修復**：`with smtplib.SMTP(host, port, timeout=30) as s:` 取代 try/except + 補 timeout

#### M-10. `flask_limiter` 使用 in-memory storage
- **位置**：`src/gui/__init__.py:233` — `storage_uri="memory://"`
- **風險**：process restart 立即重置；不支援多 worker / HA
- **修復**：改 `redis://` 或 `file:///`

#### M-11. Filebeat / Logstash / rsyslog 範例**預設無 TLS** + `password: changeme`
- **位置**：
  - `deploy/filebeat.illumio_ops.yml:21` — `hosts: ["elastic.example.com:9200"]` 無 `ssl.enabled`
  - `deploy/logstash.illumio_ops.conf:36` — 同上
  - `deploy/rsyslog.illumio_ops.conf:18-23` — plain TCP omfwd 514
  - `deploy/filebeat.illumio_ops.yml:14-15` / `deploy/logstash.illumio_ops.conf:38-39` — `password: "changeme"` 註解內
- **風險**：操作員 uncomment 後忘記改 → 明碼 password / SIEM 連線 cleartext
- **修復**：範例本身帶 TLS 設定 + 占位符明顯為 `<REPLACE_ME>` 不是 `changeme`

#### M-12. 缺 LICENSE / SBOM / NOTICE / pip-audit 強制
- **狀態**：repo 根目錄無 `LICENSE`、無 `THIRD_PARTY_NOTICES.md`、CI 無 `pip-audit` 強制
- **影響**：散布 PyInstaller binary bundle 需揭露第三方授權（Flask BSD、cryptography Apache、PyInstaller GPL with exception 等）
- **修復**：
  1. 加 `LICENSE`
  2. `pip-licenses --format=markdown > THIRD_PARTY_NOTICES.md` 隨 release 一起出
  3. `cyclonedx-py` 產 CycloneDX SBOM
  4. CI 加 `pip-audit -r requirements.lock` 強制 fail-on-findings

#### M-13. `requirements.txt` (range) vs `requirements.lock` (pinned) 不一致；`setup.sh` 不走 lock
- **位置**：
  - `requirements.txt` 用 `>=,<` range（67 個套件）
  - `requirements.lock` 由 `pip-compile --generate-hashes` 產出，全 pinned + 1447 條 SHA256
  - `setup.sh:35` `pip install -r requirements.txt --quiet`（不用 lock）
  - `.github/workflows/ci.yml:34-36` 用 `requirements.txt`（不要求 hash）
- **風險**：CI 跑出的版本 ≠ release bundle 跑出的版本；dev box 與 prod box 重現性差
- **修復**：
  1. `setup.sh:35` → `pip install --require-hashes -r requirements.lock`
  2. CI `pip install --require-hashes -r requirements.lock`

#### M-14. `_LOG_SECRET_FIELD` regex 漏掉 Telegram token 等非 key:value 模式
- **位置**：`src/loguru_config.py:18-39`，regex 涵蓋 `api_key|secret|password|token|webhook_url|authorization|smtp_password`
- **缺少**：Telegram token format `\d+:[A-Za-z0-9_-]{35}`、PCE href、X-Tower-Token、session_id、cookies
- **連帶風險（資安 H 級）**：Telegram URL `https://api.telegram.org/bot{TOKEN}/sendMessage` 過企業 forward proxy 時 access log 會記下完整 URL path → token 外洩
- **修復**：
  1. 加 generic high-entropy regex（Telegram bot token format、LINE channel token 40+ Base64-ish）
  2. 部署文件警告：Telegram alert plugin 在金融環境必須**禁止對外網路代理 access log 寫入 URL path**

### 3.4 LOW（FIPS lint / 深度防禦 / cosmetic）

| # | 項目 | 位置 | 修復 |
|---|------|------|------|
| L-1 | SHA1 / MD5 用於 cache key | `src/pce_cache/{traffic_filter,backfill,ingestor_traffic}.py`、`src/events/poller.py` | 加 `usedforsecurity=False`(Python 3.9+) 或改 SHA256/blake2b |
| L-2 | CLI shell-exec call to `clear` × 4 處（透過 `os` 模組） | `src/main.py:92,114,189,238` | 改 ANSI escape `print("\033[2J\033[H")` |
| L-3 | `/static/*` 完全略過 IP allowlist + auth | `src/gui/__init__.py:375-376` | 改為靜態仍經 IP allowlist 但不要求 session |
| L-4 | `index.html` `\|safe` 注入 JSON | `src/templates/index.html:13` | 改 `<script type="application/json">` + JS `JSON.parse(...)` |
| L-5 | `logs/*.log` 等為 0o664（world-readable） | 實機 `find` 確認 | loguru sink rotation hook 加 chmod 0o640 |
| L-6 | `config/report_config.yaml`、`config/rule_schedules.json`、`config/tls/self_signed.pem` 為 0o644 | 實機 `find` | 設 0o640 |
| L-7 | `vendor/windows/nssm-2.24.zip`（2014 釋出、無簽章）TOFU | `vendor/windows/` | 加 SHA256 註解 + 評估 WinSW 替代 |
| L-8 | `scripts/setup.sh:50` 用 `$SUDO_USER` 當 service user | `setup.sh` | 改 `useradd --system illumio-ops` |
| L-9 | systemd unit 缺 `CapabilityBoundingSet`、`RestrictAddressFamilies`、`SystemCallFilter`、`MemoryDenyWriteExecute`、`LockPersonality`、`ProtectKernelTunables`、`ProtectControlGroups`、`RestrictSUIDSGID`、`RestrictNamespaces` | `deploy/illumio-ops.service` | 補上述項目 |
| L-10 | PBS Python tarball 用 TOFU 同源 sha256 sidecar | `scripts/build_offline_bundle.sh:24-40,74,120` | hard-code SHA256 in script 或改 GPG/Sigstore 驗證 |
| L-11 | `_check_ip_allowed` 信任 `request.remote_addr`，無 ProxyFix 文件警告 | `src/gui/_helpers.py:81` | README 加 reverse proxy 部署警告 |
| L-12 | Telegram bot token 嵌在 URL path（非 key:value） | `src/alerts/plugins.py:158` | 部署文件警告 + 加強 log regex（M-14） |
| L-13 | `Server: Cheroot/11.1.2` header 仍洩漏（agent 以為已 strip） | 實機 `curl -I` | Talisman 補 server header strip |
| L-14 | `setup-prod-git.sh` 啟用 `merge.autoStash` | `scripts/setup-prod-git.sh:18-20` | 文件標註 prod box 非 bit-for-bit reproducible |

### 3.5 INFO（已驗證無問題的正面項目）

- ✅ **無命令注入**：所有 `subprocess.run` 用 argv list，無 `shell=True`；無 `eval/exec/yaml.load` 等不安全反序列化函式於 `src/`
- ✅ **無自製加密**：cryptography / argon2-cffi / hmac.compare_digest / ssl stdlib，全部委派標準庫
- ✅ **CSRF 全域生效**：實測未帶 X-CSRFToken → 400 csrf_error，**且每次失敗 token 旋轉**（高強度）
- ✅ **Session cookies 大致正確**：`Secure`、`HttpOnly`、`Path=/`、`Expires` 8 小時
- ✅ **Argon2id 密碼雜湊**（time_cost=4, memory_cost=131072, parallelism=4）
- ✅ **HMAC 常數時間 username 比較**：`hmac.compare_digest`
- ✅ **登入限流 5/min** 實測有效
- ✅ **TLS 1.2 / TLS 1.3 only**（TLS 1.0/1.1 disabled），AES_256_GCM_SHA384
- ✅ **TLS cert SAN 完整**：localhost / 127.0.0.1 / 172.16.15.106 / 172.17.0.1 / ::1
- ✅ **HSTS / X-Frame-Options=DENY / X-Content-Type-Options / Referrer-Policy / Permissions-Policy / COOP / CORP** 都正確輸出
- ✅ **`flask-login` session_protection=`strong`**：IP/UA 變更即 invalidate
- ✅ **報告路徑遍歷雙層防護**：`'..' in filename` + `realpath` fence
- ✅ **`handle_unexpected_error` 不洩 stack trace**：僅回 request_id，細節寫 logger
- ✅ **無 Flask debug mode、無 Werkzeug debugger、無 debug routes 暴露**
- ✅ **匿名 API probe**：`/api/{settings,dashboard/queries,reports,siem/destinations,cache/status,security}` 全部 401
- ✅ **預設密碼 `illumio/illumio` 已在此實機被變更**（attempt → 401）
- ✅ **敏感檔 0o600**：`config/config.json`、`config/alerts.json`、`logs/state.json`、`config/tls/self_signed_key.pem`
- ✅ **Log 機敏掃描乾淨**：無 token / password 字串外洩於 log 檔
- ✅ **套件版本疑雲解開**：pandas 3.0.2 / pillow 12.2.0 / certifi 2026.4.22 均為 2026 真實 PyPI release（agent 知識截止誤判）
- ✅ **vendor/ 僅含 `windows/nssm-2.24.zip`**，無 patched libs

---

## 4. 實機驗證證據

### 4.1 Phase A（read-only baseline）

#### systemd 安全評分
```
$ systemd-analyze security illumio-ops.service
→ Overall exposure level: 9.6 UNSAFE :-{
```
**判讀**：完全無加固。對比 repo 內 `deploy/illumio-ops.service` 範例有部分 hardening，但**未被部署**。

#### 服務 process
```
PID 853344 uid=0(root) etime=6d 15h
ExecStart=/root/illumio-ops/venv/bin/python illumio-ops.py --monitor-gui --interval 5
RSS=540 MB, Threads=22, FDs=30, sockets=3
```

#### 監聽埠
```
LISTEN 0.0.0.0:5001  python(pid=853344)
```
確認 H-1：bind 0.0.0.0。

#### 檔案權限
| 檔案 | 權限 | 評估 |
|------|------|------|
| `config/config.json` | 600 | ✓ |
| `config/alerts.json` | 600 | ✓ |
| `logs/state.json` | 600 | ✓ |
| `config/tls/self_signed_key.pem` | 600 | ✓ |
| `config/config.json.example` | 644 | L-6 |
| `config/report_config.yaml` | 644 | L-6 |
| `config/rule_schedules.json` | 644 | L-6 |
| `config/tls/self_signed.pem` | 644 | L-6 |
| `logs/*.log`（13 個檔） | 644 | L-5 |

#### config.json 機敏欄位（masked）
```
api.verify_ssl = False                    # H-6
api.key = <set,len=21>
api.secret = <set,len=64>
smtp.password = <set,len=8>
alerts.line_channel_access_token = <set,len=172>
web_gui.password = <set,len=97>           # Argon2 hash
web_gui.secret_key = <set,len=11>         # H-7: 太短
web_gui.allowed_ips = []                  # H-1 確認
web_gui.must_change_password = <set,len=5>
```

#### TLS 配置
- TLS 1.0/1.1：disabled ✓
- TLS 1.2：`ECDHE-RSA-AES256-GCM-SHA384`
- TLS 1.3：`TLS_AES_256_GCM_SHA384`
- Cert：CN=localhost, O=IllumioPCEOps, C=TW, valid 2026-04-24 → 2031-04-23（5 年）
- SAN：DNS:localhost, IP:127.0.0.1, IP:172.16.15.106, IP:172.17.0.1, IP:::1

#### HTTP security headers（`curl -kIs https://172.16.15.106:5001/login`）
```
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload  ✓
X-Frame-Options: DENY                                                     ✓
X-Content-Type-Options: nosniff                                           ✓
Referrer-Policy: strict-origin-when-cross-origin                          ✓
Permissions-Policy: camera=(), microphone=(), geolocation=(), ...         ✓
Cross-Origin-Opener-Policy: same-origin                                   ✓
Cross-Origin-Resource-Policy: same-site                                   ✓
Content-Security-Policy: ... 'unsafe-inline' ...                         M-8
Server: Cheroot/11.1.2                                                   L-13
```

### 4.2 Phase B（主動安全測試）

#### 匿名 API probe（off-host 從 192.168.20.32 發起）
| URL | HTTP | 評估 |
|-----|------|------|
| `/login` | 200 | OK by design |
| `/api/csrf-token` | 200 | session-bound 故低風險 |
| `/api/settings` | 401 | ✓ |
| `/api/dashboard/queries` | 401 | ✓ |
| `/api/reports` | 401 | ✓ |
| `/api/siem/destinations` | 401 | ✓ |
| `/api/cache/status` | 401 | ✓ |
| `/api/security` | 401 | ✓ |
| `/static/js/utils.js` | 200 | L-3 |

#### 預設帳密 / 登入限流
- `illumio` / `illumio` → 401（已被使用者變更為強密碼，緩解 H-1）
- 10 次錯誤登入：第 1~4 次 401，第 5 次起 429（驗證 `5/min` rate limit）

#### Cookie flags
```
Set-Cookie: session=...; Expires=...; Secure; HttpOnly; Path=/; SameSite=Lax
```
**注意**：靜態 GUI agent 報告為 `SameSite=Strict`，**實機是 `Lax`**。Lax 允許 top-level GET 帶 cookie，比 Strict 弱。建議改 Strict 或 documented 為知情接受。

#### CSRF 驗證
- POST `/api/security` 無 `X-CSRFToken` → 400 `csrf_error` ✓
- CSRF token **每次失敗都旋轉**（強防護，超出 GUI agent 預期）

#### M-1（`/api/security` 無 old_password）
- 透過 `src/gui/routes/config.py:59-62` 程式碼註解確認為**刻意設計**
- runtime 測試因 CSRF 旋轉複雜未完成獨立驗證，但程式碼證據足夠

### 4.3 Phase C（故障注入結果）

**整體結論**：runtime 表現大幅優於靜態預測 — 短期無觀察到資源洩漏、優雅退出 2.16 秒、kill -9 後 state files 完整、systemd auto-restart 正常。

**注意**：H-2 / H-3 的**靜態程式碼分類維持 HIGH**（稽核員看程式碼層仍會 flag），但下列 runtime 證據可作為修補**時程**與**實際生產風險**的判斷依據 — 短期無立即危害，可排在 H-5/H-6/H-7 之後修。

#### C-1：FD/Socket/Thread/RSS 15 分鐘趨勢
```
S01  pid=853344 fds=30 socks=3 rss_kb=544660 threads=22
S02  pid=853344 fds=30 socks=3 rss_kb=544660 threads=22
...
S15  pid=853344 fds=30 socks=3 rss_kb=529620 threads=22
```
| 指標 | 起始 | 終點 | 變化 |
|------|------|------|------|
| FDs | 30 | 30 | 0（**完全平穩**）|
| sockets | 3 | 3 | 0 |
| threads | 22 | 22 | 0 |
| RSS_kb | 544,660 | 529,620 | **-15,040（下降）** |

**判讀**：15 分鐘觀察期內 ApiClient/Session 重建沒有造成 FD/socket 累積；RSS 反而略下降（GC 有效）。H-2 的長期累積風險仍存在於理論上（程式碼確實沒 `close()`），但實機 6 天 uptime + 15 分鐘觀察未顯現 — 程式碼層維持 HIGH，但修補時程可延後。

#### C-2：SIGTERM 計時
```
pre-stop state.json sha:  d0d6dc6e24382a35...
pre-stop schedules  sha:  d8f0690efd1a8908...
systemctl stop elapsed:   2165 ms
post-stop status:         inactive
state.json parse:         OK
schedules.json parse:     OK
```
**判讀**：`systemctl stop` 在 **2.165 秒**內完成，遠低於 systemd 預設 `TimeoutStopSec=90s`。`_rs_background_scheduler` 雖然不檢查 shutdown_event，但 daemon thread 隨 Python interpreter 退出而結束，未造成檔案毀損或殘留 `.tmp` / `.lock`。H-3 程式碼層維持 HIGH（架構仍應改進），實機優雅退出有效，修補時程可延後。

#### C-3：kill -9 復原
```
systemctl start illumio-ops      → new pid 1066298
sleep 25 (scheduler 運作期間)
kill -9 1066298                  → process 被強制中止
state.json sha (post-kill):      93d3a9f3e13c3a36...  (合理變動 — 25s 內被寫過)
state.json parse:                OK after kill -9
schedules.json parse:            OK after kill -9
sleep 20 (等待 systemd Restart=on-failure)
final pid: 1066355               → auto-restart 成功
LISTEN 0.0.0.0:5001 python(pid=1066355)
```
**判讀**：
- `os.replace()` atomic rename 在強制中止下保持檔案完整性（page cache 在 kernel 端，process 死亡不影響）
- systemd `Restart=on-failure` 正確介入
- M-2（fsync 缺失）的真正風險是**斷電 / kernel panic**，kill -9 觸發不到 → 屬於電源異常情境，不變 MEDIUM
- M-3（ScheduleDB.load 毀損 → `{}`）未在此測試暴露，因 atomic write 未產生毀損檔；需獨立用人工毀損 inject 測試（**未執行**，建議納入未來 fuzz 測試）

### 4.4 Phase D（外送驗證）

採用程式碼證據，未執行 runtime：
- `src/alerts/plugins.py:88` LINE plugin `urlopen()` 缺 `timeout=`（H-5）
- Telegram URL 嵌 token 在 path（L-12）

---

## 5. 修復優先順序與行動計畫

### 5.1 通過稽核的最短路徑（Phase 1，預計 1-2 個 sprint）

| 順序 | 項目 | 預估工時 | 影響 |
|------|------|----------|------|
| 1 | C-1：部署 hardened systemd unit + system user | 0.5 day | 直接消除 9.6 UNSAFE 評分 |
| 2 | H-7：`web_gui.secret_key` 啟動驗證 + 現場 rotate | 0.2 day | 立即修補實機弱點 |
| 3 | H-6：`config_models` 加 production validator 拒 `verify_ssl=False` | 0.5 day | 防止意外/被社工關閉 |
| 4 | H-5：LINE plugin 補 `timeout=10` + channel cooldown | 0.5 day | DoS 緩解 |
| 5 | H-2：`ApiClient` / SIEM transport 加 `close()` + GUI thread 接 `shutdown_event` | 1-2 days | 資源洩漏 |
| 6 | H-3：`_rs_background_scheduler` 接 shutdown_event + 與 APScheduler 去重 | 1 day | 優雅退出 |
| 7 | M-2 / M-3 / M-4：state.json fsync + ScheduleDB 毀損處理 | 0.5 day | 資料完整性 |
| — | **H-1（明示接受）/ M-8（明示接受）** | 不修補 | 補償控制清單見 §3.2 H-1 / §3.3 M-8 |

### 5.2 Phase 2（next quarter，配合 release）

- M-1：`/api/security` 加 `old_password` 必填 + CLI bypass flag
- M-5：`/api/actions/*` 補 rate limit
- M-6 / M-7：webhook scheme validator + production TLS 護欄
- M-8：完成 `data-action` 改造 → 拿掉 CSP `unsafe-inline` 改 nonce
- M-9：SMTP/LINE plugin timeout + retry backoff
- M-11：Filebeat/Logstash/rsyslog 範例補 TLS
- M-12 / M-13：LICENSE + SBOM + `--require-hashes` 強制
- M-14 + L-12：log redaction 加強 + Telegram 部署文件警告
- L-1：SHA1/MD5 加 `usedforsecurity=False`
- L-5 / L-6：檔案權限 0o644 → 0o640

### 5.3 Phase 3（獨立 plan）

- H-4：naive `datetime.now()` 全域 → timezone-aware UTC（影響 20+ 檔案，需獨立 plan）

---

## 6. 附錄

### 6.1 GUI HTTP 路由清單（共 73 條）

完整清單見 GUI agent 報告（已紀錄於本次稽核 transcript）。
所有寫入端點（POST/PUT/DELETE）皆受 **CSRF + session 雙重保護**；所有 `/api/*` 端點通過 `before_request security_check` 強制 session 認證；IP allowlist 違反時透過 `_rst_drop` TCP RST 關閉 socket（防 banner 指紋識別）。

### 6.2 套件版本核對（top 10 高關注）

| 套件 | requirements.lock (pinned) | 實機 venv | 來源 | 評估 |
|------|----------------------------|----------|------|------|
| requests | 2.33.1 | 2.33.1 | PyPI | ✓（CVE-2024-35195 已修） |
| urllib3 | 2.6.3 | 2.6.3 | PyPI | ✓ |
| cryptography | 45.0.7 | 45.0.7 | PyPI | ✓（OpenSSL CVE-2024-6119 已修） |
| PyYAML | 6.0.3 | — | PyPI | ✓ |
| Jinja2 | 3.1.6 | — | PyPI | ✓（CVE-2025-27516 已修） |
| Werkzeug | 3.1.8 | 3.1.8 | PyPI | ✓ |
| Flask | 3.1.3 | 3.1.3 | PyPI | ✓ |
| pandas | 3.0.2 | 3.0.2 | PyPI | ✓（agent 知識截止誤判） |
| reportlab | 4.5.0 | — | PyPI | ✓（CVE-2023-33733/CVE-2024-31479 已修） |
| Pillow | 12.2.0 | 12.2.0 | PyPI | ✓（agent 知識截止誤判） |
| certifi | 2026.4.22 | 2026.4.22 | PyPI | ✓ |

### 6.3 稽核者交付件 checklist

供未來合規稽核員快速核對：

- [ ] systemd unit hardening（C-1）
- [ ] System user 而非 root（C-1）
- [ ] GUI bind 127.0.0.1 + IP allowlist fail-closed（H-1）
- [ ] `web_gui.secret_key` ≥ 32 bytes（H-7）
- [ ] PCE / SIEM `verify_ssl` 不可關閉於 production（H-6 / M-6）
- [ ] 全部 alert plugin 有 timeout（H-5 / M-9）
- [ ] Resource lifecycle: `ApiClient.close()`、SIEM transport `close()`（H-2）
- [ ] Scheduler thread 接 SIGTERM shutdown_event（H-3）
- [ ] state.json `fsync()` + ScheduleDB 毀損處理（M-2 / M-3）
- [ ] CSP 移除 `unsafe-inline`（M-8）
- [ ] `/api/security` 加 `old_password` 必填（M-1）
- [ ] Filebeat / Logstash / rsyslog 範例帶 TLS（M-11）
- [ ] LICENSE + SBOM + `pip-audit` CI（M-12）
- [ ] CI / setup.sh 改用 `requirements.lock --require-hashes`（M-13）
- [ ] Log redaction 加強 + Telegram 部署文件警告（M-14 / L-12）
- [ ] datetime 全域 timezone-aware（H-4，獨立 plan）

---

**本報告由 Claude 在 2026-05-22 完成。**
靜態審查由 4 個獨立並行 agent 執行（Security / Stability / GUI/Web / Supply-chain），實機驗證於 `root@172.16.15.106` 進行 Phase A/B 完整、Phase C 故障注入背景進行中、Phase D 採程式碼證據。
