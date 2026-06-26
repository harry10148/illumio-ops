---
title: Rule Scheduler
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - src/scheduler/
  - src/gui/routes/rule_scheduler.py
  - src/rule_scheduler_cli.py
  - python illumio-ops.py rule-scheduler --help
  - commit 10b3754
related_docs:
  - alerts-and-quarantine.md
  - ../architecture/i18n-contract.md
  - ../reference/cli.md
---

> 🌐 [English](rule-scheduler.md) | **[繁體中文](rule-scheduler_zh.md)**
> 📍 [INDEX](../INDEX.md) › 使用者指引 › 規則排程器
> 🔍 最後驗證 **2026-05-15** 對 commit `10b3754` — 詳見 frontmatter

# 規則排程器

規則排程器讓管理員為個別 PCE 規則附加時間觸發條件。規則可設定為「每日週期性視窗」
（例如「週一至週五 08:00–18:00 啟用」）或「固定時間點後到期」。
Daemon 每隔 `check_interval_seconds`（預設 300 秒）評估所有啟用中的排程，
並自動透過 PCE API 套用啟用／停用操作。

---

## 功能說明

規則排程器管理**暫時性 PCE 規則** — 這些規則的 `enabled` 狀態應依時間表變更，
而非永久固定開啟或關閉。

支援的使用情境：

| 情境 | 觸發類型 |
|---|---|
| 維護視窗 — 夜間批次作業期間允許特定流量 | 週期性 |
| 事件回應 — 暫時啟用隔離規則至午夜 | 單次（到期） |
| 上班時間政策 — 於非工作時間停用寬鬆允許規則 | 週期性 |
| 事後清理 — 在已知未來日期後自動停用規則 | 單次（到期） |

規則以 PCE **href** 識別（例如
`/orgs/1/sec_policy/draft/rule_sets/42/sec_rules/99`）。排程器將狀態儲存於
`config/rule_schedules.json`（本地 JSON 儲存，非 PCE）。PCE 異動僅在排程觸發時透過 API 套用。

> **注意：** 排程器**不會**佈建（provision）規則集。處於 `DRAFT` 佈建狀態的規則會在 Draft
> 中被切換；管理員需另行進行佈建。

---

## 建立排程規則

### 透過 Web GUI

1. 在側邊欄開啟 **Rule Scheduler**。
2. 瀏覽至目標規則集，點擊規則列。
3. 選擇排程類型：
   - **週期性（Recurring）** — 選擇星期幾、開始時間、結束時間及時區。
   - **單次（One-shot）** — 選取到期日期時間，屆時規則將被停用。
4. 設定 **Action**：`allow`（視窗開始時啟用規則，結束時還原）或
   `disable`（視窗開始時停用規則，結束時還原）。
5. 點擊 **Save Schedule**。規則列儲存後會顯示日曆標誌。

UI 以以下 JSON 格式呼叫 `POST /api/rule_scheduler/schedules`：

```json
{
  "href":       "/orgs/1/sec_policy/draft/rule_sets/42/sec_rules/99",
  "name":       "Nightly batch allow",
  "type":       "recurring",
  "action":     "allow",
  "days":       ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
  "start":      "22:00",
  "end":        "06:00",
  "timezone":   "Asia/Taipei"
}
```

單次排程格式：

```json
{
  "href":      "/orgs/1/sec_policy/draft/rule_sets/42/sec_rules/99",
  "name":      "Incident quarantine",
  "type":      "expire",
  "action":    "allow",
  "expire_at": "2026-05-16T23:59",
  "timezone":  "local"
}
```

### 透過互動式 Shell（CLI）

排程器互動介面位於 `src/rule_scheduler_cli.py`，可透過 `illumio-ops shell`
互動選單進入。

> **TODO：** 舊版文件提及獨立的 `illumio-ops rule-scheduler` Click 子命令，
> 但目前的 Click 根命令（`src/cli/main.py`）**尚未接入**。截至 commit `10b3754`，
> 唯一已驗證的 CLI 入口為 `illumio-ops shell`。

從互動式 Shell 選擇 **Rule Scheduler** 可：
- 從 PCE 即時瀏覽規則集。
- 選取規則並附加週期性或單次排程。
- 列出所有啟用中的排程。
- 取消（刪除）排程。

---

## 週期性 vs 單次

| 屬性 | 週期性（Recurring） | 單次（One-shot / Expire） |
|---|---|---|
| `type` 欄位 | `"recurring"` | `"expire"` |
| 必填欄位 | `days`、`start`、`end`、`timezone` | `expire_at`、`timezone` |
| 觸發時機 | 每個符合日期的 `start` 時間；`end` 時間還原 | 僅一次，於 `expire_at` |
| 觸發後 | 保持啟用，等待下一個週期 | 排程項目即告消耗 |
| PCE description 標記 | `[📅 Recurring: Mon,Tue,Wed… HH:MM-HH:MM (TZ) ...]` | `[⏰ Expire: YYYY-MM-DD HH:MM]` |

