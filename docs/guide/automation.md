---
title: 自動化：規則排程、隔離操作與背景 Job
audience: [operator]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - src/rule_scheduler.py
  - src/gui/routes/rule_scheduler.py
  - src/rule_scheduler_cli.py
  - src/static/js/rule-scheduler.js
  - src/cli/menus/_root.py
  - src/scheduler/__init__.py
  - src/scheduler/jobs.py
  - src/job_health.py
  - src/gui/routes/actions.py
  - src/api_client.py
  - src/cli/workload.py
  - src/module_log.py
  - config/config.json.example
---

# 自動化：規則排程、隔離操作與背景 Job

本篇涵蓋 illumio-ops 會**主動改變 PCE 狀態**的兩套自動化能力——Rule Scheduler（規則排程）與
Quarantine（隔離）——以及支撐整個系統的背景排程 job 總表。兩者都是「真實副作用」操作：
Rule Scheduler 會改寫 PCE 上的 rule 啟用旗標與 description，Quarantine 會改變 Workload 的
enforcement。GUI 逐分頁操作步驟見 [gui-tour.md](gui-tour.md) 的「Rule Scheduler」與
「Quarantine」兩節；本篇從自動化機制與安全約束角度補充細節。

---

## 1. Rule Scheduler（規則排程）

### 1.1 用途

Rule Scheduler 讓操作者為 PCE 上**已佈署（Active）**的 Ruleset 或單一 Rule 設定時間表，
到點自動切換其 `enabled` 旗標並 provision。典型用途：只在維護窗口內開放某條規則、或讓一條
臨時性 allow 規則在指定期限後自動失效並移除。

- 核心引擎：`src/rule_scheduler.py`（`ScheduleDB` 存取排程資料、`ScheduleEngine.check()`
  逐一比對排程與 PCE 目前狀態並觸發切換）。
- GUI：`src/gui/routes/rule_scheduler.py`（`/api/rule_scheduler/*`），對應 [gui-tour.md](gui-tour.md)
  「Rule Scheduler」分頁的 Browse／Schedules／Logs 三個子頁。
- CLI：`src/rule_scheduler_cli.py`（`illumio-ops rule`，互動選單），提供與 GUI 對等的
  瀏覽、建立、編輯、刪除功能，另外多一個「立即執行一次 check」的除錯選項。

### 1.2 排程資料儲存

排程存在 `config/rule_schedules.json`（GUI／CLI 共用同一份檔案；GUI 端路徑由
`_resolve_config_dir()` 決定，CLI 端固定為專案根目錄下的 `config/rule_schedules.json`），
以 rule／ruleset 的 href 為 key，`ScheduleDB` 用 tmp 檔 + `os.replace` 原子寫入，寫入失敗
直接拋出、不做靜默 fallback。每筆排程的欄位：

| 欄位 | 說明 |
|---|---|
| `type` | `recurring`（週期性時窗）或 `one_time`（到期即失效） |
| `name` / `detail_name` | 顯示名稱 |
| `is_ruleset` | 目標是整個 Ruleset（`true`）還是單一 Rule（`false`） |
| `action` | `allow`（時窗內啟用）或 `block`／`disable`（時窗內停用，語意相反） |
| `days`／`start`／`end`／`timezone` | `recurring` 專用：星期清單、起訖時間（`HH:MM`）、時區 |
| `expire_at` | `one_time` 專用：到期時間（ISO 格式） |
| `detail_rs`／`detail_src`／`detail_dst`／`detail_svc` | 目標所屬 Ruleset 名稱與來源/目的/服務摘要，僅供列表顯示 |
| `pce_status` | 引擎執行時維護，PCE 上該目標若回 404 會標記為 `deleted`，之後又查得到會自動清回 `active` |

