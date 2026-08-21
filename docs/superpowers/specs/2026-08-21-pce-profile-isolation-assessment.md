# PCE Profile 資料隔離 — 設計評估

> 狀態：評估，未實作。使用者 2026-08-21 回報「新增 PCE profile 後開啟 cache，新舊資料混在一起，其餘有大量設定也混雜」，要求先做設計評估再決定修法。
> 本檔所有論點皆對當下原始碼查證（HEAD 為 `814deb3f` 之後的工作分支），行號會漂移，以符號為準。

## 1. 問題陳述

這個產品支援多個 PCE profile，但**只有連線憑證是 per-profile 的**。所有由 PCE 衍生出來的資料與狀態都存在單一、全域的命名空間裡。切換 profile 不會切換其中任何一個，也不會清掉任何一個。

結果是：接上第二台 PCE 之後，cache、告警冷卻、排程執行狀態、報表歷史、dashboard 摘要全部是兩台 PCE 的混合物，而且**沒有任何一處會顯示這件事**——這是「失敗與正常長得一樣」那一類的問題。

## 2. 目前的作用域（逐項查證）

### 2.1 真正 per-profile 的

`PceProfile`（`src/config_models.py`）只宣告 `id / url / org_id / key / secret / name`；GUI 另外寫入 `verify_ssl`，靠 `model_config = ConfigDict(extra="allow")` 保留下來，不是正式欄位。

`active_pce_id` 是指向目前 profile 的全域指標；`config.api` 是**目前啟用 profile 的一份全域副本**，不是每個 profile 各自的 runtime config。

### 2.2 切換 profile 時實際發生什麼

`ConfigManager.activate_pce_profile()`（`src/config.py`）只做四件事：找到 profile、把 `url/org_id/key/secret/verify_ssl` 複製進 `config["api"]`、推導 `api.profile=dev|production` 並驗證、寫入 `active_pce_id` 後存檔。

它**沒有**：換 cache DB 路徑、清任何資料表或 watermark、清 `logs/state.json`、換 archive／報表／snapshot 目錄、換告警規則或排程、等待舊 PCE 的 in-flight 工作結束、建立任何「租戶世代」屏障。

最危險的時序：舊 PCE 的 ingest 已開始 → 使用者切 profile → 舊 job 繼續往同一個 DB 寫 → 下一輪新 PCE 的 job 也寫同一個 DB。目前沒有鎖把切換與這些背景工作串行化（`src/scheduler/jobs.py` 的各 job 是在開始執行時才讀 `cfg.db_path` 並建立新的 `ApiClient`）。

### 2.3 全域、但**應該**要 per-profile 的（真正的缺口）

| 類別 | 具體項目 | 為什麼危險 |
|---|---|---|
| Cache 資料 | `PceEvent`（以全域唯一 `pce_href` 去重）、`PceTrafficFlowRaw`（**`flow_hash` 是全域 unique**）、flow observation、每日 aggregate、consumer cursor、SIEM dispatch queue 與 DLQ（`src/pce_cache/models.py`） | 兩台 PCE 若 `flow_hash` 相同會被當成同一筆流量，第二台的資料直接被吞掉——不是混合，是遺失 |
| 擷取位置 | `IngestionWatermark` 的**主鍵只有 `source`**（通常是 `events`／`traffic`）（`src/pce_cache/models.py`、`src/pce_cache/watermark.py`） | 切到新 PCE 後沿用舊 PCE 的時間位置，新 PCE 的歷史資料永遠不會被抓 |
| 封存 | `archive_dir` 只有一個；檔名是 `<source>-<YYYY-MM-DD>.jsonl`，不含 PCE 識別（`src/pce_cache/archive.py`）；archive review DB 固定放在 cache DB 同目錄（`src/pce_cache/archive_import.py`） | 不同 PCE 的同日資料 append 進同一個檔，事後無法拆分 |
| 告警規則 | 全部放在單一 `config/alerts.json`（`src/config.py`） | 為 A 台寫的規則會直接套到 B 台 |
| 告警執行狀態 | 單一 `logs/state.json`：`event_watermark / alert_history / event_seen / throttle / overflow / PCE stats / posture summary / event timeline`（`src/analyzer.py`）。`alert_history` 以 rule id 為 key，沒有 PCE 維度 | 切換後同一條規則的冷卻直接沿用，新 PCE 的第一次告警可能被靜默壓掉 |
| 規則排程 | 共用 `config/rule_schedules.json`（`src/rule_scheduler.py`），執行狀態共用 `logs/state.json["rule_schedule_states"]` | **最危險的一項**：排程裡存的是 PCE 物件的 href/id，切換後可能拿舊 PCE 的 href 去新 PCE 上執行 |
| 報表排程與輸出 | `report_schedules` 是單一陣列；`output_dir`、KPI history（`src/report/trend_store.py`）、flow baseline（`src/report/flow_history.py`）皆無 PCE 維度；`latest_snapshot.json`、`latest_audit_summary.json`、`latest_policy_usage_summary.json` 是固定檔名 | 下一台 PCE 的報表直接覆蓋上一台的；趨勢圖會把兩台的數字接成一條線 |
| 其他衍生快取 | `logs/dashboard_summary.json`（VEN inventory/health）、`logs/async_query_jobs.json`（PCE async job href）、`logs/job_health.json`、`data/ransomware_posture_cache.json`（以 workload href 為 key，不同 org 的相同 href 會碰撞） | 切換後在下次刷新前顯示的是舊 PCE 的數字 |

> 注意 `src/report/snapshot_store.py` 的檔名裡有 `profile`，但那是**報表 profile**（`security_risk` / `traffic` 之類），不是 PCE profile。容易誤讀。