**週期性**排程採時間視窗模式：在 `start` 時將規則切換至設定的 `action` 狀態；
在 `end` 時還原。若 Daemon 在視窗邊界期間停止運作，下一次 tick 將追補執行
（APScheduler `coalesce=True`，`misfire_grace_time=60 秒`）。

**單次**排程在指定的 `expire_at` 時間停用（或依 action 啟用）規則後，不再重新評估。

---

## 為何描述固定為英文

儲存排程時，Daemon 會將一段簡短標記寫入 PCE 規則的 `description` 欄位，例如：

```
[📅 Recurring: Mon,Tue,Wed,Thu,Fri 22:00-06:00 (Asia/Taipei) Enable in window]
```

不論管理員的 UI 語言為何，這段標記一律以 `t(key, lang='en')` 寫入。
Flask 路由（`src/gui/routes/rule_scheduler.py`）與 CLI 輔助函式
（`src/rule_scheduler_cli.py`）皆套用相同模式。

**原因：**

PCE description 欄位是**儲存的原始資料**，而非 UI 標籤。它會以字面值出現於：

- **Policy-usage 報告** — 可能由以英文為主的稽核人員使用，或饋入 SIEM 管道。
- **稽核報告** — description 在 CSV／HTML 輸出中以字串直接呈現。
- **跨語言工作階段** — 若不固定語言，在 EN 與 zh-TW 之間切換的管理員
  將在歷史資料中看到混合語言的標記。

在寫入時固定為英文，可確保標記在任何讀取者、任何時間點、任何地區設定下
都保持穩定且無歧義。這正是
[i18n Contract](../architecture/i18n-contract.md) 所定義的 `t(key, lang='en')` 慣例。

---

## 列出與取消排程規則

### Web GUI

- **Rule Scheduler → Active Schedules 頁籤** — 列出所有排程及 PCE 即時狀態
  （`live_enabled`，來自 `GET /api/rule_scheduler/schedules`）。
- 選取一或多筆 → 點擊 **Delete** → 呼叫
  `POST /api/rule_scheduler/schedules/delete`，帶入 `{ "hrefs": [...] }`。
- 刪除排程同時會清除 PCE 規則 description 中的標記
  （`api.update_rule_note(href, "", remove=True)`）。

### API（直接呼叫）

```bash
# 列出所有啟用中的排程
curl -s http://localhost:8080/api/rule_scheduler/schedules | jq .

# 取得單一排程
curl -s http://localhost:8080/api/rule_scheduler/schedules/orgs/1/sec_policy/draft/rule_sets/42/sec_rules/99 | jq .

# 刪除排程
curl -s -X POST http://localhost:8080/api/rule_scheduler/schedules/delete \
  -H 'Content-Type: application/json' \
  -d '{"hrefs":["/orgs/1/sec_policy/draft/rule_sets/42/sec_rules/99"]}'

# 手動觸發排程檢查週期
curl -s -X POST http://localhost:8080/api/rule_scheduler/check

# 查看排程器狀態（間隔、排程數）
curl -s http://localhost:8080/api/rule_scheduler/status | jq .
```

### 互動式 Shell

從 `illumio-ops shell → Rule Scheduler`，選擇子選單中的
**List schedules** 或 **Cancel a schedule**。

---

## 稽核軌跡

### 記錄存放位置

| 目的地 | 內容 | 路徑 |
|---|---|---|
| **Loguru Daemon 日誌** | 每次 tick 結果：`[RuleScheduler] <訊息>` | `logs/illumio_ops.log`（預設） |
| **ModuleLog** | 相同訊息，可透過 GUI 查詢 | 記憶體環形緩衝區；GUI 頁籤 **Rule Scheduler → Logs** |
| **PCE 規則 description** | 排程儲存時寫入的英文標記 | 存於 PCE；PCE UI 與 policy-usage 報告均可見 |
| **排程儲存區** | 每個啟用中排程的 JSON 記錄 | `config/rule_schedules.json` |

### 日誌格式

每次成功 tick 會產生如下日誌行：

```
2026-05-15 22:00:03 | INFO | [RuleScheduler] rule /orgs/1/.../sec_rules/99 → enabled (recurring window start)
```

錯誤以 `ERROR` 等級記錄，並附帶完整 traceback 至 Daemon 日誌與 ModuleLog。

### GUI 日誌檢視器

在 Web UI 中導覽至 **Rule Scheduler → Logs**。此頁呼叫
`GET /api/rule_scheduler/logs`，顯示由每次 tick 的 `_append_rs_logs()` 填入的
記憶體環形緩衝區。

### Daemon 持久化

若 `config.json` 中設定 `scheduler.persist = true` 且已安裝 SQLAlchemy，
APScheduler 將使用 SQLite jobstore（路徑記錄於
`"Scheduler using persistent SQLite jobstore: <path>"`）。
否則使用記憶體 jobstore（Daemon 重啟後 APScheduler 作業消失，
但規則排程本身仍保存於 `config/rule_schedules.json`）。

---

## 相關文件
- [警示與隔離](alerts-and-quarantine.md) — 觸發規則排程的警示
- [i18n Contract](../architecture/i18n-contract.md) — 排程描述固定為英文的原因
- [CLI 參考](../reference/cli.md) — `illumio-ops` 旗標
