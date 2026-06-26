---
title: REST API
audience: [api, developer, security]
last_verified: 2026-06-26
verified_against:
  - src/gui/routes/auth.py
  - src/gui/routes/admin.py
  - src/gui/routes/dashboard.py
  - src/gui/routes/events.py
  - src/gui/routes/reports.py
  - src/gui/routes/rules.py
  - src/gui/routes/rule_scheduler.py
  - src/gui/routes/actions.py
  - src/gui/routes/config.py
  - src/gui/__init__.py
  - src/siem/web.py
  - src/pce_cache/web.py
  - v4.1.0 (branch review/audit-and-docs-rebuild)
related_docs:
  - cli.md
  - glossary.md
  - ../operations-manual_zh.md
  - ../event-rules_zh.md
---

> 🌐 [English](rest-api.md) | **[繁體中文](rest-api_zh.md)**
> 📍 [INDEX](../INDEX.md) › 參考 › REST API
> 🔍 最後驗證 **2026-06-26** 對 **v4.1.0** — 來源詳見 frontmatter

# REST API

本文件列出的所有端點皆由 illumio-ops 的 Flask GUI
（`src/gui/` + `src/siem/web.py` + `src/pce_cache/web.py`）提供。

GUI 監聽 **port 5001**，並在設定 `web_gui.tls.enabled` 時提供 **HTTPS**
——此為正式環境與離線套件安裝的預設值。因此 base URL 為：

```
https://127.0.0.1:5001
```

停用 TLS 時，同一 port 會退回 `http://`。自簽憑證的安裝需使用 `curl -k`
（或 `--cacert`）以略過憑證驗證。

---

## 認證模型

GUI 使用 **session-cookie 認證**，底層由 Flask-Login 與 Flask-WTF CSRF 保護
支撐。系統無獨立的 API 金鑰。

認證由 `src/gui/__init__.py` 中的 `before_request` 關卡**全域**強制執行
（而非透過個別路由的 decorator）。除以下公開路徑外，每個路由都需要有效的
session：

- `GET /api/csrf-token`
- `GET /login`
- `POST /api/login`
- `POST /logout`

（`/static/` 靜態資源同樣免除 session 認證。）另有一道獨立的 IP allowlist 檢查
會在**所有**路徑上優先執行——來自非允許清單位址的請求會在 socket 層以 TCP RST
直接丟棄（不回傳任何 HTTP 回應）。

每次經過認證的呼叫都必須提供：

1. **Session cookie** — 透過 `POST /api/login` 取得；具備 `HttpOnly`、
   `SameSite=Strict`、`Secure`（TLS 安裝時）。預設有效期：8 小時
   （可透過 `web_gui.session_lifetime_seconds` 設定）。
2. **CSRF token** — 所有會變更狀態的請求（`POST`、`PUT`、`DELETE`）皆需提供。
   請於 `X-CSRFToken` **或** `X-CSRF-Token` 請求標頭中傳送（兩者皆接受）。
   可從 `GET /api/csrf-token` 取得最新 token。

`POST /api/login` **免除 CSRF**，並限制為**每分鐘 5 次**請求。

**登入流程：**

```bash
BASE="https://127.0.0.1:5001"          # 自簽 TLS 請為 curl 加上 -k

# 1. 取得 CSRF token（第一次 POST 之前）
CSRF=$(curl -sk -c cookies.txt "$BASE/api/csrf-token" | python3 -c "import sys,json; print(json.load(sys.stdin)['csrf_token'])")

# 2. 登入
curl -sk -b cookies.txt -c cookies.txt "$BASE/api/login" \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" \
  -d '{"username":"illumio","password":"<password>"}'

# 3. 後續呼叫使用 session cookie
curl -sk -b cookies.txt "$BASE/api/status"
```

**CSRF token 無效或過期時的錯誤** — `400`，本文為：
```json
{ "ok": false, "code": "csrf_error", "error": "...", "csrf_token": "<new_token>" }
```
回應中包含刷新後的 token；請以該 token 重試原始請求。

> **無 API 金鑰認證。** PCE 直連的 API 金鑰是 Illumio PCE 憑證（依設定檔分別
> 儲存），並非 illumio-ops GUI 憑證。

---

## 端點分類