### 2.4 全域、而且**本來就應該**全域的

GUI 帳密與 TLS、logging、語言／佈景／時區、告警管道與 SMTP、SIEM destination、dashboard queries。這些是 installation 層級的設定，共用是對的。把它們也切成 per-profile 只會增加操作負擔。

**所以使用者說的「其餘大量設定也混雜」是對的，但不是全部都該分——真正必須 tenant-aware 的是 §2.3 那張表。**

## 3. 三個修法

### (i) DB 路徑帶 profile id — **建議**

**做法**：把 `models.pce_cache.db_path` 從「一個檔案路徑」改成「一個 resolver」，以 `profile.id`（不是 name——rename 會讓資料看起來消失）派生實際檔名。

**成本：中低。** schema、查詢、unique constraint 幾乎不用改；events / flows / observations / aggregates / watermarks / cursors / SIEM dispatch / DLQ 會整組自然隔離。既有的 engine cache 已經以 `db_path` 為 key（`src/gui/_helpers.py`），schema-once cache 也是（`src/pce_cache/schema.py`），架構上本來就容得下多個 DB。

**必須全部改到的讀取點**（漏一個就等於沒隔離）：
- analyzer 的 subscriber / cache / delta reader：`src/main.py`
- ingest、aggregate、retention、archive、capacity、SIEM dispatch：`src/scheduler/jobs.py`
- cache / SIEM / dashboard Web：`src/pce_cache/web.py`、`src/siem/web.py`、`src/gui/routes/dashboard.py`
- CLI：`src/pce_cache_cli.py`、`src/siem_cli.py`
- archive review DB：`src/pce_cache/archive_import.py`
- lag / capacity 監控：`src/pce_cache/lag_monitor.py`、`src/pce_cache/capacity.py`

**風險**：既有 DB 已經混合，**無法可靠判斷每一列屬於哪台 PCE**。遷移只能「把整個既有 DB 明確指派給某一個 profile，其他 profile 從空 DB 重抓」——不能宣稱能自動拆分。刪除 profile 時要明確決定保留／封存／刪除它的 DB，不可暗中刪檔。

**限制**：這只解決 SQLite 內的資料。archive、rules、schedules、reports、state、dashboard、async jobs 仍須另外用 profile id 分目錄或加外層 namespace。

### (ii) 每張表加 tenant 欄位

**成本最高、漏條件風險最大。** 所有表都要加 `pce_profile_id`，所有唯一鍵要改成複合鍵（`(tenant, pce_href)`、`(tenant, flow_hash)`、aggregate unique key、cursor/watermark PK）；reader、subscriber、aggregator、retention、flow delta、archive、SIEM enqueue/DLQ、dashboard query 的**每一條 SQL 都要加 tenant predicate，漏一條就重新造成跨 PCE 洩漏**。SQLite 改 unique constraint 不是 `ADD COLUMN` 能解決的，要建新表搬資料重建索引；現有 migration 框架（`src/pce_cache/schema.py`）主要處理補欄位與補索引，沒有 tenant backfill。而且同樣無法從已混合的 DB 推導 tenant。

換來的好處是「單一 DB 可做跨 tenant 管理查詢」——目前產品沒有這個需求。

### (iii) 切換時強制清空 cache

**改碼表面最少，但不構成隔離。** 要清的不只 event/traffic，還有 observation、aggregate、watermark、cursor、SIEM queue、DLQ；只刪主表會讓新 PCE 沿用舊 watermark、或留下指向已消失資料列的 queue。而且必須先停掉或 drain ingest / monitor / archive / retention / SIEM job，否則清空後正在跑的舊 job 會把舊資料寫回去。這是不可逆的資料破壞，每次切換都失去歷史並觸發重新 backfill，大型 cache 的 delete/VACUUM 還可能長時間鎖住 SQLite。它也完全不處理 archive、state、rules、schedules、reports——使用者說的「其餘大量設定混雜」原封不動。

**定位**：最多做成明示、需確認的緊急止血操作，不是多 PCE 架構。

## 4. 建議

採 **(i)**，並把 `profile.id` 提升為**所有 PCE 衍生狀態**的 namespace，分階段：

- **階段 1（止血＋隔離資料）**：cache DB 路徑帶 profile id；同階段一併隔離 `logs/state.json`、`config/rule_schedules.json`、archive 目錄、報表輸出與 history、`dashboard_summary.json`、`async_query_jobs.json`。理由是資料靜默混合與唯一鍵碰撞最危險，而且這幾項彼此有語意耦合（排程存 href、state 存 cooldown），只分一半會留下更難查的錯配。
- **階段 2（告警規則作用域）**：`config/alerts.json` 是否 per-profile 需要使用者裁決——同一套規則套到多台 PCE 可能是刻意的。
- **不動**：GUI 帳密／TLS／logging／通知管道／SIEM destination 維持 installation-global。

**遷移必須明講**：既有資料無法自動拆分。升級時把現有 cache／state／archive 整批指派給目前的 active profile，其餘 profile 從零開始。這一點要寫進 CHANGELOG 與升級說明，不能靜默處理。

**先於實作要補的守門**：一條「PCE 衍生狀態的路徑一律經過 profile resolver」的不變量測試（AST 或 grep 式），否則第 N 個新讀取點會再度直接讀 `cfg.db_path`。這正是 §3(i) 風險欄裡「漏一個就等於沒隔離」的機器化版本。

## 5. 尚未評估

- PCE profile 刪除時的資料生命週期（保留／封存／刪除）的 UI 與 CLI 流程
- 多 profile 同時擷取（目前架構是「只有 active profile 會被背景工作使用」）是否為需求
- 報表是否需要「跨 profile 比較」視圖——若需要，(ii) 的價值會重新浮現
