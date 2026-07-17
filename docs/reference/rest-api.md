---
title: REST API 參考
audience: [developer, operator]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - src/gui/__init__.py
  - src/gui/routes/__init__.py
  - src/gui/routes/auth.py
  - src/gui/routes/admin.py
  - src/gui/routes/dashboard.py
  - src/gui/routes/events.py
  - src/gui/routes/filter_objects.py
  - src/gui/routes/reports.py
  - src/gui/routes/rule_scheduler.py
  - src/gui/routes/rules.py
  - src/gui/routes/actions.py
  - src/gui/routes/config.py
  - src/siem/web.py
  - src/pce_cache/web.py
  - src/auth_models.py
  - src/cli/gui_cmd.py
---

# REST API 參考

本篇涵蓋 illumio-ops Web GUI 的完整 JSON API 端點清單，全部由 Flask 應用（`src/gui/`
+ 兩個獨立掛載的藍圖 `src/siem/web.py`、`src/pce_cache/web.py`）提供。實數為
**117 個路由**（`@*.route(...)` 宣告數，含頁面路由），其中 113 個是 `/api/` JSON
端點；每個端點依 GUI 分頁分區列出，欄位為方法｜路徑｜用途｜關鍵參數。各分頁的操作情境與畫面說明見
[guide/gui-tour.md](../guide/gui-tour.md)；本篇只列端點語法。

GUI 監聽埠見 `illumio-ops gui` 的 `--port`，預設 **5001**（`src/cli/gui_cmd.py`）；
`web_gui.tls.enabled` 開啟時走 HTTPS，否則 HTTP。基底 URL 範例：

```
https://127.0.0.1:5001
```

自簽憑證安裝需要 `curl -k`（或 `--cacert`）略過憑證驗證。TLS 設定細節見
[configuration.md](../guide/configuration.md)。

---

## 認證與 session

GUI 使用 **session cookie**（Flask-Login）＋ **CSRF token**（Flask-WTF）；沒有獨立的
API key 機制（PCE 端的 API key/secret 是另一回事，見下方「版本化」一節）。

認證是由 `src/gui/__init__.py` 的一個 `before_request` 全域守門（`security_check()`）
統一把關，不是逐路由裝飾器；順序如下：

1. **IP 允許清單檢查**（`web_gui.allowed_ips`）：比對 `request.remote_addr`，對**所有**
   路徑套用（含 `/static/`），套用時機在認證**之前**。不在清單內的連線直接以 TCP RST
   斷線，**不回任何 HTTP 回應**（避免 port scanner 偵測到這是一個 HTTP 服務）。
2. **靜態檔案**（`/static/*`）通過 IP 檢查後直接放行，不需要 session。
3. **公開路徑**（不需 session，僅需通過 IP 檢查）：

   | 方法 | 路徑 |
   |---|---|
   | GET | `/api/csrf-token` |
   | GET | `/login` |
   | POST | `/api/login` |
   | POST | `/logout` |

4. 其餘所有路徑要求 `current_user.is_authenticated`；未登入時 `/api/` 開頭回 `401`
   JSON，其餘路徑 `302` 導向 `/login`。
5. **`must_change_password` 閘門**：`web_gui.must_change_password` 為真時，除
   `GET/POST /api/security`、`POST /logout`、`GET /api/csrf-token` 外，所有請求一律
   回 `423`（`{"ok": false, "error": "must_change_password", "code": 423}`）。此欄位
   預設 `false`（`src/config_models.py` `must_change_password: bool = False`）——機制
   已實作但目前未在任何流程中被自動設為 `true`；僅供未來「強制首登改密碼」情境使用。

每次登入後的呼叫需要：

- **Session cookie**：`POST /api/login` 成功後由 Flask-Login 設定，`HttpOnly`、
  `SameSite=Strict`、TLS 安裝時另加 `Secure`。存活期預設 **8 小時**
  （`web_gui.session_lifetime_seconds`，預設 28800 秒），與 CSRF token 的
  `WTF_CSRF_TIME_LIMIT` 使用同一個值。
- **CSRF token**：每個會修改狀態的請求（`POST`／`PUT`／`DELETE`）都要帶。可用
  `X-CSRFToken` 或 `X-CSRF-Token` 兩種標頭之一（`WTF_CSRF_HEADERS` 同時允許兩種寫法，
  前者是 flask-wtf 預設、後者是舊版前端沿用的名稱）。先呼叫 `GET /api/csrf-token`
  取得。