以下所有路徑均相對於 base URL。除上方標示為**公開（public）**者外，每個端點都
需要經過認證的 session。若某路由帶有自己的速率限制（超出全域的 300 次/分），
會標示於備註欄。

### 認證與 session

| 方法 | 路徑 | 備註 |
|--------|------|-------|
| `GET`  | `/api/csrf-token` | 取得最新 CSRF token。**公開。** |
| `GET`  | `/` | SPA 外殼（`index.html`）。回傳 HTML，而非 JSON。 |
| `GET`  | `/login` | 登入頁（`login.html`）。HTML。**公開。** |
| `POST` | `/api/login` | 認證；設置 session cookie。**公開**、免除 CSRF、5 次/分。 |
| `POST` | `/logout` | 清除 session；`302` 重導向至 `/login`。**公開。** |

**`POST /api/login`** — 請求本文：
```json
{ "username": "illumio", "password": "<password>" }
```
成功回應 — `{ "ok": true, "csrf_token": "...", "must_change_password": false }`。
失敗回應 — `401` `{ "ok": false, "error": "..." }`。

### 儀表板

| 方法 | 路徑 | 說明 |
|--------|------|-------------|
| `GET`  | `/api/status` | Daemon／版本狀態、作用中的 PCE、各規則冷卻時間。健康檢查端點（永遠回傳 200）。 |
| `GET`  | `/api/ui_translations` | SPA 使用的 i18n 字串 |
| `GET`  | `/api/dashboard/overview` | 儀表板總覽（狀態檔快照） |
| `GET`  | `/api/dashboard/snapshot` | 最新快照 JSON |
| `GET`  | `/api/dashboard/audit_summary` | 稽核事件摘要 |
| `GET`  | `/api/dashboard/policy_usage_summary` | 政策使用摘要 |
| `GET`  | `/api/dashboard/chart/<chart_id>` | 單一圖表規格（`traffic_timeline`、`policy_decisions`、`ven_status`、`rule_hits`、…） |
| `POST` | `/api/dashboard/top10` | 前 10 名流量查詢（30 次/小時） |
| `GET`  | `/api/dashboard/queries` | 列出已儲存的儀表板查詢 |
| `POST` | `/api/dashboard/queries` | 新增或更新儀表板查詢 |
| `DELETE` | `/api/dashboard/queries/<idx>` | 依索引刪除儀表板查詢 |

**`GET /api/status`** — 回應（簡略）：
```json
{
  "version": "4.1.0",
  "api_url": "https://pce.example.com:8443",
  "rules_count": 12,
  "health_check": true,
  "language": "en",
  "timezone": "local",
  "cooldowns": [{ "id": 1, "name": "PCE error alert", "remaining_mins": 0 }],
  "event_watermark": "2026-06-26T10:00:00Z"
}
```

```bash
curl -sk -b cookies.txt "$BASE/api/status" | python3 -m json.tool
```

### 事件

| 方法 | 路徑 | 說明 |
|--------|------|-------------|
| `GET`  | `/api/events/viewer` | 擷取並正規化近期的 PCE 事件 |
| `GET`  | `/api/events/shadow_compare` | 將即時事件與規則比對（shadow 模式） |
| `GET`  | `/api/events/rule_test` | 顯示某筆即時事件會命中哪些規則 |
| `GET`  | `/api/event-catalog` | 可用的 PCE 事件類型（用於建立規則） |

### 警示規則

| 方法 | 路徑 | 說明 |
|--------|------|-------------|
| `GET`  | `/api/rules` | 列出所有警示規則 |
| `POST` | `/api/rules/event` | 建立事件型規則 |
| `POST` | `/api/rules/system` | 建立系統健康規則 |
| `POST` | `/api/rules/traffic` | 建立流量型規則 |
| `POST` | `/api/rules/bandwidth` | 建立頻寬規則 |
| `GET`  | `/api/rules/<idx>` | 取得單一規則 |
| `PUT`  | `/api/rules/<idx>` | 更新規則 |
| `DELETE` | `/api/rules/<idx>` | 刪除規則 |
| `GET`  | `/api/rules/<idx>/highlight` | 規則的語法高亮 JSON（`{ "html": ... }`） |

### 報告

