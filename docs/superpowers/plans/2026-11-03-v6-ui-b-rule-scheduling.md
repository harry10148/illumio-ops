# v6 介面重做 B：規則排程 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 加回 5.x 的規則排程：依每週時段或到期時間，自動啟用／停用 PCE 上已佈署的 Ruleset 或 Rule 並佈署；有畫面（樣本 05）、紀錄、5.x 遷移。

**Architecture:** 純函式在 `domain/rule_schedule.py`（時段判定、下次動作、描述註記、預覽句）；PCE 呼叫集中在 `pce/policy_write.py`；本機資料由 `store/rule_schedules.py` 單一寫入（app 遷移 `0013_rule_schedules.sql`）；引擎 `services/rule_schedules.py` 由 job `rule_schedules_tick` 每 300 秒呼叫；畫面 `web/src/pages/schedules/RuleSchedules.tsx` 用計畫 A 的外殼與元件。

**Tech Stack:** 同計畫 A；時區用標準函式庫 `zoneinfo`。

**Spec:** `docs/superpowers/specs/2026-11-03-v6-ui-redesign-design.md` §4.5（語意來源 `docs/legacy-5.x/guide/automation.md` §1；5.x 原始碼在 `git show 510957b8^:src/rule_scheduler.py` 與 `510957b8^:src/api_client.py` 的 `toggle_and_provision`／`has_draft_changes`／`update_rule_note`／`provision_changes`）。主規格 §6.5 已修訂為第三種 PCE 寫入。

**前置：** 計畫 A 已合入（外殼、`ui.tsx`、`shell.status.write_key`）。

## Global Constraints

- 寫入一律用 `ctx.pce_write_client(cfg)`（寫入用 key）；沒設定 → 不寫入，頁面反灰並寫明，job 什麼都不做。讀取（瀏覽目標）用主要 key `ctx.pce_client(cfg)`。
- 不做權限探測；PCE 拒絕時把狀態碼與 PCE 回應（截 300 字）照實存進該次紀錄並顯示，不顯示成功。
- 描述註記固定英文：每週 `[📅 Recurring: Mon,Wed,Fri 18:00-09:00 (Asia/Taipei) Disable in window]`、到期 `[⏰ Expires: 2026-12-01 00:00 (Asia/Taipei)]`。清除時要認 `📅`、`⏳`、`⏰` 三種前綴（5.x 遺留）。
- 一個目標（href）最多一筆排程（5.x 以 href 為鍵）。排程綁定建立時的 PCE（`pce_url`、`org_id`）；換 PCE 後舊排程不執行、不顯示（同告警的做法）。
- 引擎每輪中途若 PCE 設定被換掉，立即停止寫入（同 `services/quarantine.py` 的 `_ident` 檢查）。
- 單一寫入者：只有 `store/rule_schedules.py` 寫 `rule_schedules`、`rule_schedule_runs`；`tests/gates/test_single_writer.py` 要登記。
- 文字規則同計畫 A；預覽句與狀態句由模板產生。
- 契約重產、i18n、閘門、git 規則同計畫 A（閘門腳本 `.superpowers/sdd/2026-11-03-v6-ui-b-rule-scheduling/gates.sh`，複製計畫 A 的）。
- **lab PCE 寫入要使用者授權**：Task 5 開始前停下來問。NFR（.135）不做任何規則排程寫入。

## Review Focus

1. **到期排程停用失敗**：只有「停用並佈署成功」後才刪排程與註記；失敗保留並下輪重試（5.x BUG-1，安全相關）。
2. **跨午夜時段與 DST**：`22:00–06:00` 在週日晚上到週一早上；時區切換日（例如 `America/New_York` 3 月第二個週日）不會整天錯判。
3. **未佈署的 Draft**：目標或其所屬 Ruleset 的 draft 有 `update_type` → 本輪跳過並記錄，不切換、不佈署。
4. **目標被刪除**：`GET active` 回 404 → 標為已刪除、記錄、不影響其他排程；之後又找得到 → 清回正常。
5. **寫入用 key 被移除**：已存在的排程不執行，頁面與 `shell.status` 都寫明，不報錯迴圈。

---

### Task 1: 時段判定與文字（純函式）

**Files:**
- Create: `illumio_ops/domain/rule_schedule.py`
- Test: `tests/domain/test_rule_schedule.py`