排程建立時，引擎會把一段**固定英文**的排程註記寫入 PCE 該 rule 的 `description` 欄位——recurring
類型的註記開頭帶行事曆符號（U+1F4C5）：`[Recurring: Mon,Tue,Wed 08:00-18:00 (UTC+8) Enable in
window]`；one_time 類型的註記內容格式為 `[Expires: 2026-08-01 00:00]`，開頭符號依建立來源不同
而異（見下段說明）。**註記固定用英文**，不論 GUI／CLI 當下顯示語言為何——因為這段文字會落在
PCE 的 description 裡，日後被 Policy Usage／Audit 等報表原樣讀出，用操作者當下語言寫入會汙染
其他語言的報表輸出。

刪除排程或到期失效時，引擎會清除該註記：清除樣式（`update_rule_note` 內的 strip regex，
`src/api_client.py`；CLI 顯示端另有一份同樣式的 truncate 邏輯，`src/rule_scheduler.py`）
匹配三種前綴——行事曆符號（U+1F4C5，recurring，GUI／CLI 共用）、沙漏符號（U+23F3，CLI
one_time，`src/rule_scheduler_cli.py`）與鬧鐘符號（U+23F0，GUI one_time，
`src/gui/routes/rule_scheduler.py`）。歷史注意：2026-07-17 之前的版本清除樣式漏認鬧鐘符號，
GUI 建立的一次性註記刪除／到期都清不掉；已修復（守門測試 `tests/test_rule_note_tag_strip.py`），
但**修復前殘留在 PCE description 的舊註記不會被回溯清理**——看到殘留註記時，對該 rule 再建立
並刪除一次排程（或手動編輯 description）即可清掉。

### 1.3 時窗語意

`ScheduleEngine.check()` 每次執行（見下方「背景排程 job 總表」的 `tick_rule_schedules`）都會
重新計算每筆排程「此刻應該是 enabled 還是 disabled」（`target`），再與 PCE 上的即時狀態比對，
不一致才動作：

- **recurring**：`start <= end` 時是一般時窗（例如 `08:00`–`18:00`）；`start > end` 時視為
  跨午夜時窗（例如 `22:00`–`06:00`），同時比對「今天在時窗起點之後」與「昨天延續到今天時窗
  終點之前」兩種情形。`action=allow` 時，時窗內 `target=True`（啟用）；`action` 為停用類時
  語意相反，時窗內 `target=False`。
- **one_time**：到期前 `target=True`（維持啟用）；一旦當下時間超過 `expire_at`，引擎立即把
  目標**停用並 provision**、嘗試清除 PCE 上的排程註記（`src/rule_scheduler.py:288` 呼叫
  `update_rule_note(href, "", remove=True)`）、把這筆排程從 `rule_schedules.json` 刪除
  （過期排程不會留在清單裡）。清除對 GUI（鬧鐘符號前綴）與 CLI（沙漏符號前綴）建立的
  一次性註記皆生效（2026-07-17 起；更早版本殘留的舊註記處理方式見上節）。
- **Draft 狀態一律跳過**：比對前會先呼叫 `has_draft_changes(href)`，只要目標（或其所屬
  Ruleset）在 PCE 上有未佈署的草稿變更，本輪直接跳過、不做任何切換，避免排程動作疊加在
  未審核的變更之上。
- **目標在 PCE 上被刪除**（`get_live_item` 回 404）：只記一筆 `[SKIP] ... not found` 的
  警告 log 並把 `pce_status` 標為 `deleted`，不會嘗試重建或報錯中止其他排程。
- 每輪執行結果（`last_checked`／`last_action`／`last_result`／`error`）寫入
  `logs/state.json` 的 `rule_schedule_states` key，是 GUI「Schedules」子頁與
  `/api/rule_scheduler/schedules` 端點顯示 last-run 狀態的資料來源。

「下一次會觸發的排程」由 `compute_next_trigger()` 純函式算出：recurring 找未來 7 天內最近一次
`days`＋`start` 命中時刻，one_time 直接看 `expire_at`，兩者取最小值，供 GUI 狀態卡顯示與
`/api/rule_scheduler/status` 端點使用。

### 1.4 建立排程

- **GUI**（Browse 子頁）：搜尋或瀏覽 Ruleset → 選擇整個 Ruleset 或其中一條 Rule → 選
  Recurring（星期＋起訖時間＋時區）或 One-time（到期時間）→ 選 Action（`allow` 或
  `disable`）→ 送出 `POST /api/rule_scheduler/schedules`。