| 方法 | 路徑 | 說明 |
|--------|------|-------------|
| `GET`  | `/api/reports` | 列出所有已產生的報告檔案 |
| `POST` | `/api/reports/generate` | 觸發流量報告產生（非同步工作） |
| `GET`  | `/api/reports/jobs/<job_id>` | 臨時報告工作的狀態 |
| `POST` | `/api/audit_report/generate` | 觸發稽核報告（10 次/小時） |
| `POST` | `/api/policy_diff_report/generate` | 觸發政策差異報告（10 次/小時） |
| `POST` | `/api/policy_resolver_report/generate` | 觸發政策解析報告（10 次/小時） |
| `POST` | `/api/app_report/generate` | 觸發單一應用程式報告（10 次/小時） |
| `POST` | `/api/ven_status_report/generate` | 觸發 VEN 狀態報告 |
| `POST` | `/api/policy_usage_report/generate` | 觸發政策使用報告 |
| `GET`  | `/api/labels` | 依 key 列出 PCE 標籤（`?key=app\|env\|role\|loc`，60 次/小時） |
| `GET`  | `/reports/<filename>` | 下載報告檔案 |
| `DELETE` | `/api/reports/<filename>` | 刪除單一報告檔案 |
| `POST` | `/api/reports/bulk-delete` | 刪除多個報告檔案 |
| `GET`  | `/api/report-schedules` | 列出報告排程 |
| `POST` | `/api/report-schedules` | 建立報告排程 |
| `PUT`  | `/api/report-schedules/<id>` | 更新報告排程 |
| `DELETE` | `/api/report-schedules/<id>` | 刪除報告排程 |
| `POST` | `/api/report-schedules/<id>/toggle` | 啟用／停用排程 |
| `POST` | `/api/report-schedules/<id>/run` | 立即執行排程 |
| `GET`  | `/api/report-schedules/<id>/history` | 排程執行歷史 |

**`POST /api/reports/generate`** — 請求本文：
```json
{ "type": "traffic", "days": 7 }
```
長時間執行的報告會回傳 `job_id`；請輪詢 `GET /api/reports/jobs/<job_id>`
直到該工作回報完成。

```bash
curl -sk -b cookies.txt -X POST "$BASE/api/reports/generate" \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" \
  -d '{"type":"traffic","days":7}'
```

### Workload 與隔離（quarantine）動作

| 方法 | 路徑 | 說明 |
|--------|------|-------------|
| `GET` / `POST` | `/api/workloads` | 搜尋 workload（GET → 查詢參數，POST → JSON 本文） |
| `POST` | `/api/init_quarantine` | 在 PCE 中建立隔離用的標籤／政策骨架 |
| `POST` | `/api/quarantine/search` | 搜尋符合隔離條件的 workload |
| `POST` | `/api/quarantine/apply` | 隔離單一 workload |
| `POST` | `/api/quarantine/bulk_apply` | 隔離多個 workload |
| `POST` | `/api/workloads/accelerate` | 為指定的 workload href 提高流量更新頻率 |
| `POST` | `/api/actions/run` | 依名稱觸發動作 |
| `POST` | `/api/actions/debug` | 除錯動作（僅供開發） |
| `POST` | `/api/actions/test-alert` | 觸發一次測試警示派送 |
| `POST` | `/api/actions/test-connection` | 測試 PCE 連線 |
| `POST` | `/api/actions/best-practices` | 套用最佳實踐規則 |
| `POST` | `/api/actions/reset-watermark` | 清除事件浮水印（watermark）與警示冷卻（除錯用，10 次/小時） |
| `GET`  | `/api/traffic/trend` | 近 7 天每日流量計數，依政策決策分類 |

### 設定 / config

| 方法 | 路徑 | 說明 |
|--------|------|-------------|
| `GET`  | `/api/settings` | 完整設定載荷（機密已遮蔽） |
| `POST` | `/api/settings` | 更新設定 |
| `GET`  | `/api/security` | Web GUI 安全性設定 |
| `POST` | `/api/security` | 更新 Web GUI 安全性（帳號、密碼、允許的 IP） |
| `GET`  | `/api/alert-plugins` | 列出可用警示外掛的中繼資料 |
| `GET`  | `/api/pce-profiles` | 列出 PCE 設定檔 |
| `POST` | `/api/pce-profiles` | 新增／更新／啟用／刪除 PCE 設定檔 |
| `GET`  | `/api/tls/status` | TLS 憑證狀態 |
| `POST` | `/api/tls/config` | 設定 TLS（啟用／停用） |
| `POST` | `/api/tls/renew` | 更新自簽憑證 |
| `POST` | `/api/tls/generate-csr` | 產生 CSR（20 次/小時） |
| `POST` | `/api/tls/import-cert` | 匯入已簽署憑證（20 次/小時） |

