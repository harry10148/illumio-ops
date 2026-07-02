---
title: 維運手冊（Operations Manual）
audience: [operator]
version: 4.1.0
last_verified: 2026-06-26
verified_against:
  - scripts/install.sh
  - scripts/install.ps1
  - scripts/build_offline_bundle.sh
  - scripts/uninstall.sh
  - deploy/illumio-ops.service
  - deploy/install_service.ps1
  - config/config.json.example
  - src/cli/ (Click 子命令完整稽核)
  - src/gui/routes/ (約 109 條路由稽核)
  - src/gui/__init__.py、src/gui/_helpers.py
  - src/alerts/plugins.py、src/alerts/metadata.py
  - src/templates/、src/static/js/
  - docs/getting-started.md、docs/user-guide/*、docs/reference/cli.md
  - 2026-06-26 完整稽核 + 實機測試
related_docs:
  - getting-started_zh.md
  - user-guide/dashboard_zh.md
  - user-guide/troubleshooting_zh.md
  - reference/cli_zh.md
---

> 文件導覽：本頁是 illumio-ops **操作員（Operator）日常維運的核心指南**，整合並更新各分頁使用手冊。
> 詞彙（PCE、VEN、Workload、Service、Port、Policy、Ruleset、SIEM、DLQ、SMTP 等）依專案慣例保留英文。

# illumio-ops 維運手冊（v4.1.0）

illumio-ops 是針對 Illumio PCE 的**無代理（agentless）監控與自動化平台**。它透過 PCE REST API 連線——不需要在 PCE 或 Workload 上安裝任何代理、也不需更動防火牆——即可提供操作員儀表板、排程報表、告警規則、SIEM 轉送、以及 Policy／Workload 檢視與隔離（quarantine）。

本手冊章節：

1. [安裝與首次啟動](#1-安裝與首次啟動)
2. [設定](#2-設定)
3. [Web GUI 操作導覽](#3-web-gui-操作導覽)
4. [CLI 用法](#4-cli-用法)
5. [報表](#5-報表)
6. [告警](#6-告警)
7. [SIEM 轉送設定](#7-siem-轉送設定)
8. [維運](#8-維運)
9. [疑難排解](#9-疑難排解)

---

## 1. 安裝與首次啟動

### 1.1 系統需求

| 項目 | 需求 |
|---|---|
| Python | 3.10 以上（建議 3.12）。離線 bundle 不需系統 Python——bundle 自帶 CPython 3.12.7。 |
| PCE 連線 | 可透過 HTTPS 連到 PCE（預設埠 `8443`），並具備 PCE API 金鑰（監控用最低 `read_only`；quarantine 操作需 `owner`）。 |
| 作業系統 | RHEL／Rocky Linux 8+、Ubuntu 22.04+、Debian 12+、Windows Server 2019+／Windows 11。 |

> **如何建立 PCE API 金鑰**：PCE Web Console → 右上使用者選單 → **My API Keys → Add**。

### 1.2 標準安裝（Linux，正規路徑 /opt/illumio-ops）

正式環境的正規安裝路徑為 **`/opt/illumio-ops`**，由 `scripts/install.sh` 部署，並註冊一個**強化過的 systemd unit**。安裝程式以 root 執行，會：

- 建立系統使用者 `illumio-ops`（`useradd --system --no-create-home --shell /sbin/nologin`）。
- 建立執行期目錄 `logs/`、`data/`、`reports/`、`config/`、`config/tls/`。
- 設定權限：secrets `0600`、設定檔 `0640`、敏感目錄 `0750`。
- 由 `deploy/illumio-ops.service` 產生並安裝 systemd unit。

systemd unit 重點（`deploy/illumio-ops.service`）：

```ini
ExecStart=/opt/illumio-ops/python/bin/python3 /opt/illumio-ops/illumio-ops.py --monitor-gui --interval 10
User=illumio-ops
Restart=on-failure
RestartSec=10
# 強化：NoNewPrivileges、ProtectSystem=strict、ProtectHome=true、PrivateTmp、
#       SystemCallFilter=@system-service、CapabilityBoundingSet=（清空）等
ReadWritePaths=/opt/illumio-ops/logs /opt/illumio-ops/config /opt/illumio-ops/data /opt/illumio-ops/reports
```

> **安全提醒**：unit 啟用了 `ProtectHome=true` 與 `ProtectSystem=strict`，服務只能寫入 `ReadWritePaths` 列出的四個目錄。若把資料庫或設定移到其他路徑，必須一併加入 `ReadWritePaths`，否則服務會在啟動時因無法寫入而失敗。

啟用並啟動服務：

```bash
sudo systemctl enable --now illumio-ops
sudo systemctl status illumio-ops      # 應顯示 Active: active (running)
journalctl -u illumio-ops -f           # 追蹤即時日誌
```

> 自訂安裝根目錄：`sudo ./install.sh --install-root /opt/custom`——systemd unit 會自動改寫成該路徑。注意：自訂路徑會略過從舊版 `/opt/illumio_ops`（底線）的自動遷移。

### 1.3 離線／air-gapped bundle

正式或隔離網段主機建議用離線 bundle。bundle 自帶可攜式 CPython 3.12 與全部預編譯 wheels，目標主機**不需網路、也不需系統 Python**。

**建置 bundle**（在任一可連網的 Linux／WSL 主機）：

```bash
bash scripts/build_offline_bundle.sh
# 產出：
#   dist/illumio-ops-<version>-offline-linux-x86_64.tar.gz
#   dist/illumio-ops-<version>-offline-windows-x86_64.zip
```

> bundle 內**絕不包含** `config.json`、`alerts.json`、`rule_schedules.json`（含機密），只帶 `*.example` 範本。建置腳本會以 in-tree SHA256 pin 驗證下載的 CPython tarball。

**Linux 首次安裝**：

```bash
tar xzf illumio-ops-<version>-offline-linux-x86_64.tar.gz
cd illumio-ops-<version>-offline-linux-x86_64
bash ./preflight.sh                    # 任何 FAIL 會回傳非 0，先跑無妨
sudo ./install.sh                      # 安裝到 /opt/illumio-ops 並註冊 systemd
sudo nano /opt/illumio-ops/config/config.json   # 填入 PCE 憑證
sudo systemctl enable --now illumio-ops
```

### 1.4 Windows（NSSM 服務）

Windows 以 bundle 內附的 **NSSM**（`deploy\nssm.exe`）註冊名為 **`IllumioOps`** 的服務。預設安裝根目錄 `C:\illumio-ops`。

```powershell
# 以系統管理員開啟 PowerShell
Expand-Archive illumio-ops-<version>-offline-windows-x86_64.zip -DestinationPath C:\
cd C:\illumio-ops-<version>-offline-windows-x86_64
.\preflight.ps1
.\install.ps1                          # 安裝到 C:\illumio-ops 並註冊 IllumioOps 服務
notepad C:\illumio-ops\config\config.json
Get-Service IllumioOps                 # 應顯示 Running
```

> **重要差異（Linux vs Windows）**：Linux systemd 預設以 **`--monitor-gui`** 啟動（同時跑監控 daemon + Web GUI）；Windows NSSM 服務預設只跑 **`--monitor`**（僅 daemon，**不自動啟動 Web GUI**）。Windows 上若需要 Web GUI，請另以 `python\python.exe illumio-ops.py gui` 啟動，或用 `nssm edit IllumioOps` 把 `AppParameters` 改為 `--monitor-gui`。
>
> NSSM 服務日誌寫到 `C:\illumio-ops\logs\service_stdout.log` 與 `service_stderr.log`（10 MB 輪替），當機後 10 秒自動重啟。

### 1.5 從原始碼安裝（開發／測試）

```bash
git clone <repo-url> && cd illumio-ops
cp config/config.json.example config/config.json
# Ubuntu/Debian 受 PEP 668 限制，須用 venv：
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 illumio-ops.py gui             # 啟動 Web GUI
```

> 每開新 shell 都要重新 `source venv/bin/activate`。

### 1.6 四種執行模式

| 模式 | 子命令 | 等效舊旗標 | 說明 |
|---|---|---|---|
| 監控 daemon | `illumio-ops monitor` | `--monitor` | 無 GUI，背景輪詢 PCE、評估告警 |
| 僅 Web GUI | `illumio-ops gui` | `--gui` | 只起 Web 介面 |
| 監控 + GUI | `illumio-ops monitor-gui` | `--monitor-gui` | 合併模式（**systemd 預設**） |
| 互動式 CLI 選單 | `illumio-ops shell` | （裸呼叫 `illumio-ops`，已棄用） | 文字選單；TLS 憑證、PCE profile、rule-scheduler 等只能由此進入 |

Web GUI 由 **cheroot** 以 HTTPS 服務，預設綁定 **`0.0.0.0:5001`**。常用旗標：

```bash
illumio-ops gui --port 5001 --host 0.0.0.0     # -p/--port、-h/--host
illumio-ops monitor-gui --interval 10 --port 5001
```

`--host` 控制監聽介面（預設 `0.0.0.0` 表示所有介面；要只開放本機可設 `127.0.0.1`）。`--interval` 為監控週期（分鐘，預設 10）。

### 1.7 首次登入與強制改密

- Web GUI 預設使用者為 **`illumio`**（可由 `web_gui.username` 變更）。初始密碼於安裝／首次設定時產生並提示，密碼以 **Argon2id** 雜湊儲存。
- 登入頁在 **`/login`**，前端 SPA 接著呼叫 JSON API（`POST /api/login`）。
- **首次登入強制改密**：當 `web_gui.must_change_password` 為真時，後端對所有受保護 API 回傳 **HTTP 423**，直到密碼變更為止——無法略過。登入後會直接出現改密表單（新密碼至少 8 碼、需與確認欄一致），改完才能進入儀表板。

> **安全提醒**：第一次以瀏覽器開啟 `https://<host>:5001` 會出現自簽憑證警告（正常，見 [8.6](#86-tls-憑證輪替)）。請於首次登入後立即改密。

### 1.8 更新流程

**原始碼／開發安裝**：

```bash
git pull
source venv/bin/activate
pip install -r requirements.txt
# 重新啟動服務或行程
```

**離線 bundle 安裝**（安裝程式會保留你的設定）：

```bash
# Linux
sudo systemctl stop illumio-ops
tar xzf illumio-ops-<new-version>-offline-linux-x86_64.tar.gz
cd illumio-ops-<new-version>-offline-linux-x86_64
sudo ./install.sh                      # 保留 config.json / alerts.json / rule_schedules.json / logs / data
sudo systemctl restart illumio-ops
```

```powershell
# Windows
Stop-Service IllumioOps
.\install.ps1                          # 同樣保留 operator 擁有的設定檔
Restart-Service IllumioOps
```

升級後保留的檔案：`config/config.json`、`config/alerts.json`、`config/rule_schedules.json`、`logs/`、`data/pce_cache.sqlite`。升級完成後建議比對新增的設定鍵：

```bash
diff /opt/illumio-ops/config/config.json.example /opt/illumio-ops/config/config.json
```

> 正式機可先執行一次 `bash scripts/setup-prod-git.sh`，啟用 `merge.autoStash`，讓 `git pull` 自動 stash 本機修改後再快轉，避免被「local changes would be overwritten」中斷。

### 1.9 解除安裝

```bash
sudo /opt/illumio-ops/uninstall.sh             # 預設保留 config/
sudo /opt/illumio-ops/uninstall.sh --purge     # 連設定一起刪除
```

```powershell
.\install.ps1 -Action uninstall                # Windows：移除 IllumioOps 服務與安裝目錄
```

---

## 2. 設定

### 2.1 設定檔總覽

所有設定檔位於 `config/`（全部已列入 `.gitignore`，因含機密）。請從範本起步：

```bash
cp config/config.json.example config/config.json
```

| 檔案 | 內容 |
|---|---|
| `config.json` | 主設定（見下表各區塊）。 |
| `alerts.json` | 告警規則定義（event／traffic／bandwidth 規則）。原子寫入、權限 `0600`。 |
| `report_config.yaml` | 報表分析參數：ransomware 風險埠分級、lateral movement 埠、B/L 系列門檻、輸出 `top_n` 等。 |
| `rule_schedules.json` | Rule Scheduler 的本地排程記錄（以 PCE rule／ruleset href 為鍵）。 |

### 2.2 config.json 各區塊

| 區塊 | 用途 |
|---|---|
| `api` | 目前作用中的 PCE 連線（`url`、`org_id`、`key`、`secret`、`verify_ssl`）。activate profile 時會把該 profile 複製到此區塊。 |
| `pce_profiles` / `active_pce_id` | 多 PCE profile 清單與目前作用中的 profile id。 |
| `alerts` | 啟用的通道清單 `active`，及 line／webhook／telegram／teams 的金鑰。 |
| `email` / `smtp` | 郵件寄件者與收件者、SMTP 主機／埠／帳密／TLS。 |
| `settings` | `language`（`en` / `zh_TW`）、`theme`、`timezone`、`enable_health_check`、`dashboard_queries`。 |
| `report` / `report_schedules` | 報表預設與排程清單。 |
| `rule_scheduler` | `enabled`、`check_interval_seconds`（預設 300）。 |
| `scheduler` | `persist`、`db_path` — 已棄用，不再生效（僅使用記憶體 job store；`persist=true` 只會記一筆 warning）。 |
| `web_gui` | `username`、`password`（Argon2id 雜湊）、`secret_key`、`allowed_ips`、`tls{...}`、`must_change_password`。 |
| `logging` | `level`、`json_sink`、`rotation`（如 `10 MB`）、`retention`。 |
| `pce_cache` | 本地 SQLite 快取設定（見 [8.1](#81-pce-cache保留策略)）。 |
| `siem` | SIEM 轉送設定（見 [第 7 章](#7-siem-轉送設定)）。 |

> **安全提醒**：`config.json` 含 PCE secret、SMTP 密碼、LINE／Telegram／Teams token。權限應維持 `0600`，切勿提交版控。SMTP 密碼也可改用環境變數 `ILLUMIO_SMTP_PASSWORD` 覆寫，避免明文落檔。

### 2.3 PCE 連線與多 PCE

最簡單的做法是直接編輯 `api` 區塊：

```json
"api": {
  "url": "https://pce.example.com:8443",
  "org_id": "1",
  "key": "api_xxxxxxxxxxxxxx",
  "secret": "your-api-secret-here",
  "verify_ssl": true
}
```

多 PCE 時，於 `pce_profiles` 加入物件並設定 `active_pce_id`。**同一時間只有一個 profile 作用中**；所有功能（監控、報表、規則、cache）都針對該作用中 profile。切換方式：

- **Web GUI**：Settings → PCE，按該 profile 的 **Activate**（不是只按 Save）。activate 會把憑證複製進 `api` 區塊，daemon 於下個輪詢週期生效，無需重啟。
- **手動編輯**：改 `active_pce_id` 後重啟行程。

> **lab／自簽 PCE**：實驗環境可設 `"verify_ssl": false` 略過 PCE 憑證驗證。這是**有意保留的安全取捨**——正式環境請設 `true`，並把 PCE 的 CA 憑證裝進主機系統信任庫（PCE profile schema 目前沒有 per-profile CA bundle 欄位）。

### 2.4 alerts.json（規則定義）

告警規則存在獨立的 `config/alerts.json`（不在 `config.json` 內）。每條規則的關鍵欄位：

| 欄位 | 說明 |
|---|---|
| `type` | `event`、`traffic`、`bandwidth` |
| `name_key` | i18n 鍵；顯示名稱於載入時解析（檔案只存鍵，不存語言字串） |
| `filter_value` | 逗號分隔的 PCE event type（event 規則） |
| `filter_status` / `filter_severity` | `all` / `success` / `failure`；`all` / `err` / `warning` / `info` |
| `threshold_type` | `immediate`（首次命中即觸發）或 `count`（視窗內 N 次） |
| `throttle` | 速率限制格式 `N/Tm`，例如 `1/15m` 表每 15 分鐘最多一次 |
| `cooldown_minutes` | 觸發後的冷卻時間 |

規則建議透過 Web GUI（Rules 分頁）或 CLI（`illumio-ops rule list` / `rule edit`）維護；GUI 的 **Load Best Practices** 可一鍵附加／取代為內建最佳實務規則組（17 條 event + 1 條 traffic）。

### 2.5 report_config.yaml / rule_schedules.json

- `report_config.yaml` 定義報表的安全分析參數，例如 ransomware 風險埠（critical：RPC 135、SMB 445、RDP 3389、WinRM 5985/5986）、lateral movement 埠、與 B/L 系列規則門檻（如 `min_policy_coverage_pct: 30`、`exfil_bytes_threshold_mb: 100`）。多數操作員不需更動。
- `rule_schedules.json` 由 Rule Scheduler 自動維護，以 PCE href 為鍵，記錄 `type`（`recurring`/`expire`）、`action`（`allow`/`block`）、`days`、`start`、`end`、`timezone` 等，通常不需手動編輯。

### 2.6 用 CLI 修改設定

```bash
illumio-ops config show                       # 印出完整（已驗證）設定
illumio-ops config show --section api          # 只看單一區塊
illumio-ops config validate                    # 對 Pydantic schema 驗證
illumio-ops config set api.url https://pce.example.com:8443   # 寫入單一鍵【會存檔】
illumio-ops config login --url ... --key ... --secret ...      # 設定 PCE 憑證【會存檔】
```

> **副作用提醒**：`config set` 與 `config login` 會驗證並**覆寫存檔** `config.json`（secret 等機密在輸出中遮蔽）。

---

## 3. Web GUI 操作導覽

GUI 是單頁式應用：登入後以頂部分頁切換，內容由前端 JS 模組向約 109 條 JSON API 取資料。以下逐分頁說明，並標示**會產生真實副作用**的動作。

> **全域安全提醒**：除 `/login`、`/api/login`、`/logout`、`/api/csrf-token` 外，所有路由都需登入。`web_gui.allowed_ips` 提供 IP 允許清單，比對的是**直接連線來源 IP**（`request.remote_addr`），被拒的連線以 TCP RST 靜默切斷（避免被埠掃描偵測）。所有 POST／PUT／DELETE 都需 CSRF token。詳見 [8.7 反向代理與 IP 允許清單](#87-反向代理與-ip-允許清單)。

### 3.1 頁首

- 左側：產品標誌。
- 中央：**PCE 狀態晶片（status chip）**——連線健康燈號（綠 ok／琥珀 warn／紅 err／灰 unknown）、PCE 主機、Rules 數、Schedules 數、設定載入時間。
- 右側：**Operations** 下拉選單——Theme（Auto/Dark/Light）、Density（Compact/Comfortable）、**Logs**（開啟維運日誌視窗）、**Stop**（停止 Web 服務，**會跳出確認框**；只有非持久模式可用）。

### 3.2 主分頁

依序為：**Dashboard｜Traffic & Workloads｜Event Viewer｜Rules｜Reports｜Rule Scheduler｜Integrations｜Settings**。

**1) Dashboard**——即時總覽。顯示 Security Posture 分數與 Top Risk Findings、VEN 健康、Pipeline（cache 擷取）健康、OS 分佈、Enforcement 模式、以及 Health／Traffic／Risk 狀態卡。「auto-refresh 10m」勾選與 **Refresh** 鈕只是**重新抓取**最新快照（`GET /api/dashboard/*`），並不重新產生報表快照。

**2) Traffic & Workloads**——流量分析與 Workload 搜尋。

- *Traffic Analyzer*：依 Policy Decision（Blocked／Potential／Allowed／All）、label／IP／port／protocol 篩選，列出流量並可分頁。
- *Workload Search*：依名稱／IP／hostname 查 Workload，顯示線上狀態、介面、labels、管理狀態。
- **Isolate（quarantine）**：在流量列或 Workload 列按 Isolate → 選方向（來源／目的／雙向）與嚴重度（Mild／Moderate／Severe）→ 套用。
  - > **真實副作用（高風險）**：`POST /api/quarantine/apply` 或 `bulk_apply` 會在 **PCE 上對 Workload 加上 `Quarantine` label**，立即改變其 enforcement，直到手動移除。批次套用最多 5 個並行 worker。首次使用會自動建立 Quarantine labels（`/api/init_quarantine`）。
- **Accelerate**：對受管 Workload 暫時提高流量回報頻率（`POST /api/workloads/accelerate`，呼叫 PCE `set_flow_reporting_frequency`）。
  - > **真實副作用**：會變更 PCE 上該 Workload 的遙測頻率（不改 enforcement）。僅受管 Workload 可用；持續模式由前端每 10 分鐘重送。

**3) Event Viewer**——PCE 稽核事件檢視。可依時間視窗、category／group／type、關鍵字篩選，左表右詳（normalized + raw JSON）。另含 Shadow Compare（規則對實際事件的命中比對）、Rule Test（單一規則測試）、Event Catalog（事件型錄）。皆為**唯讀**（會即時呼叫 PCE API 取事件）。

**4) Rules**——告警規則維護，兩個子頁：

- *Rules*：依型別（Event／Traffic／Bandwidth／System Health）篩選、搜尋、編輯、刪除、批次刪除。新增規則開對應 modal。儲存／刪除會**寫入 `alerts.json`／`config`**。
- *Actions*：
  - **Send Test Alert（All）／Test [通道]**：
    - > **真實副作用**：`POST /api/actions/test-alert` 會**實際發送**測試訊息到指定（或全部）通道（email／LINE／webhook／Telegram／Teams）。請勿在正式環境隨意點按。
  - 此頁也提供手動分析、reset-watermark 等除錯動作（見 [3.3](#33-高風險動作彙整)）。

**5) Reports**——報表清單與排程，兩個子頁：

- *List*：瀏覽已產生報表，可 View（HTML）、Download、Delete／批次 Delete（**會刪檔，不可復原**），並提供各類報表的 **Generate** 鈕（Traffic／Audit／VEN Status／Policy Usage／Policy Diff／Policy Resolver／App Summary）。
  - > **副作用**：產生報表會於伺服器端排入背景執行緒、即時查詢 PCE 並寫出檔案；可能耗時數分鐘。
- *Schedules*：建立／編輯／啟用停用／立即執行（Run Now）／刪除報表排程。排程需 daemon 持續執行才會觸發；勾選 Email 需先設定好郵件通道。詳見 [第 5 章](#5-報表)。

**6) Rule Scheduler**——對 PCE Draft policy 的 Ruleset／Rule 排定時間觸發的啟用／停用，三個子頁：Browse（瀏覽 ruleset／rule）、Schedules（排程清單）、Logs。

- 建立排程：選 Recurring（星期＋起迄時間＋時區）或 One-time（到期時間），Action 為 `allow`（視窗內啟用）或 `disable`。
  - > **真實副作用**：`POST /api/rule_scheduler/schedules` 會在 **PCE rule 的 description 寫入英文排程註記**，並依排程在 PCE 上**啟用／停用該 rule**。**Draft（未佈署）規則會被擋下**，必須先在 PCE 佈署。刪除排程會盡力清除 PCE 上的註記。
  - > **注意**：排程器**不會自動佈署 ruleset**——它只在 Draft 狀態切換 rule 的啟用旗標，佈署需操作員另行處理。

**7) Integrations**——四個子頁：

- *Overview*：管線健康總覽。
- *Cache*：PCE cache 狀態卡、設定表單（保留天數、輪詢間隔、traffic filter／sampling）。儲存後需 **Restart Monitor**（`POST /api/daemon/restart`）才生效。可手動 **Backfill**（補填歷史，**會查 PCE 並寫入 cache DB**）或 **Retention Now**（**會永久刪除過期列**）。
- *SIEM*：destination 清單與 KPI（sent／failed／DLQ／成功率／延遲）。新增／編輯／刪除 destination，及 **Test**（**會實際送出測試事件**）。詳見 [第 7 章](#7-siem-轉送設定)。
- *DLQ*：死信佇列檢視，可 **Retry（replay）**（**重送失敗事件**）或 **Clear／Purge**（**永久刪除**）。

**8) Settings**——四個子頁：

- *PCE*：PCE profile 清單與 Activate、以及 API 連線欄位（多 PCE 見 [2.3](#23-pce-連線與多-pce)）。
- *Channels*：各告警通道（**mail、LINE、webhook、Telegram、Teams**）的啟用開關與欄位。
- *Display*：timezone、language（English／繁體中文）、theme，及報表輸出目錄／保留天數。
- *Security*：Web UI 密碼（含確認欄，前端先驗證一致性）、IP 允許清單、與 **TLS／HTTPS** 設定（啟用／停用、自簽 vs 自帶憑證、Generate CSR、Import Certificate、Renew）。
  - > **真實副作用**：TLS 的 Renew／Import／Generate CSR 會在 `config/tls/` **產生或覆寫憑證／金鑰檔**，並需**重啟服務**才套用。

### 3.3 高風險動作彙整

下列動作會改變外部系統、資料庫或檔案，操作前請再三確認：

| 動作 | 端點 | 影響 |
|---|---|---|
| Quarantine apply / bulk_apply | `/api/quarantine/apply`、`/bulk_apply` | **在 PCE 對 Workload 加 Quarantine label** |
| Accelerate workload | `/api/workloads/accelerate` | 變更 PCE 遙測頻率 |
| Send Test Alert | `/api/actions/test-alert` | **實際發送**通知到 email／LINE／webhook／Telegram／Teams |
| 手動分析 Run | `/api/actions/run` | 查 PCE 並**可能實際觸發告警** |
| Reset watermark | `/api/actions/reset-watermark` | 清空 event watermark／告警歷史，下次會重抓全部事件並可能重觸發告警 |
| Load Best Practices | `/api/actions/best-practices` | 覆寫／附加告警規則 |
| Rule Scheduler 建立／刪除 | `/api/rule_scheduler/schedules*` | **改寫 PCE rule 註記並切換 rule 啟用** |
| Report 產生／刪除 | `/api/reports/*`、`/api/*_report/generate` | 查 PCE、寫檔／刪檔；勾 Email 會寄信 |
| Cache backfill／retention | `/api/cache/backfill`、`/retention/run` | 查 PCE 寫入 / 永久刪除快取列 |
| SIEM test／DLQ replay／purge | `/api/siem/*` | 送測試事件 / 重送 / 永久刪除 |
| TLS renew／import | `/api/tls/renew`、`/import-cert` | 覆寫憑證檔，需重啟 |
| Stop／Daemon restart | `/api/shutdown`、`/api/daemon/restart` | 停止／重啟服務（持久模式禁用） |

---

## 4. CLI 用法

語法：`illumio-ops [全域旗標] <子命令> [參數...]`。PCE 憑證一律從 `config.json` 讀取，**不接受以旗標傳入**。

**全域旗標**（置於子命令前）：

| 旗標 | 說明 |
|---|---|
| `--json` | 以機器可讀 JSON 輸出 |
| `-q, --quiet` | 抑制非必要輸出（錯誤仍輸出到 stderr） |
| `-v, --verbose` | 詳細輸出（含 debug） |

> `--quiet` 與 `--verbose` 互斥。語言由 `settings.language` 決定，CLI 無 `--lang` 旗標。

**子命令一覽**：

```bash
# 狀態與版本
illumio-ops status                 # daemon／scheduler／config 狀態（支援 --json）
illumio-ops version

# 設定（config set / login 會存檔）
illumio-ops config show [--section api]
illumio-ops config validate [--file PATH]
illumio-ops config set <KEY> <VALUE>           # 例：config set smtp.host smtp.example.com
illumio-ops config login [--url --key --secret --org-id] [--no-interactive]

# PCE cache（backfill 寫入、retention --run 刪除）
illumio-ops cache status
illumio-ops cache backfill --source events|traffic --since YYYY-MM-DD [--until YYYY-MM-DD] [--json]
illumio-ops cache retention [--run]

# 規則（rule edit 會存檔）
illumio-ops rule list [--type event|traffic|bandwidth|volume|system|all] [--enabled-only]
illumio-ops rule edit <RULE_ID> [--no-preview]

# SIEM（test 送事件、replay／purge 改／刪 DB）
illumio-ops siem status
illumio-ops siem test <DESTINATION>
illumio-ops siem dlq    --dest <NAME> [--limit 50]
illumio-ops siem replay --dest <NAME> [--limit 100]
illumio-ops siem purge  --dest <NAME> [--older-than 30]

# Workload（唯讀）
illumio-ops workload list [--env prod] [--limit 50] [--enforcement full|selective|visibility_only|idle|all] [--managed-only]

# 報表（見第 5 章）、互動選單、shell 補全
illumio-ops report <子命令> [...]
illumio-ops shell
illumio-ops completion install bash|zsh|fish
```

> **互動選單限定功能**：TLS 憑證管理、PCE profile 管理、Rule Scheduler 設定**沒有**對應的頂層 CLI 子命令，只能透過 `illumio-ops shell` 進入選單操作（或用 Web GUI）。

**Exit codes**（依 BSD `sysexits.h`）：

| 碼 | 意義 |
|---|---|
| 0 | 成功 |
| 64 | 用法錯誤 |
| 65 | 輸入資料無效（CSV／日期格式） |
| 66 | 輸入檔案不存在 |
| 69 | 服務不可達（PCE／郵件） |
| 70 | 內部錯誤 |
| 71 | OS 層錯誤（權限／mkdir） |
| 78 | 設定檔錯誤 |
| 130 / 143 | 被 Ctrl-C（SIGINT）／kill（SIGTERM） |

---

## 5. 報表

illumio-ops 從即時 PCE 資料或本地 cache 產生多種報表，輸出於 `reports/`。

**報表類型與 CLI 子命令**：

| 報表 | 子命令 | 用途 |
|---|---|---|
| Traffic Flow | `report traffic` | 綜合流量安全分析（policy decisions、ransomware 曝險、lateral movement、enforcement readiness 等 15 個模組） |
| Security & Risk | `report security` | 固定 security_risk 取向；可帶 `--vuln-csv` 納入漏洞掃描（Qualys/Tenable） |
| Network & Traffic Inventory | `report inventory` | 固定 network_inventory 取向的清單型報表 |
| Audit | `report audit` | 稽核事件與 policy 變更（支援 `--start-date`/`--end-date`） |
| VEN Status | `report ven-status` | VEN 狀態（online／offline）盤點，外加 unmanaged workloads（在 Illumio 中，「Unmanaged」是 Workload 狀態——以 IP 標記、未安裝 VEN 的端點——而非 VEN 狀態） |
| Policy Usage | `report policy-usage` | 每條 rule 的命中分析，找出未使用規則 |
| App Summary | `report app-summary --app <APP> [--env --days]` | 單一 App label 的進出向視圖 |
| Policy Resolve | `report resolve` | 把 ACTIVE label-based policy 解析成 IP 層防火牆規則 |
| Policy Diff | `report policy-diff` | DRAFT vs ACTIVE 差異（含 operator 歸因） |

> 早期文件僅列出 traffic／audit/ven-status/policy-usage 四種——v4.1.0 已擴充為上表九種。`report traffic --profile security_risk|network_inventory` 旗標已**棄用**，請改用 `report security`／`report inventory` 子命令。所有報表子命令亦有 `generate-*` 別名（向後相容）。

**輸出格式**：`--format html|csv|pdf|xlsx|all`（預設 `html`）。

| 格式 | 產出 | 備註 |
|---|---|---|
| `html` | 互動式報表（含圖表、側欄導覽） | |
| `csv` | 原始流量資料 zip | 適合 SIEM 匯入 |
| `xlsx` | Excel（每模組一工作表） | |
| `pdf` | **列印就緒的 HTML**（`@media print` A4 版面） | ReportLab PDF 已移除；用瀏覽器「列印成 PDF」 |

**資料來源**：可選 `--data-source hybrid|live|cache-only`（預設 hybrid＝cache + 即時補洞）；`--source api|csv`（`csv` 時須帶 `--file`）。

**範例**：

```bash
illumio-ops report traffic --format html --output-dir /opt/illumio-ops/reports
illumio-ops report audit --start-date 2026-06-01 --end-date 2026-06-26 --format xlsx
illumio-ops report app-summary --app HRM --env production --days 14
illumio-ops report policy-diff --email          # 產生並寄出【會寄信】
```

> **副作用**：所有 `report *` 都會寫出檔案；帶 `--email` 會透過設定的 SMTP 寄送（附報表 HTML，內文為 executive summary 摘要）。

**排程報表**：可在 Web GUI（Reports → Schedules）或 CLI 互動選單建立。可排程的類型涵蓋 traffic／audit／VEN-status／policy-usage；排程於 daemon 執行時觸發，針對當下作用中的 PCE profile。

> **升級後補跑**：升級後首個排程 tick，若某排程今天的目標時刻已過且今天尚未執行過，會補跑一次（catch-up 語意，以一次為限）。

---

## 6. 告警

### 6.1 通道（5 種）

| 通道 | plugin 名 | 必要設定鍵 |
|---|---|---|
| Email（SMTP） | `mail` | `email.sender`、`email.recipients`、`smtp.host`、`smtp.port`（選用 `smtp.user`/`password`/`enable_tls`/`enable_auth`） |
| LINE Messaging API | `line` | `alerts.line_channel_access_token`、`alerts.line_target_id` |
| Webhook | `webhook` | `alerts.webhook_url`（POST JSON，期望 2xx） |
| Telegram Bot | `telegram` | `alerts.telegram_bot_token`、`alerts.telegram_chat_id` |
| Microsoft Teams | `teams` | `alerts.teams_webhook_url`（Power Automate Workflow webhook，送 Adaptive Card） |

啟用哪些通道由 `alerts.active` 清單決定（例如 `["mail", "line"]`）。在 Web GUI **Settings → Channels** 設定各通道並切換啟用。

> 部分舊版文件僅列出 mail/line/webhook 三種、或誤列「Slack」——v4.1.0 實際支援上表 **5 種**（無 Slack）。Teams webhook 內嵌有效機密，日誌中會自動遮蔽。

### 6.2 測試與安全

```bash
# Web GUI：Rules → Actions → Send Test Alert（All）或 Test [通道]
# 或對執行中的 GUI 呼叫（HTTPS :5001）
```

> **副作用提醒（取代舊文件的錯誤範例）**：「Test alert」會**真的發訊息**。Web GUI 的 test-alert 端點是 `POST /api/actions/test-alert`，走 **HTTPS、埠 5001**（舊文件曾誤寫成 `http://localhost:8443`——8443 是 PCE 埠，並非本服務埠）。正式環境測試前請確認收件者，避免誤擾值班。

### 6.3 規則型別速覽

- **Event 規則**：對應 PCE event type（如 `agent.tampering`、`user.sign_in`（failure）、`sec_policy.create`、`workloads.unpair` 等）。內建最佳實務含 16 條 event 規則。
- **Traffic 規則**：如「高 Blocked 流量」——10 分鐘視窗內 ≥ 25 筆 blocked flows 觸發。
- **Bandwidth 規則**：以頻寬（Mbps）或量（MB）門檻觸發。

每條規則可設 `threshold_type`（immediate／count）、`threshold_window`、`cooldown_minutes` 與 `throttle`（`N/Tm`）以抑制告警風暴。

> **營運實務（Illumio 建議）**：請勿孤立地監控 Illumio Core events。應將其視為整體安全工具的其中一項輸入，並與其他來源交叉關聯以取得情境。（來源：Illumio — Events Described。）

---

## 7. SIEM 轉送設定

illumio-ops 可把 PCE 稽核事件與流量記錄轉送到任何 syslog 相容 SIEM、Splunk HEC，或本地 JSON sink。轉送具持久性：事件先入本地 SQLite 派發佇列，失敗會退避重試，超過上限後進入 **DLQ（dead-letter queue）**。

### 7.1 傳輸（transport）與格式（format）

| transport | 協定 | 預設埠 |
|---|---|---|
| `udp` | Syslog UDP | 514 |
| `tcp` | Syslog TCP（自動重連） | 514 |
| `tls` | Syslog TCP + TLS（1.2+，可帶自訂 CA） | 6514 |
| `hec` | Splunk HTTP Event Collector（**僅 HTTPS**） | 8088 |

| format | 輸出 | 適用 |
|---|---|---|
| `cef` | ArcSight CEF 0.1 單行 | ArcSight、QRadar |
| `syslog_cef` | CEF 外包 RFC5424 syslog header | 需要 RFC5424 框架的 syslog 伺服器 |
| `json` | 扁平 JSON（官方 Illumio 欄位名） | Splunk HEC、Elastic、Logstash、檔案 sink |
| `syslog_json` | JSON 外包 RFC5424 header | rsyslog／syslog-ng（mmjsonparse） |

### 7.2 設定 destination

可於 Web GUI（Integrations → SIEM → Add destination）或直接編輯 `config.json › siem.destinations`：

```json
{
  "name": "splunk-prod",
  "transport": "hec",
  "format": "json",
  "host": "splunk.example.com",
  "port": 8088,
  "hec_token": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "tls_verify": true,
  "tls_ca_bundle": null,
  "batch_size": 100,
  "source_types": ["audit", "traffic"],
  "max_retries": 10
}
```

- `source_types`：`audit`（PCE 稽核事件，來源表 `pce_events`）、`traffic`（流量摘要，來源表 `pce_traffic_flows_raw`），或兩者。
- 派發器每 `siem.dispatch_tick_seconds`（預設 5 秒）執行；持續失敗達 `max_retries` 後移入 DLQ（每 destination 上限 `siem.dlq_max_per_dest`，預設 10000）。
- TLS／lab：`tls_verify: false` 僅限開發；自訂私有 CA 用 `tls_ca_bundle` 指向 CA bundle 路徑。

### 7.3 測試、狀態與 DLQ

```bash
illumio-ops siem test <destination>          # 送 siem.test 測試事件並回報延遲【會送事件】
illumio-ops siem status                       # 各 destination 的 pending／sent／failed／DLQ
illumio-ops siem dlq    --dest <name> [--limit N]
illumio-ops siem replay --dest <name> [--limit N]      # 把 DLQ 重新排入 pending【改 DB】
illumio-ops siem purge  --dest <name> [--older-than 30]  # 刪除舊 DLQ（預設 30 天）【刪 DB】
```

> 沒有 `siem flush` 子命令——派發器會依 tick 間隔自動排空。

---

## 8. 維運

### 8.1 PCE cache／保留策略

PCE cache 是**選用**的本地 SQLite（`data/pce_cache.sqlite`，WAL 模式），作為 SIEM 轉發、報表與告警的共享緩衝，**預設停用**（`pce_cache.enabled = false`，停用時一律回退即時 PCE API）。

啟用後（`config.json › pce_cache`）的重點預設：

| 設定 | 預設 | 說明 |
|---|---|---|
| `events_poll_interval_seconds` | 300 | 事件輪詢間隔 |
| `traffic_poll_interval_seconds` | 600 | 流量輪詢間隔（範本值；部分舊文件誤標 3600） |
| `events_retention_days` | 90 | 事件保留 |
| `traffic_raw_retention_days` | 7 | 原始流量保留 |
| `traffic_agg_retention_days` | 90 | 流量彙總保留 |
| `rate_limit_per_minute` | 400 | PCE API 速率上限 |

主要資料表：`pce_events`、`pce_traffic_flows_raw`、`pce_traffic_flows_agg`、`ingestion_watermarks`、`siem_dispatch`、`dead_letter`。

```bash
illumio-ops cache status                      # 各表列數與最後同步時間（不需 daemon）
illumio-ops cache backfill --source events --since 2026-06-01    # 補填歷史
illumio-ops cache retention --run             # 立即執行保留清除
```

> 採增量、watermark 為基的輪詢，無「全量刷新」模式。每日 APScheduler 工作會依 TTL 清除過期列；另有 lag 監控每 60 秒檢查擷取落後並於逾時時記 WARNING/ERROR。

**長期 archive 匯出與長壽 flow 的成長：** archiver（`ArchiveExporter`）會把 `pce_events`／`pce_traffic_flows_raw` 依 `ingested_at` 游標增量匯出成逐日 JSONL 檔。ingestor 的 upsert 現在會在 conflict 時把 `ingested_at` bump 到本次 ingest 時間（只要 re-pull 的 flow 有 volatile 欄位——`last_detected`／`bytes_in`／`bytes_out`／`flow_count`——發生變化），所以一筆持續成長的長壽 flow 會被下一輪 archive 匯出重新撿到，不再永遠停在游標之後。import 端 `ArchiveImporter` 改以 `flow_hash` 為 key upsert，`last_detected`／`bytes_in`／`bytes_out`／`flow_count` 取 MAX 合併（`first_detected` 取 MIN，`raw_json`／`report_json` 取較新 `last_detected` 那一側），因此重複匯入同一 flow 較晚的 export，只會讓 Archive Review DB 重建出的計數往上補齊，不會被凍結或縮小。修復前產生的 archive 檔案，若其中的長壽 flow 在當時仍持續成長，可能仍停在首次匯出的快照值；只要該 flow 之後（在修復後的 ingestor 下）再被 re-pull 一次並匯出，匯入那份較晚的檔案時，MAX 合併會自然把計數追上，不需要手動 backfill。細節見 `src/pce_cache/archive.py`／`archive_import.py` 的 docstring。

### 8.2 更新

見 [1.8 更新流程](#18-更新流程)。要點：原始碼用 `git pull` + `pip install`；離線 bundle 重跑 `install.sh`／`install.ps1`（保留設定）後重啟服務。

### 8.3 備份

```bash
# 設定（含機密，請存放於受控位置）
cp -a /opt/illumio-ops/config /secure-backup/illumio-config-$(date +%Y%m%d)

# PCE cache：用 SQLite backup API 熱備
sqlite3 /opt/illumio-ops/data/pce_cache.sqlite ".backup /backup/pce_cache_$(date +%Y%m%d).sqlite"
# 或停服務後直接複製（避免 WAL 撕裂）
sudo systemctl stop illumio-ops && cp /opt/illumio-ops/data/pce_cache.sqlite /backup/ && sudo systemctl start illumio-ops
```

> cache schema 無內建升級遷移工具——若版本間表結構變動，請刪庫後以 backfill 重建（升級前請看 release notes）。

### 8.4 日誌

| 檔案／來源 | 內容 |
|---|---|
| `logs/illumio_ops.log` | 人類可讀應用日誌（預設 10 MB × 10 份輪替） |
| `logs/illumio_ops.json.log` | 結構化 JSON sink（`logging.json_sink: true` 時啟用） |
| `journalctl -u illumio-ops` | systemd 服務輸出（Linux 正式機） |
| `logs/service_stdout.log` / `service_stderr.log` | Windows NSSM 服務輸出 |

調整等級：`config.json › logging.level` 設為 `ERROR`／`WARNING`／`INFO`／`DEBUG`。

```bash
sudo journalctl -u illumio-ops -f -n 100
tail -f /opt/illumio-ops/logs/illumio_ops.log
```

### 8.5 服務管理

```bash
sudo systemctl restart illumio-ops        # 套用設定變更最常用
sudo systemctl status illumio-ops -l
```

```powershell
Restart-Service IllumioOps
Get-Service IllumioOps
```

### 8.6 TLS 憑證輪替

Web GUI 預設以 **HTTPS** 服務（`web_gui.tls.enabled: true`、`self_signed: true`）。首次啟動若無憑證，會在 `config/tls/` 產生自簽憑證：

| 項目 | 值 |
|---|---|
| 憑證／金鑰 | `config/tls/self_signed.pem`、`self_signed_key.pem` |
| 有效期 | **397 天（約 13 個月，瀏覽器可接受上限）** |
| 預設演算法 | **ECDSA-P256**（若主機缺 `cryptography` 套件則回退 RSA-2048） |
| 自動續期 | `auto_renew: true` 時，每次啟動檢查，剩餘天數 ≤ `auto_renew_days`（預設 30）即自動重簽 |

> 舊文件曾標示「5 年、RSA」——v4.1.0 實際為 **397 天、ECDSA-P256**。

正式環境取得 CA 簽發憑證的流程（Settings → Security → TLS）：Generate CSR → 送 CA → Import Certificate（貼上含鏈的 PEM）→ **重啟服務**。所有憑證變更都需重啟才生效（無 in-process reload）。

### 8.7 反向代理與 IP 允許清單

`web_gui.allowed_ips` 的比對對象是**直接連線的對端 IP**（`request.remote_addr`）。目前程式碼**未套用 ProxyFix**，也不信任 `X-Forwarded-For`。

> **重要安全提醒**：把服務放在反向代理（nginx、HAProxy 等）後方時，所有請求的來源都會是代理的 IP，使內建 IP 允許清單**只會比對到代理位址而失效**。因此請擇一：
> - 在**反向代理層**做來源 IP 限制（建議），或
> - 確保代理保留真實客戶端 IP，並在 WSGI 前自行加入 ProxyFix（信任 1 hop）後，才使用 `allowed_ips`。
>
> 若不確定，最安全的做法是讓 illumio-ops 只綁定 `127.0.0.1`（`--host 127.0.0.1`），由前端代理負責 TLS 與存取控制。

### 8.8 相依套件觀察名單

目前仍可正常運作、但需要留意後續維護動作的套件：

- **flask-talisman**（`requirements.txt` Phase 4，安全 headers）：上游專案已**archived**（不再有後續發版）。目前不是急迫問題——套件本身仍可運作——但應在它真正變成相容性／CVE 風險之前規劃退場路徑。屆時的退場路徑：自寫一個 `after_request` hook（約 100 行），直接設定相同的安全 headers（CSP、HSTS、X-Frame-Options 等），移除此相依套件。

---

## 9. 疑難排解

> 本章整合 `user-guide/troubleshooting.md`，並修正其中已過期的指令。

### 9.1 安裝／啟動

- **Ubuntu/Debian `externally-managed-environment`**：PEP 668 擋系統層 pip；改用 venv（見 [1.5](#15-從原始碼安裝開發測試)）。
- **`ModuleNotFoundError` / 服務啟動即退出**：用對的直譯器跑相依檢查：
  ```bash
  /opt/illumio-ops/python/bin/python3 /opt/illumio-ops/scripts/verify_deps.py
  ```
- **`TypeError: unsupported operand type(s) for |`**：直譯器低於 3.10。離線 bundle 用自帶 CPython 3.12；開發環境重建 venv。
- **systemd 服務啟動失敗**：
  ```bash
  sudo systemctl status illumio-ops -l
  sudo journalctl -u illumio-ops -n 100 --no-pager
  ```
  常見原因：`config.json` 缺失或語法錯（`python3 -m json.tool config.json` 檢查）、`logs/`／`data/` 權限（`chown -R illumio-ops:illumio-ops`）、或埠 5001 被占用（`ss -tlnp | grep 5001`，改用 `gui --port` 換埠）。
  > 修正：舊文件提到改「`settings.port`」並不存在——埠由 `--port` 旗標（或 systemd/NSSM 的啟動參數）控制。

### 9.2 PCE 連線

- **401/403 auth failed**：`api.key`／`secret` 錯或金鑰已撤銷。於 PCE Console 重發金鑰，更新 `config.json` 後 `sudo systemctl restart illumio-ops`。
- **Connection refused／timeout**：檢查網路與埠：
  ```bash
  curl -v --max-time 5 https://pce.example.com:8443/api/v2/health
  ```
- **lab PCE 的 `SSLCertVerificationError`**：設 `"verify_ssl": false`（lab 取捨），或把 PCE CA 裝入系統信任庫。

### 9.3 TLS／憑證

- **瀏覽器 `NET::ERR_CERT_AUTHORITY_INVALID`**：自簽憑證，新安裝屬正常。可接受例外、改用 CA 憑證（Settings → Security → TLS），或部署在 TLS 終結的反向代理後。
- **憑證過期**：自簽用 **Settings → Security → Renew Certificate**（GUI），或於 `illumio-ops shell` 互動選單操作，然後重啟服務。
  > 修正：**沒有** `illumio-ops tls renew` 這個頂層 CLI 子命令；TLS 操作只在 GUI 或互動選單。

### 9.4 報表

- **空報表／無資料**：cache 視窗內無資料。先 `illumio-ops cache backfill --source events|traffic --since <較早日期>`，再以較寬日期重產。
  > 注意：處於 **Idle** policy state 的 workloads 其 traffic flow summaries 會被排除——PCE 不會將其匯出至 syslog——因此 Idle workloads 依設計不會出現在 traffic 報表中。（來源：Illumio Traffic Flow Summaries — Visibility Settings。）
- **Policy Usage 命中為 0**：只查已佈署（active）規則；draft 規則被排除。請先在 PCE 佈署。
- **PDF 中文變方塊**：安裝 CJK 字型（`fonts-noto-cjk` / `google-noto-cjk-fonts`）後重產，或改用 `--format html`。

### 9.5 儀表板資料看似過期

- 儀表板的 snapshot 來自最近一次完成的報表（`/api/dashboard/snapshot` 讀 `reports/` 下的 `latest_snapshot.json`）。**Refresh** 鈕只重新抓取，不會重新產生 snapshot。要更新 snapshot，請實際**產生一份 Traffic（Security Posture）報表**。
  > 修正：舊文件提到的 `illumio-ops report run --format snapshot` **不存在**——v4.1.0 的報表子命令為 `report traffic/security/inventory/audit/...`（見 [第 5 章](#5-報表)）。

### 9.6 SIEM 未收到事件

```bash
illumio-ops siem test <destination>          # 看具體錯誤
```

- `Connection refused`：SIEM 埠錯或 listener 未開——`nc -zv <host> <port>` 驗證。
- `SSL: CERTIFICATE_VERIFY_FAILED`：TLS destination 的 CA 未受信——設 `tls_ca_bundle`，lab 可暫設 `tls_verify: false`。
- UDP 靜默遺失：UDP 無投遞保證，建議改 `tcp` 或 `tls`。

### 9.7 升級時 `git pull` 衝突

正式機曾就地修改受版控檔時，`git pull` 會中止。一次性設定：

```bash
bash scripts/setup-prod-git.sh        # 啟用 merge.autoStash / rebase.autoStash
# 若已失敗：
git stash && git pull && git stash pop
```

### 9.8 回報問題時請附上

```bash
illumio-ops --version
git -C /opt/illumio-ops rev-parse HEAD
grep -n "ERROR\|Exception\|Traceback" /opt/illumio-ops/logs/illumio_ops.log | tail -30
```

> 附設定時請遮蔽 `api.key`／`api.secret` 與所有密碼／token，切勿外洩。

---

## 相關文件

- [Getting Started（安裝快速上手）](getting-started_zh.md)
- [CLI 參考](reference/cli_zh.md)
- [Glossary（詞彙表）](reference/glossary_zh.md)