- **CLI**（`illumio-ops rule` → Schedule Management → `a` Browse）：流程與 GUI 對等，多一層
  文字選單導覽；輸入格式錯誤（時間非 `HH:MM`、`start >= end`、到期時間非 ISO 格式）在送出前
  就地擋下並提示重新輸入。
- 兩者建立前都會呼叫 `has_draft_changes` / `is_provisioned` 擋下**未佈署（Draft）**的目標，
  回傳明確錯誤訊息（GUI：`rs_sch_draft_block`；CLI：同一段文案）——**必須先在 PCE 上佈署該
  Ruleset／Rule，排程才能建立**。

### 1.5 安全約束（Sacred Constraints）

以下約束經過多輪驗證鎖定，修改前務必確認不會破壞：

1. **排程功能未啟用時只會顯示 warning，絕不自動幫你 enable。**
   `rule_scheduler.enabled`（`config.json`，schema 預設 `true`，範本 `config.json.example`
   明確寫成 `false`）**只是一個顯示用狀態旗標**——CLI 主選單狀態列
   （`src/cli/menus/_root.py`）與 CLI 設定子選單（`rule_scheduler_cli.py`
   `_settings_submenu`）都只讀它來顯示 ON/OFF，全庫沒有任何程式路徑會在偵測到它是
   `false` 時自動把它改回 `true`——切換永遠要操作者手動執行（CLI 設定子選單選項 1）。
   **反過來也要注意**：`build_scheduler()`（`src/scheduler/__init__.py`）註冊
   `tick_rule_schedules` job 時**不會讀這個旗標**，只讀 `check_interval_seconds`——也就是
   說背景排程檢查迴圈本身**不受這個旗標控制、一律執行**，這個旗標目前只是給操作者看的狀態
   指示，不是一個真正的總開關。若日後要把它改造成真正的 kill switch，必須同時改
   `scheduler/__init__.py` 的註冊條件，否則會與 UI 顯示的狀態矛盾。
2. **刪除排程在 CLI 與 GUI 都要求一次明確確認**（CLI/GUI 雙顯式確認）：CLI 多筆刪除
   （`_delete_by_ids`）送出前要求輸入 `y` 確認、列出待刪清單與數量；GUI 刪除排程送出前
   跳出瀏覽器原生 `confirm()`（`gui_rs_confirm_delete`，文案含筆數）。兩邊都不存在「勾選即
   刪」的無確認路徑。
3. **排程器不會自動佈署 Ruleset／Rule**：它只在目標已是 Active（非 Draft）狀態下切換
   `enabled` 旗標並呼叫 provision API，佈署（把 Draft 變 Active）永遠是操作者在 PCE 或
   本專案其他流程中另行處理的事，Rule Scheduler 只負責「已佈署規則」的啟用/停用時間表。
4. **Quarantine 沒有 CLI 對應命令**：`illumio-ops workload` 子命令目前只有 `list`（瀏覽
   Workload），套用/解除隔離只能透過 GUI 的 `/api/quarantine/*` 端點操作，CLI 無法繞過
   GUI 的雙層確認流程直接隔離。

---

## 2. Quarantine（隔離）

Quarantine 是**只存在於 GUI** 的高風險操作：對指定 Workload 附加一個 `Quarantine` label
（值為 `Mild`／`Moderate`／`Severe` 三選一），立即改變其 enforcement；解除則移除該 label、
保留其餘 label 不變。完整操作步驟（modal、severity 選擇、二次確認畫面）見
[gui-tour.md](gui-tour.md) 的「Quarantine（隔離）——雙重確認流程」一節，本節聚焦後端機制與
稽核紀錄。

### 2.1 套用（Apply）

- 端點：`POST /api/quarantine/apply`（單一目標）／`POST /api/quarantine/bulk_apply`
  （多目標，`concurrent.futures.ThreadPoolExecutor(max_workers=5)` 並行處理，最多 5 個
  worker）。