**`GET /api/settings`** — 回應鍵（所有機密皆顯示為 `"***REDACTED***"`）：
```json
{
  "api": {}, "email": {}, "smtp": {}, "alerts": {},
  "settings": { "language": "en", "dashboard_queries": [] },
  "report": { "output_dir": "reports" },
  "pce_profiles": [], "active_pce_id": null
}
```

**`POST /api/pce-profiles`** — 以 action 區分的請求本文：
```json
{ "action": "add", "name": "Prod PCE", "url": "https://pce.example.com:8443",
  "org_id": "1", "key": "<api_key>", "secret": "<api_secret>", "verify_ssl": true }
```
其他 action：`"update"`、`"activate"`、`"delete"`（每個皆需 `id`）。

### 規則排程器

| 方法 | 路徑 | 說明 |
|--------|------|-------------|
| `GET`  | `/api/rule_scheduler/status` | 排程器 daemon 狀態 |
| `GET`  | `/api/rule_scheduler/rulesets` | 瀏覽 PCE ruleset（`?q=&page=&size=`） |
| `GET`  | `/api/rule_scheduler/rulesets/<rs_id>` | 單一 ruleset 詳情 |
| `GET`  | `/api/rule_scheduler/rules/search` | 在 PCE 中搜尋規則 |
| `GET`  | `/api/rule_scheduler/schedules` | 列出所有規則排程 |
| `POST` | `/api/rule_scheduler/schedules` | 建立規則排程 |
| `GET`  | `/api/rule_scheduler/schedules/<href>` | 取得單一排程 |
| `POST` | `/api/rule_scheduler/schedules/delete` | 刪除排程 |
| `POST` | `/api/rule_scheduler/check` | 排程乾跑（dry-run）檢查 |
| `GET`  | `/api/rule_scheduler/logs` | 排程器日誌條目 |

### SIEM 目的地

Blueprint 前綴：`/api/siem`。

| 方法 | 路徑 | 說明 |
|--------|------|-------------|
| `GET`  | `/api/siem/destinations` | 列出所有 SIEM 目的地 |
| `POST` | `/api/siem/destinations` | 建立目的地 |
| `PUT`  | `/api/siem/destinations/<name>` | 更新目的地 |
| `DELETE` | `/api/siem/destinations/<name>` | 刪除目的地 |
| `POST` | `/api/siem/destinations/<name>/test` | 傳送測試事件 |
| `GET`  | `/api/siem/status` | 轉發器／派送佇列狀態 |
| `GET`  | `/api/siem/forwarder` | 轉發器設定 |
| `PUT`  | `/api/siem/forwarder` | 更新轉發器設定 |
| `GET`  | `/api/siem/dlq` | 死信佇列（DLQ）清單（`?dest=&limit=`） |
| `GET`  | `/api/siem/dlq/<id>` | 單一 DLQ 項目詳情 |
| `POST` | `/api/siem/dlq/replay` | 重播 DLQ 項目 |
| `POST` | `/api/siem/dlq/purge` | 清除 DLQ |
| `GET`  | `/api/siem/dlq/export` | 將 DLQ 匯出為 CSV |

**`POST /api/siem/destinations`** — 最小請求本文：
```json
{ "name": "siem-udp", "transport": "udp", "host": "syslog.internal",
  "port": 514, "source_types": ["audit"] }
```

```bash
curl -sk -b cookies.txt "$BASE/api/siem/destinations"
```

### PCE 快取

Blueprint 前綴：`/api/cache`。

| 方法 | 路徑 | 說明 |
|--------|------|-------------|
| `GET`  | `/api/cache/status` | 快取 DB 狀態與資料列計數 |
| `GET`  | `/api/cache/lag` | 各浮水印來源的 ingestor 落後量（`ok` / `warning` / `error`） |
| `GET`  | `/api/cache/health` | 單一管線健康判定（`ok` / `warn` / `error` / `unknown`） |
| `GET`  | `/api/cache/throughput` | 近 1 小時與 24 小時的 ingest 事件與流量計數 |
| `GET`  | `/api/cache/settings` | 目前快取設定 |
| `PUT`  | `/api/cache/settings` | 更新快取設定 |
| `POST` | `/api/cache/backfill` | 觸發手動回填 |
| `POST` | `/api/cache/retention/run` | 立即執行保留期清理 |

