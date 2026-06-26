---
title: REST API
audience: [api, developer, security]
last_verified: 2026-06-26
verified_against:
  - src/api/
  - src/gui/routes/
  - docs/API_Cookbook.md (legacy, audited)
  - commit 4f78332
related_docs:
  - cli.md
  - ../_archive/user-guide/siem-integration.md
  - ../architecture/overview.md
  - glossary.md
---

> 🌐 [English](rest-api.md) | **[繁體中文](rest-api_zh.md)**
> 📍 [INDEX](../INDEX.md) › 參考 › REST API
> 🔍 最後驗證 **2026-05-15** 對 commit `4f78332` — 詳見 frontmatter

# REST API

> ⚠️ **此中文版端點清單尚未同步最新路由——請以 [English 版](rest-api.md)（已於 2026-06-26 依原始碼重建）為準。**

所有端點均由 illumio-ops 的 Flask GUI 提供
（`src/gui/`、`src/siem/web.py`、`src/pce_cache/web.py`）。
預設 base URL 為 `http://127.0.0.1:5001`（啟用 TLS 的安裝請使用 `https://`）。

---

## 認證模型

GUI 使用 **session-cookie 認證**，底層為 Flask-Login 與 Flask-WTF CSRF 保護。
系統無獨立 API 金鑰——初次登入後的每次呼叫都必須提供：

1. **Session cookie** — 透過 `POST /api/login` 取得；`HttpOnly`、`SameSite=Strict`、
   `Secure`（TLS 安裝）。預設有效期：8 小時（可透過
   `web_gui.session_lifetime_seconds` 設定）。
2. **CSRF token** — 所有狀態變更請求（`POST`、`PUT`、`DELETE`）均需提供。
   於請求標頭 `X-CSRFToken` **或** `X-CSRF-Token` 中傳送。
   可從 `GET /api/csrf-token` 取得最新 token。

**登入流程：**

```bash
BASE="http://127.0.0.1:5001"

# 1. 取得 CSRF token（第一次 POST 前）
CSRF=$(curl -s -c cookies.txt "$BASE/api/csrf-token" | python3 -c "import sys,json; print(json.load(sys.stdin)['csrf_token'])")

# 2. 登入
curl -s -b cookies.txt -c cookies.txt "$BASE/api/login" \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" \
  -d '{"username":"illumio","password":"<password>"}'

# 3. 後續呼叫使用 session cookie
curl -s -b cookies.txt "$BASE/api/status"
```

**CSRF token 無效或過期時回應** — `400`：
```json
{ "ok": false, "code": "csrf_error", "error": "...", "csrf_token": "<new_token>" }
```
回應中包含刷新後的 token；請以新 token 重試原始請求。

> **無 API 金鑰認證。** 舊版 `docs/API_Cookbook.md` 所提及的 API 金鑰為
> Illumio PCE 憑證，非 illumio-ops GUI 憑證。

---

## 端點分類

以下所有路徑均相對於 base URL。
`login_required` 表示必須提供 session cookie。

### 認證

| 方法 | 路徑 | 說明 |
|------|------|------|
| `GET`  | `/api/csrf-token` | 取得最新 CSRF token（無需認證） |
| `POST` | `/api/login` | 登入；設置 session cookie |
| `POST` | `/logout` | 清除 session；重導向至 `/login` |

**`GET /api/csrf-token`** — 回應：
```json
{ "csrf_token": "<token>" }
```

**`POST /api/login`** — 請求本文：
```json
{ "username": "illumio", "password": "<password>" }
```
成功回應：
```json
{ "ok": true }
```
失敗回應：`401` `{ "ok": false, "error": "..." }`

---

### 儀表板

所有儀表板端點均需 `login_required`。

| 方法 | 路徑 | 說明 |
|------|------|------|
| `GET`  | `/api/status` | Daemon 狀態與目前 PCE 資訊 |
| `GET`  | `/api/ui_translations` | SPA 使用的 i18n 字串 |
| `GET`  | `/api/dashboard/snapshot` | 最新快照 JSON |
| `GET`  | `/api/dashboard/audit_summary` | 稽核事件摘要 |
| `GET`  | `/api/dashboard/policy_usage_summary` | 政策使用摘要 |
| `GET`  | `/api/dashboard/chart/<chart_id>` | 單一圖表資料 |
| `POST` | `/api/dashboard/top10` | 前 10 名流量查詢 |
| `GET`  | `/api/dashboard/queries` | 列出已儲存的儀表板查詢 |
| `POST` | `/api/dashboard/queries` | 新增或更新儀表板查詢 |
| `DELETE` | `/api/dashboard/queries/<idx>` | 依索引刪除儀表板查詢 |