- 首次使用會透過 `check_and_create_quarantine_labels()`（`src/api_client.py`）確保 PCE 上
  存在 `Quarantine` 這個 label key 的三個值 `Mild`／`Moderate`／`Severe`，不存在就自動建立。
- 套用邏輯：取得 Workload 現有 label 清單，過濾掉任何既有的 Quarantine label（三個值都會被
  濾除），append 選定 severity 對應的那一個——**同一 Workload 永遠只會有一個 Quarantine
  label**，重複套用等於「換一個嚴重度」，不會疊加多個。

### 2.2 解除（Lift）

- 端點：`POST /api/quarantine/lift`。
- 因為套用階段是「附加」而非「取代整份 label 清單」，解除只需把目前三個 Quarantine label
  href 從 Workload 的 label 清單中過濾掉即可，**不需要還原機制**、也不會動到其餘 label
  （env、role、app 等維持原樣）。
- Bulk lift 會分辨三種結果：`success`（成功移除）、`not_quarantined`（該 Workload 本來就沒有
  Quarantine label，過濾前後 label 數不變，視為不算失敗的 no-op）、`failed`（API 呼叫失敗）。

### 2.3 影響範圍

| 操作 | 對 PCE 的實際影響 |
|---|---|
| Apply | 覆蓋套用選定 severity 的 `Quarantine` label，立即改變該 Workload 的 enforcement，直到手動解除 |
| Bulk apply | 同上，逐一套用到多個 Workload；單一失敗不影響其他目標（各自獨立呼叫、各自記錄結果） |
| Lift | 移除 Quarantine label，enforcement 回到其餘 label 決定的原本狀態 |

Apply／Lift 都不會做「延時自動解除」——一旦套用，Quarantine 狀態會一直維持到操作者手動按
Lift 為止，沒有 TTL 或排程到期機制（與 Rule Scheduler 的 `one_time` 到期自動失效是不同的
兩套機制，不要混淆）。

### 2.4 稽核紀錄

每次 Apply／Bulk apply／Lift 都會呼叫 `_audit_action()`（`src/gui/routes/actions.py`），寫入
一行到 `logs/modules/actions.log`（`ModuleLog.get("actions")`），內容含操作類型、操作帳號
（session 使用者，讀不到則記 `?`）、目標 href（或數量統計）、severity、結果。**這是
best-effort 稽核**：寫入本身若失敗（例如磁碟問題）會被吞掉、絕不會因此擋下已經生效的
Quarantine 操作——也就是說稽核紀錄可能漏記，但實際的 label 變更不會因為記錄失敗而回滾或
被擋下。稽核紀錄目前只落地檔案，沒有另外的 GUI 檢視頁面；要查閱請直接看
`logs/modules/actions.log`（GUI 頁首 Operations → Logs 可開啟維運日誌檢視窗，含此檔內容）。

### 2.5 與 CLI 的關係

`illumio-ops workload list` 可用來瀏覽/搜尋 Workload（依 env label、enforcement mode、
managed-only 等條件過濾），適合在套用隔離前先確認目標範圍，但**該命令本身不具備套用或解除
隔離的能力**——隔離動作必須回到 GUI 執行，這是刻意的設計（見上方安全約束第 4 條），避免
CLI 腳本或自動化流程繞過 GUI 的雙層確認直接對 PCE 下隔離指令。

---

## 3. 背景排程 job 總表

daemon 啟動時（`--monitor`／`--monitor-gui`）由 `src/scheduler/__init__.py:build_scheduler`
統一註冊全部背景 job；純 GUI 模式（`--gui`，不含 daemon）不會註冊任何 job。每個 job 都包一層
`_instrument` wrapper：註冊當下先寫 `registered` 記錄，之後每次執行完寫 `ok`/`error` 到
`logs/job_health.json`（`src/job_health.py`），**job id 本身就是 `logs/job_health.json` 裡的
key**——例如 `tick_rule_schedules` job 的健康狀態就存在 `job_health.json` 的
`"tick_rule_schedules"` 這個 key 下，兩者一一對應、不需要另外的對照表。GUI Integrations →
Overview 的 Job Health 表格即讀取這份檔案，never-ran／overdue 的判讀規則見
[gui-tour.md](gui-tour.md) 「Integrations」一節。

