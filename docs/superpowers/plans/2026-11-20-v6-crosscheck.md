# 交叉檢查工具 Implementation Plan

**Goal:** `python -m illumio_ops.crosscheck {events|alerts|reports|all}`：拿 PCE 原始資料，對本系統收到的事件、事件規則的告警、報表的關鍵數字
逐項比對，輸出 `report.md`＋`findings.json`，有不一致時結束碼 1。

**Spec:** `docs/superpowers/specs/2026-11-20-v6-crosscheck-design.md`（`b38b1167`）。

**Architecture:** 新套件 `illumio_ops/crosscheck/`：`__main__.py`（argparse）、`io.py`（唯讀資料庫、PCE client、輸出）、`events.py`、`alerts.py`、
`reports.py`、`kpis.py`（每份報表 KPI 的獨立算法）。結果統一成 `Finding(area, item, status, detail, sample)`，`status ∈ {consistent, inconsistent, unchecked}`。

## Global Constraints

- **獨立性**（規格 §2 反目標第一條）：`illumio_ops/crosscheck/**` 只可 import 標準庫、`illumio_ops.pce.client`、`illumio_ops.pce.async_query`
  （傳輸層）、`illumio_ops.pce.timefmt`、`illumio_ops.settings.*`、`illumio_ops.paths`、`illumio_ops.domain.event_catalog`（要檢查的清單本身）、
  `illumio_ops.domain.values`、`illumio_ops.pce.rate_limit`。其他一律禁止（Task 1 的 AST 守門測試）。
- 資料庫一律 `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`；不呼叫 `illumio_ops.store.db.connect`（它可能跑 migration）。
- 對 PCE 只用 GET。例外只有 async traffic query：建立與輪詢查詢；對本工具建立的查詢 PUT `update_rules`；DELETE 本工具建立的查詢（一定放在 `finally`；刪除失敗時在 report.md 列為殘留並附 href）。其他一律不寫入（使用者 2026-11-20：lab 與 NFR 都允許上述三種）。
- 輸出不可含憑證；事件範例只印欄位名與 event_type／timestamp／href，不印其他內容值。
- 工作目錄 `/home/harry/rd/illumio-ops/.worktrees/v6-crosscheck`，分支 `feat/v6-crosscheck`。每個 brief 開頭驗證 `pwd`、分支、`git status` 乾淨。
- commit：英文 conventional commits；只 `git add` 明確路徑；不在閘門後用 `;` 或管線接 commit；不 push；結尾兩行
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`、`Claude-Session: https://claude.ai/code/session_01V7rXuiroWZKXLffJeydNsX`。
- 測試：`cd /home/harry/rd/illumio-ops/.worktrees/v6-crosscheck && timeout 900 .venv/bin/python -m pytest tests/crosscheck -x -q -p no:logging`。
  全套閘門照 `.superpowers/sdd/2026-11-03-v6-ui-b-rule-scheduling/gates.sh`，但路徑換成這個工作樹（主對話跑）。
- mypy strict、ruff 全過。測試不打真 PCE：用 `AppContext.pce_factory` 那種假 client 或直接傳入 fake。

## Review Focus

1. 檢查器用了產品的判斷（守門測試、人工讀 import）。
2. 「沒檢查」被算成「一致」。
3. 期間切分在 10,000 筆上限時漏資料。
4. 冷卻／頻率限制的解釋寫得太寬，把真漏報吃掉。

---

### Task 1: 骨架、輸出、守門

**Files:** Create `illumio_ops/crosscheck/{__init__,__main__,io,model}.py`；Modify `tests/gates/test_no_print.py`（`EXEMPT` 加 `illumio_ops.crosscheck.__main__`）；
Create `tests/crosscheck/test_boundary.py`、`tests/crosscheck/test_cli.py`。

- CLI：`events|alerts|reports|all`、`--days`（預設 7，1–90）、`--margin-minutes`（預設 30）、`--out`（必填，不存在就建立）、`--root`（預設照 `resolve_paths`）。
  期間 `end = now − margin`、`start = end − days`。