**Interfaces:**
- Produces：
  - `class Weekly(BaseModel)`：`days: tuple[Weekday, ...]`（`Weekday = Literal["mon","tue","wed","thu","fri","sat","sun"]`，至少 1 個，不重複）、`start: str`、`end: str`（`HH:MM`，`start != end`）、`timezone: str`（IANA，`ZoneInfo` 可載入）、`action: Literal["enable_in_window","disable_in_window"]`。
  - `class Expiry(BaseModel)`：`expire_at: AwareDatetime`、`timezone: str`。
  - `Plan = Weekly | Expiry`
  - `desired(plan: Plan, now: datetime) -> bool | Literal["expired"]`：Weekly：`start < end` 時 `[start, end)` 且當天在 days；`start > end` 時「當天在 days 且 ≥ start」或「前一天在 days 且 < end」；`enable_in_window` 時段內 True、外 False，`disable_in_window` 相反。Expiry：`now >= expire_at` → `"expired"`，否則 True。所有比較在 `plan.timezone` 的當地時間。
  - `next_change(plan: Plan, now: datetime) -> datetime | None`：Weekly 往後 8 天內最近的一個 start 或 end 時刻（當地時間轉 UTC）；Expiry 回 `expire_at`（已過回 None）。
  - `note(plan: Plan) -> str`（Global Constraints 的英文格式；days 依週一到週日排序，首字大寫三字母）。
  - `strip_notes(description: str) -> str`：移除所有 `\s*\[(📅|⏳|⏰)[^\]]*\]`，去頭尾空白。
  - `with_note(description: str, plan: Plan) -> str`：`strip_notes` 後，有原文則 `原文\n註記`，否則只有註記。
  - `preview(plan: Plan) -> tuple[str, dict[str, str]]`：i18n 鍵與參數，例：Weekly disable → `("rs_preview_weekly_disable", {"days": "mon,wed,fri", "start": "18:00", "end": "09:00", "next_day": "1"})`；畫面以 `rs_day_<d>` 組出「一三五 18:00 停用並佈署，隔天 09:00 啟用並佈署」。

- [ ] **Step 1: 寫失敗測試**（每條一個 test）：一般時段內外；`end` 當下為時段外；跨午夜（週日 23:00 在 `sun 22:00–06:00` 內、週一 05:59 在內、週一 06:00 在外、週一 22:30 若週一不在 days 則在外）；`disable_in_window` 相反；Expiry 到期前 True、等於與之後 `"expired"`；DST：`America/New_York` 2027-03-14 01:30 與 03:30 的 `08:00–18:00` 判定正確、`next_change` 不回不存在的當地時刻；`next_change` 跨週；`note` 兩種格式；`strip_notes` 三種前綴與多個註記、保留其他文字；`with_note` 空描述與既有描述；`Weekly` 驗證拒絕 `start == end`、未知時區、空 days。
- [ ] **Step 2: 跑** `timeout 300 python -m pytest tests/domain/test_rule_schedule.py -q` → FAIL（模組不存在）。
- [ ] **Step 3: 實作。**
- [ ] **Step 4: 跑同一指令** → PASS。
- [ ] **Step 5: Commit** `feat(v6): rule schedule windows, next change and description notes (pure)`。

### Task 2: PCE 呼叫、儲存、引擎與 job

**Files:**
- Create: `illumio_ops/pce/policy_write.py`、`illumio_ops/store/migrations/0013_rule_schedules.sql`、`illumio_ops/store/rule_schedules.py`、`illumio_ops/services/rule_schedules.py`
- Modify: `illumio_ops/jobs/scheduler.py`（`job_intervals` 加 `"rule_schedules_tick": 300`；排程加入）、`tests/gates/test_single_writer.py` 的登記（若以清單登記）
- Modify: `tests/e2e/fake_pce.py`（rule_sets／sec_rules 的 draft 與 active、`PUT enabled／description`、`POST /sec_policy/draft/dependencies`、`POST /sec_policy`、可設定回 403）
- Test: `tests/pce/test_policy_write.py`、`tests/store/test_rule_schedules_store.py`、`tests/services/test_rule_schedules_engine.py`、`tests/jobs/`（job id 清單若有斷言則更新）