**`GET /api/cache/status`** — 回應（簡略）：
```json
{ "ok": true, "enabled": true, "events_rows": 45000,
  "traffic_raw_rows": 8200, "traffic_agg_rows": 120000, "db_size_mb": 38.4 }
```

### 系統 / 管理

| 方法 | 路徑 | 說明 |
|--------|------|-------------|
| `GET`  | `/api/logs` | 列出日誌模組與其條目數 |
| `GET`  | `/api/logs/<module>` | 某模組的近期日誌條目（`?n=`，上限 500） |
| `POST` | `/api/shutdown` | 優雅關機（5 次/小時；持久模式下回傳 `403`） |
| `POST` | `/api/daemon/restart` | 重啟背景 daemon（5 次/小時；若由外部管理則回傳 `409`） |

---

## 分頁

**此 API 預設不分頁。** 集合端點（`/api/reports`、`/api/rules`、
`/api/siem/destinations` 等）會在單一回應中回傳完整陣列。illumio-ops GUI API
不提供 `page` / `offset` / `Link` 標頭機制。

例外情況——路由會對 PCE 端結果做切片：

- `/api/rule_scheduler/rulesets` 接受 `?page=&size=`。
- `/api/siem/dlq` 接受 `?limit=`（上限 500）。
- `/api/logs/<module>` 接受 `?n=`（上限 500）。

**PCE 直連**呼叫（Illumio PCE REST API v2）上的 `page` / `page_size` /
`limit` / `offset` 屬於另一回事，並不適用於此 GUI API。

---

## 錯誤模型

所有 JSON 錯誤回應共用相同的封裝結構：

```json
{ "ok": false, "error": "<人類可讀訊息>" }
```

特定情境下會出現額外欄位：

| 欄位 | 出現時機 |
|-------|-------------|
| `code` | CSRF 錯誤（`"csrf_error"`）；以及 `423` 強制變更密碼關卡 |
| `csrf_token` | CSRF 錯誤回應 — 請將此 token 帶入重試 |
| `description` | 速率限制錯誤（HTTP 429） |

**HTTP 狀態碼：**

| 碼 | 意義 |
|------|---------|
| `200` | 成功 |
| `400` | 請求錯誤 / 驗證失敗 / CSRF 錯誤 |
| `401` | 未認證 |
| `403` | 禁止（例如：持久模式下執行關機） |
| `404` | 資源不存在 |
| `409` | 衝突（例如：daemon 由外部管理） |
| `423` | 已鎖定 — 必須先變更密碼才能進行其他呼叫 |
| `429` | 超過速率限制 |
| `500` | 內部錯誤 |

**全域速率限制：** 每 IP 每分鐘 300 次請求（固定視窗、記憶體內）。
上方提及的更嚴格的個別路由限制包括：`POST /api/login` 5 次/分；
`POST /api/shutdown` 與 `POST /api/daemon/restart` 5 次/小時；報告產生器
10 次/小時；`POST /api/dashboard/top10` 30 次/小時；`GET /api/labels`
60 次/小時；`POST /api/tls/generate-csr` 與 `POST /api/tls/import-cert`
20 次/小時。

---

## 版本控管

**illumio-ops GUI API 無版本號。** 所有端點皆使用 `/api/` 前綴，不含版本段
（例如 `/api/status`，而非 `/api/v1/status`）。

`https://<pce_host>:<port>/api/v2/orgs/<org_id>/...` 格式指的是
**Illumio PCE REST API**——一個完全獨立、由 PCE 設備（而非 illumio-ops）
提供的 API。

---

## 相關文件

- [CLI 參考](cli.md) — 對應的 CLI 指令
- [操作手冊](../operations-manual_zh.md) — SIEM 轉發（§7）、TLS 與 day-2 維運的操作者工作流程（繁體中文）
- [事件規則](../event-rules_zh.md) — `/api/rules` 與 `/api/event-catalog` 背後的規則引擎（繁體中文）
- [README](../../README.md) — 架構概覽與請求流程
- [術語表](glossary.md) — Illumio 術語