`POST /api/login` 對 CSRF 免疫（登入當下還沒有 token）、限流 **5 次／分鐘**；驗證帳密時
兩個比較（帳號、密碼）都會完整跑完才判斷成敗，避免用回應時間差推斷帳號是否存在。

**登入流程範例：**

```bash
BASE="https://127.0.0.1:5001"          # 自簽憑證加 curl -k

# 1. 取得 CSRF token
CSRF=$(curl -sk -c cookies.txt "$BASE/api/csrf-token" | python3 -c "import sys,json; print(json.load(sys.stdin)['csrf_token'])")

# 2. 登入
curl -sk -b cookies.txt -c cookies.txt "$BASE/api/login" \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" \
  -d '{"username":"illumio","password":"<password>"}'

# 3. 用同一組 cookie 呼叫其他端點
curl -sk -b cookies.txt "$BASE/api/status"
```

**CSRF token 過期或無效**時回 `400`：

```json
{ "ok": false, "code": "csrf_error", "error": "...", "csrf_token": "<new_token>" }
```

回應內附一個新 token；用它重試原本的請求即可，不需要重新登入。

> **沒有獨立 API key 認證。** 設定裡的 PCE `key`／`secret` 是 illumio-ops 呼叫 **PCE**
> 用的憑證，跟登入這個 GUI 完全是兩件事。

---

## 端點總覽（依 GUI 分頁分區）

以下所有路徑皆相對於基底 URL；除上一節列出的公開路徑外，每個端點都需要已登入的
session。有獨立限流的端點會在「關鍵參數」欄位標出（超出全域限流 300 次／分鐘，見文末
「限流彙整」）。

### 1) 認證與 session（`src/gui/routes/auth.py`）

| 方法 | 路徑 | 用途 | 關鍵參數 |
|---|---|---|---|
| GET | `/api/csrf-token` | 取得新的 CSRF token | 公開 |
| GET | `/` | SPA 殼頁（`index.html`），回傳 HTML 而非 JSON | 需登入 |
| GET | `/login` | 登入頁（`login.html`） | 公開 |
| POST | `/api/login` | 登入，設定 session cookie | `username`, `password`；公開、CSRF 免疫、5/分鐘 |
| POST | `/logout` | 登出、清 session，`302` 導回 `/login` | 公開 |

**`POST /api/login`** 成功回應：`{"ok": true, "csrf_token": "...", "must_change_password": false}`；
失敗回 `401` `{"ok": false, "error": "..."}`。

### 2) Dashboard 分頁（`src/gui/routes/dashboard.py`）

| 方法 | 路徑 | 用途 | 關鍵參數 |
|---|---|---|---|
| GET | `/api/ui_translations` | 目前語言的前端 i18n 字串表 | — |
| GET | `/api/status` | daemon／版本狀態、規則冷卻剩餘分鐘、事件 watermark、告警通道摘要 | — |
| GET | `/api/dashboard/overview` | Dashboard 總覽磚塊快照：`ven`／`blocked`／`pipeline`／`alerts`／`os_dist`／`enforcement`／`posture`／`job_health`／`tls` | — |
| GET | `/api/dashboard/queries` | 列出已儲存的 Dashboard 查詢 | — |
| POST | `/api/dashboard/queries` | 新增或更新一筆 Dashboard 查詢（支援 FilterBar 物件篩選鍵） | `idx`（更新用）, `name`, `rank_by`, `pd`, `filters{...}` |
| DELETE | `/api/dashboard/queries/<idx>` | 依索引刪除 Dashboard 查詢 | — |
| GET | `/api/dashboard/snapshot` | 最近一次 Traffic 報表快照（含首頁 hero 卡） | — |
| GET | `/api/dashboard/audit_summary` | 最近一次 Audit 報表摘要 | — |
| GET | `/api/dashboard/policy_usage_summary` | 最近一次 Policy Usage 報表摘要 | — |
| POST | `/api/dashboard/top10` | 依 bandwidth／volume／count 排序查前 10 大流量 | `mins`, `pd`, `rank_by`, `search`，及完整 FilterBar 篩選鍵；**30/hour** |

`/api/dashboard/overview` 的 `job_health` 欄位就是 Integrations → Overview「Job Health
表格」的資料來源（讀 `logs/job_health.json`，無獨立端點）；判讀規則（error／warn／ok、
never-ran／overdue）見 [gui-tour.md](../guide/gui-tour.md) 「7) Integrations」節。