**Interfaces:**
- Consumes：Task 1 全部。
- Produces（`pce/policy_write.py`，`client` 為 `PceClient`，href 為 PCE 回的完整 `/orgs/<n>/sec_policy/...` 路徑，呼叫時 `org_scoped=False`）：
  - `draft_href(href) -> str`、`active_href(href) -> str`、`ruleset_of(href) -> str`（前 6 段：`/orgs/1/sec_policy/draft/rule_sets/5`）
  - `draft_pending(client, href) -> bool`：draft 物件 `update_type` 非空，或（目標是 rule 時）所屬 ruleset 的 draft `update_type` 非空。非 200 → 拋 `PolicyReadError(status, body)`。
  - `get_active(client, href) -> tuple[int, dict | None]`
  - `set_fields(client, href, fields: dict) -> PceResponse`（`PUT` draft；成功為 204）
  - `provision(client, ruleset_href, note: str) -> PceResponse`：先 `POST /sec_policy/draft/dependencies` 取依賴，把回傳各型別的 href 併入 `change_subset`，再 `POST /sec_policy`（`update_description=note`）；成功為 201。（照 5.x `provision_changes`。）
- Produces（儲存）：表 `rule_schedules(id INTEGER PK, pce_url, org_id, href, is_ruleset INTEGER, name, ruleset_name, summary, plan_json, paused INTEGER, pce_status TEXT CHECK IN ('active','deleted','unknown'), created_by, created_at, updated_at, UNIQUE(pce_url, org_id, href))`、`rule_schedule_runs(id INTEGER PK, schedule_id, href, name, at, action TEXT CHECK IN ('enable','disable','expire','skip_draft','not_found','error','note','note_cleared'), result TEXT CHECK IN ('ok','failed','skipped'), status INTEGER, detail TEXT)`；runs 保留 30 天（引擎每輪刪舊）。store 函式：`create`、`update_plan`、`set_paused`、`set_pce_status`、`delete`、`list_for(pce_url, org_id)`、`get`、`add_run`、`runs(pce_url, org_id, limit, schedule_id=None)`、`prune_runs(before)`。
- Produces（服務）：`tick(ctx, *, now=None) -> TickResult(checked, switched, failed, skipped)`；`create(ctx, *, href, plan, by) -> ScheduleView`（要求：寫入用 key、`get_active` 200、`draft_pending` False、尚無同 href 排程；然後寫註記並佈署；PCE 拒絕 → 拋 `PceRefused(status, detail)`，不存排程）；`update(ctx, id, plan, by)`（重寫註記並佈署）；`pause(ctx, id)`／`resume(ctx, id)`（只改本機）；`delete(ctx, id, by) -> DeleteResult(note_cleared: bool, detail: str | None)`（先清註記並佈署；PCE 失敗仍刪本機排程，結果寫明註記沒清掉與 PCE 回應）；`overview(ctx, now) -> ScheduleOverview`（排程數、今日切換／失敗、本輪跳過、下次動作 `next_change` 最小者、`write_key`）。

- [ ] **Step 1: 失敗測試**（引擎用假的 client 物件，不打網路）：
  - `test_switches_when_live_differs_and_provisions`：Weekly 時段內、PCE `enabled=false` → PUT `{"enabled": true}` 後佈署，run `enable/ok`。
  - `test_no_action_when_already_in_state`：不寫入，不記 run（只更新最後檢查時間）。
  - `test_skips_when_rule_or_parent_draft_pending`：兩種情形都記 `skip_draft/skipped`、不 PUT。
  - `test_marks_deleted_on_404_and_continues`：第一筆 404、第二筆照常切換。
  - `test_restores_active_when_found_again`。
  - `test_expiry_deletes_only_after_disable_provision_ok`：佈署回 500 → 排程仍在、run `expire/failed`；下一輪成功 → 刪排程、清註記。
  - `test_paused_not_evaluated`、`test_other_pce_not_evaluated`。
  - `test_pce_refusal_recorded_verbatim`：PUT 回 403 → run `status=403`、`detail` 含 PCE 回應。
  - `test_no_write_key_does_nothing`。
  - `test_stops_when_pce_changes_mid_tick`。
  - `test_create_refuses_draft_pending_and_unprovisioned`、`test_create_writes_note_and_provisions`、`test_delete_clears_note_even_when_draft_pending`（draft pending 時只 PUT description 不佈署，結果寫明「已在 Draft 清除，待佈署」）。
  - `test_provision_includes_dependencies`（`tests/pce/test_policy_write.py`）。
  - `test_job_registered_every_300s`（`job_intervals` 含 `rule_schedules_tick == 300`）。