- `io.py`：`open_ro(path)`；`pce(settings)` 用 `client_from_settings` 與自己的 `RateLimiter`；`write(out, findings, meta)` 寫 `findings.json`
  與 `report.md`（依區分組，每區先列不一致、再列沒檢查、最後一致的計數；開頭寫期間、PCE、版本、各項限制）。
- 結束碼：有 `inconsistent` → 1；否則 0；設定讀不到或 PCE 連不上 → 2（訊息寫原因，不印憑證）。
- 守門測試：AST 掃 `illumio_ops/crosscheck` 的 import 只在 Global Constraints 的白名單內；**先注入缺陷**（暫存目錄放一個 import
  `illumio_ops.services.eventsource` 的檔案）確認會紅。
- CLI 測試：參數驗證、期間計算、唯讀開啟（對唯讀連線執行 INSERT 會丟 `sqlite3.OperationalError`）、結束碼。
- commit `feat(v6-crosscheck): command skeleton, read-only access and the import boundary`

### Task 2: 事件

**Files:** Create `illumio_ops/crosscheck/events.py`、`tests/crosscheck/test_events.py`。

- 抓取：`GET /events?timestamp[gte]&timestamp[lte]&max_results=10000`。回傳筆數 ≥ 上限 → 期間對半切再抓，直到不滿；切到 1 秒還滿 → 該段記為
  `unchecked`（原因：同一秒超過上限）。依 href 去重。逾時與 429/5xx 重試三次，仍失敗 → 該段 `unchecked`。
- 自己從原始 JSON 取 `href`、`event_type`、`timestamp`、`status`、`severity`；缺 href 或 timestamp 的事件計數列出（不丟）。
- 清單檢查：`event_catalog.catalog()` 的 event_type 集合 vs PCE 出現的；清單沒有的 → `inconsistent`（每種一筆，附筆數與一筆範例的**欄位名**）；
  清單有但沒出現的只寫計數（`consistent` 的附註）。
- 收進來的比對：唯讀讀 flows 資料庫的 `events` 表（`href, event_type, timestamp`）在期間內的列。可比對的時段＝期間 ∩ [保留起點（設定的 event 保留天數）,
  end]，且事件收集有開（設定）；時段外的列為 `unchecked` 並寫原因。PCE 有本系統沒有 → `inconsistent`（列 href、type、時間，最多 50 筆範例＋總數）；
  本系統有 PCE 沒有 → `inconsistent`（附註：可能是 PCE 已刪除，需人工判斷）。
- 測試：上限切分（假 client 第一次回滿、切半後不滿）、同一秒滿、去重、清單漏、漏收、多收、保留期外列為沒檢查。
- commit `feat(v6-crosscheck): events against the PCE and the event catalog`

### Task 3: 事件規則的告警

**Files:** Create `illumio_ops/crosscheck/alerts.py`、`tests/crosscheck/test_alerts.py`。

- 讀設定裡**啟用的** `type=event` 規則（設定檔是 JSON，直接讀欄位；不用產品的 `event_matches`）。
- 獨立比對器 `supported(rule) -> str | None`（None＝支援；否則回原因）與 `matches(rule, raw)`：event_types 的確切類型、`a|b`、`*`；status、
  event_severity 為 `""`／`*`／`any`／`all`（不分大小寫）或 `|` 串的值，`error`＝`err`。用到正規表示式、`!`、`match_fields` → 該規則 `unchecked`。