### 3) Traffic & Workloads 分頁（`src/gui/routes/actions.py` 部分＋`filter_objects.py`）

| 方法 | 路徑 | 用途 | 關鍵參數 |
|---|---|---|---|
| POST | `/api/init_quarantine` | 確保 PCE 上已建立三個 severity 的 Quarantine label | — |
| POST | `/api/quarantine/search` | 查詢可隔離的流量（依 policy decision＋FilterBar 篩選） | `source`(live/archive), `mins`, `policy_decision`, 完整篩選鍵 |
| GET/POST | `/api/workloads` | 搜尋 Workload（name／hostname／ip_address；IP 可逗號或 CIDR 多值） | `name`, `hostname`, `ip_address`, `max_results` |
| POST | `/api/quarantine/apply` | **真實副作用**：隔離單一 Workload（依 severity 套用 Quarantine label，覆蓋既有） | `href`, `level`(Mild/Moderate/Severe) |
| POST | `/api/quarantine/bulk_apply` | **真實副作用**：批次隔離（最多 5 個平行 worker） | `hrefs[]`, `level` |
| POST | `/api/quarantine/lift` | **真實副作用**：解除隔離（移除 Quarantine label、保留其餘 label） | `hrefs[]` |
| POST | `/api/workloads/accelerate` | **真實副作用**：提高受管 Workload 的流量回報頻率 | `hrefs[]`, `duration_minutes` |
| GET | `/api/traffic/trend` | 近 7 天（或 archive 全範圍）逐日流量，依 policy decision 分桶 | `source`(live/archive) |
| GET | `/api/filter-objects/suggest` | FilterBar pill 輸入即時建議；label／label_group／iplist／service 走快取，workload 即時查 PCE | `q`, `types`, `limit`(≤25)；**240/hour** |
| GET | `/api/filter-objects/browse` | FilterBar pill 分頁瀏覽（不支援 `type=workload`） | `type`, `offset`, `limit`(≤100)；**240/hour** |

隔離／解除隔離的雙重確認流程、`Accelerate` 的持續模式，見
[gui-tour.md](../guide/gui-tour.md) 「2) Traffic & Workloads」節。

### 4) Event Viewer 分頁（`src/gui/routes/events.py`）

| 方法 | 路徑 | 用途 | 關鍵參數 |
|---|---|---|---|
| GET | `/api/events/viewer` | 依時間窗／關鍵字／分類即時查 PCE 稽核事件 | `mins`(≤10080), `limit`(≤200), `offset`, `search`, `category`, `type_group`, `event_type` |
| GET | `/api/events/shadow_compare` | 比對目前事件規則對近期事件的命中結果（shadow mode） | `mins`(≤10080), `limit`(≤500) |
| GET | `/api/events/rule_test` | 單一事件規則的命中測試（新舊比對邏輯差異） | `idx`, `mins`(≤10080), `limit`(≤500) |
| GET | `/api/event-catalog` | 事件型錄（分類、已翻譯標籤、related_events，供規則建立 UI 用） | — |

此分頁全部端點皆為唯讀，即時呼叫 PCE API，不寫入本地狀態。

### 5) Rules（Alerts）分頁（`src/gui/routes/rules.py` ＋ `actions.py` Actions 子頁）

**Rules 子頁：**

| 方法 | 路徑 | 用途 | 關鍵參數 |
|---|---|---|---|
| GET | `/api/rules` | 列出所有告警規則（含冷卻／節流即時狀態） | — |
| POST | `/api/rules/event` | 新增事件型規則 | `filter_value`, `filter_status`, `filter_severity`, `threshold_*`, `throttle`, `match_fields` |
| POST | `/api/rules/system` | 新增系統健康規則（目前僅支援 `pce_health`） | `cooldown_minutes`, `throttle` |
| POST | `/api/rules/traffic` | 新增流量型規則（支援 FilterBar 篩選；`label_group` 系列鍵一律回 400） | `pd`, `port`, `proto`, `filters{...}`, `threshold_*`, `throttle` |
| POST | `/api/rules/bandwidth` | 新增頻寬／流量型規則 | `rule_type`, `pd`, `port`, `filters{...}`, `threshold_count`(float), `throttle` |
| GET | `/api/rules/<idx>` | 取得單一規則 | — |
| PUT | `/api/rules/<idx>` | 更新規則（帶 `filters` 時整組替換舊篩選鍵） | — |
| DELETE | `/api/rules/<idx>` | 刪除規則 | — |
| GET | `/api/rules/<idx>/highlight` | 該規則 JSON 的語法高亮 HTML（`{"html": "..."}`） | — |