全部條件開啟時共 **14 個**註冊 job（與 [architecture.md](../handover/architecture.md) §5.2
的清單一致，兩篇互不矛盾）：

| Job id | 職責 | 間隔（預設） | 註冊條件 |
|---|---|---|---|
| `monitor_cycle` | 監控分析＋告警派送 | cache 啟用 30s，否則設定分鐘數 | 一律 |
| `tick_report_schedules` | 報表排程 tick | 60s | 一律 |
| `tick_rule_schedules` | Rule Scheduler 檢查與切換（本篇 §1） | `rule_scheduler.check_interval_seconds`（預設 300s） | 一律（不受 `rule_scheduler.enabled` 旗標影響，見 §1.5） |
| `ven_summary` | VEN 健康摘要寫入 store | 300s（可設定） | 一律 |
| `posture_summary` | Security Posture 分數摘要 | 600s（可設定） | 一律 |
| `tls_renew_check` | self-signed 憑證到期檢查與換發 | 24h | TLS 啟用＋自簽＋`auto_renew` |
| `pce_cache_ingest_events` | 事件 ingest 進 cache | `events_poll_interval_seconds` | pce_cache 啟用 |
| `pce_cache_ingest_traffic` | 流量 ingest 進 cache | `traffic_poll_interval_seconds` | pce_cache 啟用 |
| `pce_cache_aggregate` | 流量聚合表更新 | 1h | pce_cache 啟用 |
| `pce_cache_retention` | cache 保留清理（永久刪除過期列） | 24h | pce_cache 啟用 |
| `cache_lag_monitor` | ingest 落後偵測＋告警 | 60s | pce_cache 啟用 |
| `pce_cache_capacity_monitor` | DB 大小／磁碟／佇列容量監控（唯讀） | 30m | pce_cache 啟用 |
| `pce_cache_archive` | cache 增量封存成分日 JSONL | `archive_interval_hours` | pce_cache＋archive 皆啟用 |
| `siem_dispatch` | SIEM 佇列派送 | `dispatch_tick_seconds` | SIEM 啟用 |

- 5 個一律註冊，其餘 9 個依設定條件啟用（TLS 1 個、pce_cache 系 7 個、SIEM 1 個）；本篇
  只涉及 `tick_rule_schedules`，其餘 job 的資料流細節分別屬於 [cache-maintenance.md](cache-maintenance.md)、
  [siem.md](siem.md)、[monitoring-alerts.md](monitoring-alerts.md)、[troubleshooting.md](troubleshooting.md)（見各篇說明）。
- 所有會寫 cache DB 的 job 走專用單一 worker 的 `cache_writer` executor（序列化寫入，避免
  SQLite 寫鎖互撞）；其餘（含 `tick_rule_schedules`）走預設的 5-worker executor。
- 長間隔 job（`tls_renew_check`、`pce_cache_aggregate`、`pce_cache_retention`、
  `pce_cache_archive`、`pce_cache_capacity_monitor`）一律帶啟動後錯開的首跑 kick
  （`next_run_time`），避免 APScheduler `IntervalTrigger` 預設「首跑排在啟動後一整個間隔」
  在頻繁重啟部署下永遠跑不到（2026-07-14 archive 事故的根治對策）。`tick_rule_schedules`
  本身間隔較短（預設 300s），同樣有 40 秒的首跑 kick。

---

## 延伸閱讀

- Rule Scheduler／Quarantine 的 GUI 操作步驟與畫面元素：[gui-tour.md](gui-tour.md)
- `rule_scheduler` 與 `scheduler` 設定鍵完整說明：[configuration.md](configuration.md)
- 架構總覽與模組地圖：[architecture.md](../handover/architecture.md)
- job never-ran／overdue 判讀與故障排除：見 [troubleshooting.md](troubleshooting.md)
- pce_cache 系 job（ingest／aggregate／retention／archive）的容量與維運細節：見
  [cache-maintenance.md](cache-maintenance.md)
- SIEM dispatch job 與 DLQ：見 [siem.md](siem.md)