**`GET /api/dashboard/snapshot`** — 回應（簡略）：
```json
{
  "ok": true,
  "snapshot": {
    "kpis": [{ "label": "Total Flows", "value": 12345, "label_key": "kpi_total_flows" }],
    "generated_at": "2026-05-15T10:00:00Z"
  }
}
```

```bash
curl -s -b cookies.txt "$BASE/api/dashboard/snapshot" | python3 -m json.tool
```

**`GET /api/dashboard/audit_summary`** — 回應：
```json
{ "ok": true, "summary": { "total": 42, "by_severity": { "err": 3, "warn": 10 } } }
```

**`GET /api/dashboard/policy_usage_summary`** — 回應：
```json
{ "ok": true, "summary": { "total_rules": 500, "unused": 87, "active": 413 } }
```

---

### 報告

所有報告端點均需 `login_required`。

| 方法 | 路徑 | 說明 |
|------|------|------|
| `GET`  | `/api/reports` | 列出所有已產生的報告檔案 |
| `POST` | `/api/reports/generate` | 觸發流量報告產生 |
| `POST` | `/api/audit_report/generate` | 觸發稽核報告產生 |
| `POST` | `/api/ven_status_report/generate` | 觸發 VEN 狀態報告 |
| `POST` | `/api/policy_usage_report/generate` | 觸發政策使用報告 |
| `GET`  | `/reports/<filename>` | 下載報告檔案 |
| `DELETE` | `/api/reports/<filename>` | 刪除單一報告檔案 |
| `POST` | `/api/reports/bulk-delete` | 批次刪除報告檔案 |
| `GET`  | `/api/report-schedules` | 列出報告排程 |
| `POST` | `/api/report-schedules` | 建立報告排程 |
| `PUT`  | `/api/report-schedules/<id>` | 更新報告排程 |
| `DELETE` | `/api/report-schedules/<id>` | 刪除報告排程 |
| `POST` | `/api/report-schedules/<id>/toggle` | 啟用/停用排程 |
| `POST` | `/api/report-schedules/<id>/run` | 立即執行排程 |
| `GET`  | `/api/report-schedules/<id>/history` | 排程執行歷史 |

**`POST /api/reports/generate`** — 請求本文：
```json
{ "type": "traffic", "days": 7 }
```

**`POST /api/policy_usage_report/generate`** — 請求本文：
```json
{ "start_date": "2026-04-01", "end_date": "2026-05-01" }
```
回應：
```json
{ "ok": true, "files": ["policy_usage_2026-05-01.html"], "record_count": 1200, "kpis": {} }
```

```bash
# 觸發流量報告
curl -s -b cookies.txt -X POST "$BASE/api/reports/generate" \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" \
  -d '{"type":"traffic","days":7}'
```

---

### SIEM 目的地

Blueprint 前綴：`/api/siem`。所有端點均需 `login_required`。

| 方法 | 路徑 | 說明 |
|------|------|------|
| `GET`  | `/api/siem/destinations` | 列出所有 SIEM 目的地 |
| `POST` | `/api/siem/destinations` | 建立目的地 |
| `PUT`  | `/api/siem/destinations/<name>` | 更新目的地 |
| `DELETE` | `/api/siem/destinations/<name>` | 刪除目的地 |
| `POST` | `/api/siem/destinations/<name>/test` | 傳送測試事件 |
| `GET`  | `/api/siem/status` | 轉發器佇列狀態 |
| `GET`  | `/api/siem/forwarder` | 轉發器設定 |
| `PUT`  | `/api/siem/forwarder` | 更新轉發器設定 |
| `GET`  | `/api/siem/dlq` | 死信佇列（DLQ）內容 |
| `POST` | `/api/siem/dlq/replay` | 重播 DLQ 項目 |
| `POST` | `/api/siem/dlq/purge` | 清除 DLQ |
| `GET`  | `/api/siem/dlq/export` | 匯出 DLQ 為檔案 |

**`GET /api/siem/destinations`** — 回應：
```json
{
  "destinations": [
    {
      "name": "splunk-hec",
      "transport": "hec",
      "host": "splunk.internal",
      "port": 8088,
      "enabled": true,
      "source_types": ["audit", "traffic"]
    }
  ]
}
```

**`POST /api/siem/destinations`** — 最小請求本文：
```json
{
  "name": "siem-udp",
  "transport": "udp",
  "host": "syslog.internal",
  "port": 514,
  "source_types": ["audit"]
}
```