規則型別、`filters` 物件白名單鍵與 `label_group` 為何被拒絕，見
[monitoring-alerts.md](../guide/monitoring-alerts.md)；新增 filter key 要同步的七層
白名單見 [development.md](../handover/development.md) 「4.1 新增流量 filter key 要同步的層」。

**Actions 子頁：**

| 方法 | 路徑 | 用途 | 關鍵參數 |
|---|---|---|---|
| POST | `/api/actions/run` | 手動觸發一次完整監控分析＋寄送告警 | **10/hour** |
| POST | `/api/actions/debug` | 除錯模式跑分析，回傳文字輸出 | `mins`, `pd_sel`；**10/hour** |
| POST | `/api/actions/test-alert` | **真實副作用**：發送測試告警（全部通道或單一 `channel`） | `channel`；**10/hour** |
| POST | `/api/actions/reset-watermark` | 除錯用：清除事件 watermark＋告警冷卻歷史＋事件去重狀態 | **10/hour** |
| POST | `/api/actions/best-practices` | 套用內建最佳實務規則組（16 條 event + 1 條 traffic） | `mode`(append_missing/replace)；**5/hour** |
| POST | `/api/actions/test-connection` | 測試 PCE 連線 | **20/hour** |

`POST /api/actions/test-alert` 也是 Settings → Channels 卡片上「Send test」按鈕呼叫的
同一個端點（帶 `{channel: <name>}`）。

### 6) Reports 分頁（`src/gui/routes/reports.py`）

**List 子頁 — 報表產生／管理：**

| 方法 | 路徑 | 用途 | 關鍵參數 |
|---|---|---|---|
| GET | `/api/reports` | 列出已產生的報表檔（含 metadata sidecar） | — |
| DELETE | `/api/reports/<filename>` | **會刪檔**：刪除單一報表檔（含 metadata） | — |
| POST | `/api/reports/bulk-delete` | **會刪檔**：批次刪除報表檔 | `filenames[]` |
| GET | `/reports/<filename>` | 下載／檢視報表檔（路徑穿越防護） | `?download=1` |
| POST | `/api/reports/generate` | 產生 Traffic 家族報表（api 或 csv 來源），背景 job | `source`, `traffic_report_profile`, `format`, `filters{...}`, `data_source`；**30/hour** |
| GET | `/api/reports/jobs/<job_id>` | 查詢背景報表 job 狀態（`running`/`done`/`error`） | — |
| POST | `/api/audit_report/generate` | 產生 Audit 報表 | `start_date`, `end_date`, `format`；**10/hour** |
| POST | `/api/policy_diff_report/generate` | 產生 Policy Diff 報表 | `format`(html/csv)；**10/hour** |
| POST | `/api/policy_resolver_report/generate` | 產生 Policy Resolver 報表 | `format`(json/csv/all)；**10/hour** |
| GET | `/api/labels` | 列出 PCE label 值，供 App Summary 的 app/env 下拉選單 | `key`(app/env/role/loc)；**60/hour** |
| POST | `/api/app_report/generate` | 產生單一 Application Summary 報表，背景 job | `app`, `env`, `start_date`, `end_date`；**10/hour** |
| POST | `/api/ven_status_report/generate` | 產生 VEN Status 報表 | `format`；**10/hour** |
| POST | `/api/policy_usage_report/generate` | 產生 Policy Usage 報表（api 或 csv 來源） | `start_date`, `end_date`, `format`；**10/hour** |
| GET | `/api/rule_hit_count/enablement` | 查詢 Rule Hit Count 原生數據啟用狀態 | — |
| POST | `/api/rule_hit_count/enable` | 啟用 Rule Hit Count（GUI 僅支援 all-VEN 範圍，label scope 限 CLI 精靈） | **5/hour** |
| POST | `/api/rule_hit_count_report/generate` | 產生 Rule Hit Count 報表（native 或 csv 來源） | `source`, `format`(html/csv/all)；**10/hour** |
| POST | `/api/readiness_report/generate` | 產生 Enforcement Readiness 報表 | `start_date`, `end_date`, `format`, `data_source`；**10/hour** |