- [ ] **Step 2: 跑** `timeout 600 python -m pytest tests/pce/test_policy_write.py tests/store/test_rule_schedules_store.py tests/services/test_rule_schedules_engine.py -q` → FAIL。
- [ ] **Step 3: 實作。** job 在 `build_scheduler` 以 `instrument("rule_schedules_tick", ...)` 加入，不放進 `COLLECTOR_FIRST_RUN_DELAY` 的收集器群（首輪 60 秒後）。
- [ ] **Step 4: 跑同一指令** → PASS；`timeout 900 python -m pytest tests/gates tests/jobs -q` → PASS。
- [ ] **Step 5: Commit** `feat(v6): rule scheduling engine — toggle and provision on the write key, draft skip, expiry, run log`。

### Task 3: API 與畫面（樣本 05）

**Files:**
- Create: `illumio_ops/web/routes/rule_schedules.py`；Modify: `illumio_ops/web/app.py`、`illumio_ops/services/shell.py`（`ShellStatus` 不變；規則排程頁自己讀 `overview`）
- Create: `web/src/pages/schedules/RuleSchedules.tsx`
- Test: `tests/web/test_rule_schedules_routes.py`、`tests/e2e/test_rule_schedules_e2e.py`

**Interfaces:**
- Produces（operations）：`rule_schedules.list` `GET /api/rule-schedules` → `RuleSchedulesView(overview: ScheduleOverview, items: list[ScheduleView])`；`rule_schedules.targets` `GET /api/rule-schedules/targets?q=` → `TargetSearch(items: list[TargetHit(href, is_ruleset, name, ruleset_name, summary, enabled: bool, draft_pending: bool, scheduled: bool)])`（active ruleset 名稱比對，最多 20 個 ruleset 與其規則；`summary` 為「來源 → 目的：服務」，由 label／IP list 名稱組成）；`rule_schedules.create` `POST`、`rule_schedules.update` `PUT /<id>`、`rule_schedules.pause` `POST /<id>/pause`、`rule_schedules.resume` `POST /<id>/resume`、`rule_schedules.delete` `DELETE /<id>`、`rule_schedules.runs` `GET /api/rule-schedules/runs?schedule_id=`。寫入類回 409（Draft 未佈署、已排程）、412（沒有寫入用 key）、502（PCE 拒絕，body 帶 PCE 狀態碼與回應）。
- `ScheduleView`：`id, href, is_ruleset, name, ruleset_name, summary, plan, paused, pce_status, live: Literal["enabled","disabled","unknown"]`（上次檢查時的 PCE 狀態）`, last_run: RunView | None, next_change: datetime | None, preview_key, preview_params`。

- [ ] **Step 1: 路由失敗測試**：`test_list_shows_overview`、`test_create_conflict_when_draft_pending_409`、`test_create_without_write_key_412`、`test_create_pce_refusal_502_carries_pce_answer`、`test_pause_resume_local_only`（不打 PCE）、`test_delete_reports_note_not_cleared`、`test_csrf_required_for_writes`、`test_targets_search`。
- [ ] **Step 2–4:** `timeout 600 python -m pytest tests/web/test_rule_schedules_routes.py -q` → FAIL → 實作 → PASS；重產契約。
- [ ] **Step 5: 畫面** 照樣本 05：註冊 `section: "main"`、`path: "/rule-schedules"`、`labelKey: "nav_rule_schedules"`、order 在主機之後；狀態數字（排程數、今日切換、今日失敗、本輪跳過、下次動作）；本週時間表（七天 × 24 小時，每筆排程一列色帶，到期排程一個標記）；排程清單（目標、類型、時間、現在＝`live`、上次結果＋時間、動作：暫停／繼續、編輯、刪除＝紅框）；新增排程側欄（搜尋目標 → 選 Ruleset 或其中一條 Rule；Draft 未佈署或已排程的選項反灰並寫原因；類型、星期、起訖、時區預設顯示設定的時區、動作；即時預覽句）；執行紀錄表。沒有寫入用 key：整頁上方說明框＋所有寫入按鈕反灰。PCE 拒絕：側欄顯示 PCE 狀態碼與回應原文。
- [ ] **Step 6: e2e**（fake PCE）：`test_create_weekly_and_see_preview`、`test_draft_target_disabled_in_picker`、`test_no_write_key_greys_out`、`test_refusal_shows_pce_answer`、`test_no_overflow_760`。
- [ ] **Step 7:** build ＋ `timeout 900 python -m pytest tests/e2e/test_rule_schedules_e2e.py tests/e2e/test_shell_e2e.py -q` → PASS；gates.sh → ALL GREEN。
- [ ] **Step 8: Commit** `feat(v6-ui): rule scheduling page and API`。