```bash
# 列出 SIEM 目的地
curl -s -b cookies.txt "$BASE/api/siem/destinations"

# 傳送測試事件
curl -s -b cookies.txt -X POST "$BASE/api/siem/destinations/splunk-hec/test" \
  -H "X-CSRFToken: $CSRF"
```

---

### 警示（Alert Rules）

所有端點均需 `login_required`。

| 方法 | 路徑 | 說明 |
|------|------|------|
| `GET`  | `/api/rules` | 列出所有警示規則 |
| `POST` | `/api/rules/event` | 建立事件型規則 |
| `POST` | `/api/rules/system` | 建立系統健康規則 |
| `POST` | `/api/rules/traffic` | 建立流量型規則 |
| `POST` | `/api/rules/bandwidth` | 建立頻寬規則 |
| `GET`  | `/api/rules/<idx>` | 取得單一規則 |
| `PUT`  | `/api/rules/<idx>` | 更新規則 |
| `DELETE` | `/api/rules/<idx>` | 刪除規則 |
| `GET`  | `/api/event-catalog` | 可用的 PCE 事件類型（用於建立規則） |
| `POST` | `/api/actions/test-alert` | 觸發測試警示派送 |

**`GET /api/rules`** — 回應（簡略）：
```json
{
  "ok": true,
  "rules": [
    { "idx": 0, "type": "event", "enabled": true, "name": "PCE error alert" }
  ]
}
```

```bash
curl -s -b cookies.txt "$BASE/api/rules"
```

---

### 快取（PCE Cache）

Blueprint 前綴：`/api/cache`。所有端點均需 `login_required`。

| 方法 | 路徑 | 說明 |
|------|------|------|
| `GET`  | `/api/cache/status` | 快取 DB 狀態與資料列計數 |
| `GET`  | `/api/cache/settings` | 目前快取設定 |
| `PUT`  | `/api/cache/settings` | 更新快取設定 |
| `POST` | `/api/cache/backfill` | 觸發手動回填 |
| `POST` | `/api/cache/retention/run` | 立即執行保留期清理 |

**`GET /api/cache/status`** — 回應（簡略）：
```json
{
  "ok": true,
  "enabled": true,
  "events_rows": 45000,
  "traffic_raw_rows": 8200,
  "traffic_agg_rows": 120000,
  "db_size_mb": 38.4
}
```

```bash
curl -s -b cookies.txt "$BASE/api/cache/status"
```

---

### 設定

所有設定端點均需 `login_required`（除非另有說明）。

| 方法 | 路徑 | 說明 |
|------|------|------|
| `GET`  | `/api/settings` | 完整設定載荷（機密已遮蔽） |
| `POST` | `/api/settings` | 更新設定 |
| `GET`  | `/api/security` | Web GUI 安全性設定 |
| `POST` | `/api/security` | 更新安全性設定（帳號、密碼、允許 IP） |
| `GET`  | `/api/alert-plugins` | 列出可用警示外掛的中繼資料 |
| `GET`  | `/api/pce-profiles` | 列出 PCE 設定檔 |
| `POST` | `/api/pce-profiles` | 新增 / 更新 / 啟用 / 刪除 PCE 設定檔 |
| `GET`  | `/api/tls/status` | TLS 憑證狀態 |
| `POST` | `/api/tls/config` | 設定 TLS（啟用/停用） |
| `POST` | `/api/tls/renew` | 更新自簽憑證 |
| `POST` | `/api/tls/generate-csr` | 產生 CSR |
| `POST` | `/api/tls/import-cert` | 匯入已簽署憑證 |

**`GET /api/settings`** — 回應鍵（所有機密顯示為 `"***REDACTED***"`）：
```json
{
  "api": {},
  "email": {},
  "smtp": {},
  "alerts": {},
  "settings": { "language": "en", "dashboard_queries": [] },
  "report": { "output_dir": "reports" },
  "pce_profiles": [],
  "active_pce_id": null
}
```

**`POST /api/pce-profiles`** — 以 action 區分的請求本文：
```json
{ "action": "add", "name": "Prod PCE", "url": "https://pce.example.com:8443",
  "org_id": "1", "key": "<api_key>", "secret": "<api_secret>", "verify_ssl": true }
```
其他 action：`"update"`（需 `id`）、`"activate"`（需 `id`）、`"delete"`（需 `id`）。

```bash
curl -s -b cookies.txt "$BASE/api/pce-profiles"
```

---

### 規則排程器

所有端點均需 `login_required`。