**Schedules 子頁：**

| 方法 | 路徑 | 用途 | 關鍵參數 |
|---|---|---|---|
| GET | `/api/report-schedules` | 列出報表排程（含上次執行狀態／錯誤） | — |
| POST | `/api/report-schedules` | 新增報表排程 | — |
| PUT | `/api/report-schedules/<schedule_id>` | 更新報表排程 | — |
| DELETE | `/api/report-schedules/<schedule_id>` | 刪除報表排程 | — |
| POST | `/api/report-schedules/<schedule_id>/toggle` | 切換排程啟用／停用 | — |
| POST | `/api/report-schedules/<schedule_id>/run` | 立即執行排程（背景執行緒，非同步） | **20/hour** |
| GET | `/api/report-schedules/<schedule_id>/history` | 排程執行歷史（目前僅保留最近一次） | — |

九種報表的用途、欄位、資料來源見 [reports.md](../guide/reports.md)；`/api/reports/generate`
與 CLI `illumio-ops report traffic --format html` 走同一份 `ReportGenerator`。

### 7) Rule Scheduler 分頁（`src/gui/routes/rule_scheduler.py`）

| 方法 | 路徑 | 用途 | 關鍵參數 |
|---|---|---|---|
| GET | `/api/rule_scheduler/status` | 排程器狀態：排程數、下次觸發時間、近 24 小時動作時間軸 | — |
| GET | `/api/rule_scheduler/rulesets` | 分頁瀏覽／搜尋 PCE ruleset | `q`, `page`, `size` |
| GET | `/api/rule_scheduler/rulesets/<rs_id>` | 單一 ruleset 詳情（含 allow／deny／override_deny 規則列表） | — |
| GET | `/api/rule_scheduler/rules/search` | 依 rule ID 或 description 關鍵字搜尋 PCE 規則 | `q`, `scope`(id/desc) |
| GET | `/api/rule_scheduler/schedules` | 列出所有規則排程（含 PCE 上即時 `enabled`／`name` 狀態） | — |
| POST | `/api/rule_scheduler/schedules` | **真實副作用**：建立規則排程；Draft（未佈署）規則一律擋下 | `href`, `type`(recurring/one_time), `days`/`start`/`end` 或 `expire_at`, `action`(allow/disable) |
| GET | `/api/rule_scheduler/schedules/<href>` | 取得單一排程 | — |
| POST | `/api/rule_scheduler/schedules/delete` | **真實副作用**：刪除排程，並盡力清除 PCE 上的排程註記 | `hrefs[]` |
| POST | `/api/rule_scheduler/check` | 手動觸發一次排程檢查（GUI「Check now」與背景 job 共用） | — |
| GET | `/api/rule_scheduler/logs` | 排程器歷史動作日誌 | — |

`POST /api/rule_scheduler/schedules` 會把英文排程註記寫進 PCE rule 的 description
欄位並依排程切換 rule 的啟用旗標；排程器**不會自動佈署 ruleset**，安全約束與時窗語意見
[automation.md](../guide/automation.md)。

### 8) Integrations 分頁

**Cache 子頁**（`src/pce_cache/web.py`，藍圖前綴 `/api/cache`）：

| 方法 | 路徑 | 用途 | 關鍵參數 |
|---|---|---|---|
| GET | `/api/cache/status` | cache DB 各表列數（events／traffic_raw／traffic_agg） | — |
| GET | `/api/cache/lag` | 各來源（events／traffic）ingest lag，等級 ok/warning/error | — |
| GET | `/api/cache/health` | 單一管線健康判定（ok/warn/error/unknown），含容量快照 | — |
| GET | `/api/cache/throughput` | 近 1 小時／24 小時 ingest 筆數 | — |
| GET | `/api/cache/settings` | 目前 cache 設定 | — |
| PUT | `/api/cache/settings` | 更新 cache 設定（存檔後需 Restart Monitor 才生效） | — |
| POST | `/api/cache/backfill` | **真實副作用**：手動回補歷史資料（events 或 traffic），同步執行 | `source`, `since`, `until` |
| POST | `/api/cache/retention/run` | **真實副作用**：立即執行一次 retention 清除（依設定保留天數，會永久刪除過期列） | — |
| POST | `/api/cache/archive/load` | 載入指定日期區間的歸檔 JSONL 到 review DB，背景執行、回 `202` | `start_date`, `end_date`（受 `archive_review_max_days` 上限，超過回 422；已有 load 進行中回 409） |
| GET | `/api/cache/archive/status` | 查詢 archive review DB 狀態與載入進度 | — |