### Task 4: 5.x 遷移

**Files:**
- Create: `illumio_ops/migrate/v5_rule_schedules.py`；Modify: `illumio_ops/migrate/v5.py`（`NOT_IN_V6_SECTIONS` 拿掉 `"rule_scheduler"`，該段的鍵改由新模組逐鍵回報；`"scheduler"`、`"rule_backups"` 不變）、`illumio_ops/migrate/report.py`（若報告分段需要）、`v5_write.py`（寫入 app DB 的位置，照 `v5_reports.py` 寫報表排程的做法）
- Test: `tests/migrate/test_v5_rule_schedules.py`

**Interfaces:**
- 讀 5.x 安裝目錄的 `config/rule_schedules.json`（不存在 → 報告寫「沒有規則排程」）；每筆轉為**暫停**的排程，綁定遷移後設定的 `pce.url`／`org_id`，`pce_status="unknown"`，`created_by="migrated-5.x"`。
- 對應：`type=recurring` → Weekly（`days` 以 5.x `normalize_day` 規則轉為三字母；`timezone` 取該筆，`local` 或缺 → 遷移時主機的時區名稱，取不到 → `UTC` 並在報告寫明）；`one_time` → Expiry（naive 的 `expire_at` 解讀為該筆時區的當地時間）；`action=allow` → `enable_in_window`，`block`／`disable` → `disable_in_window`。
- 轉不了的（時間格式錯、未知時區、`start == end`）→ 不遷移，報告逐筆寫原因。
- 5.x `config.json` 的 `rule_scheduler.enabled=false` → 報告寫「5.x 未啟用規則排程；遷移後仍為暫停」。

- [ ] **Step 1: 失敗測試**：`test_recurring_becomes_paused_weekly`、`test_one_time_naive_expiry_in_item_timezone`、`test_local_timezone_resolved_or_reported`、`test_action_mapping`、`test_invalid_entries_reported_not_migrated`、`test_missing_file_reported`、`test_rule_scheduler_section_reported_key_by_key`（既有遷移報告測試若斷言 `rule_scheduler` 為 unsupported，改為新說法）。
- [ ] **Step 2–4:** `timeout 600 python -m pytest tests/migrate -q` → FAIL → 實作 → PASS。
- [ ] **Step 5:** gates.sh → ALL GREEN。
- [ ] **Step 6: Commit** `feat(v6): migrate 5.x rule schedules as paused schedules`。

### Task 5: lab 驗收（需使用者授權 lab PCE 寫入）

**停點：** 開始前向使用者說明要在 lab PCE 做的寫入（建一個測試用 Ruleset＋一條規則並佈署；兩筆排程各跨過一次切換點；最後刪除排程與測試 Ruleset 並佈署），取得同意或請使用者用 `!` 執行建立／刪除步驟。沒有授權就把 Task 5 留在帳本為「待授權」，計畫其他部分照常合入。

- [ ] **Step 1:** 合併與部署同計畫 A Task 8（gates 全綠 → main → push 單獨一行 → CI；部署 .106 先備份）。
- [ ] **Step 2:** 在 .106 建一筆每週時段（起點設在 10 分鐘後、迄點 20 分鐘後）與一筆到期停用（15 分鐘後），跨過切換點各確認一次 PCE 狀態（`get-rulesets` 唯讀查詢）與 PCE 的 provision 事件。
- [ ] **Step 3:** 在測試規則上製造未佈署的 Draft（使用者授權的寫入），確認下一輪記錄 `skip_draft`、PCE 狀態不變。
- [ ] **Step 4:** 截圖排程頁（1280、760），結果寫進 `tmp/v6-ui-b-verification/report.md`；清理測試物件。