| 方法 | 路徑 | 說明 |
|------|------|------|
| `GET`  | `/api/rule_scheduler/status` | 排程器 daemon 狀態 |
| `GET`  | `/api/rule_scheduler/rulesets` | 瀏覽 PCE rule set（`?q=&page=&size=`） |
| `GET`  | `/api/rule_scheduler/rulesets/<rs_id>` | 單一 rule set 詳情 |
| `GET`  | `/api/rule_scheduler/rules/search` | 在 PCE 中搜尋規則 |
| `GET`  | `/api/rule_scheduler/schedules` | 列出所有規則排程 |
| `POST` | `/api/rule_scheduler/schedules` | 建立規則排程 |
| `GET`  | `/api/rule_scheduler/schedules/<href>` | 取得單一排程 |
| `POST` | `/api/rule_scheduler/schedules/delete` | 刪除排程 |
| `POST` | `/api/rule_scheduler/check` | 排程乾跑（dry-run）檢查 |
| `GET`  | `/api/rule_scheduler/logs` | 排程器日誌條目 |

---

### 系統 / 管理

| 方法 | 路徑 | 說明 | 認證 |
|------|------|------|------|
| `GET`  | `/api/logs/<module>` | 模組的最新日誌條目 | `login_required` |
| `POST` | `/api/shutdown` | 優雅關機（速率限制：5 次/小時） | `login_required` |
| `POST` | `/api/daemon/restart` | 重啟背景 daemon | `login_required` |
| `POST` | `/api/actions/run` | 依名稱觸發動作 | `login_required` |
| `POST` | `/api/actions/debug` | 除錯動作（開發用） | `login_required` |
| `POST` | `/api/actions/test-connection` | 測試 PCE 連線 | `login_required` |
| `POST` | `/api/actions/best-practices` | 套用最佳實踐規則 | `login_required` |

---

## 分頁

**此 API 不支援分頁。** 所有集合端點（`/api/reports`、`/api/rules`、
`/api/siem/destinations` 等）均在單一回應中返回完整陣列。
GUI API 無 `page` / `offset` / `Link` 標頭機制。

`docs/API_Cookbook.md` 所記載的 `page`、`page_size`、`limit`、`offset` 參數
適用於 **PCE 直接 API**（Illumio PCE REST API v2），**不適用**於此 GUI API。

例外：`/api/rule_scheduler/rulesets` 接受 `?page=&size=` 參數，
用於 PCE rule set 結果的伺服器端分頁。

---

## 錯誤模型

所有 JSON 錯誤回應共用相同封裝結構：

```json
{ "ok": false, "error": "<人類可讀訊息>" }
```

特定情境下會出現額外欄位：

| 欄位 | 出現時機 |
|------|---------|
| `code` | CSRF 錯誤（`"csrf_error"`） |
| `csrf_token` | CSRF 錯誤回應 — 請以此 token 重試請求 |
| `description` | 速率限制錯誤（HTTP 429） |

**HTTP 狀態碼：**

| 碼 | 意義 |
|----|------|
| `200` | 成功 |
| `400` | 請求錯誤 / 驗證失敗 / CSRF 錯誤 |
| `401` | 未認證 |
| `403` | 禁止（例如：持久模式下執行關機） |
| `404` | 資源不存在 |
| `409` | 衝突（例如：daemon 由外部管理） |
| `429` | 超過速率限制（`{ "ok": false, "error": "rate_limit_exceeded" }`） |
| `500` | 內部錯誤 |

全域速率限制：每 IP **每分鐘 300 次**請求（固定視窗、記憶體）。
特定限制：`POST /api/shutdown`、`POST /api/daemon/restart` — 每小時 5 次。

---

## 版本控管

**illumio-ops GUI API 無版本號。** 所有端點使用 `/api/` 前綴，
無版本段（例如：`/api/status`，而非 `/api/v1/status`）。

`docs/API_Cookbook.md` 所記載的
`https://<pce_host>:<port>/api/v2/orgs/<org_id>/...` 格式
屬於 **Illumio PCE REST API**——由 PCE 設備提供，與 illumio-ops 無關。

> **TODO：** 若 GUI API 將來被 SPA 以外的外部工具使用，
> 請補充語意化版本控管合約或棄用政策。

---

## 相關文件
- [CLI 參考](cli.md) — 對應的 CLI 指令
- [SIEM 整合](../_archive/user-guide/siem-integration.md) — SIEM 目的地操作者工作流程
- [架構概覽](../_archive/architecture/overview.md) — 請求流程與 Flask 路由（下一任務）
- [術語表](glossary.md) — Illumio 術語