`/api/cache/*` 在 pce_cache DB 不可用時回 `503`。cache 架構、backfill／archive 操作見
[cache-maintenance.md](../guide/cache-maintenance.md)。

**SIEM 子頁**（`src/siem/web.py`，藍圖前綴 `/api/siem`）：

| 方法 | 路徑 | 用途 | 關鍵參數 |
|---|---|---|---|
| GET | `/api/siem/destinations` | 列出所有 SIEM destination | — |
| POST | `/api/siem/destinations` | 新增 destination（名稱重複回 `409`） | `name`, `transport`, `host`, `port`, `source_types[]` … |
| PUT | `/api/siem/destinations/<name>` | 更新 destination | — |
| DELETE | `/api/siem/destinations/<name>` | 刪除 destination | — |
| POST | `/api/siem/destinations/<name>/test` | **真實副作用**：送出一筆測試事件到該 destination | — |
| GET | `/api/siem/status` | 各 destination 的 pending／failed／sent／DLQ／成功率／平均延遲 | — |
| GET | `/api/siem/forwarder` | 轉送器設定（`enabled`, `dispatch_tick_seconds`, `dlq_max_per_dest`） | — |
| PUT | `/api/siem/forwarder` | 更新轉送器設定 | — |

**DLQ 子頁**（同一藍圖）：

| 方法 | 路徑 | 用途 | 關鍵參數 |
|---|---|---|---|
| GET | `/api/siem/dlq` | 死信佇列清單 | `dest`, `limit`(≤500) |
| GET | `/api/siem/dlq/<id>` | 單筆 DLQ 詳情（原始事件已被清除時退回 preview） | — |
| POST | `/api/siem/dlq/replay` | **真實副作用**：重送 DLQ 條目（依 `ids[]` 或 `dest`+`limit`） | `ids[]` 或 `dest`, `limit`(≤1000) |
| POST | `/api/siem/dlq/purge` | **真實副作用**：清除 DLQ（永久刪除，依保留天數） | `dest`, `older_than_days` |
| GET | `/api/siem/dlq/export` | 匯出 DLQ 為 CSV | `dest`, `reason` |

destination／格式／佇列與重試、三個 DLQ CLI 對應指令見 [siem.md](../guide/siem.md)。

**跨子頁：**

| 方法 | 路徑 | 用途 | 關鍵參數 |
|---|---|---|---|
| POST | `/api/daemon/restart` | **真實副作用**：重啟背景 daemon；GUI 未擁有 daemon 生命週期時回 `409` | **5/hour** |

### 9) Settings 分頁（`src/gui/routes/config.py`）

| 方法 | 路徑 | 用途 | 關鍵參數 |
|---|---|---|---|
| GET | `/api/settings` | 完整設定（機密欄位已遮蔽為 `***REDACTED***`） | — |
| POST | `/api/settings` | 更新設定（`api`／`email`／`smtp`／`alerts`／`settings`／`report` 及告警外掛設定區塊） | **30/hour** |
| GET | `/api/security` | Web GUI 安全設定（帳號、允許 IP、是否已設密碼） | — |
| POST | `/api/security` | 更新帳號／密碼／IP 允許清單 | **10/hour** |
| GET | `/api/alert-plugins` | 各告警通道外掛的欄位定義（動態表單用） | `lang` |
| GET | `/api/pce-profiles` | 列出 PCE profile（機密遮蔽） | — |
| POST | `/api/pce-profiles` | 新增／更新／切換／刪除 PCE profile | `action`(add/update/activate/delete) |
| GET | `/api/tls/status` | TLS 憑證狀態（含剩餘天數） | — |
| POST | `/api/tls/config` | 設定 TLS 啟用／停用與憑證來源 | **10/hour** |
| POST | `/api/tls/renew` | **真實副作用**：續期自簽憑證（僅 `self_signed=true` 可用） | **10/hour** |
| POST | `/api/tls/generate-csr` | **真實副作用**：於 `config/tls/` 產生 CSR＋私鑰 | `cn`, `san_dns`, `san_ip`, `key_algorithm`；**20/hour** |
| POST | `/api/tls/import-cert` | **真實副作用**：匯入已簽署憑證，覆寫 `config/tls/` 憑證檔 | `cert_pem`；**20/hour** |