- 告警：唯讀讀 app 資料庫 `alerts` 表該規則在期間內的列（`rule_id, subject_key, fired_at, first_seen, last_seen, facts_json`），限定目前 PCE（`pce_url`、`org_id`）。
- 判斷（規格 §4.2）：
  - 每個符合的 PCE 事件：被某筆告警的 `[first_seen, last_seen]` 包含 → 解釋；或落在同規則某筆告警 `fired_at` 之後的冷卻（`cooldown_minutes`）或頻率限制
    期間（`throttle.period_minutes`）內 → 解釋（並計數「被冷卻／限制吃掉」）；或早於該規則的評估起點（app 資料庫 `alert_eval` 類表的起點；找不到就用
    期間起點並在報告寫明）→ 解釋。都不是 → `inconsistent`「可能漏報」。
  - 每筆告警：`[first_seen, last_seen]` 內至少一個符合的 PCE 事件，否則 `inconsistent`「沒有事件支撐」。
  - `threshold=count`：每筆告警 `[fired_at − window, fired_at]` 內符合數 ≥ 門檻，否則 `inconsistent`「門檻不足」。
  - 每條規則一筆總結：符合事件數、告警數、各種解釋的計數。
- 寫實作者要先讀的：`app.sqlite` 的 migration（`illumio_ops/store/migrations/*.sql`）找評估起點與 alerts 欄位的真實格式（時間字串格式）。
- 測試：每種判斷各一個正例一個反例；冷卻邊界（剛好在冷卻結束時的事件不算被吃掉）；不支援的規則列為沒檢查。
- commit `feat(v6-crosscheck): event-rule alerts against the PCE's events`

### Task 4: 報表 KPI 盤點（主對話執行，可派 reviewer 協助讀碼）

- 對 16 種報表（`illumio_ops/services/reports/registry.py`）的每個 KPI 寫一列：報表、KPI key、定義（讀程式）、資料來源、能否獨立重算、
  獨立算法（PCE 哪個 API／async query 條件＋怎麼算）、預期誤差來源。
- 結果寫成規格的附錄 A（`docs/superpowers/specs/2026-11-20-v6-crosscheck-design.md`），並交給使用者看。Task 5 只做標為可重算的。
- commit `docs(v6-crosscheck): every report KPI and whether it can be recomputed`

### Task 5: 報表數字

**Files:** Create `illumio_ops/crosscheck/reports.py`、`kpis.py`、`tests/crosscheck/test_reports.py`。

- 每種報表取 app 資料庫 `reports` 表最近一份 `status=done` 的列（`period_start`、`period_end`、`kpis_json`、`params_json`）；沒有就該報表 `unchecked`。
- 依附錄 A 的獨立算法，在**那份報表的期間**用 `async_query`（或 PCE API）重算，逐個 KPI 比較：相同 → `consistent`；不同 → `inconsistent`
  並寫差異量與百分比；報表有 filter（`params_json`）時把相同條件帶進查詢，帶不進的 → `unchecked`。
- 每份報表的查詢條件、筆數、是否被截斷（`capped`）寫進報告；截斷 → 該報表 `unchecked`。
- 測試：每個 KPI 算法用小型假流量資料；截斷與 filter 帶不進的路徑。
- commit `feat(v6-crosscheck): report numbers recomputed from raw PCE traffic`

### Task 6: 在 .106 跑、交付（主對話執行）

- 全套閘門綠。
- .106 跑的是 6.12.5（與本分支同基底）：把分支的 `illumio_ops/` 複製到 .106 的暫存目錄，用安裝版的 python
  `sudo -u illumio-ops env PYTHONPATH=<暫存> PYTHONNOUSERSITE=1 /opt/illumio-ops/python/bin/python3 -m illumio_ops.crosscheck all --days 7 --out <暫存>/out`。
  先確認暫存目錄的 `illumio_ops/__init__.py` 版本與安裝版相同。
- 讀 `report.md`，每個 `inconsistent` 查明是工具錯還是產品錯；工具錯就修工具重跑。產品錯列成缺陷清單給使用者（不在這個計畫裡修）。
- 合入 main（照長期授權：閘門綠才合、push 單獨一行、盯 CI），版本與 CHANGELOG 跟下一個發版一起。
- 回報分「驗到」「沒驗到」；更新記憶 [[v6-batch-after-alert-rules-page]]。