TLS 相關端點存檔後都需要**重啟服務**才會套用；自簽憑證每日續期 job 見
[configuration.md](../guide/configuration.md)。設定鍵逐一對照表也見同一篇。

### 10) 系統／除錯（跨分頁，`src/gui/routes/admin.py`）

| 方法 | 路徑 | 用途 | 關鍵參數 |
|---|---|---|---|
| GET | `/api/logs` | 列出可用日誌模組與各自筆數 | — |
| GET | `/api/logs/<module>` | 該模組最近日誌條目 | `n`(≤500) |
| POST | `/api/shutdown` | **真實副作用**：優雅關閉服務（persistent mode 下回 `403`） | **5/hour** |

`/api/logs*` 是模組日誌檢視器（`src/static/js/module-log.js`）的後端，不屬於 8 個主分頁
中任何一個固定入口；`/api/shutdown` 由前端除錯用途呼叫。

---

## 端點總數對帳

| 分頁／區塊 | 對應檔案 | 端點數 |
|---|---|---|
| 認證與 session | `auth.py` | 5 |
| Dashboard | `dashboard.py` | 10 |
| Traffic & Workloads | `actions.py`（部分）＋ `filter_objects.py` | 10 |
| Event Viewer | `events.py` | 4 |
| Rules（Alerts） | `rules.py` ＋ `actions.py`（部分） | 15 |
| Reports | `reports.py` | 24 |
| Rule Scheduler | `rule_scheduler.py` | 10 |
| Integrations（Cache／SIEM／DLQ／daemon） | `pce_cache/web.py` ＋ `siem/web.py` ＋ `__init__.py` | 24 |
| Settings | `config.py` | 12 |
| 系統／除錯 | `admin.py` | 3 |
| **合計** | | **117** |

此數字為 `grep -c "@[a-z_]*\.route(" src/gui/routes/*.py src/gui/__init__.py`（94）
加上另外掛載的 `src/siem/web.py`（13）與 `src/pce_cache/web.py`（10）。其中 4 個是頁面
路由（`/`、`/login`、`/logout`、`/reports/<filename>`），其餘 113 個是 `/api/` JSON
端點。[gui-tour.md](../guide/gui-tour.md) 的『約 85 條』是較早盤點的粗略數字（僅計 src/gui/routes
與 gui/__init__ 的 /api 路由），非逐條稽核；本檔的對帳表才是權威清單。

---

## Pagination

**本 API 預設不分頁。** 大多數集合端點（`/api/reports`、`/api/rules`、
`/api/siem/destinations` 等）一次回傳完整陣列，沒有 `page`／`offset`／`Link` header
機制。

例外（伺服器端會切片的端點）：

- `/api/rule_scheduler/rulesets` 接受 `?page=&size=`。
- `/api/siem/dlq` 接受 `?limit=`（上限 500）；`/api/siem/dlq/replay` 的 `limit` 上限
  1000。
- `/api/logs/<module>` 接受 `?n=`（上限 500）。
- `/api/filter-objects/browse` 接受 `?offset=&limit=`（上限 100）。

`page`／`page_size`／`limit`／`offset` 用在 **PCE 端** API（Illumio PCE REST API v2）
是另一回事，跟本 GUI API 無關。

---

## 錯誤模型

所有 JSON 錯誤回應共用同一個信封：

```json
{ "ok": false, "error": "<可讀錯誤訊息>" }
```

伺服器內部例外經 `_err_with_log` 包裝時會額外附一個 `request_id`（8 碼，僅供對照伺服器
日誌，不是安全 token）：

```json
{ "ok": false, "error": "...", "request_id": "a1b2c3d4" }
```

額外欄位：

| 欄位 | 出現時機 |
|---|---|
| `code` | CSRF 錯誤（`"csrf_error"`）；`423` must-change-password 閘門 |
| `csrf_token` | CSRF 錯誤回應——帶進重試請求 |
| `request_id` | `_err_with_log` 包裝的內部例外，用於對照日誌 |
| `needs_enablement` / `pull_timeout` | `POST /api/rule_hit_count_report/generate` 的特定失敗情境 |

**HTTP 狀態碼：**

| 代碼 | 意義 |
|---|---|
| `200` | 成功 |
| `202` | 已接受，背景執行中（`POST /api/cache/archive/load`） |
| `400` | 請求格式錯誤／驗證失敗／CSRF 錯誤 |
| `401` | 未登入 |
| `403` | 禁止（例如 persistent mode 下呼叫 shutdown、報表路徑穿越） |
| `404` | 找不到資源 |
| `409` | 衝突（SIEM destination 重名、daemon 由外部管理、archive load 已在進行中） |
| `415` | 不支援的檔案類型（CSV 上傳副檔名／mimetype 不符） |
| `422` | 驗證失敗但語意上是可處理的請求（例如 archive 區間超過上限、SIEM／cache 設定驗證失敗） |
| `423` | 鎖定——must-change-password 閘門 |
| `429` | 超出限流 |
| `500` | 內部錯誤 |
| `502` | 呼叫 PCE 失敗或逾時（Bad Gateway 語意，非本服務自身錯誤） |
| `503` | 依賴服務不可用（pce_cache DB 未設定或無法連線） |

---

## 限流彙整

**全域限流：300 次／分鐘／IP**（fixed-window 演算法）。限流狀態存放在
`flask_limiter` 的持久化 JSON 檔後端（`/var/lib/illumio-ops/limiter` 或設定目錄下的
`limiter/`），跨服務重啟仍保留計數，而非純記憶體。

較嚴格的個別端點限流：

| 端點 | 限流 |
|---|---|
| `POST /api/login` | 5/分鐘 |
| `POST /api/shutdown`、`POST /api/daemon/restart` | 5/小時 |
| `POST /api/actions/best-practices`、`POST /api/rule_hit_count/enable` | 5/小時 |
| `POST /api/security`、`POST /api/tls/config`、`POST /api/tls/renew` | 10/小時 |
| 報表產生端點（audit／policy_diff／policy_resolver／app_report／ven_status／policy_usage／rule_hit_count_report／readiness） | 10/小時 |
| `POST /api/actions/run`、`POST /api/actions/debug`、`POST /api/actions/test-alert`、`POST /api/actions/reset-watermark` | 10/小時 |
| `POST /api/tls/generate-csr`、`POST /api/tls/import-cert` | 20/小時 |
| `POST /api/actions/test-connection` | 20/小時 |
| `POST /api/report-schedules/<id>/run` | 20/小時 |
| `POST /api/dashboard/top10`、`POST /api/settings` | 30/小時 |
| `POST /api/reports/generate` | 30/小時 |
| `GET /api/labels` | 60/小時 |
| `GET /api/filter-objects/suggest`、`GET /api/filter-objects/browse` | 240/小時 |

---

## 版本化

**illumio-ops GUI API 不做版本化。** 所有端點都用 `/api/` 前綴、不帶版本號區段
（例如 `/api/status`，不是 `/api/v1/status`）。

`https://<pce_host>:<port>/api/v2/orgs/<org_id>/...` 這種形式指的是 **Illumio PCE
REST API**——由 PCE 設備自己提供的另一套 API，不是 illumio-ops 這個服務。PCE domain
的行為特性（分頁上限、`X-Total-Count` 語意、async query 流程等）見
[pce-domain-notes.md](../handover/pce-domain-notes.md)。

---

## 相關文件

- [CLI 參考手冊](cli.md) — 對應的 CLI 指令
- [Web GUI 導覽](../guide/gui-tour.md) — 各分頁畫面與操作情境
- [設定參照](../guide/configuration.md) — `config.json` 逐鍵對照表
- [報表家族](../guide/reports.md) — 九種報表的用途與欄位
- [監控規則、告警、事件規則](../guide/monitoring-alerts.md) — `/api/rules`、`/api/event-catalog` 背後的規則引擎
- [rule scheduler、quarantine、自動化](../guide/automation.md) — 排程與隔離的安全約束
- [SIEM 轉送](../guide/siem.md) — `/api/siem/*` 的 destination／DLQ 語意
- [pce_cache 維運](../guide/cache-maintenance.md) — `/api/cache/*` 背後的快取架構
- [開發流程](../handover/development.md) — 新增 filter key 要同步的七層白名單
- [PCE domain 須知](../handover/pce-domain-notes.md) — PCE 端 REST API 的行為特性
- [架構導覽](../handover/architecture.md) — 模組地圖與資料流
